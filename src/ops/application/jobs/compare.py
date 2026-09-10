"""compare 任务执行器：多战法横向对比。"""
from __future__ import annotations

import os
from typing import Any

from src.ops.application.jobs.context import (
    JobCancelled,
    JobContext,
    JobError,
    JobTimedOut,
)


def execute_compare(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """横向对比多个战法，重计算可切到受控 ``spawn`` worker。"""
    if _process_mode(config):
        return _run_process(config, context)

    from src.backtest import run_compare_job

    with context.market() as store:
        return run_compare_job(store, config)


def _run_process(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    from src.backtest import (
        ProcessWorkerCancelled,
        ProcessWorkerError,
        ProcessWorkerTimedOut,
        run_isolated_job,
    )
    from src.shared.paths import market_db
    from src.shared.tenancy import current_tenant

    try:
        return run_isolated_job(
            "compare",
            config,
            market_db=str(context.market_db or market_db()),
            tenant_id=current_tenant(),
            timeout_seconds=context.remaining_seconds(),
            cancel_check=context.is_cancelled,
        )
    except ProcessWorkerCancelled as exc:
        raise JobCancelled(str(exc)) from exc
    except ProcessWorkerTimedOut as exc:
        raise JobTimedOut(str(exc)) from exc
    except ProcessWorkerError as exc:
        raise JobError(str(exc)) from exc


def _process_mode(config: dict[str, Any]) -> bool:
    value = str(
        config.get("execution_mode")
        or os.environ.get("LOCI_BACKTEST_EXECUTION")
        or "thread"
    )
    return value.strip().lower() in {"process", "isolated", "spawn"}


__all__ = ["execute_compare"]
