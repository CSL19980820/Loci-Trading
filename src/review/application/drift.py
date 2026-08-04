"""回测-实盘偏离追踪：把计划收益拆解成各因素的贡献。

## 为什么要追踪偏离

回测说赚8%、实盘赚3%，差额可能来自：
1. 滑点/冲击成本（买的时候推高了价格）
2. 信号日没成功买入（涨停买不进、停牌、资金不够）
3. 止损规则执行不一致（看着跌了没舍得割）
4. 持有期不一致（本来打算拿5天，第3天手动卖了）
5. 回测中存在前视偏差（根本问题）

不追踪就永远是"运气不好"，追踪才能找到真正可改进的地方。

## 数据流

- ``sync_position_tracking``（outcome job 每日调用）：把候选池的精选
  预案写入 position_tracking（计划买入价 = 信号日收盘，到期日 = T+3）。
- ``compute_drift``：读 position_tracking 的计划收益，再从
  position_events（真实成交）推出实盘收益，两者之差即偏离。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.ledger import PalaceStore
from src.review.application.outcomes import CandidateOutcome, PRIMARY_HORIZONS


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


def sync_position_tracking(
    palace: PalaceStore,
    outcomes: list[CandidateOutcome],
    calendar: list[str],
) -> dict[str, int]:
    """把精选候选的 T+N 计划写入 position_tracking（幂等 upsert）。

    - 不存在 → open_tracking：entry_price = 信号日收盘，到期日 = 信号日后第 3 个交易日。
    - 已存在且 T+3 已可算 → close_tracking：exit_price = T+3 收盘，actual_return = T+3 收益。
    - 未到期的 active 记录保持 open，下次运行再结算。

    position_tracking 存的是「计划」；实盘收益由 compute_drift 从
    position_events（真实成交）对比得出。两表分离，才谈得上偏离。
    """
    position_of = {day: index for index, day in enumerate(calendar)}
    horizon = max(PRIMARY_HORIZONS)
    opened = 0
    closed = 0
    skipped = 0

    for outcome in outcomes:
        if not outcome.selected:
            continue
        strategy_tag = outcome.strategy_tag()
        signal_date = outcome.base_date
        index = position_of.get(signal_date)
        if index is None:
            following = [day for day in calendar if day >= signal_date]
            if not following:
                skipped += 1
                continue
            index = position_of[following[0]]
        if index + horizon >= len(calendar):
            # 观察窗口未走完，只能开仓，到期日取最后一个交易日
            exit_by_date = calendar[-1]
        else:
            exit_by_date = calendar[index + horizon]
        entry_price = outcome.base_close

        existing = palace.find_tracking(
            strategy_tag=strategy_tag,
            pool_id=outcome.pool_id or f"POOL-{signal_date}",
            code=outcome.code,
            signal_date=signal_date,
        )
        if existing is None:
            if entry_price is None or not entry_price > 0:
                skipped += 1
                continue
            palace.open_tracking(
                strategy_tag=strategy_tag,
                pool_id=outcome.pool_id or f"POOL-{signal_date}",
                code=outcome.code,
                name=outcome.name,
                tier=outcome.tier or "core",
                signal_date=signal_date,
                entry_date=signal_date,
                hold_days=horizon,
                exit_by_date=exit_by_date,
                entry_price=entry_price,
            )
            opened += 1
        elif existing["status"] == "active":
            t_h = outcome.returns.get(horizon)
            if t_h is None or entry_price is None or not entry_price > 0:
                skipped += 1
                continue
            exit_price = round(entry_price * (1 + t_h / 100), 4)
            palace.close_tracking(
                existing["id"],
                exit_price=exit_price,
                actual_return=t_h,
                reason="expired",
            )
            closed += 1
        else:
            skipped += 1
    return {"opened": opened, "closed": closed, "skipped": skipped}


def compute_drift(
    palace: PalaceStore,
    strategy_tag: str,
    limit: int = 50,
) -> DriftReport:
    """计算回测-实盘偏离。

    逻辑：
    1. 读 position_tracking 的已关闭条目，取 entry_price / exit_price（计划）。
    2. 从 position_events 找同标的的真实成交，推出实盘买入/卖出价。
    3. 按偏离类型分类：no_trade / late_entry / early_exit / plan_followed。
    4. 返回 DriftReport。

    注意：expected_return 用计划 entry_price → exit_price 估算；
    实盘收益用真实成交（BUY → SELL）计算，成交缺失时 drift = None。
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

    # 读所有相关代码的成交记录：BUY/OPENING 建仓，SELL 平仓
    codes = list({str(r["code"]) for r in tracking_rows})
    placeholders = ",".join("?" * len(codes))
    trade_rows = palace.conn.execute(
        f"""
        SELECT code, occurred_on, action, price
        FROM position_events
        WHERE code IN ({placeholders}) AND action IN ('BUY', 'OPENING', 'SELL')
        ORDER BY occurred_on
        """,
        codes,
    ).fetchall()

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

        # 计划收益：计划买入价 → 计划卖出价
        expected_return: float | None = None
        if entry_price and entry_price > 0 and exit_price and exit_price > 0:
            expected_return = round((exit_price / entry_price - 1) * 100, 4)

        # 实盘：entry_date 当日及之后第一条建仓 = 实际买入
        buys = [
            t for t in trades_by_code.get(code, [])
            if t["action"] in ("BUY", "OPENING") and t["occurred_on"] >= entry_date
        ]
        sells = [
            t for t in trades_by_code.get(code, [])
            if t["action"] == "SELL" and t["occurred_on"] <= exit_by_date
        ]

        if not buys:
            category = "no_trade"
        else:
            first_buy_date = buys[0]["occurred_on"]
            if first_buy_date > entry_date:
                category = "late_entry"
            elif sells and sells[-1]["occurred_on"] < exit_by_date:
                category = "early_exit"
            else:
                category = "plan_followed"

        by_category[category] = by_category.get(category, 0) + 1

        # 实盘收益：真实买入价 → 真实卖出价（无卖出则按到期日收盘计）
        actual_return: float | None = None
        if buys and buys[0].get("price") and buys[0]["price"] > 0:
            buy_price = float(buys[0]["price"])
            if sells:
                sell_price = float(sells[-1]["price"])
                if sell_price and sell_price > 0:
                    actual_return = round((sell_price / buy_price - 1) * 100, 4)
            else:
                actual_return = None  # 持仓未了结，无实盘收益可算

        drift: float | None = None
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
