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

短线自动跟踪窗口为 T+1 / T+3 / T+5；另保留 T+10/20/60 供中长期验证。
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any

from src.market import MarketStore
from src.ledger import PalaceStore, normalize_decision

#: 短线自动统计主窗口（选出后 5 个交易日内）。
PRIMARY_HORIZONS = (1, 3, 5)
#: 完整观察窗口。短中期 + 60 看漏掉的大牛股。
HORIZONS = (1, 3, 5, 10, 20, 60)

#: 样本可信度阈值（已兑现候选数），与回测侧 ``backtest.application.metrics``
#: 的 SAMPLE_LOW / SAMPLE_MEDIUM 同口径：目录页的「胜率」和回测页的「胜率」
#: 摆在一起看，样本分档必须一致，否则 3 个样本的 100% 会被当成结论。
SAMPLE_LOW = 30
SAMPLE_MEDIUM = 100


def sample_confidence(n: int) -> str:
    if n < SAMPLE_LOW:
        return "low"
    if n < SAMPLE_MEDIUM:
        return "medium"
    return "high"


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
    #: 观察窗口（不含选股日）最低价→最高价涨幅（%），(max_high - min_low) / min_low。
    swing_pct: float | None = None
    benchmark_returns: dict[int, float | None] = field(default_factory=dict)
    note: str = ""
    tier: str = "core"
    pool_id: str = ""
    strategy_slug: str = ""
    rule_version: str = ""

    def alpha(self, horizon: int) -> float | None:
        own = self.returns.get(horizon)
        bench = self.benchmark_returns.get(horizon)
        if own is None or bench is None:
            return None
        return round(own - bench, 4)

    def strategy_tag(self) -> str:
        return (self.strategy_slug or self.rule_version or "").strip() or "未标注"

    def window_progress(self) -> dict[str, Any]:
        """短线窗口进度：observing / partial / complete。"""
        ready = [h for h in PRIMARY_HORIZONS if self.returns.get(h) is not None]
        if not ready:
            status = "observing"
        elif len(ready) >= len(PRIMARY_HORIZONS):
            status = "complete"
        else:
            status = "partial"
        return {
            "status": status,
            "ready_horizons": ready,
            "pending_horizons": [h for h in PRIMARY_HORIZONS if h not in ready],
        }

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
            "swing_pct": self.swing_pct,
            "note": self.note,
            "tier": self.tier,
            "strategy_slug": self.strategy_slug,
            "rule_version": self.rule_version,
            "window": self.window_progress(),
        }


def _is_selected(decision: str) -> bool:
    return normalize_decision(str(decision or "")) == "精选"


def _series_for(market: MarketStore, code: str, start: str, end: str) -> dict[str, dict[str, float]]:
    frame = market.history(code, start=start, end=end, adjust="qfq")
    if frame.empty:
        return {}
    return {
        str(row.trade_date): {
            "close": float(row.close) if row.close is not None else float("nan"),
            "high": float(row.high) if row.high is not None else float("nan"),
            "low": float(row.low) if row.low is not None else float("nan"),
        }
        for row in frame.itertuples()
    }


def _series_from_panel(
    panels: dict[str, Any], code: str, start: str, end: str
) -> dict[str, dict[str, float]]:
    """从宽表面板切出单票 [start, end] 的 close/high/low，形状同 ``_series_for``。

    面板里缺票/停牌是 NaN：整日三列全 NaN 视为「当天没有这根 K 线」，
    不落 key（等价于原来 history 里没有这一行），**绝不把 NaN 当 0**。
    """
    columns: dict[str, Any] = {}
    for key in ("close", "high", "low"):
        panel = panels.get(key)
        if panel is None or getattr(panel, "empty", True):
            continue
        if code not in panel.columns:
            continue
        column = panel[code]
        # 面板窗口是全局合并区间，这里要回到本票自己的 [start, end]
        columns[key] = column[(column.index >= start) & (column.index <= end)]
    if not columns:
        return {}
    series: dict[str, dict[str, float]] = {}
    for key, column in columns.items():
        for day, value in column.items():
            if value != value:  # NaN：该字段当日无数
                continue
            series.setdefault(str(day), {})[key] = float(value)
    for bar in series.values():
        for key in ("close", "high", "low"):
            bar.setdefault(key, float("nan"))
    return series


def filter_recent_outcomes(
    outcomes: list[CandidateOutcome],
    calendar: list[str],
    *,
    as_of: str,
    window_days: int = 5,
    selected_only: bool = True,
) -> list[CandidateOutcome]:
    """只保留近 ``window_days`` 个交易日内选出的候选。

    口径：T 日选出、T+1 买入、最迟 T+4 卖出 → 共 5 个交易日。
    在观察日 ``as_of``（对齐交易日）上，展示 base_date ∈ [D−(window−1), D]。
    """
    if window_days <= 0 or not calendar:
        return []
    day = str(as_of or "").strip()
    if not day:
        return []
    end_idx = bisect_left(calendar, day)
    if end_idx >= len(calendar) or calendar[end_idx] != day:
        end_idx -= 1
    if end_idx < 0:
        return []
    start_idx = max(0, end_idx - int(window_days) + 1)
    allowed = set(calendar[start_idx : end_idx + 1])
    rows: list[CandidateOutcome] = []
    for outcome in outcomes:
        if selected_only and not outcome.selected:
            continue
        if outcome.base_date in allowed:
            rows.append(outcome)
    return rows


