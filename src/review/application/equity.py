"""真实资金曲线：把账本 + 行情算成一条能看回撤的净值线。

## 和此前那条曲线的区别

``analytics_payload()`` 的 ``equity_curve`` 是**已实现盈亏的累加**：只在
发生卖出的那天跳变，持仓期间完全是平的。它无法回答"我最大回撤多少"，
因为浮亏根本没进曲线——扛着 −30% 的票在那条线上和空仓毫无区别。

这里算的是真实的每日净值：

    总资产(t) = 现金(t) + Σ 持股数(t) × 收盘价(t)

需要三样东西：账本回放出的每日持仓、行情仓里的收盘价、以及现金推算。
某日缺收盘价时用该标的**最近可用收盘**递补（避免市值断崖）；全程无行情的标的
仍不计市值，并在 ``note`` 里写明。

## 现金怎么来

现金没有独立账本，只能推算：以 ``account_snapshots`` 的总资产为锚点，
用交易现金流与 CASHFLOW 事件往前后递推。若用户从未记过快照，就退化为
"持仓市值 + 已实现盈亏"这条不含现金的曲线，并把 ``confidence`` 标成
``estimated``——**不伪造一个看起来精确的总资产数字**。这条线的形状仍然
可用（涨跌节奏、回撤幅度都对），只是绝对值不可当真。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from src.market import MarketStore
from src.ledger import PalaceStore
from src.review.application.replay import holdings_timeline

#: 年化用的交易日数。A 股每年约 242 个交易日。
TRADING_DAYS_PER_YEAR = 242

#: 无风险利率（年化），用于夏普。取一年期定存量级，不追求精确。
RISK_FREE_ANNUAL = 0.015


@dataclass
class EquityPoint:
    trade_date: str
    holding_value: float
    cash: float
    total_equity: float
    floating_pnl: float
    realized_pnl_cum: float
    drawdown_pct: float
    benchmarks: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "holding_value": round(self.holding_value, 2),
            "cash": round(self.cash, 2),
            "total_equity": round(self.total_equity, 2),
            "floating_pnl": round(self.floating_pnl, 2),
            "realized_pnl_cum": round(self.realized_pnl_cum, 2),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "benchmarks": {k: round(v, 4) for k, v in self.benchmarks.items()},
        }


@dataclass
class EquityCurve:
    points: list[EquityPoint]
    metrics: dict[str, Any]
    confidence: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [point.to_dict() for point in self.points],
            "metrics": self.metrics,
            "confidence": self.confidence,
            "note": self.note,
        }


def _realized_by_day(palace: PalaceStore) -> dict[str, float]:
    """每日已实现盈亏。含历史基线导入，口径与账本 scorecard 一致。"""
    out: dict[str, float] = {}
    for row in palace.conn.execute(
        "SELECT occurred_on, SUM(realized_pnl) AS pnl FROM position_events GROUP BY occurred_on"
    ):
        out[str(row["occurred_on"])] = out.get(str(row["occurred_on"]), 0.0) + float(row["pnl"] or 0)
    for row in palace.conn.execute(
        "SELECT occurred_on, SUM(amount) AS pnl FROM account_events"
        " WHERE kind = 'REALIZED_PNL_IMPORT' GROUP BY occurred_on"
    ):
        out[str(row["occurred_on"])] = out.get(str(row["occurred_on"]), 0.0) + float(row["pnl"] or 0)
    return out


def _cash_flow_by_day(palace: PalaceStore) -> dict[str, float]:
    """每日净出入金 + 交易现金流。买入耗现金，卖出回笼现金。"""
    out: dict[str, float] = {}
    for row in palace.conn.execute(
        "SELECT occurred_on, SUM(amount) AS amount FROM account_events"
        " WHERE kind = 'CASHFLOW' GROUP BY occurred_on"
    ):
        out[str(row["occurred_on"])] = out.get(str(row["occurred_on"]), 0.0) + float(row["amount"] or 0)
    for row in palace.conn.execute(
        "SELECT occurred_on, action, SUM(shares * price) AS amount FROM position_events"
        " GROUP BY occurred_on, action"
    ):
        day = str(row["occurred_on"])
        amount = float(row["amount"] or 0)
        action = str(row["action"])
        # OPENING 为已有持仓导入（trades 口径不碰现金），只算 BUY/SELL
        delta = 0.0 if action == "OPENING" else (amount if action == "SELL" else -amount)
        out[day] = out.get(day, 0.0) + delta
    return out


def _latest_snapshot(palace: PalaceStore) -> tuple[str, float, float | None] | None:
    row = palace.conn.execute(
        "SELECT occurred_on, total_assets, cash FROM account_snapshots"
        " ORDER BY occurred_on DESC, created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cash = None if row["cash"] is None else float(row["cash"])
    return str(row["occurred_on"]), float(row["total_assets"]), cash


def build_equity_curve(
    palace: PalaceStore,
    market: MarketStore,
    *,
    start: str | None = None,
    end: str | None = None,
    benchmarks: tuple[str, ...] = ("000300",),
) -> EquityCurve:
    """算出逐日净值曲线与绩效指标。"""
    changes = holdings_timeline(palace)
    if not changes:
        return EquityCurve(points=[], metrics={"days": 0}, confidence="none", note="账本里还没有成交记录")

    first_event_day = min(changes)
    days = market.trading_days(start=start or first_event_day, end=end)
    if not days:
        return EquityCurve(
            points=[], metrics={"days": 0}, confidence="none",
            note="行情仓里没有覆盖该区间的交易日，请先执行 python market.py sync",
        )

    realized = _realized_by_day(palace)
    cash_flows = _cash_flow_by_day(palace)
    snapshot = _latest_snapshot(palace)

    codes = sorted({code for snap in changes.values() for code in snap})
    closes = _close_lookup(market, codes, days[0], days[-1])
    cost_values = _cost_values_by_day(palace, days)

    # 事件日之间持仓不变，这里把变化点前向填充到每个交易日。
    change_days = sorted(changes)
    points: list[EquityPoint] = []
    holdings: dict[str, int] = {}
    cursor = 0
    realized_cum = 0.0
    cash_cum = 0.0
    missing_codes: set[str] = set()
    carried_codes: set[str] = set()
    last_close: dict[str, float] = {}

    for day in days:
        while cursor < len(change_days) and change_days[cursor] <= day:
            holdings = changes[change_days[cursor]]
            cursor += 1
        realized_cum += realized.get(day, 0.0)
        cash_cum += cash_flows.get(day, 0.0)

        holding_value = 0.0
        for code, shares in holdings.items():
            price = closes.get(code, {}).get(day)
            if price is not None:
                last_close[code] = price
            else:
                price = last_close.get(code)
                if price is not None:
                    carried_codes.add(code)
            if price is None:
                missing_codes.add(code)
                continue
            holding_value += shares * price
        cost_value = cost_values[day]
        points.append(
            EquityPoint(
                trade_date=day,
                holding_value=holding_value,
                cash=cash_cum,
                total_equity=holding_value + cash_cum,
                floating_pnl=holding_value - cost_value,
                realized_pnl_cum=realized_cum,
                drawdown_pct=0.0,
            )
        )

    confidence, note, offset = _resolve_cash_anchor(points, snapshot)
    for point in points:
        point.cash += offset
        point.total_equity += offset

    _fill_drawdown(points)
    _attach_benchmarks(points, market, benchmarks, days)

    metrics = compute_curve_metrics(points)
    if carried_codes:
        note = (note + " " if note else "") + (
            f"{len(carried_codes)} 只标的部分交易日缺收盘价，已用最近可用收盘递补："
            f"{', '.join(sorted(carried_codes)[:5])}"
            + ("…" if len(carried_codes) > 5 else "")
        )
    if missing_codes:
        note = (note + " " if note else "") + (
            f"{len(missing_codes)} 只标的全程无行情，市值未计入（补齐行情后会恢复）："
            f"{', '.join(sorted(missing_codes)[:5])}"
            + ("…" if len(missing_codes) > 5 else "")
        )
    return EquityCurve(points=points, metrics=metrics, confidence=confidence, note=note.strip())


def _cost_values_by_day(palace: PalaceStore, days: list[str]) -> dict[str, float]:
    """一次读取事件并增量计算每个交易日的持仓成本合计。

    事件按发生日和 rowid 升序处理，等价于逐日取每只票的最后状态，
    但避免对同一批 position_events 执行一次相关子查询。
    """
    if not days:
        return {}

    rows = palace.conn.execute(
        """
        SELECT occurred_on, code, shares_after, cost_after
        FROM position_events
        WHERE occurred_on <= ?
        ORDER BY occurred_on ASC, rowid ASC
        """,
        (days[-1],),
    )
    latest: dict[str, float] = {}
    values: dict[str, float] = {}
    total = 0.0
    day_index = 0
    for row in rows:
        event_day = str(row["occurred_on"])
        while day_index < len(days) and days[day_index] < event_day:
            values[days[day_index]] = total
            day_index += 1

        code = str(row["code"])
        current = float(row["shares_after"] or 0) * float(row["cost_after"] or 0.0)
        total += current - latest.get(code, 0.0)
        latest[code] = current

    while day_index < len(days):
        values[days[day_index]] = total
        day_index += 1
    return values


def _close_lookup(
    market: MarketStore, codes: list[str], start: str, end: str
) -> dict[str, dict[str, float]]:
    """{代码: {日期: 前复权收盘价}}。

    用前复权：不复权的历史价在除权处有断崖，算出来的市值会凭空跳一截。
    """
    if not codes:
        return {}
    panels = market.load_panel(fields=("close",), codes=codes, start=start, end=end, adjust="qfq")
    close = panels.get("close")
    if close is None or close.empty:
        return {}
    out: dict[str, dict[str, float]] = {}
    for code in close.columns:
        series = close[code].dropna()
        out[str(code)] = {str(idx): float(value) for idx, value in series.items()}
    return out


def _resolve_cash_anchor(
    points: list[EquityPoint], snapshot: tuple[str, float, float | None] | None
) -> tuple[str, str, float]:
    """用总资产快照把现金曲线校准到真实水平。

    没有快照时不硬凑一个"真实"数字，但也不能让曲线从 0 附近起步：
    现金流里买入是负数，未校准的总资产 = 持仓市值 − 买入金额 ≈ 0，
    在它上面算回撤百分比会除以一个接近 0 的峰值，得到无意义的结果
    （实测直接退化成恒为 0）。所以退而求其次，用历史最大投入成本
    当作本金基准——形状与回撤幅度都正确，只是绝对值不可当真，
    由 confidence=estimated 明确标注。
    """
    if snapshot is None:
        base = max((point.holding_value - point.floating_pnl for point in points), default=0.0)
        offset = base - min((point.total_equity for point in points), default=0.0)
        return (
            "estimated",
            "从未记录总资产快照，本金按历史最大投入成本推算，绝对值仅供参考；"
            "记一次资产快照即可校准（曲线形状与回撤幅度不受影响）。",
            offset if base > 0 else 0.0,
        )
    anchor_day, total_assets, _ = snapshot
    match = next((p for p in reversed(points) if p.trade_date <= anchor_day), None)
    if match is None:
        return ("estimated", "总资产快照日期早于行情覆盖区间，未能校准现金。", 0.0)
    return ("anchored", "", total_assets - match.total_equity)


def _fill_drawdown(points: list[EquityPoint]) -> None:
    peak = -math.inf
    for point in points:
        peak = max(peak, point.total_equity)
        if peak > 0:
            point.drawdown_pct = (point.total_equity / peak - 1) * 100


def _attach_benchmarks(
    points: list[EquityPoint], market: MarketStore, benchmarks: tuple[str, ...], days: list[str]
) -> None:
    """把基准指数换算成"与账户同起点"的归一化涨幅，便于同图对比。"""
    for code in benchmarks:
        frame = market.history(code, start=days[0], end=days[-1], adjust="none")
        if frame.empty:
            continue
        series = {str(row.trade_date): float(row.close) for row in frame.itertuples() if row.close}
        base = next((series[p.trade_date] for p in points if p.trade_date in series), None)
        if not base:
            continue
        for point in points:
            value = series.get(point.trade_date)
            if value is not None:
                point.benchmarks[code] = (value / base - 1) * 100


def compute_curve_metrics(points: list[EquityPoint]) -> dict[str, Any]:
    """年化、最大回撤、夏普、卡玛。

    只有一天数据时不硬算年化——把一天的涨跌乘 242 得到的数字毫无意义，
    只会误导。
    """
    if len(points) < 2:
        # 只有一天也要把已知的事实报出来，不要满屏 None——用户看到的应该是
        # "账本只覆盖了一天"，而不是"这个功能坏了"。
        return {
            "days": len(points),
            "start_date": points[0].trade_date if points else None,
            "end_date": points[-1].trade_date if points else None,
            "end_equity": round(points[-1].total_equity, 2) if points else None,
            "realized_pnl": round(points[-1].realized_pnl_cum, 2) if points else None,
            "floating_pnl": round(points[-1].floating_pnl, 2) if points else None,
            "caution": "账本只覆盖了 1 个交易日，无法计算收益率、回撤与年化",
        }

    start_equity = points[0].total_equity
    end_equity = points[-1].total_equity
    max_drawdown = min(point.drawdown_pct for point in points)

    daily_returns: list[float] = []
    for previous, current in zip(points, points[1:]):
        if previous.total_equity > 0:
            daily_returns.append(current.total_equity / previous.total_equity - 1)

    metrics: dict[str, Any] = {
        "days": len(points),
        "start_date": points[0].trade_date,
        "end_date": points[-1].trade_date,
        "start_equity": round(start_equity, 2),
        "end_equity": round(end_equity, 2),
        "total_return_pct": round((end_equity / start_equity - 1) * 100, 4)
        if start_equity > 0
        else None,
        "max_drawdown_pct": round(max_drawdown, 4),
        "realized_pnl": round(points[-1].realized_pnl_cum, 2),
        "floating_pnl": round(points[-1].floating_pnl, 2),
    }

    if daily_returns and start_equity > 0:
        years = len(points) / TRADING_DAYS_PER_YEAR
        total_ratio = end_equity / start_equity
        if years > 0 and total_ratio > 0:
            annual = (total_ratio ** (1 / years) - 1) * 100
            metrics["annualized_pct"] = round(annual, 4)
            if max_drawdown < 0:
                metrics["calmar"] = round(annual / abs(max_drawdown), 3)

        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / max(1, len(daily_returns) - 1)
        std = math.sqrt(variance)
        if std > 0:
            excess = mean - RISK_FREE_ANNUAL / TRADING_DAYS_PER_YEAR
            metrics["sharpe"] = round(excess / std * math.sqrt(TRADING_DAYS_PER_YEAR), 3)
        metrics["daily_volatility_pct"] = round(std * 100, 4)

    for code, value in points[-1].benchmarks.items():
        metrics[f"benchmark_{code}_pct"] = round(value, 4)
        if metrics.get("total_return_pct") is not None:
            metrics[f"alpha_vs_{code}_pct"] = round(metrics["total_return_pct"] - value, 4)

    if len(points) < TRADING_DAYS_PER_YEAR // 4:
        metrics["caution"] = (
            f"区间仅 {len(points)} 个交易日，年化与夏普由短样本外推，波动很大，不宜据此判断长期水平"
        )
    return metrics
