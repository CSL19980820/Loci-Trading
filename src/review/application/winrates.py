"""战法胜率：汇总 / 分周期 / 样本明细。

三个视角共用同一个事实源——**精选候选的 T+N 结局**（``evaluate_candidates``）；
手工 ``reviews`` 只在某战法一条候选样本都没有时兜底。

2026-09 之前这里只有 ``strategy_winrate_summary``，胜率页的「分周期明细」走的是
``PalaceStore.winrate_trend``（只读 ``reviews.return_pct``）。选股落池后复盘已经
全面改成候选 T+N 自动跟踪，没人再手工填 ``reviews``——线上该表 0 行，于是那张表
**永远空着**，页面上一句「无周期明细」既解释不了原因也修不好。现在分周期与主表
同源，空表只在「确实还没有任何样本」时出现。

``build_winrate_summary`` / ``winrate_periods`` / ``winrate_samples`` 都接受**已经
算好的** outcomes，由 API 层缓存一次三处复用，避免同一条请求链上把 700ms 的
``evaluate_candidates`` 跑三遍。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.ledger import PalaceStore
from src.market import MarketStore
from src.review.application.outcomes import (
    HORIZONS,
    CandidateOutcome,
    evaluate_candidates,
    horizon_aggregate,
    sample_confidence,
    summarize_by_strategy,
)

#: 「最佳持有期」至少要有这么多已兑现样本才参与评选——2 个样本的 100% 不是结论。
_BEST_HORIZON_MIN_N = 3


def strategy_winrate_summary(
    palace: PalaceStore,
    market: MarketStore,
    *,
    limit: int = 2000,
    primary_horizon: int = 5,
    benchmark: str | None = "000300",
) -> list[dict[str, Any]]:
    """目录 / 胜率页用的战法胜率表；自带 outcomes 计算，供非 HTTP 调用方。"""
    outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
    return build_winrate_summary(
        outcomes,
        palace.strategy_winrates(),
        primary_horizon=primary_horizon,
    )


def build_winrate_summary(
    outcomes: list[CandidateOutcome],
    review_rows: list[dict[str, Any]],
    *,
    primary_horizon: int = 5,
) -> list[dict[str, Any]]:
    """优先精选候选在 ``primary_horizon`` 已兑现的样本；无候选样本的战法回退手工复盘。

    每行在 ``summarize_by_strategy`` 之上补三样「凭什么这么算」的证据：全持有期分档
    ``horizons``、最佳/最差样本 ``best_sample`` / ``worst_sample``、最优持有期
    ``best_horizon``。数字全部来自同一批 outcomes，页面无需再发第二个请求。
    """
    from_candidates = summarize_by_strategy(
        outcomes,
        selected_only=True,
        primary_horizon=primary_horizon,
    )
    by_tag = {row["strategy_tag"]: row for row in from_candidates if row.get("strategy_tag")}

    selected_by_tag: dict[str, list[CandidateOutcome]] = {}
    for outcome in outcomes:
        if outcome.selected:
            selected_by_tag.setdefault(outcome.strategy_tag(), []).append(outcome)

    for tag, row in by_tag.items():
        items = selected_by_tag.get(tag, [])
        row["horizons"] = _all_horizon_stats(items)
        row["best_horizon"] = _best_horizon(row["horizons"])
        best, worst = _extreme_samples(items, primary_horizon)
        row["best_sample"] = best
        row["worst_sample"] = worst

    for row in review_rows:
        tag = str(row.get("strategy_tag") or "")
        if not tag:
            continue
        existing = by_tag.get(tag)
        if existing and int(existing.get("total") or 0) > 0:
            continue
        if existing and int(existing.get("sample_all") or 0) > 0:
            # 有入选但窗口未走完：保留候选行（胜率可能为空），不盖成复盘口径
            continue
        by_tag[tag] = {
            **row,
            "source": "reviews",
            "horizons": {},
            "best_horizon": None,
            "best_sample": None,
            "worst_sample": None,
            "observing": 0,
            "sample_all": int(row.get("total") or 0),
        }

    rows = list(by_tag.values())
    rows.sort(
        key=lambda r: (
            -int(r.get("total") or 0),
            -int(r.get("sample_all") or 0),
            str(r.get("strategy_tag")),
        )
    )
    return rows


def winrate_periods(
    outcomes: list[CandidateOutcome],
    *,
    granularity: str = "month",
    strategy_tags: list[str] | None = None,
    primary_horizon: int = 5,
) -> list[dict[str, Any]]:
    """精选候选按**选出日**分月 / 分周聚合 T+N 胜率。

    period 口径与 ``PalaceStore.winrate_trend`` 对齐：月为 ``YYYY-MM``，周为该周
    周一的 ``YYYY-MM-DD``——两种数据源画进同一张表，不能有两套周编号。
    """
    wanted = set(strategy_tags) if strategy_tags else None
    buckets: dict[tuple[str, str], list[float]] = {}
    for outcome in outcomes:
        if not outcome.selected:
            continue
        tag = outcome.strategy_tag()
        if wanted is not None and tag not in wanted:
            continue
        value = outcome.returns.get(primary_horizon)
        if value is None:
            continue
        period = _period_key(outcome.base_date, granularity)
        if not period:
            continue
        buckets.setdefault((period, tag), []).append(value)

    rows: list[dict[str, Any]] = []
    for (period, tag), values in buckets.items():
        wins = sum(1 for v in values if v > 0)
        rows.append(
            {
                "period": period,
                "strategy_tag": tag,
                "total": len(values),
                "wins": wins,
                "win_rate": round(wins / len(values) * 100, 1),
                "avg_return": round(sum(values) / len(values), 2),
                "source": "candidates",
            }
        )
    rows.sort(key=lambda r: (r["period"], r["strategy_tag"]))
    return rows


def winrate_samples(
    outcomes: list[CandidateOutcome],
    *,
    strategy_tag: str,
    primary_horizon: int = 5,
    limit: int = 300,
) -> dict[str, Any]:
    """某战法的逐条样本：胜率的分母到底是哪几只票、哪天选出、各自涨跌多少。

    ``settled`` 是已走完 ``primary_horizon`` 的条数（= 胜率分母），``observing`` 是
    还在窗口里的条数。两者相加才是「入选过多少次」——页面把它们分开摆，才不会让人
    以为 12 个样本就是这个战法一共只选出过 12 次。
    """
    items = [o for o in outcomes if o.selected and o.strategy_tag() == strategy_tag]
    items.sort(key=lambda o: (o.base_date, o.code), reverse=True)

    settled = [
        o.returns[primary_horizon]
        for o in items
        if o.returns.get(primary_horizon) is not None
    ]
    wins = sum(1 for v in settled if v > 0)

    samples: list[dict[str, Any]] = []
    for outcome in items[:limit]:
        value = outcome.returns.get(primary_horizon)
        body = outcome.to_dict()
        body["win"] = None if value is None else bool(value > 0)
        body["primary_return"] = value
        samples.append(body)

    return {
        "strategy_tag": strategy_tag,
        "primary_horizon": primary_horizon,
        "settled": len(settled),
        "observing": len(items) - len(settled),
        "wins": wins,
        "win_rate": round(wins / len(settled) * 100, 1) if settled else None,
        "avg_return": round(sum(settled) / len(settled), 2) if settled else None,
        "sample_confidence": sample_confidence(len(settled)),
        "truncated": len(items) > limit,
        "samples": samples,
    }


def _all_horizon_stats(items: list[CandidateOutcome]) -> dict[str, Any]:
    """T+1…T+60 全档统计。

    ``summarize_by_strategy`` 只报 T+1/3/5（目录页够用），但 ``evaluate_candidates``
    本来就把 T+10/20/60 都算了——丢掉它们，等于让人无法回答「这战法该拿几天」。
    口径直接借 ``horizon_aggregate``：胜率页与目录页的同一个数字不能有两套算法。
    """
    stats: dict[str, Any] = {}
    for horizon in HORIZONS:
        aggregate = horizon_aggregate(items, horizon)
        if aggregate is not None:
            stats[f"t{horizon}"] = aggregate
    return stats


def _best_horizon(horizons: dict[str, Any]) -> dict[str, Any] | None:
    """样本够的持有期里胜率最高者（同胜率比均收益）。"""
    ranked = [b for b in horizons.values() if int(b.get("n") or 0) >= _BEST_HORIZON_MIN_N]
    if not ranked:
        return None
    ranked.sort(key=lambda b: (b["win_rate"], b["avg"]), reverse=True)
    return ranked[0]


def _extreme_samples(
    items: list[CandidateOutcome],
    horizon: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """最佳 / 最差样本：``horizon_aggregate`` 只报了数值，这里补上「是哪只票」。"""
    settled = [o for o in items if o.returns.get(horizon) is not None]
    if not settled:
        return None, None
    best = max(settled, key=lambda o: o.returns[horizon])
    worst = min(settled, key=lambda o: o.returns[horizon])
    return _sample_brief(best, horizon), _sample_brief(worst, horizon)


def _sample_brief(outcome: CandidateOutcome, horizon: int) -> dict[str, Any]:
    return {
        "code": outcome.code,
        "name": outcome.name,
        "base_date": outcome.base_date,
        "base_close": outcome.base_close,
        "return_pct": outcome.returns.get(horizon),
        "max_favorable_pct": outcome.max_favorable_pct,
        "horizon": horizon,
    }


def _period_key(base_date: str, granularity: str) -> str:
    """选出日 → 周期键。周口径与 SQLite ``date(d,'weekday 0','-6 days')`` 等价（周一为周首）。"""
    if not base_date or len(base_date) < 10:
        return ""
    if granularity != "week":
        return base_date[:7]
    try:
        day = date.fromisoformat(base_date[:10])
    except ValueError:
        return ""
    return (day - timedelta(days=day.weekday())).isoformat()
