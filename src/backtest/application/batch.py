"""运维回测批处理的纯应用用例。

这些函数只接收显式的 ``MarketStore`` 与可序列化配置，不碰 ``ops.db``，因此
既能被线程任务调用，也能由进程隔离 worker 调用。任务生命周期仍由 ``ops``
上下文负责，避免在两个限界上下文之间复制一套 run 状态机。
"""
from __future__ import annotations

from typing import Any

from src.backtest.application.runner import backtest_strategy
from src.backtest.domain.models import BacktestConfig
from src.market import MarketStore


def _config(config: dict[str, Any], *, hold_days: int | None = None) -> BacktestConfig:
    """把任务配置收敛成一份成交口径，缺省值与 HTTP 回测保持一致。"""
    return BacktestConfig(
        hold_days=int(config.get("hold_days", 3) if hold_days is None else hold_days),
        stop_loss_pct=config.get("stop_loss_pct", -6.0),
        take_profit_pct=config.get("take_profit_pct"),
        commission_bps=float(config.get("commission_bps", 3.0)),
        stamp_duty_bps=float(config.get("stamp_duty_bps", 10.0)),
        slippage_bps=float(config.get("slippage_bps", 5.0)),
        allow_limit_up_entry=bool(config.get("allow_limit_up_entry", False)),
        benchmark=config.get("benchmark", "000300"),
    )


def run_backtest_job(store: MarketStore, config: dict[str, Any]) -> dict[str, Any]:
    """执行单次回测并压缩成运维任务需要的结果。"""
    slug = str(config.get("strategy") or "").strip()
    if not slug:
        raise ValueError("backtest 任务必须指定 strategy")

    result = backtest_strategy(
        store,
        slug,
        start=config.get("start"),
        end=config.get("end"),
        params=config.get("params"),
        config=_config(config),
        codes=config.get("codes"),
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


def run_compare_job(store: MarketStore, config: dict[str, Any]) -> dict[str, Any]:
    """在同一区间、同一成本口径下横向对比多个战法。"""
    from src.strategy import all_strategies, get

    holds = [int(h) for h in (config.get("holds") or [1, 3])]
    # 保留 compare 旧入口的 -8% 止损缺省；单次回测与 optimize 的缺省仍由
    # BacktestConfig 的统一口径提供。
    compare_config = {
        **config,
        "stop_loss_pct": config.get("stop_loss_pct", -8.0),
    }
    slugs = config.get("strategies")
    engines = [get(str(s)) for s in slugs] if slugs else all_strategies()

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for engine in engines:
        for hold in holds:
            label = f"{engine.slug}/{hold}d"
            try:
                result = backtest_strategy(
                    store,
                    engine.slug,
                    start=config.get("start"),
                    end=config.get("end"),
                    config=_config(compare_config, hold_days=hold),
                    codes=config.get("codes"),
                    universe=config.get("universe"),
                )
            except Exception as exc:  # 一个战法失败不该让整批对比作废
                failures.append(
                    {"label": label, "error": f"{type(exc).__name__}: {exc}"[:200]}
                )
                continue
            metrics = result.metrics
            if not metrics.get("trades"):
                continue
            rows.append(
                {
                    "label": label,
                    "strategy": engine.slug,
                    "hold_days": hold,
                    "trades": metrics["trades"],
                    "win_rate": metrics["win_rate"],
                    "avg_net_return": metrics["avg_net_return"],
                    "avg_mfe": metrics.get("avg_mfe"),
                    "avg_mae": metrics.get("avg_mae"),
                    "avg_alpha": metrics.get("avg_alpha"),
                    "give_back": round(
                        (metrics.get("avg_mfe") or 0)
                        - (metrics.get("avg_net_return") or 0),
                        4,
                    ),
                    "caution": metrics.get("caution", ""),
                }
            )

    rows.sort(
        key=lambda item: item.get("avg_alpha")
        if item.get("avg_alpha") is not None
        else item["avg_net_return"],
        reverse=True,
    )
    worst = max(rows, key=lambda item: item["give_back"]) if rows else None
    return {
        "rows": rows,
        "failures": failures,
        "range": {"start": config.get("start"), "end": config.get("end")},
        "worst_give_back": worst,
        "hint": (
            f"回吐最严重的是 {worst['label']}（{worst['give_back']:.2f} 个百分点）。"
            "若多数战法回吐都大，说明问题在退出纪律而不在选股。"
        )
        if worst and worst["give_back"] > 4
        else "",
    }


def run_optimize_job(store: MarketStore, config: dict[str, Any]) -> dict[str, Any]:
    """扫描持有期、止盈和止损组合，并保留每条 trial 的汇总。"""
    slug = str(config.get("strategy") or "").strip()
    if not slug:
        raise ValueError("optimize 任务必须指定 strategy")

    holds = [int(x) for x in (config.get("holds") or [1, 2, 3, 5])]
    targets = [None if not x else float(x) for x in (config.get("targets") or [0, 3, 5, 8])]
    stops = [None if not x else float(x) for x in (config.get("stops") or [0, -5, -8])]

    rows: list[dict[str, Any]] = []
    for hold in holds:
        for target in targets:
            for stop in stops:
                try:
                    result = backtest_strategy(
                        store,
                        slug,
                        start=config.get("start"),
                        end=config.get("end"),
                        config=_config(
                            {**config, "take_profit_pct": target, "stop_loss_pct": stop},
                            hold_days=hold,
                        ),
                        codes=config.get("codes"),
                        universe=config.get("universe"),
                    )
                except Exception:
                    continue
                metrics = result.metrics
                if not metrics.get("trades"):
                    continue
                rows.append(
                    {
                        "hold_days": hold,
                        "take_profit_pct": target,
                        "stop_loss_pct": stop,
                        "trades": metrics["trades"],
                        "win_rate": metrics["win_rate"],
                        "avg_net_return": metrics["avg_net_return"],
                        "avg_alpha": metrics.get("avg_alpha"),
                        "exit_reasons": metrics.get("exit_reasons", {}),
                        "caution": metrics.get("caution", ""),
                    }
                )

    if not rows:
        return {"rows": [], "note": "没有产生任何可评估的交易"}

    rows.sort(
        key=lambda item: item.get("avg_alpha")
        if item.get("avg_alpha") is not None
        else item["avg_net_return"],
        reverse=True,
    )
    best = rows[0]
    baseline = next(
        (
            row
            for row in rows
            if row["take_profit_pct"] is None and row["stop_loss_pct"] is None
        ),
        None,
    )
    key = "avg_alpha" if best.get("avg_alpha") is not None else "avg_net_return"
    return {
        "strategy": slug,
        "rows": rows,
        "best": best,
        "baseline": baseline,
        "improvement": round((best.get(key) or 0) - (baseline.get(key) or 0), 4)
        if baseline
        else None,
        "warning": (
            "这是在同一段历史上反复试参数，天然存在过拟合风险。"
            "换一段区间重跑一次，若最优组合完全不同，说明它只拟合了噪声。"
        ),
    }


__all__ = ["run_backtest_job", "run_compare_job", "run_optimize_job"]
