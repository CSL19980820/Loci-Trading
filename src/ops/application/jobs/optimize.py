"""optimize 任务执行器：退出规则参数扫描。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError


def execute_optimize(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """扫描退出规则：固定选股信号，只改持有期 / 止盈 / 止损。

    参数扫描天生会生产漂亮数字。结果里必须带上过拟合提示，并建议换区间
    重跑——不加这句，它就只是个自我欺骗的工具。
    """
    from src.backtest import BacktestConfig, backtest_strategy

    slug = config.get("strategy")
    if not slug:
        raise JobError("optimize 任务必须指定 strategy")

    holds = [int(x) for x in (config.get("holds") or [1, 2, 3, 5])]
    targets = [None if not x else float(x) for x in (config.get("targets") or [0, 3, 5, 8])]
    stops = [None if not x else float(x) for x in (config.get("stops") or [0, -5, -8])]

    rows: list[dict[str, Any]] = []
    with context.market() as store:
        for hold in holds:
            for target in targets:
                for stop in stops:
                    try:
                        result = backtest_strategy(
                            store, str(slug),
                            start=config.get("start"), end=config.get("end"),
                            config=BacktestConfig(
                                hold_days=hold, take_profit_pct=target, stop_loss_pct=stop,
                                benchmark=config.get("benchmark", "000300"),
                            ),
                            universe=config.get("universe"),
                        )
                    except Exception:
                        continue
                    metrics = result.metrics
                    if not metrics.get("trades"):
                        continue
                    rows.append(
                        {
                            "hold_days": hold, "take_profit_pct": target, "stop_loss_pct": stop,
                            "trades": metrics["trades"], "win_rate": metrics["win_rate"],
                            "avg_net_return": metrics["avg_net_return"],
                            "avg_alpha": metrics.get("avg_alpha"),
                            "exit_reasons": metrics.get("exit_reasons", {}),
                            "caution": metrics.get("caution", ""),
                        }
                    )

    if not rows:
        return {"rows": [], "note": "没有产生任何可评估的交易"}

    rows.sort(key=lambda item: item.get("avg_alpha") if item.get("avg_alpha") is not None
              else item["avg_net_return"], reverse=True)
    best = rows[0]
    baseline = next(
        (r for r in rows if r["take_profit_pct"] is None and r["stop_loss_pct"] is None), None
    )
    key = "avg_alpha" if best.get("avg_alpha") is not None else "avg_net_return"
    return {
        "strategy": slug, "rows": rows, "best": best, "baseline": baseline,
        "improvement": round((best.get(key) or 0) - (baseline.get(key) or 0), 4)
        if baseline else None,
        "warning": (
            "这是在同一段历史上反复试参数，天然存在过拟合风险。"
            "换一段区间重跑一次，若最优组合完全不同，说明它只拟合了噪声。"
        ),
    }
