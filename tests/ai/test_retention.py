"""AI 助手表的保留期：事件流按 15 天砍，会话按条数砍且绝不砍成半截。

八张 ``ai_*`` 表此前一张都没有清理。这套用例守两条相反方向的线：

- ``ai_agent_events`` **必须**被 15 天砍掉（活跃用户 1-20 MB/日，是全仓增长
  最快的一张表），而且砍它不能让对话内容缺失。
- ``ai_sessions`` **绝不能**按 15 天砍（对话是用户资产），只按条数截断，
  而且单位必须是**整个会话**——按时间删 ``ai_messages`` 会把一个会话截成
  半截，读起来像模型突然失忆，比整个删掉更糟。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ai.application.retention import (
    ACTIVE_SESSION_STATUSES,
    DEFAULT_SESSION_KEEP,
    purge_ai_retention,
)
from src.ai.infrastructure.assistant_store import AssistantStore


@pytest.fixture
def store(tmp_path: Path) -> AssistantStore:
    opened = AssistantStore(tmp_path / "ops.db")
    try:
        yield opened
    finally:
        opened.close()


def _utc(days_ago: float) -> str:
    """与 ``shared.clock.utc_now()`` 同格式的 ISO UTC 串。"""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
        timespec="seconds"
    )


def _legacy_utc(days_ago: float) -> str:
    """历史行的 UTC 裸串（``datetime('now')`` 落下的那种）。"""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _session(store: AssistantStore, sid: str, *, updated: str, status: str = "idle") -> str:
    store.conn.execute(
        "INSERT INTO ai_sessions(id, title, status, created_at, updated_at)"
        " VALUES(?,?,?,?,?)",
        (sid, sid, status, updated, updated),
    )
    store.conn.commit()
    return sid


def _message(store: AssistantStore, sid: str, seq: int, *, created: str) -> str:
    mid = f"{sid}-m{seq}"
    store.conn.execute(
        "INSERT INTO ai_messages(id, session_id, seq, role, content, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, sid, seq, "user", "hi", created),
    )
    store.conn.commit()
    return mid


def _run_with_events(
    store: AssistantStore, sid: str, rid: str, *, created: str, events: int = 3
) -> str:
    store.conn.execute(
        "INSERT INTO ai_agent_runs(id, session_id, status, started_at) VALUES(?,?,?,?)",
        (rid, sid, "done", created),
    )
    for seq in range(events):
        store.conn.execute(
            "INSERT INTO ai_agent_events(id, run_id, seq, event_type, created_at)"
            " VALUES(?,?,?,?,?)",
            (f"{rid}-e{seq}", rid, seq, "token", created),
        )
    store.conn.commit()
    return rid


def _count(store: AssistantStore, table: str) -> int:
    return int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# --------------------------------------------------------------------------
# 1. ai_agent_events：15 天截断（收益最大的一段）
# --------------------------------------------------------------------------


def test_agent_events_are_truncated_at_fifteen_days(store: AssistantStore) -> None:
    sid = _session(store, "AIS-1", updated=_utc(0))
    _run_with_events(store, sid, "RUN-old", created=_utc(90), events=5)
    _run_with_events(store, sid, "RUN-new", created=_utc(2), events=4)

    result = purge_ai_retention(store, event_days=15)

    assert result["ai_agent_events"]["deleted"] == 5
    alive = {r[0] for r in store.conn.execute("SELECT run_id FROM ai_agent_events")}
    assert alive == {"RUN-new"}


def test_event_truncation_keeps_the_conversation_intact(store: AssistantStore) -> None:
    """删事件流不等于删对话：messages / runs / sessions 一条都不能少。

    富状态（thinking / tool_receipts / artifacts）在 run 收口时已折叠进
    ``ai_messages.metadata_json``（ADR-006），事件流只是重放用的原始增量。
    """
    sid = _session(store, "AIS-1", updated=_utc(0))
    _message(store, sid, 1, created=_utc(90))
    _message(store, sid, 2, created=_utc(89))
    _run_with_events(store, sid, "RUN-old", created=_utc(90), events=6)

    purge_ai_retention(store, event_days=15, session_keep=DEFAULT_SESSION_KEEP)

    assert _count(store, "ai_agent_events") == 0
    assert _count(store, "ai_messages") == 2
    assert _count(store, "ai_agent_runs") == 1
    assert _count(store, "ai_sessions") == 1


def test_event_age_gate_handles_mixed_timestamp_formats(store: AssistantStore) -> None:
    """新旧两种时间戳并存时判定必须一致（字符串比会差 8 小时）。"""
    sid = _session(store, "AIS-1", updated=_utc(0))
    _run_with_events(store, sid, "RUN-legacy-fresh", created=_legacy_utc(1), events=1)
    _run_with_events(store, sid, "RUN-legacy-old", created=_legacy_utc(90), events=1)
    _run_with_events(store, sid, "RUN-modern-fresh", created=_utc(1), events=1)
    _run_with_events(store, sid, "RUN-modern-old", created=_utc(90), events=1)

    purge_ai_retention(store, event_days=15)

    alive = {r[0] for r in store.conn.execute("SELECT run_id FROM ai_agent_events")}
    assert alive == {"RUN-legacy-fresh", "RUN-modern-fresh"}


def test_execution_grants_are_truncated(store: AssistantStore) -> None:
    for idx, age in ((1, 90), (2, 1)):
        store.conn.execute(
            "INSERT INTO ai_execution_grants(id, session_id, run_id, message_hash, action,"
            " target, params_hash, idempotency_key, status, expires_at, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
         (f"G{idx}", "s", f"r{idx}", "h", "a", "t", "p", f"key{idx}", "issued", "", _utc(age)),
        )
    store.conn.commit()

    result = purge_ai_retention(store, grant_days=15)

    assert result["ai_execution_grants"]["deleted"] == 1
    assert _count(store, "ai_execution_grants") == 1


def test_event_days_zero_disables_the_segment(store: AssistantStore) -> None:
    sid = _session(store, "AIS-1", updated=_utc(0))
    _run_with_events(store, sid, "RUN-old", created=_utc(900), events=3)

    result = purge_ai_retention(store, event_days=0)

    assert result["ai_agent_events"]["deleted"] == 0
    assert _count(store, "ai_agent_events") == 3


# --------------------------------------------------------------------------
# 2. ai_sessions：按条数截断，且整段走
# --------------------------------------------------------------------------


def test_sessions_are_truncated_by_count_not_by_age(store: AssistantStore) -> None:
    """全部会话都超过 15 天，但只要没超过条数上限就一个都不能删。"""
    for i in range(4):
        sid = _session(store, f"AIS-{i}", updated=_utc(400 + i))
        _message(store, sid, 1, created=_utc(400 + i))

    result = purge_ai_retention(store, session_keep=10)

    assert result["ai_sessions"]["deleted"] == 0
    assert _count(store, "ai_sessions") == 4
    assert _count(store, "ai_messages") == 4


def test_session_truncation_keeps_the_newest_n(store: AssistantStore) -> None:
    for i in range(8):
        _session(store, f"AIS-{i}", updated=_utc(i))

    result = purge_ai_retention(store, session_keep=3)

    assert result["ai_sessions"]["deleted"] == 5
    alive = {r[0] for r in store.conn.execute("SELECT id FROM ai_sessions")}
    assert alive == {"AIS-0", "AIS-1", "AIS-2"}


def test_session_truncation_never_leaves_half_a_conversation(
    store: AssistantStore,
) -> None:
    """被截断的会话连 messages / runs / events 一起走；留下的一条不少。

    这是本文件最重要的一条：如果哪天有人图省事改成「按时间删 ai_messages」，
    留下的会话就会前半段消息不见、后半段还在。
    """
    doomed = _session(store, "AIS-old", updated=_utc(200))
    kept = _session(store, "AIS-new", updated=_utc(1))
    for seq in range(1, 6):
        _message(store, doomed, seq, created=_utc(200))
        _message(store, kept, seq, created=_utc(200))
    _run_with_events(store, doomed, "RUN-doomed", created=_utc(200), events=4)
    _run_with_events(store, kept, "RUN-kept", created=_utc(1), events=4)

    result = purge_ai_retention(store, event_days=15, session_keep=1)

    assert result["ai_sessions"]["deleted"] == 1
    assert result["ai_sessions"]["messages_deleted"] == 5
    assert result["ai_sessions"]["runs_deleted"] == 1
    # 留下的那个会话，消息序号 1..5 必须完整——半截会话比整个删掉更糟。
    seqs = [
        row[0]
        for row in store.conn.execute(
            "SELECT seq FROM ai_messages WHERE session_id = ? ORDER BY seq", (kept,)
        )
    ]
    assert seqs == [1, 2, 3, 4, 5]
    # 被删会话的子行一条不留（不能靠连接级 PRAGMA 决定有没有孤儿行）。
    orphan_runs = store.conn.execute(
        "SELECT COUNT(*) FROM ai_agent_runs WHERE session_id = ?", (doomed,)
    ).fetchone()[0]
    orphan_events = store.conn.execute(
        "SELECT COUNT(*) FROM ai_agent_events WHERE run_id = 'RUN-doomed'"
    ).fetchone()[0]
    assert orphan_runs == 0
    assert orphan_events == 0


@pytest.mark.parametrize("status", ACTIVE_SESSION_STATUSES)
def test_active_sessions_are_never_truncated(store: AssistantStore, status: str) -> None:
    """删掉正在跑 / 正在等用户回话的会话，会让那一轮当场卡死在 running。"""
    _session(store, "AIS-active", updated=_utc(500), status=status)
    _session(store, "AIS-fresh", updated=_utc(0))

    purge_ai_retention(store, session_keep=1)

    alive = {r[0] for r in store.conn.execute("SELECT id FROM ai_sessions")}
    assert "AIS-active" in alive


def test_session_keep_zero_deletes_nothing(store: AssistantStore) -> None:
    """0 在配置里最可能是「忘了填」；解释成「删光全部对话」是灾难。"""
    for i in range(3):
        _session(store, f"AIS-{i}", updated=_utc(400))

    result = purge_ai_retention(store, session_keep=0)

    assert result["ai_sessions"]["deleted"] == 0
    assert _count(store, "ai_sessions") == 3


# --------------------------------------------------------------------------
# 3. 不该碰的表 + 健壮性
# --------------------------------------------------------------------------


def test_user_assets_and_usage_rollup_are_left_alone(store: AssistantStore) -> None:
    """``ai_usage_daily`` 是配额输入，画像与记忆是用户资产，一条都不许删。"""
    store.conn.execute(
        "INSERT INTO ai_usage_daily(day, provider, model, calls) VALUES(?,?,?,?)",
        ("2020-01-01", "p", "m", 3),
    )
    store.conn.commit()

    purge_ai_retention(store, event_days=1, grant_days=1, session_keep=1)

    assert _count(store, "ai_usage_daily") == 1


def test_missing_tables_are_not_an_error(tmp_path: Path) -> None:
    """从没打开过助手的库里根本没有这些表；缺表是常态不是异常。"""
    import sqlite3

    conn = sqlite3.connect(tmp_path / "empty.db")
    try:
        result = purge_ai_retention(conn)
    finally:
        conn.close()

    assert result["ai_agent_events"]["deleted"] == 0
    assert result["ai_sessions"]["skipped"] == "表不存在"


def test_one_failing_segment_does_not_take_down_the_round(
    store: AssistantStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.ai.application import retention

    sid = _session(store, "AIS-1", updated=_utc(0))
    _run_with_events(store, sid, "RUN-old", created=_utc(90), events=3)

    def boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(retention, "_purge_sessions", boom)
    result = purge_ai_retention(store, event_days=15)

    assert "database is locked" in result["ai_sessions"]["error"]
    assert result["ai_agent_events"]["deleted"] == 3


def test_batched_delete_clears_everything_due(store: AssistantStore) -> None:
    """批大小远小于待删量时，一轮也要删干净。"""
    sid = _session(store, "AIS-1", updated=_utc(0))
    _run_with_events(store, sid, "RUN-old", created=_utc(90), events=57)

    result = purge_ai_retention(store, event_days=15, batch=8)

    assert result["ai_agent_events"]["deleted"] == 57
    assert _count(store, "ai_agent_events") == 0
