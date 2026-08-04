"""运维库共用辅助：ID、JSON、YAML、常量与错误类型。"""
from __future__ import annotations

from typing import Any
import json
import uuid

from src.shared.paths import ops_db as _default_ops_db

DEFAULT_DB = _default_ops_db()

#: 任务类型。每种对应 application/jobs 里的一个执行器。
JOB_KINDS = (
    "sync",
    "screen",
    "backtest",
    "compare",
    "optimize",
    "prune",
    "skill",
    "notify",
    "outcome",
)

#: 行情同步托管任务名（运维「行情同步」面板 upsert，勿改名）
MANAGED_SYNC_INTRADAY = "行情盘中增量"
MANAGED_SYNC_EOD = "行情日终重刷"

#: 候选 T+N 自动跟踪（选出后 5 个交易日内盘后重算）
MANAGED_OUTCOME_TRACK = "候选T+N跟踪"
MANAGED_OUTCOME_CRON = "45 15 * * 1-5"

#: 任务与执行状态。
RUN_STATUSES = ("running", "success", "failed", "skipped")


class OpsError(RuntimeError):
    """运维库的可预期错误，应转成 4xx 而不是 500。"""


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
