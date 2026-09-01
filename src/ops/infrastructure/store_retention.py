"""OpsStore：只追加表的保留期截断（时间闸 / 条数闸 / 双闸门）。

与 ``store_runs`` 的分工：那里管一条 run 的**生命周期**（占槽、心跳、收尾、
崩溃回收），这里管「历史留多久」。放一起会让一个 600 行的文件同时承担状态机
和垃圾回收两件事，改任何一件都要先读懂另一件。

三类截断（逐表口径见 ``src/ops/README.md`` 的「保留期与垃圾回收」）：

- **纯时间**：``prune_by_age``。``monitor_runs`` / ``alert_hits`` /
  ``ai_decisions`` / ``leader_role_snapshots`` / ``mcp_quota`` 都走这条。
- **纯条数**：不在本文件——``ai_sessions`` 是用户资产，按会话数截断，
  实现在 ``src/ai/application/retention.py``。
- **时间 + 条数双闸门**：``prune_runs_windowed``，只有 ``job_runs`` 用。

为什么 ``job_runs`` 非要双闸门：老的 ``prune_runs(keep_per_job=200)`` 是**单**
参数，而各任务的 cron 频率差了两个数量级——``*/5 9-14`` 的价格提醒一天 48 条，
200 条 = **2.8 天**；日更的候选跟踪一天 1 条，200 条 = **10 个月**。同一个数字
给出 2.8 天到 10 个月的保留期，两头都不对：前者查不到上周的故障，后者白占地方。
拆成三个各管一件事的参数：

- ``keep_min``  —— 保底条数，**永不删**。哪怕这个任务半年没跑，也要留得下
  "最近一次跑没跑过、报了什么错"。
- ``keep_max``  —— 硬上限，超出的一律删，不管多新。挡住高频任务把库刷爆。
- ``keep_days`` —— 中间地带的判据：条数在 ``keep_min`` 与 ``keep_max`` 之间的
  记录，够老就删。

时间比较全部经 ``julianday()``，理由见 ``src.shared.sqlite_retention`` 模块头
与 ``store_runs.RUN_STALE_SQL``——``job_runs`` 正是新旧两种时间戳并存的那张表。
"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_runs import RUN_ORDER_SQL
from src.shared.sqlite_retention import (
    DEFAULT_BATCH,
    age_param,
    age_predicate,
    count_rows,
    delete_in_batches,
    table_exists,
)

#: ``job_runs`` 双闸门的默认三参数。
DEFAULT_RUN_KEEP_MIN = 5
DEFAULT_RUN_KEEP_MAX = 200
DEFAULT_RUN_KEEP_DAYS = 15


class OpsRetentionMixin:
    """只追加表的保留期截断。依赖宿主提供 ``conn``。"""

    conn: Any

    def prune_by_age(
        self,
        table: str,
        column: str,
        *,
        keep_days: int,
        batch: int = DEFAULT_BATCH,
        date_only: bool = False,
        pause: float = 0.0,
    ) -> dict[str, Any]:
        """纯时间截断：删掉 ``column`` 早于 ``keep_days`` 天前的行。

        ``keep_days <= 0`` 视为「关闭该段」，一行都不删——0 在配置里最可能是
        「忘了填」而不是「全部删光」，把它解释成清空是灾难性的默认值。

        ``date_only=True`` 用于纯 ``YYYY-MM-DD`` 列（``trade_date`` 等）。
        """
        days = int(keep_days)
        if not table_exists(self.conn, table):
            return {"table": table, "deleted": 0, "kept": 0, "skipped": "表不存在"}
        kept_before = count_rows(self.conn, table)
        if days <= 0:
            return {"table": table, "deleted": 0, "kept": kept_before, "skipped": "未启用"}
        deleted = delete_in_batches(
            self.conn,
            table,
            where=age_predicate(column, date_only=date_only),
            params=(age_param(days, date_only=date_only),),
            batch=batch,
            pause=pause,
        )
        return {
            "table": table,
            "deleted": deleted,
            "kept": max(0, kept_before - deleted),
            "keep_days": days,
        }

    def prune_runs_windowed(
        self,
        *,
        keep_min: int = DEFAULT_RUN_KEEP_MIN,
        keep_max: int = DEFAULT_RUN_KEEP_MAX,
        keep_days: int = DEFAULT_RUN_KEEP_DAYS,
        batch: int = DEFAULT_BATCH,
        pause: float = 0.0,
    ) -> dict[str, Any]:
        """``job_runs`` 的时间 + 条数双闸门。见模块头。

        ``status='running'`` 的行既不参与排名也永不删除：清掉执行中的运行槽会让
        ``finish_run`` 当场报「任务运行不存在」，正在跑的任务直接炸
        （``prune_runs`` 踩过这个坑，语义原样保留）。
        """
        floor = max(1, int(keep_min))
        ceiling = max(floor, int(keep_max))
        days = max(0, int(keep_days))
        if not table_exists(self.conn, "job_runs"):
            return {"table": "job_runs", "deleted": 0, "kept": 0, "skipped": "表不存在"}
        kept_before = count_rows(self.conn, "job_runs")
        size = max(1, int(batch))
        # rn > floor 是保底闸；括号里是「超硬上限 或 够老」。两个闸门都过才删。
        aged = age_predicate("started_at") if days > 0 else "0"
        subquery = (
            "SELECT rowid FROM ("
            " SELECT rowid AS rowid,"
            f" ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY {RUN_ORDER_SQL}) AS rn,"
            " started_at AS started_at"
            " FROM job_runs WHERE status <> 'running'"
            f" ) WHERE rn > ? AND (rn > ? OR {aged}) LIMIT {size}"
        )
        params: tuple[Any, ...] = (floor, ceiling)
        if days > 0:
            params = (floor, ceiling, age_param(days))
        deleted = delete_in_batches(
            self.conn,
            "job_runs",
            subquery=subquery,
            params=params,
            batch=size,
            pause=pause,
        )
        return {
            "table": "job_runs",
            "deleted": deleted,
            "kept": max(0, kept_before - deleted),
            "keep_min": floor,
            "keep_max": ceiling,
            "keep_days": days,
        }


__all__ = [
    "DEFAULT_RUN_KEEP_DAYS",
    "DEFAULT_RUN_KEEP_MAX",
    "DEFAULT_RUN_KEEP_MIN",
    "OpsRetentionMixin",
]
