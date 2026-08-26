"""尾盘 14:50 选股器：从信号搜索到可执行战法。

与姊妹脚本 ``tail_1450_next_day_touch_research.py`` 的分工：那一份在检验「次日冲高
≥0.5%」这个**标签**能不能用（结论：不能，基准冲高率就有 75.12%）。本脚本是**产出侧**
——不再优化冲高率，直接优化每笔净收益，目标是交出一个能上的尾盘战法。

四条比上一轮多出来的维度，每一条都是上一轮的盲区：

1. **持有期**。上一轮只测 T+1。仓内 ``qianlong-close-v3`` 持约 3 日，尾盘信号的 edge
   很可能要多给一两天才出得来。这里跑 1/2/3/5 日。
2. **止损**。上一轮无止损（或只有 T+1 的 −3%）。这里跑 无 / −5% / −7%。
3. **每日 top-N 排序**。上一轮是「条件命中就全买」，动辄日均上百只，不可执行。
   这里必须先按打分取前 N 只，N ∈ {1,2,3,5}。
4. **筛选闸门**。候选必须同时过四关才进决赛：日均出票 ≤5、前后两段皆正、
   **日内截面中性化后仍为正**（证明在选股而非踩大盘）、逐年至少 4/6 为正。

只读 ``market.db``，不注册战法，不写任何业务表。
入场价用当日收盘价代理 14:50，其局限见
``docs/research/2026-08-tail-1450-next-day-touch-backtest.md`` §8。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
from itertools import combinations
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.formula import HHV, MA, REF  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.heat_tail_attention_proxy_research import _load_panels  # noqa: E402
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402
from scripts.tail_1450_next_day_touch_research import (  # noqa: E402
    ROUND_TRIP_COST,
    TARGET,
    Gates,
    _load_universe,
    build_features,
    day_demean,
)

#: 最长持有期，决定要往前多加载几根 K。
MAX_HOLD = 5


class Book:
    """扁平样本集，带 1..MAX_HOLD 日的前瞻 OHLC。"""

    def __init__(self, parts: list[dict[str, np.ndarray]], window: list[str]) -> None:
        # fwd_* 是 (MAX_HOLD, n) 的二维栈，要沿样本轴拼；其余是一维。
        merged = {
            k: np.concatenate([p[k] for p in parts], axis=1 if parts[0][k].ndim == 2 else 0)
            for k in parts[0]
        }
        parts.clear()
        self.day_idx = merged.pop("day_idx")
        self.n_days = len(window)
        self.window = window
        self.half = self.day_idx >= self.n_days // 2
        self.years = np.asarray([d[:4] for d in window])[self.day_idx]
        self.entry = merged.pop("entry")
        self.fwd = {
            key: merged.pop(f"fwd_{key}") for key in ("open", "high", "low", "close")
        }
        self.factors = merged
        # 冲高率：次日最高 ≥ 入场 ×1.005。保留它只为与姊妹篇对照，不用于寻优。
        self.spike = self.fwd["high"][0] >= self.entry * (1.0 + TARGET)
        vol_rank = self.cs_rank(self.factors["f_prev_atr_pct"])
        self.vol_bucket = np.where(
            np.isfinite(vol_rank), np.clip(np.nan_to_num(vol_rank) * 10.0, 0, 9), -1
        ).astype("int16")

    def size(self) -> int:
        return int(self.entry.size)

    def cs_rank(self, vals: np.ndarray) -> np.ndarray:
        ok = np.isfinite(vals)
        out = np.full(vals.size, np.nan, dtype="float32")
        order = np.lexsort((np.where(ok, vals, np.inf), self.day_idx))
        d = self.day_idx[order]
        bounds = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
        for start, end in zip(bounds[:-1], bounds[1:]):
            block = order[start:end]
            good = block[ok[block]]
            if good.size < 20:
                continue
            out[good] = np.arange(good.size, dtype="float32") / max(good.size - 1, 1)
        return out

    def exit_net(self, hold: int, stop: float | None) -> np.ndarray:
        """持有 hold 个交易日，到期按收盘了结；带止损时逐日检查。

        止损先后与 ``src/backtest`` 引擎一致：开盘已跌破按开盘价成交（时点无歧义），
        否则当日最低触及按止损价成交。触发后不再参与后续日。
        """
        n = self.size()
        done = np.zeros(n, dtype=bool)
        px = np.zeros(n, dtype="float64")
        if stop is not None:
            stop_px = self.entry * (1.0 - stop)
            for d in range(hold):
                o, low = self.fwd["open"][d], self.fwd["low"][d]
                gap = (~done) & np.isfinite(o) & (o <= stop_px)
                px[gap], done[gap] = o[gap], True
                touched = (~done) & np.isfinite(low) & (low <= stop_px)
                px[touched], done[touched] = stop_px[touched], True
        last = self.fwd["close"][hold - 1]
        px[~done] = last[~done]
        return (px / self.entry - 1.0 - ROUND_TRIP_COST).astype("float32")

    def valid(self, hold: int) -> np.ndarray:
        return np.isfinite(self.fwd["close"][hold - 1]) & np.isfinite(self.entry)


def flatten_chunk(
    feats: dict[str, pd.DataFrame], seg: list[str], day_offset: int
) -> dict[str, np.ndarray]:
    keep = feats["tradable"].loc[seg].to_numpy() & feats["sellable"].loc[seg].to_numpy()
    rows, cols = np.nonzero(keep)
    out: dict[str, np.ndarray] = {"day_idx": (rows + day_offset).astype("int32")}
    out["entry"] = feats["entry"].loc[seg].to_numpy()[rows, cols].astype("float64")
    for key in ("open", "high", "low", "close"):
        stack = np.empty((MAX_HOLD, rows.size), dtype="float32")
        for d in range(1, MAX_HOLD + 1):
            stack[d - 1] = feats[f"fwd{d}_{key}"].loc[seg].to_numpy()[rows, cols]
        out[f"fwd_{key}"] = stack
    for key in feats:
        if key.startswith("f_"):
            out[key] = feats[key].loc[seg].to_numpy()[rows, cols].astype("float32")
    return out


def add_forward_panels(feats: dict[str, pd.DataFrame], qfq: dict[str, pd.DataFrame]) -> None:
    for d in range(1, MAX_HOLD + 1):
        for key in ("open", "high", "low", "close"):
            feats[f"fwd{d}_{key}"] = qfq[key].shift(-d)


def add_legal_features(feats: dict[str, pd.DataFrame], qfq: dict[str, pd.DataFrame]) -> None:
    """补上 14:50 时点**真实可得**的因子，并删掉裸用当日最高/最低的那些。

    本仓 ``entry_timing="close"`` 的静态审计（``src/strategy/README.md``）把
    「裸用当日 high / low」判为 **block**——因为全天最高最低要等收盘才知道。
    所以 ``f_clv`` / ``f_range_pct`` / ``f_range_contract`` / ``f_atr_pct`` 这几个
    上一轮用得最多的因子，做出来的战法在本仓 ``guard_strategy`` 那关就过不了，
    等于不能上线。这里换成同义但合法的版本：

    - ``f_kmid``：``(close-open)/open``，qlib Alpha158 的 KBAR 组同名特征。
      它和 CLV 表达同一个直觉「今天收在强的一头」，但只用开盘价与收盘价。
    - ``f_prev_clv`` / ``f_prev_atr_pct`` / ``f_prev_hhv60_pos``：把需要当日极值的
      因子整体滞后一天，14:50 时它们已经是历史。
    - ``f_ma5_over_ma10``：均线多头排列，只用收盘价。
    """
    close, open_ = qfq["close"], qfq["open"]
    feats["f_kmid"] = (close / open_ - 1.0) * 100.0
    feats["f_prev_clv"] = feats["f_clv"].shift(1)
    feats["f_prev_atr_pct"] = feats["f_atr_pct"].shift(1)
    feats["f_prev_hhv60_pos"] = close / HHV(qfq["high"], 60).shift(1)
    feats["f_ma5_over_ma10"] = (MA(close, 5) / MA(close, 10) - 1.0) * 100.0
    feats["f_up_days5"] = (close > REF(close, 1)).rolling(5).sum()
    for key in ("f_clv", "f_atr_pct", "f_range_pct", "f_range_contract", "f_hhv60_pos"):
        feats.pop(key, None)


# ---- 候选条件池 ----------------------------------------------------------------
#
# 种子来自上一轮唯一日中性为正的家族（收盘位置强 + 温和放量 + 未超买），
# 但全部换成 14:50 真实可得的版本（见 add_legal_features），另补几条上一轮
# 没测过的经典尾盘概念：均线多头、连阳、缩量回踩。

CONDS: tuple[tuple[str, str, float], ...] = (
    ("f_kmid", "ge", 0.0),
    ("f_kmid", "ge", 1.0),
    ("f_kmid", "ge", 2.5),
    ("f_prev_clv", "ge", 0.7),
    ("f_prev_clv", "ge", 0.9),
    ("f_vol_ratio", "ge", 1.2),
    ("f_vol_ratio", "ge", 1.5),
    ("f_vol_ratio", "ge", 2.0),
    ("f_vol_ratio", "le", 3.0),
    ("f_rsi6", "le", 55.0),
    ("f_rsi6", "le", 65.0),
    ("f_rsi6", "le", 80.0),
    ("f_prev_atr_pct", "le", 3.0),
    ("f_prev_atr_pct", "le", 4.5),
    ("f_ma20_bias", "ge", 0.0),
    ("f_ma5_bias", "ge", 0.0),
    ("f_ma5_bias", "le", 4.0),
    ("f_ma5_over_ma10", "ge", 0.0),
    ("f_pct_chg", "ge", 0.0),
    ("f_pct_chg", "le", 5.0),
    ("f_prev_hhv60_pos", "ge", 0.9),
    ("f_prev_hhv60_pos", "le", 1.0),
    ("f_turnover", "ge", 1.0),
    ("f_turnover", "le", 10.0),
    ("f_roc5", "le", 12.0),
    ("f_log_amount", "ge", 8.0),
    ("f_up_days5", "ge", 3.0),
)

#: top-N 排序打分。负号表示越小越优先。
SCORES: tuple[tuple[str, str], ...] = (
    ("roc5", "+f_roc5"),
    ("kmid", "+f_kmid"),
    ("vol_ratio", "+f_vol_ratio"),
    ("low_atr", "-f_prev_atr_pct"),
    ("low_rsi", "-f_rsi6"),
)


def cond_label(c: tuple[str, str, float]) -> str:
    return f"{c[0][2:]}{'≥' if c[1] == 'ge' else '≤'}{c[2]:g}"


def cond_mask(book: Book, c: tuple[str, str, float]) -> np.ndarray:
    v = book.factors[c[0]]
    ok = np.isfinite(v)
    return (v >= c[2] if c[1] == "ge" else v <= c[2]) & ok


def combo_ok(combo: Sequence[tuple[str, str, float]]) -> bool:
    seen: dict[tuple[str, str], float] = {}
    for factor, op, value in combo:
        if (factor, op) in seen:
            return False
        seen[(factor, op)] = value
    for (factor, op), value in seen.items():
        if op == "ge" and (factor, "le") in seen and seen[(factor, "le")] <= value:
            return False
    return True


#: 未入选样本的名次哨兵，比任何 top_n 都大。
_RANK_INF = np.int32(1 << 30)


def daily_rank(book: Book, sel: np.ndarray, score: np.ndarray) -> np.ndarray:
    """每只票在当日候选内的名次（0 = 当日最优）。未入选记 ``_RANK_INF``。

    返回名次而不是布尔掩码，是为了让同一次排序服务全部 top_n——
    否则 40 个条件集 × 5 种打分 × 4 个 top_n 要做 800 次百万级 lexsort。
    """
    rank = np.full(sel.size, _RANK_INF, dtype="int32")
    idx = np.flatnonzero(sel)
    if idx.size == 0:
        return rank
    order = idx[np.lexsort((-score[idx], book.day_idx[idx]))]
    d = book.day_idx[order]
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    group_len = np.diff(np.r_[starts, order.size])
    rank[order] = (np.arange(order.size) - np.repeat(starts, group_len)).astype("int32")
    return rank


def stats(book: Book, net: np.ndarray, sel: np.ndarray, *, full: bool = False) -> dict[str, Any]:
    part = net[sel]
    n = int(part.size)
    if n == 0:
        return {"n": 0}
    wins, losses = part[part > 0], part[part < 0]
    mean_win = float(wins.mean()) if wins.size else 0.0
    mean_loss = float(-losses.mean()) if losses.size else 0.0
    half = book.half[sel]
    out: dict[str, Any] = {
        "n": n,
        "per_day": round(n / book.n_days, 2),
        "win_rate": round(float(np.mean(part > 0) * 100), 2),
        "payoff": round(mean_win / mean_loss, 3) if mean_loss > 0 else None,
        "mean_pct": round(float(np.mean(part, dtype="float64") * 100), 4),
        "median_pct": round(float(np.median(part)) * 100, 4),
        "spike_rate": round(float(np.mean(book.spike[sel]) * 100), 2),
        "front_mean_pct": round(float(np.mean(part[~half], dtype="float64") * 100), 4)
        if (~half).any()
        else None,
        "back_mean_pct": round(float(np.mean(part[half], dtype="float64") * 100), 4)
        if half.any()
        else None,
    }
    if full:
        out["profit_factor"] = (
            round(float(wins.sum() / -losses.sum()), 3) if losses.size and losses.sum() else None
        )
        out["avg_win_pct"] = round(mean_win * 100, 4)
        out["avg_loss_pct"] = round(-mean_loss * 100, 4)
        out["mean_atr_pct"] = round(float(np.nanmean(book.factors["f_prev_atr_pct"][sel])), 3)
    return out


def yearly(book: Book, net: np.ndarray, sel: np.ndarray) -> list[dict[str, Any]]:
    out = []
    for y in sorted(set(book.years.tolist())):
        part = sel & (book.years == y)
        if int(part.sum()) < 30:
            continue
        out.append(
            {
                "year": y,
                "n": int(part.sum()),
                "mean_pct": round(float(np.mean(net[part], dtype="float64") * 100), 4),
            }
        )
    return out


def load_book(args: argparse.Namespace, gates: Gates) -> tuple[Book, list[str], int]:
    conn = _read_only_connection(Path(args.db))
    try:
        days = _load_days(conn)
        window = [d for d in days if args.start <= d <= args.end]
        codes, list_date = _load_universe(conn, boards=set(args.boards.split(",")))
        print(f"票池 {len(codes)} 只 / 窗口 {window[0]}~{window[-1]} 共 {len(window)} 日", flush=True)
        parts: list[dict[str, np.ndarray]] = []
        for offset in range(0, len(window), args.chunk_days):
            seg = window[offset : offset + args.chunk_days]
            head, tail = days.index(seg[0]), days.index(seg[-1])
            qfq, raw = _load_panels(
                conn,
                load_start=days[max(head - gates.warmup_bars, 0)],
                load_end=days[min(tail + MAX_HOLD, len(days) - 1)],
                dates=days,
                codes=codes,
            )
            feats = build_features(qfq, raw, list_date, gates)
            add_legal_features(feats, qfq)
            add_forward_panels(feats, qfq)
            del qfq, raw
            parts.append(flatten_chunk(feats, seg, offset))
            del feats
            gc.collect()
            print(f"  {seg[0]}~{seg[-1]} 样本 {parts[-1]['day_idx'].size:,}", flush=True)
    finally:
        conn.close()
    book = Book(parts, window)
    gc.collect()
    print(f"可交易样本 {book.size():,}", flush=True)
    return book, codes, len(window)


def phase1(book: Book, args: argparse.Namespace) -> list[tuple[Any, ...]]:
    """先在「全取、无止损」下按 hold 找出值得细搜的条件集。"""
    masks = {c: cond_mask(book, c) for c in CONDS}
    nets = {h: book.exit_net(h, None) for h in (1, 2, 3)}
    valids = {h: book.valid(h) for h in (1, 2, 3)}
    rows: list[dict[str, Any]] = []
    for k in (1, 2, 3):
        for combo in combinations(CONDS, k):
            if not combo_ok(combo):
                continue
            base = masks[combo[0]].copy()
            for c in combo[1:]:
                base &= masks[c]
            if int(base.sum()) < args.min_pool:
                continue
            for h in (1, 2, 3):
                sel = base & valids[h]
                if int(sel.sum()) < args.min_pool:
                    continue
                m = float(np.mean(nets[h][sel], dtype="float64"))
                rows.append({"combo": combo, "hold": h, "mean": m, "n": int(sel.sum())})
    rows.sort(key=lambda r: r["mean"], reverse=True)
    seen: set[tuple[Any, ...]] = set()
    out: list[tuple[Any, ...]] = []
    for r in rows:
        if r["combo"] in seen:
            continue
        seen.add(r["combo"])
        out.append(r["combo"])
        if len(out) >= args.phase1_keep:
            break
    print(f"phase1：{len(rows)} 组评估，保留 {len(out)} 个条件集进入细搜", flush=True)
    return out


def phase2(
    book: Book, keep: Iterable[tuple[Any, ...]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    """对入围条件集跑 (打分 × top-N × 持有期 × 止损) 全网格。"""
    holds = tuple(int(x) for x in args.holds.split(","))
    stops: tuple[float | None, ...] = (None, 0.05, 0.07)
    nets = {(h, s): book.exit_net(h, s) for h in holds for s in stops}
    neutral = {key: day_demean(book, v) for key, v in nets.items()}
    valids = {h: book.valid(h) for h in holds}
    scored = {
        name: (
            np.nan_to_num(book.factors[expr[1:]], nan=-1e9)
            if expr[0] == "+"
            else -np.nan_to_num(book.factors[expr[1:]], nan=1e9)
        )
        for name, expr in SCORES
    }
    out: list[dict[str, Any]] = []
    for combo in keep:
        base = cond_mask(book, combo[0]).copy()
        for c in combo[1:]:
            base &= cond_mask(book, c)
        label = " & ".join(cond_label(c) for c in combo)
        for score_name, score in scored.items():
            rank = daily_rank(book, base, score)
            for top_n in (1, 2, 3, 5):
                picked_base = rank < top_n
                for h in holds:
                    sel = picked_base & valids[h]
                    if int(sel.sum()) < args.min_trades:
                        continue
                    for s in stops:
                        row = stats(book, nets[(h, s)], sel)
                        row.update(
                            label=label,
                            score=score_name,
                            top_n=top_n,
                            hold=h,
                            stop=s,
                            day_neutral_mean_pct=round(
                                float(np.mean(neutral[(h, s)][sel], dtype="float64") * 100), 4
                            ),
                        )
                        row["yearly_pos"] = sum(
                            1 for y in yearly(book, nets[(h, s)], sel) if y["mean_pct"] > 0
                        )
                        out.append(row)
    return out


def qualifies(row: dict[str, Any], *, max_per_day: float, min_years: int) -> bool:
    return bool(
        row["mean_pct"] > 0
        and row["per_day"] <= max_per_day
        and (row["front_mean_pct"] or -1) > 0
        and (row["back_mean_pct"] or -1) > 0
        and row["day_neutral_mean_pct"] > 0
        and row["yearly_pos"] >= min_years
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    gates = Gates(amount_min=args.amount_min, price_min=args.price_min)
    book, codes, n_days = load_book(args, gates)
    keep = phase1(book, args)
    rows = phase2(book, keep, args)
    print(f"phase2：{len(rows)} 个配置", flush=True)
    for row in rows:
        row["qualified"] = qualifies(row, max_per_day=args.max_per_day, min_years=args.min_years)
    rows.sort(key=lambda r: (r["qualified"], r["mean_pct"]), reverse=True)
    winners = [r for r in rows if r["qualified"]]
    report: dict[str, Any] = {
        "window": [book.window[0], book.window[-1]],
        "trading_days": n_days,
        "universe": len(codes),
        "samples": book.size(),
        "configs": len(rows),
        "qualified": len(winners),
        "filters": {
            "max_per_day": args.max_per_day,
            "min_years_positive": args.min_years,
            "requires": "均净>0 且 前后两段皆正 且 日中性>0",
        },
        "top": rows[: args.top],
    }
    detail = []
    for row in winners[: args.detail_top] or rows[: args.detail_top]:
        combo = tuple(
            c for c in CONDS if cond_label(c) in row["label"].split(" & ")
        )
        base = cond_mask(book, combo[0]).copy()
        for c in combo[1:]:
            base &= cond_mask(book, c)
        score = dict(SCORES)[row["score"]]
        vals = (
            np.nan_to_num(book.factors[score[1:]], nan=-1e9)
            if score[0] == "+"
            else -np.nan_to_num(book.factors[score[1:]], nan=1e9)
        )
        sel = (daily_rank(book, base, vals) < row["top_n"]) & book.valid(row["hold"])
        net = book.exit_net(row["hold"], row["stop"])
        entry = dict(row)
        entry["full"] = stats(book, net, sel, full=True)
        entry["yearly"] = yearly(book, net, sel)
        detail.append(entry)
    report["detail"] = detail
    if args.csv:
        pd.DataFrame(rows).to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"网格明细 → {args.csv}", flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="尾盘 14:50 选股器搜索")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--start", default="2021-01-04")
    ap.add_argument("--end", default="2026-08-11")
    ap.add_argument("--boards", default="main,chi_next")
    ap.add_argument("--amount-min", type=float, default=30_000_000.0)
    ap.add_argument("--price-min", type=float, default=3.0)
    ap.add_argument("--chunk-days", type=int, default=240)
    ap.add_argument("--holds", default="1,2,3,5")
    ap.add_argument("--min-pool", type=int, default=20_000)
    ap.add_argument("--min-trades", type=int, default=400)
    ap.add_argument("--max-per-day", type=float, default=5.0)
    ap.add_argument("--min-years", type=int, default=4)
    ap.add_argument("--phase1-keep", type=int, default=40)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--detail-top", type=int, default=8)
    ap.add_argument("--csv", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    report = run(args)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告 → {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
