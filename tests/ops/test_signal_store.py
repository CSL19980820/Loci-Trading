"""ops.db 的实时信号两张表：建表、规则覆盖、信号日志与**保留策略**。

保留策略的两个阈值是用户需求（7 天 / 每租户 80 条），因此这里逐条钉死：
阈值漂了、闸门失灵了，测试必须红，而不是等某天用户翻不到昨天的信号才发现。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.ops import OpsStore
from src.ops.infrastructure.store_signals import (
    JOURNAL_TIME_FORMAT,
    SIGNAL_JOURNAL_MAX_ROWS,
    SIGNAL_RETENTION_DAYS,
    signal_dedup_id,
)

NOW = datetime(2026, 8, 29, 10, 30, 0)


@pytest.fixture()
def store(tmp_path):
    with OpsStore(tmp_path / "ops.db") as handle:
        yield handle


def signal(**overrides):
    row = {
        "code": "600000",
        "name": "浦发测试",
        "rule": "ma_golden_cross",
        "rule_label": "均线金叉",
        "detail": "MA5 上穿 MA20",
        "direction": "long",
        "strength": 0.5,
        "price": 10.5,
        "pct": 3.2,
        "at": NOW.strftime(JOURNAL_TIME_FORMAT),
        "trade_date": "2026-08-29",
        "repeatable": False,
    }
    row.update(overrides)
    return row


def at(moment: datetime) -> str:
    return moment.strftime(JOURNAL_TIME_FORMAT)


def test_retention_thresholds_are_the_user_requirement() -> None:
    """阈值出处是用户需求 5。改这两个数就是改需求，必须有人按下这一行。"""
    assert SIGNAL_RETENTION_DAYS == 7
    assert SIGNAL_JOURNAL_MAX_ROWS == 80


def test_both_tables_exist_after_migration(store) -> None:
    names = {
        row[0]
        for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"signal_rule_config", "signal_journal"} <= names
    indexes = {
        row[0]
        for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_signal_journal_tenant_time" in indexes


def test_rule_config_primary_key_is_tenant_plus_rule(store) -> None:
    """同一个 rule_id 在两个租户下是**两行**，不是互相覆盖的一行。"""
    store.upsert_signal_rule_config("fast_surge", tenant="u_a", enabled=False, params=dict())
    store.upsert_signal_rule_config(
        "fast_surge", tenant="u_b", enabled=True, params={"speed_pct": 5.0}
    )
    a = store.get_signal_rule_config("fast_surge", tenant="u_a")
    b = store.get_signal_rule_config("fast_surge", tenant="u_b")
    assert a["enabled"] is False and a["params"] == dict()
    assert b["enabled"] is True and b["params"] == {"speed_pct": 5.0}
    assert [row["rule_id"] for row in store.list_signal_rule_config(tenant="u_a")] == ["fast_surge"]


def test_rule_config_upsert_replaces_not_appends(store) -> None:
    store.upsert_signal_rule_config("fast_surge", tenant="u_a", enabled=True, params={"speed_pct": 5.0})
    store.upsert_signal_rule_config("fast_surge", tenant="u_a", enabled=False, params=dict())
    rows = store.list_signal_rule_config(tenant="u_a")
    assert len(rows) == 1
    assert rows[0]["enabled"] is False
    assert rows[0]["params"] == dict()


def test_journal_dedups_same_code_rule_and_trade_day(store) -> None:
    """同 (租户, code, rule, 交易日) 只存一条——**重启后重复命中也压得住**。

    引擎的内存去抖表一重启就没了；这一层用确定性主键兜底。
    """
    first = store.append_signal_journal([signal()], tenant="u_a", now=NOW)
    assert first["inserted"] == 1
    # 同一条信号，晚 3 分钟又报了一次（模拟进程重启后重新命中）。
    later = signal(at=at(NOW + timedelta(minutes=3)))
    second = store.append_signal_journal([later], tenant="u_a", now=NOW + timedelta(minutes=3))
    assert second["inserted"] == 0
    assert second["deduped"] == 1
    assert len(store.list_signal_journal(tenant="u_a", now=NOW + timedelta(minutes=3))) == 1


def test_repeatable_rules_keep_one_row_per_moment(store) -> None:
    """可重复规则用 ``triggered_at`` 区分：一天多条是它的正常语义。"""
    morning = signal(rule="near_limit_up", repeatable=True, at=at(NOW))
    afternoon = signal(
        rule="near_limit_up", repeatable=True, at=at(NOW + timedelta(hours=4))
    )
    store.append_signal_journal([morning], tenant="u_a", now=NOW)
    store.append_signal_journal([afternoon], tenant="u_a", now=NOW + timedelta(hours=4))
    rows = store.list_signal_journal(tenant="u_a", now=NOW + timedelta(hours=4))
    assert len(rows) == 2
    assert [row["triggered_at"] for row in rows] == [at(NOW + timedelta(hours=4)), at(NOW)]


def test_rows_older_than_the_retention_window_are_deleted(store) -> None:
    """① 早于 7 天的行在下一次写入时被物理删除（不是查询时过滤掉）。"""
    stale = signal(code="000001", at=at(NOW - timedelta(days=SIGNAL_RETENTION_DAYS, hours=1)))
    fresh = signal(code="600519", at=at(NOW - timedelta(days=SIGNAL_RETENTION_DAYS, hours=-1)))
    store.append_signal_journal([stale, fresh], tenant="u_a", now=NOW - timedelta(days=8))
    assert store.conn.execute("SELECT COUNT(*) FROM signal_journal").fetchone()[0] == 2

    # 时间推进到 NOW 再写一条：过期那条应当被**删掉**，而不是只在查询里被藏起来。
    result = store.append_signal_journal([signal(code="300750")], tenant="u_a", now=NOW)
    assert result["expired"] == 1
    codes = {
        row[0] for row in store.conn.execute("SELECT code FROM signal_journal")
    }
    assert "000001" not in codes
    assert codes == {"600519", "300750"}


def test_the_eighty_first_row_pushes_out_the_oldest(store) -> None:
    """② 每租户只留最新 80 条：第 81 条写进来，最旧那条消失。"""
    for index in range(SIGNAL_JOURNAL_MAX_ROWS):
        moment = NOW - timedelta(minutes=SIGNAL_JOURNAL_MAX_ROWS - index)
        store.append_signal_journal(
            [signal(code=f"60{index:04d}", at=at(moment))], tenant="u_a", now=NOW
        )
    total = store.conn.execute("SELECT COUNT(*) FROM signal_journal").fetchone()[0]
    assert total == SIGNAL_JOURNAL_MAX_ROWS
    oldest = "60" + "0000"
    assert oldest in {row["code"] for row in store.list_signal_journal(tenant="u_a", now=NOW)}

    result = store.append_signal_journal(
        [signal(code="999999", at=at(NOW))], tenant="u_a", now=NOW
    )
    assert result["overflow"] == 1
    codes = {row["code"] for row in store.list_signal_journal(tenant="u_a", now=NOW)}
    assert len(codes) == SIGNAL_JOURNAL_MAX_ROWS
    assert "999999" in codes
    assert oldest not in codes, "第 81 条写入后最旧那条应当被物理删除"


def test_retention_gates_are_scoped_per_tenant(store) -> None:
    """A 疯狂写入不能把 B 的历史挤掉：两道闸门都按租户收窄。"""
    store.append_signal_journal([signal(code="600519")], tenant="u_b", now=NOW)
    for index in range(SIGNAL_JOURNAL_MAX_ROWS + 5):
        moment = NOW - timedelta(minutes=index)
        store.append_signal_journal(
            [signal(code=f"60{index:04d}", at=at(moment))], tenant="u_a", now=NOW
        )
    mine = store.list_signal_journal(tenant="u_b", now=NOW)
    assert [row["code"] for row in mine] == ["600519"]
    assert len(store.list_signal_journal(tenant="u_a", now=NOW)) == SIGNAL_JOURNAL_MAX_ROWS


def test_tenant_a_signals_never_show_up_in_tenant_b_history(store) -> None:
    """⑤ 租户隔离：同一条行情、同一条规则，A 的信号不出现在 B 的历史里。"""
    store.append_signal_journal([signal(name="A 的票")], tenant="u_a", now=NOW)
    store.append_signal_journal([signal(name="B 的票")], tenant="u_b", now=NOW)
    a_rows = store.list_signal_journal(tenant="u_a", now=NOW)
    b_rows = store.list_signal_journal(tenant="u_b", now=NOW)
    assert [row["name"] for row in a_rows] == ["A 的票"]
    assert [row["name"] for row in b_rows] == ["B 的票"]
    # 去重键带租户，所以两行的 id 必须不同——否则第二条会被当成重复吞掉。
    assert a_rows[0]["id"] != b_rows[0]["id"]


def test_reads_are_capped_at_seven_days_and_eighty_rows(store) -> None:
    """读侧自己也压两道闸门：收盘后没有写入，过期行只能靠读侧挡住。"""
    store.append_signal_journal([signal(code="600519", at=at(NOW))], tenant="u_a", now=NOW)
    # 时间往后走 8 天，期间没有任何新信号写入（收盘 / 周末）。
    later = NOW + timedelta(days=8)
    assert store.conn.execute("SELECT COUNT(*) FROM signal_journal").fetchone()[0] == 1
    assert store.list_signal_journal(tenant="u_a", now=later) == []


def test_list_limit_never_exceeds_the_hard_cap(store) -> None:
    store.append_signal_journal([signal()], tenant="u_a", now=NOW)
    assert len(store.list_signal_journal(tenant="u_a", limit=10_000, now=NOW)) == 1


def test_dedup_id_includes_tenant_and_only_uses_time_when_repeatable() -> None:
    base = dict(
        code="600000", rule_id="fast_surge", trade_day="2026-08-29", triggered_at="2026-08-29 10:30:00"
    )
    assert signal_dedup_id(tenant="u_a", repeatable=False, **base) != signal_dedup_id(
        tenant="u_b", repeatable=False, **base
    )
    other_time = dict(base, triggered_at="2026-08-29 14:55:00")
    assert signal_dedup_id(tenant="u_a", repeatable=False, **base) == signal_dedup_id(
        tenant="u_a", repeatable=False, **other_time
    )
    assert signal_dedup_id(tenant="u_a", repeatable=True, **base) != signal_dedup_id(
        tenant="u_a", repeatable=True, **other_time
    )


def test_dirty_rows_are_dropped_not_stored(store) -> None:
    """没有 code / 没有 rule 的「信号」是上游 bug，不许落成脏行。"""
    result = store.append_signal_journal(
        [{"name": "没代码"}, {"code": "600000"}, signal()], tenant="u_a", now=NOW
    )
    assert result["received"] == 1
    assert result["inserted"] == 1
