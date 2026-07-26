"""候选池与预案的事后验证。

## 为什么这是最有价值的一块

交易复盘只能告诉你"买过的票表现如何"——那是**幸存者偏差**的样本。真正
能改进选股规则的，是回答两个反向问题：

1. 当初判"剔除/不纳入"的票，后来涨了多少？漏掉的赢家比买错的输家更
   说明规则有问题。
2. 打了高分的票和打了低分的票，事后收益真的分开了吗？分不开就说明评分
   没有区分度——此前那份手工回测正是这样发现"评分与结果相关性弱"的。

所以这里对**全部裁决一视同仁**地算 T+N 收益，包括被否决的，而不只是
统计买入的那些。

## 时间口径

T+N 走**交易日历**，不是自然日。按自然日加 5 天会跨过周末与长假，
算出来的"T+5 收益"根本不是第 5 个交易日的收益。

基准日取候选记录当天的收盘价：候选是当天盘后/盘中做出的判断，用当天
收盘作为"如果我当时买了"的参考点，与手工回测的保守口径一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.market.store import MarketStore
from src.palace import PalaceStore

#: 观察窗口。5/10/20 覆盖短中期，60 用来看"漏掉的大牛股"。
HORIZONS = (5, 10, 20, 60)

#: 视为"看多"的裁决关键词。与账本 _is_selected_decision 的口径保持一致。
POSITIVE_HINTS = ("买", "精选", "入选", "重点", "建仓", "参与")


@dataclass
class CandidateOutcome:
    candidate_id: str
    code: str
    name: str
    base_date: str
    decision: str
    selected: bool
    score: float | None
    base_close: float | None
    returns: dict[int, float | None] = field(default_factory=dict)
    max_favorable_pct: float | None = None
    benchmark_returns: dict[int, float | None] = field(default_factory=dict)
    note: str = ""

    def alpha(self, horizon: int) -> float | None:
        own = self.returns.get(horizon)
        bench = self.benchmark_returns.get(horizon)
        if own is None or bench is None:
            return None
        return round(own - bench, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "code": self.code,
            "name": self.name,
            "base_date": self.base_date,
            "decision": self.decision,
            "selected": self.selected,
            "score": self.score,
            "base_close": self.base_close,
            "returns": {f"t{h}": self.returns.get(h) for h in HORIZONS},
            "alpha": {f"t{h}": self.alpha(h) for h in HORIZONS},
            "max_favorable_pct": self.max_favorable_pct,
            "note": self.note,
        }


def _is_selected(decision: str) -> bool:
    text = str(decision or "")
    return any(hint in text for hint in POSITIVE_HINTS)


def _series_for(market: MarketStore, code: str, start: str, end: str) -> dict[str, dict[str, float]]:
    frame = market.history(code, start=start, end=end, adjust="qfq")
    if frame.empty:
        return {}
    return {
        str(row.trade_date): {
            "close": float(row.close) if row.close is not None else float("nan"),
            "high": float(row.high) if row.high is not None else float("nan"),
        }
        for row in frame.itertuples()
    }


def evaluate_candidates(
    palace: PalaceStore,
    market: MarketStore,
    *,
    limit: int = 500,
    benchmark: str | None = "000300",
) -> list[CandidateOutcome]:
    """对候选池里的每一条裁决算 T+N 结局。"""
    rows = [
        dict(row)
        for row in palace.conn.execute(
            """
            SELECT id, occurred_on, code, name, score, decision FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY occurred_on, pool_id, code
                    ORDER BY created_at DESC, id DESC
                ) AS rn FROM candidate_reviews
            ) ranked WHERE rn = 1
            ORDER BY occurred_on DESC, code
            LIMIT ?
            """,
            (int(limit),),
        )
    ]
    if not rows:
        return []

    calendar = market.trading_days()
    if not calendar:
        return [
            CandidateOutcome(
                candidate_id=str(row["id"]), code=str(row["code"]), name=str(row["name"] or ""),
                base_date=str(row["occurred_on"]), decision=str(row["decision"]),
                selected=_is_selected(row["decision"]),
                score=None if row["score"] is None else float(row["score"]),
                base_close=None, note="行情仓为空，未取得真实数据",
            )
            for row in rows
        ]

    position_of = {day: index for index, day in enumerate(calendar)}
    max_horizon = max(HORIZONS)
    benchmark_series = (
        _series_for(market, benchmark, calendar[0], calendar[-1]) if benchmark else {}
    )

    outcomes: list[CandidateOutcome] = []
    for row in rows:
        base_date = str(row["occurred_on"])
        outcome = CandidateOutcome(
            candidate_id=str(row["id"]),
            code=str(row["code"]),
            name=str(row["name"] or ""),
            base_date=base_date,
            decision=str(row["decision"]),
            selected=_is_selected(row["decision"]),
            score=None if row["score"] is None else float(row["score"]),
            base_close=None,
        )

        index = position_of.get(base_date)
        if index is None:
            # 候选日不是交易日（周末做的功课），顺延到下一个交易日。
            following = [day for day in calendar if day >= base_date]
            if not following:
                outcome.note = "候选日之后还没有交易日数据"
                outcomes.append(outcome)
                continue
            index = position_of[following[0]]

        window = calendar[index : index + max_horizon + 1]
        series = _series_for(market, outcome.code, window[0], window[-1])
        base = series.get(window[0], {}).get("close")
        if base is None or not base > 0:
            outcome.note = "未取得真实行情，无法评估"
            outcomes.append(outcome)
            continue
        outcome.base_close = round(base, 4)

        highs: list[float] = []
        for horizon in HORIZONS:
            if index + horizon >= len(calendar):
                outcome.returns[horizon] = None
                outcome.benchmark_returns[horizon] = None
                continue
            target_day = calendar[index + horizon]
            close = series.get(target_day, {}).get("close")
            outcome.returns[horizon] = (
                round((close / base - 1) * 100, 4) if close and close == close else None
            )
            outcome.benchmark_returns[horizon] = _benchmark_return(
                benchmark_series, window[0], target_day
            )

        for day in window[1:]:
            high = series.get(day, {}).get("high")
            if high and high == high:
                highs.append(high)
        if highs:
            outcome.max_favorable_pct = round((max(highs) / base - 1) * 100, 4)
        if all(value is None for value in outcome.returns.values()):
            outcome.note = "观察窗口尚未走完"
        outcomes.append(outcome)

    return outcomes


def _benchmark_return(
    series: dict[str, dict[str, float]], base_day: str, target_day: str
) -> float | None:
    base = series.get(base_day, {}).get("close")
    target = series.get(target_day, {}).get("close")
    if not base or not target or base != base or target != target:
        return None
    return round((target / base - 1) * 100, 4)


def summarize_candidates(outcomes: list[CandidateOutcome]) -> dict[str, Any]:
    """按裁决分组汇总，并把"漏掉的赢家"单独拎出来。"""
    groups: dict[str, list[CandidateOutcome]] = {}
    for outcome in outcomes:
        groups.setdefault(outcome.decision or "未标注", []).append(outcome)

    def aggregate(items: list[CandidateOutcome]) -> dict[str, Any]:
        stats: dict[str, Any] = {"count": len(items)}
        for horizon in HORIZONS:
            values = [o.returns.get(horizon) for o in items]
            values = [v for v in values if v is not None]
            if not values:
                stats[f"t{horizon}"] = None
                continue
            stats[f"t{horizon}"] = {
                "n": len(values),
                "avg": round(sum(values) / len(values), 4),
                "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100, 2),
                "best": round(max(values), 4),
                "worst": round(min(values), 4),
            }
        alphas = [o.alpha(20) for o in items]
        alphas = [a for a in alphas if a is not None]
        if alphas:
            stats["avg_alpha_t20"] = round(sum(alphas) / len(alphas), 4)
        return stats

    rejected = [o for o in outcomes if not o.selected]
    missed = sorted(
        (o for o in rejected if (o.returns.get(20) or 0) > 10),
        key=lambda o: o.returns.get(20) or 0,
        reverse=True,
    )

    summary: dict[str, Any] = {
        "total": len(outcomes),
        "evaluated": sum(1 for o in outcomes if o.base_close is not None),
        "by_decision": {name: aggregate(items) for name, items in sorted(groups.items())},
        "selected": aggregate([o for o in outcomes if o.selected]),
        "rejected": aggregate(rejected),
        # 反向证据：当初否决、事后大涨的票。这是改进规则最直接的线索。
        "missed_winners": [
            {
                "code": o.code, "name": o.name, "base_date": o.base_date,
                "decision": o.decision, "return_t20": o.returns.get(20),
                "max_favorable_pct": o.max_favorable_pct,
            }
            for o in missed[:20]
        ],
    }

    scored = [o for o in outcomes if o.score is not None and o.returns.get(20) is not None]
    if len(scored) >= 8:
        summary["score_buckets"] = _score_buckets(scored)
    return summary


def _score_buckets(outcomes: list[CandidateOutcome]) -> list[dict[str, Any]]:
    """按评分分箱看 T+20 收益是否单调。

    不单调就说明评分没有区分度——高分票并不比低分票赚得多，那这套打分
    在做无用功。此前那份手工回测正是这样发现问题的。
    """
    buckets = [(0, 60), (60, 72), (72, 80), (80, 101)]
    result: list[dict[str, Any]] = []
    for low, high in buckets:
        items = [o for o in outcomes if low <= (o.score or 0) < high]
        values = [o.returns[20] for o in items if o.returns.get(20) is not None]
        result.append(
            {
                "range": f"{low}-{high - 1}",
                "count": len(items),
                "avg_t20": round(sum(values) / len(values), 4) if values else None,
                "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100, 2)
                if values
                else None,
            }
        )
    return result


def evaluate_plans(palace: PalaceStore, market: MarketStore) -> list[dict[str, Any]]:
    """预案兑现：止损/止盈事后有没有被触发。"""
    rows = [
        dict(row)
        for row in palace.conn.execute(
            "SELECT id, occurred_on, code, title, stop_price, target_price, status"
            " FROM plans ORDER BY occurred_on DESC"
        )
    ]
    results: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        base_date = str(row["occurred_on"])
        stop = row["stop_price"]
        target = row["target_price"]
        frame = market.history(code, start=base_date, adjust="qfq")

        record: dict[str, Any] = {
            "plan_id": str(row["id"]),
            "code": code,
            "title": str(row["title"]),
            "occurred_on": base_date,
            "stop_price": stop,
            "target_price": target,
            "stop_hit_on": None,
            "target_hit_on": None,
            "status_final": "observing",
        }
        if frame.empty:
            record["status_final"] = "no_data"
            record["note"] = "未取得真实行情"
            results.append(record)
            continue

        for item in frame.itertuples():
            low, high = item.low, item.high
            if stop is not None and low is not None and low <= float(stop) and not record["stop_hit_on"]:
                record["stop_hit_on"] = str(item.trade_date)
            if (
                target is not None
                and high is not None
                and high >= float(target)
                and not record["target_hit_on"]
            ):
                record["target_hit_on"] = str(item.trade_date)

        if record["target_hit_on"] and record["stop_hit_on"]:
            record["status_final"] = (
                "target_first" if record["target_hit_on"] <= record["stop_hit_on"] else "stop_first"
            )
        elif record["target_hit_on"]:
            record["status_final"] = "target_hit"
        elif record["stop_hit_on"]:
            record["status_final"] = "stop_hit"
        results.append(record)
    return results
