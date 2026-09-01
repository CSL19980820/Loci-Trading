"""组合权益的口径披露与保守盯市下界。

``analyze_portfolio`` 的 ``equity`` 是 **持仓按成本计入、未实现盈亏不盯市**：
输入只有逐笔 ``Trade``（入场价、退出价、净收益、MAE/MFE），没有逐日收盘价，
所以持仓期内那条曲线是平的，全部盈亏在退出日一次性落地。

后果是 ``max_drawdown_pct`` 量的是 **已实现盈亏回撤**，不是账户回撤——一只票
持仓中途跌 30% 又涨回来，这条曲线上一个点都看不到。以前没有任何字段说明这件
事，读的人会当成账户净值回撤，这是本模块要堵的洞。

补两件事，都不引入新输入、不改 ``analyze_portfolio`` 的签名：

1. :data:`EQUITY_BASIS` 口径声明，随 ``metrics.assumption`` 一起回显，让调用方
   不可能把它读成账户净值。
2. 用每笔**已经测出来的** MAE 算一条保守下界曲线：持仓期内每一天都假设它同时
   落在各自最差点。这是真实回撤的**上界**（过度悲观，因为不同持仓的最差点不会
   真的撞在同一天），不是真实路径。界小就说明真实回撤一定更小；界大则说明这条
   平滑曲线不可信，必须拿逐日行情重算。

不做的事：**不猜 MAE 发生在哪一天**，因此不生成「更像真的」的中间曲线——那属于
编造路径。要真盯市就得把逐日收盘价传进来，那是另一个函数的职责。
"""
from __future__ import annotations

from math import isfinite

#: ``analyze_portfolio`` 的权益口径标识。持仓按入场名义额计入，直到退出日才结算。
EQUITY_BASIS = "cost_until_exit"

#: 现金守恒允许的绝对误差（元）。逐笔 ``exit_notional`` 由百分比回乘得到，
#: 累加上千笔后 float64 的尾差在这个量级，超出即为真错。
CASH_TOLERANCE = 1e-6


class PortfolioInvariantError(ValueError):
    """组合账本违反了资金不变式。属于实现缺陷，不是输入问题。"""


def drawdown_pct(curve: list[float], *, peak_floor: float) -> float:
    """曲线相对历史峰值的最大回撤（百分数，≤0）。

    ``peak_floor`` 是初始资金：峰值从它起算，否则第一天亏损会因为「峰值等于
    当前值」而被记成 0 回撤。
    """
    peak = float(peak_floor)
    worst = 0.0
    for value in curve:
        number = float(value)
        if not isfinite(number):
            continue
        peak = max(peak, number)
        if peak > 0:
            worst = min(worst, (number / peak - 1.0) * 100.0)
    return worst


def mae_floor_value(cash: float, open_positions: list[tuple[float, float]]) -> float:
    """某一天的保守下界权益。

    ``open_positions`` 是 ``(entry_notional, mae_pct)`` 列表。MAE 是负数百分比
    （最不利偏移），``mae_pct=0`` 或非有限值时退化为按成本计——不放大也不编造。
    """
    total = float(cash)
    for entry_notional, mae_pct in open_positions:
        notional = float(entry_notional)
        adverse = float(mae_pct)
        if not isfinite(adverse) or adverse >= 0.0:
            total += notional
            continue
        total += notional * max(0.0, 1.0 + adverse / 100.0)
    return total


def assert_cash_conservation(
    *,
    initial_capital: float,
    final_equity: float,
    realized_pnl_total: float,
) -> None:
    """收口不变式 I1：期末权益 = 初始资金 + 全部已实现盈亏。

    所有持仓在结束时都会被结算回现金，因此期末不应残留任何未结算敞口。
    这条一旦破，说明槽位释放、现金扣减或退出结算有一处漏了。
    """
    expected = float(initial_capital) + float(realized_pnl_total)
    actual = float(final_equity)
    gap = abs(actual - expected)
    if gap > max(CASH_TOLERANCE, abs(expected) * 1e-9):
        raise PortfolioInvariantError(
            "组合现金不守恒："
            f"期末权益 {actual:.6f} ≠ 初始 {float(initial_capital):.6f} "
            f"+ 已实现盈亏 {float(realized_pnl_total):.6f}（差 {gap:.6f}）"
        )


def equity_assumption(*, max_drawdown_pct: float, mae_bound_pct: float) -> dict[str, object]:
    """随 metrics 回显的口径声明。调用方必须先读它再读回撤。"""
    return {
        "equity_basis": EQUITY_BASIS,
        "marks_to_market": False,
        "drawdown_basis": "realized_only",
        "note": (
            "持仓按入场名义额计入权益，未实现盈亏不盯市（输入只有逐笔 Trade，"
            "没有逐日收盘价）。因此 max_drawdown_pct 只在退出日跳变，"
            "量的是已实现盈亏回撤，不是账户回撤，禁止当账户净值披露。"
        ),
        "realized_max_drawdown_pct": max_drawdown_pct,
        "mae_bound_max_drawdown_pct": mae_bound_pct,
        "mae_bound_note": (
            "保守上界：持仓期内每一天都假设所有持仓同时落在各自 MAE 最差点。"
            "真实账户回撤介于 realized 与该上界之间；两者接近说明这条曲线可用，"
            "相差很大说明必须拿逐日行情重算。"
        ),
    }


__all__ = [
    "CASH_TOLERANCE",
"EQUITY_BASIS",
    "PortfolioInvariantError",
    "assert_cash_conservation",
    "drawdown_pct",
    "equity_assumption",
    "mae_floor_value",
]
