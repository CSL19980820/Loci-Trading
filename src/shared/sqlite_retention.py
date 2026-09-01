"""保留期清理的公共底座：``julianday()`` 时间闸 + 分批删除。

为什么要有这个模块（三处上下文都要用同一套语义，各写一份必然走样）：

1. **时间比较一律经 ``julianday()``，绝不拿字符串比。**
   全仓的时间戳列有两种写法并存：历史行是 ``datetime('now')`` 落下的 UTC 裸串
   ``"YYYY-MM-DD HH:MM:SS"``，新行是各库 ``_now()`` 落下的本地带偏移
   ``"YYYY-MM-DDTHH:MM:SS.ffffff+08:00"``。字符串比这两种会差 8 小时，而且
   ``'T' > ' '`` 会让同一天的新行无条件排到旧行前面——排序和截断一起错。
   ``julianday()`` 把两种写法折算到同一条 UTC 时间轴（不带偏移的旧值按 UTC
   解释，正是它当初的含义），比较因此与格式无关。这一招的完整论证见
   ``src/ops/infrastructure/store_runs.py::RUN_STALE_SQL``，本模块是它的推广。

   解析不了的脏值让 ``julianday()`` 返回 NULL，谓词整体为 NULL → 该行**不**被
   删除。宁可漏删一条脏值，也不能因为一次解析失败把整张表清空。

   **纯 ``YYYY-MM-DD`` 的列不受此影响**（``trade_date`` / ``as_of_date`` /
   ``day`` / ``period``）：定长、无时区、字典序即时间序，直接串比是对的。
   这类列走 ``date_only=True``。

2. **必须分批删。** 首次把保留期从「无限」调成 15 天，一次会删掉几十万行：
   单条 DELETE 会把 WAL 撑爆，并在整个过程里独占写锁（凌晨 02:30 跑，意味着
   这段时间任何后台任务写 ops.db 都在等锁）。SQLite 的 ``DELETE ... LIMIT``
   需要编译时打开 ``SQLITE_ENABLE_UPDATE_DELETE_LIMIT``，**CPython 自带的
   sqlite3 没开**，所以用 ``WHERE rowid IN (SELECT rowid ... LIMIT n)`` 循环，
   每批提交一次，把写锁还给别人再拿下一批。

3. **用 ``rowid`` 而不是 ``id`` 做批次键。** 要清的表里有 ``mcp_quota``
   （主键 ``(trade_date, pool)``）、``leaderboard_snapshots``（三列复合主键）
   这种根本没有 ``id`` 列的。``rowid`` 每张普通表都有，一套代码通吃。
"""
from __future__ import annotations

from datetime import date, timedelta
import sqlite3
import time
from typing import Any, Callable, Sequence

#: 单批删除行数。5000 行是「一次事务足够短」与「批次开销不喧宾夺主」的折中。
DEFAULT_BATCH = 5000

#: 循环上限，纯属防御：5000 × 4000 = 两千万行。真删到这个量级说明配置写错了，
#: 与其无限转下去把凌晨占满，不如停下来让 payload 里的数字露出异常。
MAX_BATCHES = 4000


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """表是否存在。清理任务面对的是**存量库**，缺表是常态不是异常。

    典型场景：用户从没打开过 AI 助手，``ai_agent_events`` 就不存在；子租户的
    ops.db 可能还没跑过任何纸面舱，``monitor_runs`` 也没有。
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def age_predicate(column: str, *, date_only: bool = False) -> str:
    """「比截断点更早」的 SQL 谓词，配合 :func:`age_param` 使用。"""
    if date_only:
        return f"{column} < ?"
    return f"julianday({column}) < julianday('now', ?)"


def age_param(days: int, *, date_only: bool = False, today: str = "") -> str:
    """:func:`age_predicate` 的绑定参数。

    ``date_only`` 时返回 ``YYYY-MM-DD`` 截断日，否则返回 ``julianday`` 的修饰符。
    ``today`` 仅供测试注入，留空则取当天（与 ``julianday('now')`` 同轴）。
    """
    count = max(0, int(days))
    if not date_only:
        return f"-{count} days"
    base = date.fromisoformat(today) if today else date.today()
    return (base - timedelta(days=count)).isoformat()


def count_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    where: str = "",
    params: Sequence[Any] = (),
) -> int:
    """行数。表不存在返回 0（缺表 = 没有要清的东西，不是错误）。"""
    if not table_exists(conn, table):
        return 0
    clause = f" WHERE {where}" if where else ""
    row = conn.execute(f"SELECT COUNT(*) FROM {table}{clause}", tuple(params)).fetchone()
    return int(row[0]) if row else 0


def delete_in_batches(
    conn: sqlite3.Connection,
    table: str,
    *,
    where: str = "",
    params: Sequence[Any] = (),
    batch: int = DEFAULT_BATCH,
    pause: float = 0.0,
    key: str = "rowid",
    subquery: str = "",
) -> int:
    """按 ``where`` 分批删除，返回删除总行数。

    每批一次提交：提交点就是把写锁交还给别人的地方。``pause>0`` 时批间再睡一下，
    给争抢同一个库的写入者一个确定的窗口（默认 0 = 只让出执行权，不额外等）。

    ``subquery`` 可传入一段自定义的「产出待删 rowid」的 SELECT（窗口函数这类
    ``where`` 表达不了的规则用它）；它必须**自己**带上 ``LIMIT``。
    """
    if not table_exists(conn, table):
        return 0
    size = max(1, int(batch))
    if subquery:
        sql = f"DELETE FROM {table} WHERE {key} IN ({subquery})"
    else:
        sql = (
            f"DELETE FROM {table} WHERE {key} IN "
            f"(SELECT {key} FROM {table} WHERE {where} LIMIT {size})"
        )
    total = 0
    for _ in range(MAX_BATCHES):
        cursor = conn.execute(sql, tuple(params))
        removed = int(cursor.rowcount or 0)
        conn.commit()
        total += removed
        if removed < size:
            break
        # 提交已经放锁；这一拍只是把执行权让出去，别在循环里长期霸着连接。
        time.sleep(pause if pause > 0 else 0)
    return total


def segment(label: str, run: Callable[[], Any]) -> dict[str, Any]:
    """跑一段清理，收成 ``{table, deleted, ms}``；**异常只写进返回值不外抛**。

    这是「单段失败不能带走整轮」的唯一实现（照 ``jobs/prune.py`` 对盘中留存带
    的做法）：一张表因为缺列 / 被别的连接锁住而删不动，不该让另外十张表也不清。
    失败留在 payload 里，运维页看得见，比刷红一条任务更有用。
    """
    started = time.perf_counter()
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001 — 单段失败不带走整轮，见 docstring
        return {
            "table": label,
            "deleted": 0,
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "ms": int((time.perf_counter() - started) * 1000),
        }
    payload = dict(result) if isinstance(result, dict) else {"deleted": int(result or 0)}
    payload.setdefault("table", label)
    payload["ms"] = int((time.perf_counter() - started) * 1000)
    return payload


__all__ = [
    "DEFAULT_BATCH",
    "MAX_BATCHES",
    "age_param",
    "age_predicate",
    "count_rows",
    "delete_in_batches",
    "segment",
    "table_exists",
]
