"""compare 任务执行器：多战法横向对比。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext


def execute_compare(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """横向对比多个战法在同一区间、同一成本口径下的超额。

    单看一个战法的绝对收益意义有限——大盘涨的时候什么都赚。这里统一区间
    与成本，按超额排序，并算出每个战法的"回吐"（MFE 均值 − 净收益均值）。
    回吐大说明浮盈拿不住，问题在退出而不在选股。
    """
    from src.backtest import BacktestConfig, backtest_strategy
    from src.strategy import all_strategies, get

    holds = [int(h) for h in (config.get("holds") or [1, 3])]
    slugs = config.get("strategies")
    engines = [get(str(s)) for s in slugs] if slugs else all_strategies()

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with context.market() as store:
        for engine in engines:
            for hold in holds:
                label = f"{engine.slug}/{hold}d"
                try:
                    result = backtest_strategy(
                        store, engine.slug,
                        start=config.get("start"), end=config.get("end"),
                        config=BacktestConfig(
                            hold_days=hold,
                            stop_loss_pct=config.get("stop_loss_pct", -8.0),
                            benchmark=config.get("benchmark", "000300"),
                        ),
                        universe=config.get("universe"),
                    )
                except Exception as exc:
                    # 一个战法算不出来不该让整批对比作废。
                    failures.append({"label": label, "error": f"{type(exc).__name__}: {exc}"[:200]})
                    continue
                metrics = result.metrics
                if not metrics.get("trades"):
                    continue
                rows.append(
                    {
                        "label": label, "strategy": engine.slug, "hold_days": hold,
                        "trades": metrics["trades"], "win_rate": metrics["win_rate"],
                        "avg_net_return": metrics["avg_net_return"],
                        "avg_mfe": metrics.get("avg_mfe"), "avg_mae": metrics.get("avg_mae"),
                        "avg_alpha": metrics.get("avg_alpha"),
                        "give_back": round(
                            (metrics.get("avg_mfe") or 0) - (metrics.get("avg_net_return") or 0), 4
                        ),
                        "caution": metrics.get("caution", ""),
                    }
                )

    rows.sort(key=lambda item: item.get("avg_alpha") if item.get("avg_alpha") is not None
              else item["avg_net_return"], reverse=True)
    worst = max(rows, key=lambda item: item["give_back"]) if rows else None
    return {
        "rows": rows, "failures": failures,
        "range": {"start": config.get("start"), "end": config.get("end")},
        "worst_give_back": worst,
        "hint": (
            f"回吐最严重的是 {worst['label']}（{worst['give_back']:.2f} 个百分点）。"
            "若多数战法回吐都大，说明问题在退出纪律而不在选股。"
        ) if worst and worst["give_back"] > 4 else "",
    }
