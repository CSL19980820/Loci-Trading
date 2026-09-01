"""AI 助手表的保留期清理：事件流按时间截断，会话按条数截断。

八张 ``ai_*`` 表此前**一张都没有清理**。分三类处理，理由各不相同：

1. **``ai_agent_events`` —— 收益最大的一张，按 15 天截断。**
   ``StreamEventBuffer`` 每 120 字符 flush 一条，工具密集的一次 run 能写
   100-500 行 / 50 KB-1 MB；活跃用户 **1-20 MB/日**，是全仓增长最快的表。
   删它**不会**让对话变残：run 收口时富状态（``thinking`` / ``tool_receipts``
   / ``artifacts`` / ``warnings`` / ``agents``）已经折叠进
   ``ai_messages.metadata_json``（ADR-006），事件流只是重放用的原始增量。

2. **``ai_execution_grants`` —— 按 15 天截断。** 单次消费的执行凭证，
   过期即无效；留着只为短期审计。

3. **``ai_sessions`` —— 按**条数**截断，保留最近 500 个会话，绝不按 15 天砍。**
   两条理由，缺一不可：
   - 对话是**用户资产**。一个人两周没跟助手说话，回来发现历史全没了，
     这是数据丢失，不是垃圾回收。
   - 按时间删 ``ai_messages`` 会把一个会话**截成半截**（前半段消息没了，
     后半段还在），比整个删掉更糟：读起来像模型突然失忆。
   所以截断的单位是**整个会话**，连同它的 messages / runs / events 一起走。

``ai_usage_daily`` 不清：日粒度聚合，一天一行，同时是月度配额判定的输入。
``ai_assistant_profile`` / ``ai_memories`` 不清：用户的画像与记忆，是资产。

删除子表**不依赖外键级联**：``ai_messages`` / ``ai_agent_runs`` 上确实挂了
``ON DELETE CASCADE``，但级联只在连接开了 ``PRAGMA foreign_keys=ON`` 时生效，
而本函数可能收到任意一条调用方给的连接（运维清理任务就是拿 ops.db 的连接进来
的）。靠一个连接级 PRAGMA 决定「会不会留下孤儿行」太脆，这里显式逐层删。
"""
from __future__ import annotations

from typing import Any, Sequence

from src.shared.sqlite_retention import (
    DEFAULT_BATCH,
    age_param,
    age_predicate,
    count_rows,
    delete_in_batches,
    segment,
    table_exists,
)

#: 事件流 / 执行凭证的默认保留天数。
DEFAULT_EVENT_DAYS = 15
DEFAULT_GRANT_DAYS = 15

#: 保留的会话数。500 个会话按每个 20 条消息估算约 1 万条 messages，
#: 对 SQLite 是小数目；再多的历史用户自己也翻不到。
DEFAULT_SESSION_KEEP = 500

#: 正在跑 / 正在等用户回话的会话永不参与截断——删掉执行中的会话会让
#: 收口时的 UPDATE 找不到行，前端那一轮直接卡死在 running。
ACTIVE_SESSION_STATUSES = ("running", "waiting_user")

#: 一条 ``IN (...)`` 里塞的 id 数。SQLite 默认变量上限历史上是 999，
#: 取 200 留足余量，反正外层本来就是分批的。
_ID_CHUNK = 200


def _chunks(items: Sequence[str], size: int = _ID_CHUNK) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _purge_by_age(conn: Any, table: str, column: str, days: int, batch: int, pause: float):
    kept_before = count_rows(conn, table)
    if not table_exists(conn, table):
        return {"deleted": 0, "kept": 0, "skipped": "表不存在"}
    if days <= 0:
        return {"deleted": 0, "kept": kept_before, "skipped": "未启用"}
    deleted = delete_in_batches(
        conn,
        table,
        where=age_predicate(column),
        params=(age_param(days),),
        batch=batch,
        pause=pause,
    )
    return {"deleted": deleted, "kept": max(0, kept_before - deleted), "keep_days": days}


