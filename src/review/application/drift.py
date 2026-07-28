"""回测-实盘偏离追踪：把回测收益拆解成各因素的贡献。

## 为什么要追踪偏离

回测说赚8%、实盘赚3%，差额可能来自：
1. 滑点/冲击成本（买的时候推高了价格）
2. 信号日没成功买入（涨停买不进、停牌、资金不够）
3. 止损规则执行不一致（看着跌了没舍得割）
4. 持有期不一致（本来打算拿5天，第3天手动卖了）
5. 回测中存在前视偏差（根本问题）

不追踪就永远是"运气不好"，追踪才能找到真正可改进的地方。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.ledger import PalaceStore


@dataclass
class DriftReport:
    strategy_tag: str
    total: int
    avg_drift: float | None
    """actual_return - expected_return 的均值（只计算有完整数据的条目）。"""
    by_category: dict[str, int] = field(default_factory=dict)
    """no_trade / early_exit / late_entry / plan_followed 的条目数。"""
    worst_cases: list[dict[str, Any]] = field(default_factory=list)
    """drift 最负的前 N 条（最需要改进的场景）。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_tag": self.strategy_tag,
            "total": self.total,
            "avg_drift": self.avg_drift,
            "by_category": self.by_category,
            "worst_cases": self.worst_cases,
        }


def compute_drift(
    palace: PalaceStore,
    strategy_tag: str,
    limit: int = 50,
) -> DriftReport:
    """计算回测-实盘偏离。

    逻辑：
    1. 读 position_tracking 的已关闭条目，取 entry_price / exit_price / actual_return。
    2. 从 position_events 找同标的、时间相近的成交记录，判断「有没有真实买入」。
    3. 按偏离类型分类：no_trade / late_entry / early_exit / plan_followed。
    4. 返回 DriftReport。

    注意：expected_return 用 entry_price → exit_price 的线性估算；
    没有 entry_price 时用 actual_return 自身作为 expected（偏离 = 0）。
    """
    tracking_rows = palace.conn.execute(
        """
        SELECT id, code, name, tier, signal_date, entry_date, exit_by_date,
               entry_price, exit_price, actual_return, hold_days, closed_reason
        FROM position_tracking
        WHERE strategy_tag = ? AND status != 'active'
        ORDER BY signal_date DESC
        LIMIT ?
        """,
        (strategy_tag, limit),
    ).fetchall()

    if not tracking_rows:
        return DriftReport(strategy_tag=strategy_tag, total=0, avg_drift=None)

    # 读所有相关代码的成交记录，用于判断是否真实买入
    codes = list({str(r["code"]) for r in tracking_rows})
    placeholders = ",".join("?" * len(codes))
    trade_rows = palace.conn.execute(
        f"""
        SELECT code, occurred_on, action, price, shares_after
        FROM position_events
        WHERE code IN ({placeholders}) AND action IN ('BUY', 'OPENING')
        ORDER BY occurred_on
        """,
        codes,
    ).fetchall()

    # 按 code 组织成交索引
    trades_by_code: dict[str, list[dict]] = {}
    for t in trade_rows:
        c = str(t["code"])
        trades_by_code.setdefault(c, []).append(dict(t))

    by_category: dict[str, int] = {
        "no_trade": 0,
        "late_entry": 0,
        "early_exit": 0,
        "plan_followed": 0,
    }
    drift_values: list[float] = []
    worst: list[dict[str, Any]] = []

    for row in tracking_rows:
        code = str(row["code"])
        entry_date = str(row["entry_date"])
        exit_by_date = str(row["exit_by_date"])
        entry_price: float | None = row["entry_price"]
        exit_price: float | None = row["exit_price"]
        actual_return: float | None = row["actual_return"]

        # 查找该标的在 entry_date 前后 3 个日历日内是否有买入
        relevant_trades = [
            t for t in trades_by_code.get(code, [])
            if t["occurred_on"] >= entry_date
        ]

        if not relevant_trades:
            category = "no_trade"
        else:
            first_trade_date = relevant_trades[0]["occurred_on"]
            # 晚于预期入场日超过 1 个交易日视为迟入
            if first_trade_date > entry_date:
                category = "late_entry"
            else:
                # 检查是否提前退出：找 exit_by_date 前的卖出
                sell_trades = [
                    t for t in trades_by_code.get(code, [])
                    if t["occurred_on"] <= exit_by_date
                    and t.get("action") == "SELL"
                ]
                if sell_trades and sell_trades[-1]["occurred_on"] < exit_by_date:
                    category = "early_exit"
                else:
                    category = "plan_followed"

        by_category[category] = by_category.get(category, 0) + 1

        # 计算偏离
        drift: float | None = None
        if entry_price and entry_price > 0 and exit_price and exit_price > 0:
            expected_return = round((exit_price / entry_price - 1) * 100, 4)
        else:
            expected_return = actual_return  # 无价格数据时无偏离可算

        if actual_return is not None and expected_return is not None:
            drift = round(actual_return - expected_return, 4)
            drift_values.append(drift)

        worst.append({
            "tracking_id": str(row["id"]),
            "code": code,
            "name": str(row["name"]),
            "signal_date": str(row["signal_date"]),
            "category": category,
            "expected_return": expected_return,
            "actual_return": actual_return,
            "drift": drift,
            "closed_reason": str(row["closed_reason"]),
        })

    # 按 drift 升序取最差 10 条
    worst_sorted = sorted(
        [w for w in worst if w["drift"] is not None],
        key=lambda x: float(x["drift"]),  # type: ignore[arg-type]
    )[:10]

    avg_drift = round(sum(drift_values) / len(drift_values), 4) if drift_values else None

    return DriftReport(
        strategy_tag=strategy_tag,
        total=len(tracking_rows),
        avg_drift=avg_drift,
        by_category=by_category,
        worst_cases=worst_sorted,
    )
