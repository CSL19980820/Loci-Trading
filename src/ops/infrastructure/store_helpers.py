"""运维库共用辅助：ID、时钟、JSON、YAML、常量与错误类型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import uuid

from src.shared.paths import ops_db as _default_ops_db

DEFAULT_DB = _default_ops_db()

#: 任务类型。每种对应 application/jobs 里的一个执行器。
JOB_KINDS = (
    "stock_agent",
    "stock_agent_maintenance",
    "guardian",
    "guardian_review",
    "guardian_delivery",
    "exchange_calendar",
    "sync",
    "screen",
    "backtest",
    "compare",
    "optimize",
    "prune",
    # 租户段清理。**不在** tenant_jobs.SYSTEM_JOB_KINDS 里 —— 默认即租户级，
    # 每个租户在自己的 ops.db 上各跑一份（见 application/ensure_prune_tenant_job）。
    "prune_tenant",
    "skill",
    "notify",
    "outcome",
    "hot_rebuild",
    "data_quality",
    "intel_fetch",
    # 悟道 AI 简报 → 企微（四档，各比悟道出稿晚 10 分钟）
    "intel_brief",
    "intraday_capture",
    "skill_watch",
    "alert_scan",
    "strategy_monitor",
    "paper_eod",
)

#: 行情同步托管任务名（运维「行情同步」面板 upsert，勿改名）
MANAGED_SYNC_INTRADAY = "行情盘中增量"
MANAGED_SYNC_EOD = "行情日终重刷"

#: 行情热库重建托管任务名（全量重灌近 N 交易日滚动热读库，勿改名）
MANAGED_HOT_REBUILD = "行情热库重建"

#: 行情库数据体检托管任务名（只读体检、只报不改,勿改名）
MANAGED_MARKET_QUALITY = "行情库体检"

#: 候选 T+N 自动跟踪（选出后 5 个交易日内盘后重算）
MANAGED_OUTCOME_TRACK = "候选T+N跟踪"
MANAGED_OUTCOME_CRON = "45 15 * * mon-fri"

#: 运维库清理托管任务名（job_runs / leader_role_snapshots 保留窗，勿改名）
MANAGED_PRUNE = "运维清理"

#: 租户库清理托管任务名（每租户一条，清本租户 ops.db 的只追加表，勿改名）
MANAGED_PRUNE_TENANT = "租户库清理"

#: 任务与执行状态。
RUN_STATUSES = ("running", "success", "failed", "skipped", "cancelled", "timed_out")


class OpsError(RuntimeError):
    """运维库的可预期错误，应转成 4xx 而不是 500。"""


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now() -> str:
    """运维库统一时钟：本地时区 + 偏移 + 微秒的 ISO8601。

    与 ``src/ledger/infrastructure/store_types._now()`` 同口径。此前 ops.db 的
    ``jobs`` / ``job_runs`` / ``llm_providers`` / ``strategy_versions`` / ``meta``
    走 SQLite 的 ``datetime('now')``——**UTC、秒级、空格分隔**，运维页把这串原样
    截断显示（``JobRecentRunsPanel.vue:formatStartedAt`` 只做 ``T``→空格 + 切 19
    位，不做任何时区换算），于是北京时间 15:30 跑的任务在页面上写着 07:30。
    而同库较新的 ``paper_*`` / ``alert_*`` / ``leader_role_snapshots`` 早就用的是
    本地时间（旧 ``OpsStore._now()``），一个库两套时钟。

    带偏移是关键：``+08:00`` 让 SQLite 的 ``julianday()`` 和 Python 的
    ``fromisoformat()`` 都能把它折算回绝对时刻，因此**新格式与历史 UTC 行可以在
    同一条时间轴上比较**，不必重写任何历史数据。微秒是为了同一秒内多次写入仍可
    排序（补跑时同一秒能连开好几个 run）。
    """
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if fallback is None else fallback


def yaml_safe_dump(meta: dict[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    except Exception:
        return json.dumps(meta, ensure_ascii=False, indent=2)