def evaluate_candidates(
    palace: PalaceStore,
    market: MarketStore,
    *,
    limit: int = 500,
    benchmark: str | None = "000300",
) -> list[CandidateOutcome]:
    """对候选池里的每一条裁决算 T+N 结局。"""
    rows = palace.candidate_outcome_rows(limit=limit)
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
                tier=str(row.get("tier") or "core"),
                pool_id=str(row.get("pool_id") or ""),
                strategy_slug=str(row.get("strategy_slug") or ""),
                rule_version=str(row.get("rule_version") or ""),
            )
            for row in rows
        ]

    max_horizon = max(HORIZONS)
    windows_by_candidate: dict[str, list[str]] = {}
    ranges_by_code: dict[str, tuple[str, str]] = {}
    for row in rows:
        index = bisect_left(calendar, str(row["occurred_on"]))
        if index >= len(calendar):
            continue
        window = calendar[index : index + max_horizon + 1]
        if not window:
            continue
        candidate_id = str(row["id"])
        windows_by_candidate[candidate_id] = window
        code = str(row["code"])
        previous = ranges_by_code.get(code)
        if previous is None:
            ranges_by_code[code] = (window[0], window[-1])
        else:
            ranges_by_code[code] = (
                min(previous[0], window[0]),
                max(previous[1], window[-1]),
            )

    # 基准指数只有一只票、一个区间，保留原来的单次 history 查询。
    benchmark_series = (
        _series_for(market, benchmark, calendar[0], calendar[-1]) if benchmark else {}
    )
    # 为什么批量：候选池常在不同池/不同日重复收录同一标的，按代码合并区间后
    # 仍有 N_code 次 history（默认 300、任务下 2000 条候选 = 上千次 SQLite 往返）；
    # load_panel 一条 IN (...) 全取回，只剩 1 次（加基准 1 次）。
    series_by_code: dict[str, dict[str, dict[str, float]]] = {}
    if ranges_by_code:
        # 面板必须给 start；取全局合并区间，再在内存按票切回各自区间。
        min_start = min(window_start for window_start, _ in ranges_by_code.values())
        max_end = max(window_end for _, window_end in ranges_by_code.values())
        panels = market.load_panel(
            fields=("close", "high", "low"),
            codes=sorted(ranges_by_code),
            start=min_start,
            end=max_end,
            adjust="qfq",
        )
        series_by_code = {
            code: _series_from_panel(panels, code, window_start, window_end)
            for code, (window_start, window_end) in ranges_by_code.items()
        }

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
            tier=str(row.get("tier") or "core"),
            pool_id=str(row.get("pool_id") or ""),
            strategy_slug=str(row.get("strategy_slug") or ""),
            rule_version=str(row.get("rule_version") or ""),
        )

        window = windows_by_candidate.get(outcome.candidate_id)
        if window is None:
            outcome.note = "候选日之后还没有交易日数据"
            outcomes.append(outcome)
            continue
        index = bisect_left(calendar, base_date)
        series = series_by_code.get(outcome.code, {})
        base = series.get(window[0], {}).get("close")
        if base is None or not base > 0:
            outcome.note = "未取得真实行情，无法评估"
            outcomes.append(outcome)
            continue
        outcome.base_close = round(base, 4)

        highs: list[float] = []
        lows: list[float] = []
        post_highs: list[float] = []
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

        # 浮盈高点 / 低→高波幅都不含选股日当天，只看 T+1 起的观察窗。
        for day in window[1:]:
            bar = series.get(day, {})
            high = bar.get("high")
            low = bar.get("low")
            if high and high == high:
                highs.append(high)
                post_highs.append(high)
            if low and low == low and low > 0:
                lows.append(low)
        if post_highs:
            outcome.max_favorable_pct = round((max(post_highs) / base - 1) * 100, 4)
        if highs and lows:
            floor = min(lows)
            peak = max(highs)
            if floor > 0 and peak >= floor:
                outcome.swing_pct = round((peak - floor) / floor * 100, 4)
        if all(value is None for value in outcome.returns.values()):
            outcome.note = "观察窗口尚未走完"
        elif any(outcome.returns.get(h) is None for h in PRIMARY_HORIZONS):
            pending = [h for h in PRIMARY_HORIZONS if outcome.returns.get(h) is None]
            outcome.note = f"短线窗口未满（待 T+{'/'.join(str(h) for h in pending)}）"
        outcomes.append(outcome)

    return outcomes


