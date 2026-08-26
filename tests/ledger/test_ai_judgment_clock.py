"""同一个 palace.db 只能有一套时钟。

`ai_judgments.created_at` 原本由 SQLite 的 `datetime('now')` 生成：**UTC**、秒级、
空格分隔（`'2026-08-25 03:11:22'`）；而全库其余表走 `store_types._now()`：**本地时间
带偏移**、微秒、ISO8601 带 `'T'`（`'2026-08-25T11:11:22.123456+08:00'`）。

同库两种时区两种格式，跨表比时间戳（AI 判定 vs 同一天写的候选）会差整整一个时区，
按字符串排序更是把两条时间轴混着比。写入统一到 `_now()`。

旧行不重写（那是既成事实），所以读取侧必须能同时吃下两种格式：排序折算到同一条时间轴，
取值原样返回，不因此抛错。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ledger import PalaceStore

#: `_now()` 的形状：日期 T 时间 . 六位微秒 ± 偏移
_NOW_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:\d{2}$")


@pytest.fixture()
def store(tmp_path: Path):
    palace = PalaceStore(tmp_path / "palace.db")
    try:
        yield palace
    finally:
        palace.close()


def _created_at(store: PalaceStore, jid: str) -> str:
    return str(
        store.conn.execute(
            "SELECT created_at FROM ai_judgments WHERE id = ?", (jid,)
        ).fetchone()[0]
    )


def _insert_raw(store: PalaceStore, jid: str, created_at: str, occurred_on: str) -> None:
    """绕过写入方法造行：模拟库里既有的历史数据。"""
    store.conn.execute(
        "INSERT INTO ai_judgments(id, occurred_on, strategy_tag, decision, top_codes,"
        " reason, provider, model, token_used, source, created_at)"
        " VALUES(?, ?, '龙回头', 'hold_cash', '[\"600519\"]', '', '', '', 0, 'ai', ?)",
        (jid, occurred_on, created_at),
    )
    store.conn.commit()


def test_new_rows_use_the_same_clock_as_the_rest_of_the_library(store: PalaceStore) -> None:
    """新写入必须是本地带偏移的 ISO8601 微秒格式，和其它表逐字段同形。"""
    jid = store.record_ai_judgment(
        occurred_on="2026-08-25", strategy_tag="龙回头", decision="hold_cash", top_codes=["600519"]
    )
    candidate_id = store.record_candidate(
        occurred_on="2026-08-25", code="600519", name="贵州茅台", score=88.0,
        decision="观察", reason="同一天写的对照行",
    )
    other = str(
        store.conn.execute(
            "SELECT created_at FROM candidate_reviews WHERE id = ?", (candidate_id,)
        ).fetchone()[0]
    )

    judged = _created_at(store, jid)
    assert _NOW_SHAPE.match(judged), judged
    assert _NOW_SHAPE.match(other), other
    # 同一台机器上两张表的偏移必须相同——曾经一个 UTC 一个本地，差一整个时区。
    assert datetime.fromisoformat(judged).utcoffset() == datetime.fromisoformat(other).utcoffset()
    assert datetime.fromisoformat(judged).utcoffset() == datetime.now().astimezone().utcoffset()


def test_ai_judgment_is_not_recorded_hours_before_a_row_written_after_it(
    store: PalaceStore,
) -> None:
    """先写判定再写候选，判定的时刻不能反而更早（UTC 冒充本地就会这样）。"""
    jid = store.record_ai_judgment(
        occurred_on="2026-08-25", strategy_tag="龙回头", decision="hold_cash", top_codes=["600519"]
    )
    candidate_id = store.record_candidate(
        occurred_on="2026-08-25", code="600519", name="贵州茅台", score=88.0,
        decision="观察", reason="判定之后写的",
    )
    later = str(
        store.conn.execute(
            "SELECT created_at FROM candidate_reviews WHERE id = ?", (candidate_id,)
        ).fetchone()[0]
    )

    assert datetime.fromisoformat(_created_at(store, jid)) <= datetime.fromisoformat(later)


def test_legacy_utc_rows_are_still_read_out_verbatim(store: PalaceStore) -> None:
    """旧格式的行照旧读得出来，取值原样，不被改写也不炸。"""
    _insert_raw(store, "AJ-LEGACY", "2026-08-25 03:11:22", "2026-08-25")

    rows = store.ai_judgment_payload("龙回头")

    assert [row["id"] for row in rows] == ["AJ-LEGACY"]
    assert rows[0]["created_at"] == "2026-08-25 03:11:22"
    assert rows[0]["top_codes"] == ["600519"]


def test_mixed_old_and_new_rows_sort_by_real_instant(store: PalaceStore) -> None:
    """同一天里新旧两种格式并存时，按真实时刻排，而不是按字符串。

    旧行 `'2026-08-25 13:00:00'` 是 UTC，即东八区的 21:00；新行是 20:00+08:00，
    真实上更早。按字符串比 `'T' > ' '`，新行会被排到前面——那就错了。
    """
    _insert_raw(store, "AJ-OLD-LATER", "2026-08-25 13:00:00", "2026-08-25")
    _insert_raw(store, "AJ-NEW-EARLIER", "2026-08-25T20:00:00.000000+08:00", "2026-08-25")

    rows = store.ai_judgment_payload("龙回头")

    assert [row["id"] for row in rows] == ["AJ-OLD-LATER", "AJ-NEW-EARLIER"]


def test_new_rows_come_first_over_older_legacy_rows(store: PalaceStore) -> None:
    """真实场景：库里躺着旧行，今天新写一条，新的必须排最前。"""
    stale = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().astimezone().date().isoformat()
    _insert_raw(store, "AJ-LEGACY", stale, today)
    fresh = store.record_ai_judgment(
        occurred_on=today, strategy_tag="龙回头", decision="hold_cash", top_codes=["600519"]
    )

    rows = store.ai_judgment_payload("龙回头")

    assert [row["id"] for row in rows] == [fresh, "AJ-LEGACY"]


def test_unparseable_timestamps_do_not_break_the_read(store: PalaceStore) -> None:
    """脏时间戳沉底就好，不能让整个查询抛错。"""
    _insert_raw(store, "AJ-JUNK", "not-a-timestamp", "2026-08-25")
    _insert_raw(store, "AJ-OK", "2026-08-25T20:00:00.000000+08:00", "2026-08-25")

    rows = store.ai_judgment_payload("龙回头")

    assert [row["id"] for row in rows] == ["AJ-OK", "AJ-JUNK"]
    assert rows[1]["created_at"] == "not-a-timestamp"
