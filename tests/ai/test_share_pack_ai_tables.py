"""分享包不得外发 AI 对话与个人画像记忆。

清单式脱敏的失效方式只有一种：**加了新表，没人记得改清单**。八张助手表就是
这么漏掉的（``ai_sessions`` 到 ``ai_memories``，含对话原文与长期记忆）。
所以这里不背清单，而是对着**真实建出来的 ops.db** 反查：凡是命中个人表命名
约定的表，必须已经登记在 ``PERSONAL_TABLES`` 里。
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

from src.ai.infrastructure.assistant_store import AssistantStore
from src.ops.application.share_pack_sanitize import (
    PERSONAL_TABLES,
    PERSONAL_TABLE_PREFIXES,
    sanitize_ops_db,
)
from src.ops.infrastructure.store import OpsStore

SECRET = "我上周把仓位加到八成，别告诉别人"


def _real_ops_db(path: Path) -> None:
    """按生产路径把 ops.db 建全：运维表 + 助手表都在同一个文件里。"""
    OpsStore(path).close()
    with AssistantStore(path) as store:
        session_id = store.create_session(title="私密对话")
        store.append_message(session_id, role="user", content=SECRET)
        run_id = store.create_run(session_id, provider="p", model="m", user_message=SECRET)
        store.append_event(run_id, "token", {"delta": SECRET})
        store.record_usage(provider="p", model="m", input_tokens=9, output_tokens=9)
        store.add_memory(target="user", content="我只做龙头首板")


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def test_every_personal_looking_table_is_declared_personal(tmp_path: Path) -> None:
    src = tmp_path / "ops.db"
    _real_ops_db(src)

    personal_looking = {
        name
        for name in _tables(src)
        if name.startswith(PERSONAL_TABLE_PREFIXES)
    }
        
    assert personal_looking, "ops.db 里一张 AI 表都没建出来，这个断言就白写了"
    missing = sorted(personal_looking - set(PERSONAL_TABLES))
    assert not missing, f"这些个人表没登记进 PERSONAL_TABLES，分享包会外发：{missing}"


def test_share_pack_ships_no_ai_conversation_or_memory(tmp_path: Path) -> None:
    src = tmp_path / "ops.db"
    _real_ops_db(src)
    dest = tmp_path / "out" / "ops.db"

    sanitize_ops_db(src, dest)

    conn = sqlite3.connect(dest)
    try:
        for table in (
            "ai_sessions",
            "ai_messages",
            "ai_agent_runs",
            "ai_agent_events",
            "ai_usage_daily",
            "ai_execution_grants",
            "ai_assistant_profile",
            "ai_memories",
        ):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} 仍有 {count} 行会被打进分享包"
    finally:
        conn.close()

    # 表清空还不够——VACUUM 前的页里可能残留原文。直接扫文件字节。
    assert SECRET.encode("utf-8") not in dest.read_bytes()