def _horizon_aggregate(items: list[CandidateOutcome], horizon: int) -> dict[str, Any] | None:
    values = [o.returns.get(horizon) for o in items]
    values = [v for v in values if v is not None]
    if not values:
        return None
    body = {
        "n": len(values),
        "avg": round(sum(values) / len(values), 4),
        "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100, 2),
        "best": round(max(values), 4),
        "worst": round(min(values), 4),
        # 一只候选走完 T+5 就能报「胜率 100%」。数字本身没错，但不标样本档
        # 等于放任把它当结论；与回测 metrics 用同一套 low/medium/high。
        "sample_confidence": sample_confidence(len(values)),
    }
    if len(values) < SAMPLE_LOW:
        body["caution"] = f"样本仅 {len(values)} 只候选，胜率不稳定，不宜据此外推"
    return body


def summarize_by_strategy(
    outcomes: list[CandidateOutcome],
    *,
    selected_only: bool = True,
    primary_horizon: int = 5,
) -> list[dict[str, Any]]:
    """按战法汇总精选候选的 T+1/T+3/T+5 胜率（目录用）。"""
    groups: dict[str, list[CandidateOutcome]] = {}
    for outcome in outcomes:
        if selected_only and not outcome.selected:
            continue
        groups.setdefault(outcome.strategy_tag(), []).append(outcome)

    rows: list[dict[str, Any]] = []
    for tag, items in groups.items():
        horizons: dict[str, Any] = {}
        for horizon in PRIMARY_HORIZONS:
            stats = _horizon_aggregate(items, horizon)
            if stats is not None:
                horizons[f"t{horizon}"] = stats

        primary = horizons.get(f"t{primary_horizon}")
        primary_values = [
            o.returns.get(primary_horizon)
            for o in items
            if o.returns.get(primary_horizon) is not None
        ]
        wins = sum(1 for v in primary_values if v is not None and v > 0)
        observing = sum(
            1 for o in items if o.window_progress()["status"] != "complete"
        )
        last_dates = [o.base_date for o in items if o.base_date]
        row: dict[str, Any] = {
            "strategy_tag": tag,
            "total": len(primary_values),
            "wins": wins,
            "win_rate": primary["win_rate"] if primary else None,
            "avg_return": primary["avg"] if primary else None,
            "last_reviewed": max(last_dates) if last_dates else "",
            "source": "candidates",
            "horizons": horizons,
            "observing": observing,
            "sample_all": len(items),
            "primary_horizon": primary_horizon,
            "sample_confidence": sample_confidence(len(primary_values)),
        }
        if primary_values and len(primary_values) < SAMPLE_LOW:
            row["caution"] = (
                f"T+{primary_horizon} 仅 {len(primary_values)} 只候选走完窗口，"
                "胜率不稳定，不宜据此外推"
            )
        rows.append(row)
    rows.sort(
        key=lambda r: (-int(r.get("total") or 0), -int(r.get("sample_all") or 0), str(r["strategy_tag"]))
    )
    return rows


def track_candidate_outcomes(
    palace: PalaceStore,
    market: MarketStore,
    *,
    limit: int = 2000,
    benchmark: str | None = "000300",
    max_age_trading_days: int = 5,
) -> dict[str, Any]:
    """盘后自动跟踪：重算近期候选 T+N，产出战法胜率快照。

    ``max_age_trading_days`` 默认 5：只强调短线窗口内的跟踪进度；
    汇总仍基于全量 limit 内候选，便于目录胜率连贯。

    **口径变更（2026-08，实盘项下线）**：此前本函数在算完候选 T+N 之后，还会把
    精选候选镜像写进 ``position_tracking``，供「回测-实盘偏离」消费；返回值里
    因此带一个 ``tracking`` 计数。``position_tracking`` 已随实盘项一并删除，那段
    镜像写入和 ``tracking`` 键都已移除。**T+N 数字本身一个都没变**——它们从来
    只由 ``candidate_reviews`` + 行情推导，``position_tracking`` 是只写不读的旁路。
    """
    outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
    calendar = market.trading_days()
    as_of = calendar[-1] if calendar else ""
    age_cutoff = ""
    if calendar and max_age_trading_days > 0:
        idx = max(0, len(calendar) - max_age_trading_days)
        age_cutoff = calendar[idx]

    recent = [o for o in outcomes if not age_cutoff or o.base_date >= age_cutoff]
    selected_recent = [
        o
        for o in outcomes
        if o.selected
        and (
            o.window_progress()["status"] != "complete"
            or not age_cutoff
            or o.base_date >= age_cutoff
        )
    ]
    by_status = {"observing": 0, "partial": 0, "complete": 0}
    for outcome in selected_recent:
        status = outcome.window_progress()["status"]
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "as_of": as_of,
        "age_cutoff": age_cutoff,
        "max_age_trading_days": max_age_trading_days,
        "total_outcomes": len(outcomes),
        "recent_selected": len(selected_recent),
        "recent_dated": len([o for o in recent if o.selected]),
        "window_status": by_status,
        "by_strategy": summarize_by_strategy(outcomes, selected_only=True),
        "summary": summarize_candidates(outcomes),
        "horizons": list(PRIMARY_HORIZONS),
    }


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
            stats[f"t{horizon}"] = _horizon_aggregate(items, horizon)
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