def _doomed_session_ids(conn: Any, keep: int) -> list[str]:
    """排在第 ``keep`` 名之后、且不处于活跃状态的会话 id。

    排名用**全部**会话算（活跃会话照样占名额），只是活跃的不删——否则一个
    长期 waiting_user 的会话会把它后面的会话一个个顶出保留窗。
    时间排序走 ``julianday()``：``updated_at`` 同样可能新旧格式并存。
    """
    rows = conn.execute(
        "SELECT id, status FROM ai_sessions"
        " ORDER BY COALESCE(julianday(updated_at), 0) DESC, updated_at DESC, id DESC"
        " LIMIT -1 OFFSET ?",
        (max(0, int(keep)),),
    ).fetchall()
    out: list[str] = []
    for row in rows:
        status = str(row[1] or "")
        if status in ACTIVE_SESSION_STATUSES:
            continue
        out.append(str(row[0]))
    return out


def _delete_sessions(conn: Any, ids: Sequence[str]) -> dict[str, int]:
    """整会话删除：events → runs → messages → session。顺序即依赖顺序。"""
    counts = {"events": 0, "runs": 0, "messages": 0, "sessions": 0}
    for chunk in _chunks(list(ids)):
        marks = ",".join("?" for _ in chunk)
        if table_exists(conn, "ai_agent_events") and table_exists(conn, "ai_agent_runs"):
            cursor = conn.execute(
                "DELETE FROM ai_agent_events WHERE run_id IN"
                f" (SELECT id FROM ai_agent_runs WHERE session_id IN ({marks}))",
                tuple(chunk),
            )
            counts["events"] += int(cursor.rowcount or 0)
        for table, key in (("ai_agent_runs", "runs"), ("ai_messages", "messages")):
            if not table_exists(conn, table):
                continue
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE session_id IN ({marks})", tuple(chunk)
            )
            counts[key] += int(cursor.rowcount or 0)
        cursor = conn.execute(
            f"DELETE FROM ai_sessions WHERE id IN ({marks})", tuple(chunk)
        )
        counts["sessions"] += int(cursor.rowcount or 0)
        conn.commit()
    return counts


def _purge_sessions(conn: Any, keep: int) -> dict[str, Any]:
    if not table_exists(conn, "ai_sessions"):
        return {"deleted": 0, "kept": 0, "skipped": "表不存在"}
    kept_before = count_rows(conn, "ai_sessions")
    if keep <= 0:
        # 0 在配置里最可能是「忘了填」。把它解释成「删光全部对话」是灾难。
        return {"deleted": 0, "kept": kept_before, "skipped": "未启用"}
    doomed = _doomed_session_ids(conn, keep)
    if not doomed:
        return {"deleted": 0, "kept": kept_before, "keep_sessions": keep}
    counts = _delete_sessions(conn, doomed)
    return {
        "deleted": counts["sessions"],
        "kept": max(0, kept_before - counts["sessions"]),
        "keep_sessions": keep,
        "messages_deleted": counts["messages"],
        "runs_deleted": counts["runs"],
        "events_deleted": counts["events"],
    }


def purge_ai_retention(
    target: Any,
    *,
    event_days: int = DEFAULT_EVENT_DAYS,
    grant_days: int = DEFAULT_GRANT_DAYS,
    session_keep: int = DEFAULT_SESSION_KEEP,
    batch: int = DEFAULT_BATCH,
    pause: float = 0.0,
) -> dict[str, Any]:
    """清 AI 助手的三段。``target`` 可以是 ``AssistantStore`` 或裸 sqlite 连接。

    收裸连接是刻意的：这些表就在租户的 ``ops.db`` 里，运维清理任务手上已经有
    一条 ``OpsStore`` 连接。再开一条 ``AssistantStore`` 去删同一个文件，等于让
    两条连接在凌晨互相抢写锁（还会顺手给从没用过助手的用户建出八张空表）。

    **每段各自 try**，单段失败不带走整轮。
    """
    conn = getattr(target, "conn", target)
    return {
        "ai_agent_events": segment(
            "ai_agent_events",
            lambda: _purge_by_age(
                conn, "ai_agent_events", "created_at", event_days, batch, pause
            ),
        ),
        "ai_execution_grants": segment(
            "ai_execution_grants",
            lambda: _purge_by_age(
                conn, "ai_execution_grants", "created_at", grant_days, batch, pause
            ),
        ),
        "ai_sessions": segment(
            "ai_sessions", lambda: _purge_sessions(conn, session_keep)
        ),
    }


__all__ = [
    "ACTIVE_SESSION_STATUSES",
    "DEFAULT_EVENT_DAYS",
    "DEFAULT_GRANT_DAYS",
    "DEFAULT_SESSION_KEEP",
    "purge_ai_retention",
]
