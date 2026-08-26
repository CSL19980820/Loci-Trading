"""杨氏六条（T28）的横截面排序与组合层回测。

上游：`docs/research/2026-08-yule-materials-tail-close-feasibility.md` §7 证明 T28 闸门
在 5.6 年、19,132 笔上是正期望（次开买持 2 日 +0.5853%/笔，逐年零负年）。但那是**逐笔全取**
口径，日均出票 14.1 只，单人账户不可执行。本脚本回答两个上线前必须回答的问题：

1. **按什么排序取 Top-N？** T28 的 alpha 主要来自小盘，那排序也该沿着小盘走吗？
   还是该按「越冷越好」（低换手 / 低量比）——`_scratch_tail_close_entry_baseline.json`
   显示这两个维度的低分位过路费接近零。8 个候选因子 × 正反方向，逐一实测。
2. **组合层还剩多少？** 本仓 `2026-08-dragon-survivorship-and-portfolio-fragility.md` 已证明
   「信号数差 3.4%、组合全期收益能差 187%」——逐笔为正不等于组合能用。

**选优判据是稳健性不是收益**：先要求「逐年零负年 + 前后两段皆正」，在通过的组合里再看收益。
网格 8 因子 × 4 个 Top-N × 2 个宽度闸门 × 2 个持有期 = 128 组，属多重比较；
判据固定在事前、且报告通过率，避免挑出一个孤例。

组合模型（重叠持仓的标准处理，Jegadeesh-Titman overlapping portfolios）：
资金分成 `hold` 份，第 i 份只在 `day_idx % hold == i` 的信号日投入，因此每份内部是**串行无重叠**的，
可以直接连乘得净值；组合净值取 `hold` 份的等权平均，回撤在平均后的曲线上算。

数据限制与姊妹篇一致：本机无分钟线；`amount` 95.48% 合成；`instruments` 是当前快照（存活偏差）。
脚本只读 ``market.db``，不写任何业务表，不注册活动战法。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.formula import MA, REF, limit_up_flags  # noqa: E402
from src.market.domain.universe import classify_board, is_st_name  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.heat_tail_attention_proxy_research import (  # noqa: E402
    WIDE_LIMIT_PREFIXES,
    _load_panels,
)
from scripts.sanyuan_tail_resonance_research import (  # noqa: E402
    _load_days,
    _read_only_connection,
)

ROUND_TRIP_COST = 0.0026

#: 持有期以「卖出日距信号日的交易日数」计。次开买 + horizon=2 即
#: T+1 开盘买、T+2 收盘卖，等价于本仓 `screen_hold_days = 1`。
HORIZONS = (2, 3)
TOP_NS = (1, 2, 3, 5)
BREADTH_GATES: tuple[float | None, ...] = (None, 0.40)

#: 排序因子：名字 → (面板键, 是否升序在前)。升序在前 = 值越小排越前。
RANK_FACTORS: dict[str, tuple[str, bool]] = {
    "流通市值小优先": ("f_float_mv", True),
    "流通市值大优先": ("f_float_mv", False),
    "换手低优先": ("f_turnover", True),
    "换手高优先": ("f_turnover", False),
    "当日涨幅小优先": ("f_pct_chg", True),
    "当日涨幅大优先": ("f_pct_chg", False),
    "5日涨幅小优先": ("f_roc5", True),
    "5日涨幅大优先": ("f_roc5", False),
    "20日涨幅小优先": ("f_roc20", True),
    "量比低优先": ("f_vol_ratio", True),
    "距MA20低优先": ("f_ma20_bias", True),
}


@dataclass(frozen=True, slots=True)
class Gates:
    amount_min: float = 30_000_000.0
    price_min: float = 3.0
    min_listed_days: int = 60
    warmup_bars: int = 40
    # ── T28 杨氏六条（ROE 一条本机无财务数据，未实现）──
    shares_max_yi: float = 2.0
    price_max: float = 12.0
    pct_chg_min: float = 1.0
    pct_chg_max: float = 5.0
    turnover_min: float = 2.0


def _pct(x: np.ndarray) -> float:
    return float(np.mean(x, dtype="float64") * 100.0)


def _load_universe(
    conn: sqlite3.Connection, *, boards: set[str]
) -> tuple[list[str], dict[str, str]]:
    rows = conn.execute(
        "SELECT code,name,list_date,status FROM instruments WHERE instrument_type='STOCK'"
    ).fetchall()
    codes: list[str] = []
    list_date: dict[str, str] = {}
    for code_raw, name_raw, listed_raw, status_raw in rows:
        code = str(code_raw).zfill(6)
        if classify_board(code) not in boards or is_st_name(str(name_raw or "")):
            continue
        if str(status_raw or "normal") in {"suspended", "delisted"}:
            continue
        codes.append(code)
        list_date[code] = str(listed_raw or "")[:10]
    return sorted(set(codes)), list_date


def build_features(
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    list_date: dict[str, str],
    gates: Gates,
) -> dict[str, pd.DataFrame]:
    close, high, low, open_ = qfq["close"], qfq["high"], qfq["low"], qfq["open"]
    raw_close, raw_high, raw_low = raw["close"], raw["high"], raw["low"]
    volume, amount = raw["volume"], raw["amount"]
    turnover, shares = raw["turnover"], raw["outstanding_share"]

    prev_close = REF(close, 1)
    pct_chg = (close / prev_close - 1.0) * 100.0
    turnover_pct = turnover * 100.0
    ratios = pd.DataFrame(
        np.repeat(
            [[0.20 if c.startswith(WIDE_LIMIT_PREFIXES) else 0.10 for c in close.columns]],
            len(close),
            axis=0,
        ),
        index=close.index,
        columns=close.columns,
    )
    sealed = limit_up_flags(raw_close, raw_high, ratios, tolerance=0.995)
    one_word = pd.DataFrame(
        np.isclose(raw_high, raw_low, equal_nan=False), index=close.index, columns=close.columns
    )
    day_at = pd.to_datetime(pd.Index(close.index)).to_numpy().astype("datetime64[D]")
    listed_at = (
        pd.to_datetime(
            pd.Series([list_date.get(c) or "" for c in close.columns]), errors="coerce"
        )
        .fillna(pd.Timestamp("1990-01-01"))
        .to_numpy()
        .astype("datetime64[D]")
    )
    seasoned = pd.DataFrame(
        (day_at[:, None] - listed_at[None, :]) >= np.timedelta64(gates.min_listed_days, "D"),
        index=close.index,
        columns=close.columns,
    )
    tradable = (
        (volume > 0)
        & amount.ge(gates.amount_min)
        & close.gt(0)
        & raw_close.ge(gates.price_min)
        & seasoned
        & ~sealed
        & ~one_word
    ).fillna(False)

    # T28 五条（ROE 未实现）。全部只用 T 日已定型字段，不含当日 high/low。
    yangshi = (
        (shares / 1e8).lt(gates.shares_max_yi)
        & raw_close.lt(gates.price_max)
        & pct_chg.gt(gates.pct_chg_min)
        & pct_chg.lt(gates.pct_chg_max)
        & turnover_pct.gt(gates.turnover_min)
    ).fillna(False)

    breadth_series = (pct_chg.where(tradable) > 0).sum(axis=1) / tradable.sum(axis=1).replace(0, np.nan)
    breadth = pd.DataFrame(
        np.repeat(breadth_series.to_numpy(dtype="float32")[:, None], close.shape[1], axis=1),
        index=close.index,
        columns=close.columns,
    )

    feats: dict[str, pd.DataFrame] = {
        "entry_next_open": open_.shift(-1),
        "gate": (tradable & yangshi).fillna(False),
        "next_open_ok": (open_.shift(-1).notna() & ~one_word.shift(-1).fillna(True)).fillna(False),
        "f_float_mv": raw_close * shares,
        "f_turnover": turnover_pct,
        "f_pct_chg": pct_chg,
        "f_roc5": (close / REF(close, 5) - 1.0) * 100.0,
        "f_roc20": (close / REF(close, 20) - 1.0) * 100.0,
        "f_vol_ratio": (volume / MA(volume, 20)).clip(upper=15.0),
        "f_ma20_bias": (close / MA(close, 20) - 1.0) * 100.0,
        "f_breadth": breadth,
    }
    for h in HORIZONS:
        feats[f"exit_{h}"] = close.shift(-h)
        feats[f"exit_ok_{h}"] = (
            close.shift(-h).notna() & ~one_word.shift(-h).fillna(True)
        ).fillna(False)
    return feats


PRICE_KEYS = ("entry_next_open", *[f"exit_{h}" for h in HORIZONS])


def flatten_chunk(
    feats: dict[str, pd.DataFrame], seg: list[str], day_offset: int
) -> dict[str, np.ndarray]:
    """只压平通过 T28 闸门的格子——全池 439 万里这一档只有约 2 万，没必要全带。"""
    keep = feats["gate"].loc[seg].to_numpy() & feats["next_open_ok"].loc[seg].to_numpy()
    for h in HORIZONS:
        keep = keep & feats[f"exit_ok_{h}"].loc[seg].to_numpy()
    rows, cols = np.nonzero(keep)
    out: dict[str, np.ndarray] = {"day_idx": (rows + day_offset).astype("int32")}
    for key in PRICE_KEYS:
        out[key] = feats[key].loc[seg].to_numpy()[rows, cols].astype("float64")
    for key in feats:
        if key.startswith("f_"):
            out[key] = feats[key].loc[seg].to_numpy()[rows, cols].astype("float32")
    return out


class Book:
    def __init__(self, parts: list[dict[str, np.ndarray]], window: list[str]) -> None:
        merged = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        parts.clear()
        self.day_idx = merged.pop("day_idx")
        self.n_days = len(window)
        self.window = window
        self.half = self.day_idx >= self.n_days // 2
        self.years = np.asarray([d[:4] for d in window])[self.day_idx]
        self.entry = merged.pop("entry_next_open")
        self.nets = {
            h: (merged.pop(f"exit_{h}") / self.entry - 1.0 - ROUND_TRIP_COST).astype("float32")
            for h in HORIZONS
        }
        self.f = merged

    def size(self) -> int:
        return int(self.entry.size)

    def top_n_mask(self, factor: str, ascending: bool, top_n: int, gate: np.ndarray) -> np.ndarray:
        """逐日在 gate 内按 factor 取前 top_n。并列时按样本顺序稳定裁决。"""
        vals = self.f[factor].astype("float64")
        # 升序在前就直接排 vals，降序在前排 -vals；NaN 一律沉底。
        keys = vals if ascending else -vals
        keys = np.where(np.isfinite(keys) & gate, keys, np.inf)
        order = np.lexsort((keys, self.day_idx))
        d = self.day_idx[order]
        bounds = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
        out = np.zeros(vals.size, dtype=bool)
        for start, end in zip(bounds[:-1], bounds[1:]):
            block = order[start:end]
            block = block[gate[block] & np.isfinite(vals[block])]
            out[block[:top_n]] = True
        return out


def portfolio_curve(
    book: Book, net: np.ndarray, sel: np.ndarray, hold: int
) -> dict[str, Any]:
    """重叠持仓的组合净值：资金分 hold 份，第 i 份只吃 day_idx % hold == i 的信号日。

    每份内部串行无重叠，可直接连乘；组合净值取 hold 份的等权平均。
    """
    day = book.day_idx[sel]
    ret = net[sel].astype("float64")
    # 按信号日聚合成「批次收益」= 当日选中票的等权平均。
    batch_sum = np.bincount(day, weights=ret, minlength=book.n_days)
    batch_cnt = np.bincount(day, minlength=book.n_days)
    batch_ret = np.divide(batch_sum, batch_cnt, out=np.zeros_like(batch_sum), where=batch_cnt > 0)

    sleeves = np.ones((hold, book.n_days), dtype="float64")
    invested = np.zeros((hold, book.n_days), dtype=bool)
    for i in range(hold):
        value = 1.0
        for d in range(book.n_days):
            if d % hold == i and batch_cnt[d] > 0:
                value *= 1.0 + batch_ret[d]
                invested[i, d : min(d + hold, book.n_days)] = True
            sleeves[i, d] = value
    curve = sleeves.mean(axis=0)
    peak = np.maximum.accumulate(curve)
    drawdown = curve / peak - 1.0
    return {
        "portfolio_return_pct": round((curve[-1] - 1.0) * 100.0, 3),
        "max_drawdown_pct": round(float(drawdown.min()) * 100.0, 3),
        "occupancy_pct": round(float(invested.mean()) * 100.0, 2),
        "signal_days": int((batch_cnt > 0).sum()),
    }


def evaluate(book: Book, net: np.ndarray, sel: np.ndarray, hold: int) -> dict[str, Any]:
    part = net[sel]
    n = int(part.size)
    if n < 200:
        return {"n": n, "skipped": True}
    wins, losses = part[part > 0], part[part < 0]
    mean_win = float(wins.mean()) if wins.size else 0.0
    mean_loss = float(-losses.mean()) if losses.size else 0.0
    half = book.half[sel]
    front, back = part[~half], part[half]
    years = book.years[sel]
    year_means = {
        y: round(_pct(part[years == y]), 4) for y in sorted(set(years.tolist()))
    }
    out: dict[str, Any] = {
        "n": n,
        "per_day": round(n / book.n_days, 2),
        "win_rate": round(_pct(part > 0), 3),
        "mean_pct": round(_pct(part), 4),
        "median_pct": round(float(np.median(part)) * 100.0, 4),
        "pl_ratio": round(mean_win / mean_loss, 3) if mean_loss > 0 else None,
        "profit_factor": (
            round(float(wins.sum() / -losses.sum()), 3) if losses.size and losses.sum() else None
        ),
        "front_mean_pct": round(_pct(front), 4) if front.size else None,
        "back_mean_pct": round(_pct(back), 4) if back.size else None,
        "by_year": year_means,
        "negative_years": [y for y, v in year_means.items() if v < 0],
    }
    out["both_halves_positive"] = bool(
        out["front_mean_pct"] and out["back_mean_pct"]
        and out["front_mean_pct"] > 0 and out["back_mean_pct"] > 0
    )
    out["zero_negative_years"] = not out["negative_years"]
    out["robust"] = bool(out["both_halves_positive"] and out["zero_negative_years"])
    out.update(portfolio_curve(book, net, sel, hold))
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    gates = Gates(amount_min=args.amount_min, price_min=args.price_min)
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
                load_end=days[min(tail + max(HORIZONS), len(days) - 1)],
                dates=days,
                codes=codes,
            )
            feats = build_features(qfq, raw, list_date, gates)
            del qfq, raw
            parts.append(flatten_chunk(feats, seg, offset))
            del feats
            gc.collect()
            print(f"  {seg[0]}~{seg[-1]} 闸门内 {parts[-1]['day_idx'].size:,}", flush=True)
    finally:
        conn.close()

    book = Book(parts, window)
    gc.collect()
    print(f"T28 闸门内样本 {book.size():,}\n", flush=True)

    rows: list[dict[str, Any]] = []
    for breadth_gate in BREADTH_GATES:
        base = (
            np.ones(book.size(), dtype=bool)
            if breadth_gate is None
            else book.f["f_breadth"] >= breadth_gate
        )
        for rank_name, (factor, ascending) in RANK_FACTORS.items():
            for top_n in TOP_NS:
                sel = book.top_n_mask(factor, ascending, top_n, base)
                for hold in HORIZONS:
                    row = evaluate(book, book.nets[hold], sel, hold)
                    if row.get("skipped"):
                        continue
                    row.update(
                        {
                            "rank": rank_name,
                            "top_n": top_n,
                            "hold": hold,
                            "breadth_gate": breadth_gate,
                        }
                    )
                    rows.append(row)
    print(f"网格 {len(rows)} 组", flush=True)
    robust = [r for r in rows if r["robust"]]
    return {
        "window": [window[0], window[-1]],
        "trading_days": len(window),
        "universe": len(codes),
        "gate_samples": book.size(),
        "round_trip_cost_bps": ROUND_TRIP_COST * 1e4,
        "grid_size": len(rows),
        "robust_count": len(robust),
        "grid": rows,
    }


def format_summary(report: dict[str, Any], limit: int) -> str:
    lines: list[str] = []
    w = report["window"]
    lines.append(
        f"窗口 {w[0]}~{w[1]}　交易日 {report['trading_days']}　T28 闸门内 {report['gate_samples']:,} 笔"
    )
    lines.append(
        f"网格 {report['grid_size']} 组，其中「逐年零负年 + 两段皆正」的 "
        f"**{report['robust_count']}** 组（通过率 {report['robust_count']/max(report['grid_size'],1):.0%}）"
    )
    robust = sorted(
        (r for r in report["grid"] if r["robust"]), key=lambda r: -r["mean_pct"]
    )
    header = (
        f"{'排序因子':<16}{'N':>3}{'持有':>5}{'宽度':>6}{'笔数':>7}{'日均':>6}"
        f"{'胜率%':>7}{'均净%':>8}{'盈亏比':>7}{'组合收益%':>11}{'回撤%':>9}{'占用%':>7}"
    )
    lines.append("")
    lines.append(f"── 通过稳健性判据的前 {limit} 组（按均净降序）──")
    lines.append(header)
    lines.append("-" * len(header))
    for r in robust[:limit]:
        gate = "—" if r["breadth_gate"] is None else f"{r['breadth_gate']:.2f}"
        lines.append(
            f"{r['rank']:<16}{r['top_n']:>3}{r['hold']:>5}{gate:>6}{r['n']:>7,}{r['per_day']:>6.2f}"
            f"{r['win_rate']:>7.2f}{r['mean_pct']:>8.4f}{(r['pl_ratio'] or 0):>7.3f}"
            f"{r['portfolio_return_pct']:>11.1f}{r['max_drawdown_pct']:>9.1f}{r['occupancy_pct']:>7.1f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="杨氏六条 Top-N 排序与组合层回测")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--start", default="2021-01-04")
    parser.add_argument("--end", default="2026-08-11")
    parser.add_argument("--boards", default="main,chi_next")
    parser.add_argument("--amount-min", type=float, default=30_000_000.0)
    parser.add_argument("--price-min", type=float, default=3.0)
    parser.add_argument("--chunk-days", type=int, default=250)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = run(args)
    print()
    print(format_summary(report, args.limit))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n完整报告写出 {args.out}")


if __name__ == "__main__":
    main()
