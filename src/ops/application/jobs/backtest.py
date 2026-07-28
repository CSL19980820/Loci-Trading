"""backtest 任务执行器。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError


def execute_backtest(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """跑一次回测。只回指标与少量样例交易，避免执行记录被撑爆。"""
    from src.backtest import BacktestConfig, backtest_strategy

    slug = config.get("strategy")
    if not slug:
        raise JobError("backtest 任务必须指定 strategy")

    cfg = BacktestConfig(
        hold_days=int(config.get("hold_days", 3)),
        stop_loss_pct=config.get("stop_loss_pct", -6.0),
        take_profit_pct=config.get("take_profit_pct"),
        benchmark=config.get("benchmark", "000300"),
    )
    with context.market() as store:
        result = backtest_strategy(
            store, str(slug),
            start=config.get("start"), end=config.get("end"),
            params=config.get("params"), config=cfg, codes=config.get("codes"),
            universe=config.get("universe"),
        )
    return {
        "strategy": result.strategy_slug,
        "metrics": result.metrics,
        "skipped": result.skipped,
        "sample_trades": [
            {
                "code": trade.code,
                "signal_date": trade.signal_date,
                "net_return_pct": trade.net_return_pct,
                "exit_reason": trade.exit_reason,
            }
            for trade in result.trades[:20]
        ],
    }
