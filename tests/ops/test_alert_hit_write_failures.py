"""`insert_alert_hit` 不许再把写入失败压成「幂等跳过」。

原实现是 `except Exception: return {}`。空 dict 在调用方（`scan_alert_rules`）那里的
含义是「这一桶已经命中过，跳过」，于是外键违例、NOT NULL、schema 漂移全都被翻译成
了「一切正常，只是没写」。

这不是理论风险：给 `alert_hits` 造种子数据时忘了先建 `alert_rules` 父行，5 次
`insert_alert_hit` 每次都返回带 id 的 payload，落库行数却是 0——写测试的人照着返回值
断言，测试跟着一起绿。

所以边界要划在「预期内的重复」与「真失败」之间：
- 唯一约束冲突（同一 rule+bucket 重扫、同一 hit id 重放）→ 静默返回 {}；
- 其余一律抛出。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.ops.infrastructure.store import OpsError, OpsStore


@pytest.fixture()
def store(tmp_path: Path):
    with OpsStore(tmp_path / "ops.db") as opened:
        yield opened


def _rule(store: OpsStore, rule_id: str = "AR-1") -> dict[str, Any]:
    return store.upsert_alert_rule({"id": rule_id, "code": "600519", "name": "测试规则"})


def _payload(rule_id: str, bucket: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "rule_id": rule_id,
        "trigger_bucket": bucket,
        "trigger_time": f"2026-08-25T{bucket[-5:]}:00+08:00",
        "snapshot": {"quote": {"price": 1700.0}},
    }
    payload.update(extra)
    return payload


def _count(store: OpsStore) -> int:
    return int(store.conn.execute("SELECT COUNT(*) FROM alert_hits").fetchone()[0])


def test_missing_parent_rule_raises_instead_of_returning_empty(store: OpsStore) -> None:
    """rule_id 指向不存在的规则 = 外键违例，必须炸，不能装作跳过。"""
    with pytest.raises(OpsError) as caught:
        store.insert_alert_hit(_payload("AR-404", "202608250930"))

    assert "FOREIGN KEY" in str(caught.value)
    assert isinstance(caught.value.__cause__, sqlite3.IntegrityError)
    assert _count(store) == 0


def test_a_whole_seed_batch_can_no_longer_report_success_while_writing_nothing(
    store: OpsStore,
) -> None:
    """复现当初的坑：没建父行的 5 行种子数据，不能再「行行成功、一行没落」。"""
    written = []
    with pytest.raises(OpsError):
        for i in range(5):
            written.append(store.insert_alert_hit(_payload("AR-404", f"20260825093{i}")))

    assert written == []  # 第一行就该炸掉，而不是攒够 5 个假回执
    assert _count(store) == 0
    assert store.list_alert_hits() == []


def test_duplicate_bucket_stays_a_silent_idempotent_skip(store: OpsStore) -> None:
    """同一规则同一分钟桶重复扫描是正常的：静默返回 {}，且不覆盖首行。"""
    rule = _rule(store)
    first = store.insert_alert_hit(_payload(rule["id"], "202608250930", notify_ok=True))
    again = store.insert_alert_hit(
        _payload(rule["id"], "202608250930", notify_error="第二次不该覆盖")
    )

    assert first["id"]
    assert again == {}
    assert _count(store) == 1
    row = store.list_alert_hits(rule_id=rule["id"])[0]
    assert row["notify_ok"] is True
    assert row["notify_error"] == ""


def test_duplicate_hit_id_is_also_a_silent_skip(store: OpsStore) -> None:
    """显式重放同一个 hit id（主键冲突）同样属于预期内的重复。"""
    rule = _rule(store)
    store.insert_alert_hit(_payload(rule["id"], "202608250930", id="ALH-fixed"))
    again = store.insert_alert_hit(_payload(rule["id"], "202608250931", id="ALH-fixed"))

    assert again == {}
    assert _count(store) == 1


def test_schema_drift_surfaces_as_well(store: OpsStore) -> None:
    """不是 IntegrityError 的写入错误（表没了/列没了）更不该被吞。"""
    _rule(store)
    store.conn.execute("ALTER TABLE alert_hits RENAME TO alert_hits_gone")
    store.conn.commit()

    with pytest.raises(sqlite3.OperationalError):
        store.insert_alert_hit(_payload("AR-1", "202608250930"))


def test_successful_insert_still_returns_the_payload_and_actually_lands(
    store: OpsStore,
) -> None:
    """修完之后正常路径不变：返回带 id 的 payload，且行真的在库里。"""
    rule = _rule(store)
    hit = store.insert_alert_hit(_payload(rule["id"], "202608250930"))

    assert hit["id"].startswith("ALH-")
    assert hit["rule_id"] == rule["id"]
    rows = store.list_alert_hits(rule_id=rule["id"])
    assert [row["id"] for row in rows] == [hit["id"]]
    assert rows[0]["snapshot"] == {"quote": {"price": 1700.0}}
