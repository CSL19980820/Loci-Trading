"""成交路径组合诊断绩效（显式资金假设）。

权威成交仍是 ``engine.run_backtest`` 的逐笔独立评估。本模块只在已结算
交易之上构造**诊断用**资金曲线，供回撤 / 夏普等风险指标使用。

假设（必须在结果里原样回显，禁止冒充真实多仓组合）：

- ``model = trade_sequence_compounding``
- 仅纳入非 ``data_end`` 交易，按 ``(exit_date, entry_date, code)`` 排序
- 每笔占用 100% 名义资金，顺序复利：``equity *= 1 + net_return_pct/100``
- 无风险利率默认 0（年化百分比），参与夏普 / 索提诺超额收益
- 这**不是** ``research_portfolio`` 的固定槽位组合账本
"""
from __future__ import annotations

from datetime import date
from math import isfinite, sqrt
from typing import Any, Sequence

import numpy as np

from src.backtest.domain.models import Trade

ASSUMPTION_MODEL = "trade_sequence_compounding"
DEFAULT_RISK_FREE_PCT = 0.0


def compute_trade_performance(
    trades: Sequence[Trade],
    *,
    risk_free_rate_pct: float = DEFAULT_RISK_FREE_PCT,
    initial_equity: float = 1.0,
) -> dict[str, Any]:
    """从已结算交易构造诊断绩效；样本不足时返回空壳 + 原因。"""
    assumption = {
        "model": ASSUMPTION_MODEL,
        "description": (
            "按退出日排序的单笔顺序复利诊断曲线；每笔占满名义资金，"
            "不模拟多仓并行与槽位约束"
        ),
        "risk_free_rate_pct": float(risk_free_rate_pct),
        "initial_equity": float(initial_equity),
        "excludes_data_end": True,
    }
    evaluable = [
        trade
        for trade in trades
        if trade.exit_reason != "data_end" and isfinite(float(trade.net_return_pct))
    ]
    if not evaluable:
        return {
            "available": False,
            "reason": "无可评估交易",
            "assumption": assumption,
        }

    ordered = sorted(
        evaluable,
        key=lambda t: (str(t.exit_date), str(t.entry_date), str(t.code)),
    )
    equity = float(initial_equity)
    peak = equity
    max_dd = 0.0
    dd_peak_date = str(ordered[0].entry_date)
    dd_trough_date = str(ordered[0].exit_date)
    running_peak = equity
    running_peak_date = str(ordered[0].entry_date)
    curve: list[dict[str, Any]] = [
        {
            "date": str(ordered[0].entry_date),
            "equity": round(equity, 6),
            "drawdown_pct": 0.0,
            "trade_count": 0,
            "return_pct": 0.0,
        }
    ]
    for i, trade in enumerate(ordered, start=1):
        ret = float(trade.net_return_pct)
        equity *= 1.0 + ret / 100.0
        if equity > running_peak:
            running_peak = equity
            running_peak_date = str(trade.exit_date)
        dd = (equity / running_peak - 1.0) * 100.0 if running_peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            dd_peak_date = running_peak_date
            dd_trough_date = str(trade.exit_date)
            peak = running_peak
        curve.append(
            {
                "date": str(trade.exit_date),
                "equity": round(equity, 6),
                "drawdown_pct": round(float(dd), 4),
                "trade_count": i,
                "return_pct": round(ret, 4),
                "code": trade.code,
            }
        )

    first_entry = str(ordered[0].entry_date)
    last_exit = str(ordered[-1].exit_date)
    years = _calendar_years(first_entry, last_exit)
    cumulative_return_pct = (equity / float(initial_equity) - 1.0) * 100.0
    cagr_pct = None
    if years and years > 0 and equity > 0 and initial_equity > 0:
        cagr_pct = ((equity / float(initial_equity)) ** (1.0 / years) - 1.0) * 100.0

    rets = np.array([float(t.net_return_pct) for t in ordered], dtype=float)
    vol_pct = float(rets.std(ddof=1)) if rets.size > 1 else 0.0
    downside = rets[rets < 0]
    downside_vol = float(downside.std(ddof=1)) if downside.size > 1 else 0.0

    trades_per_year = (len(ordered) / years) if years and years > 0 else None
    rf_per_trade = 0.0
    if trades_per_year and trades_per_year > 0:
        rf_per_trade = float(risk_free_rate_pct) / trades_per_year

    sharpe = None
    sortino = None
    if trades_per_year and trades_per_year > 0 and vol_pct > 1e-12:
        excess = float(rets.mean() - rf_per_trade)
        sharpe = (excess / vol_pct) * sqrt(trades_per_year)
    if trades_per_year and trades_per_year > 0 and downside_vol > 1e-12:
        excess = float(rets.mean() - rf_per_trade)
        sortino = (excess / downside_vol) * sqrt(trades_per_year)

    calmar = None
    if cagr_pct is not None and abs(max_dd) > 1e-12:
        calmar = cagr_pct / abs(max_dd)

    recovery_days = _calendar_days(dd_trough_date, last_exit) if max_dd < 0 else None

    return {
        "available": True,
        "assumption": assumption,
        "trades": len(ordered),
        "cumulative_return_pct": round(cumulative_return_pct, 4),
        "cagr_pct": round(float(cagr_pct), 4) if cagr_pct is not None else None,
        "max_drawdown_pct": round(float(max_dd), 4),
        "max_drawdown_peak_date": dd_peak_date if max_dd < 0 else None,
        "max_drawdown_trough_date": dd_trough_date if max_dd < 0 else None,
        "max_drawdown_recovery_days": recovery_days,
        "volatility_pct": round(vol_pct, 4),
        "downside_volatility_pct": round(downside_vol, 4),
        "sharpe": round(float(sharpe), 4) if sharpe is not None else None,
        "sortino": round(float(sortino), 4) if sortino is not None else None,
        "calmar": round(float(calmar), 4) if calmar is not None else None,
        "years": round(float(years), 4) if years else None,
        "trades_per_year": round(float(trades_per_year), 2) if trades_per_year else None,
        "final_equity": round(equity, 6),
        "equity_curve": curve,
        "drawdown_curve": [
            {"date": row["date"], "drawdown_pct": row["drawdown_pct"]} for row in curve
        ],
        "peak_equity": round(float(peak if max_dd < 0 else running_peak), 6),
        "curve_peak_date": running_peak_date,
    }


def _calendar_years(start: str, end: str) -> float | None:
    days = _calendar_days(start, end)
    if days is None or days <= 0:
        return None
    return days / 365.25


def _calendar_days(start: str, end: str) -> int | None:
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (b - a).days
