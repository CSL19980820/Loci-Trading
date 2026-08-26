"""尾盘买入 + 次日冲高 0.5% 的可执行性研究。

用户口径：T 日 14:45-14:50 买入，T+1 只要盘中触及 +0.5% 就算赢，按次日**最高价**判定。
关注笔数、胜率、盈亏比、中位数。

本脚本要回答的不是"能不能挑出高命中率的票"——+0.5% 这个阈值太低，命中率几乎完全由
**波动率**决定，任何偏向高波动票的过滤器都会自动把命中率抬上去。真正的问题是：

1. 全市场无条件命中率是多少？不知道基准，任何过滤器的"高胜率"都无法判读。
2. 止盈封在 +0.5%、亏损不封顶时，盈亏比的**结构上限**是多少？保本胜率要多高？
3. 命中率的提升里有多少只是波动率？每条臂都配一个**波动率匹配对照**：按 ATR% 十分位
   把池子基准重新加权成该臂的波动率结构，得到"只有波动率、没有 alpha 时的应得值"。

数据限制（必须与结论一并阅读）：

- ``market.db`` **不存分钟线**（``src/market/README.md``："所有分钟线都不写 market.db"），
  14:50 的成交价只能用当日收盘价代理。A 股 14:57-15:00 是收盘集合竞价，收盘价与 14:50
  连续竞价价并不相等，该偏差在本机无法量化。
- ``f_clv`` / ``f_range_pct`` / ``f_range_contract`` 用了**当日 high/low**，``f_atr_pct``
  的窗口右端含当根。按本仓 ``entry_timing=close`` 的审计口径这属于裸用当日极值，对真实
  14:50 时点是**轻度前视**（最后 10 分钟仍可能刷新极值）。方向上让结果偏乐观，而本轮结论
  是否定式，故对判定安全；要做严格版本必须有分钟线。
- ``instruments`` 是当前快照：已退市票不在池内（存活偏差），ST 判定用的是当前名称。

脚本只读 ``market.db``，不写任何业务表，不注册活动战法。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
from itertools import combinations
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.formula import ATR, HHV, MA, REF, RSI, STD, limit_up_flags  # noqa: E402
from src.market.domain.universe import classify_board, is_st_name  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.heat_tail_attention_proxy_research import WIDE_LIMIT_PREFIXES, _load_panels  # noqa: E402
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

#: 往返成本：佣金 3bps 双边 + 印花税 10bps 卖出单边 + 滑点 5bps 双边 = 26bps。
#: 与 ``src/backtest`` 的 ``BacktestConfig`` 默认值一致。
ROUND_TRIP_COST = 0.0026

#: 用户的判盈阈值。
TARGET = 0.005

FACTOR_NOTE = {
    "f_clv": "收盘位置 (C-L)/(H-L)",
    "f_pct_chg": "当日涨幅 %",
    "f_vol_ratio": "量比 vol/MA20",
    "f_turnover": "换手率 %",
    "f_log_amount": "log10(成交额)",
    "f_atr_pct": "ATR14/close %（波动率）",
    "f_range_pct": "当日振幅 %",
    "f_range_contract": "振幅 / MA20(振幅)",
    "f_ma5_bias": "close/MA5-1 %",
    "f_ma20_bias": "close/MA20-1 %",
    "f_roc5": "5 日涨幅 %",
    "f_hhv60_pos": "close/HHV60",
    "f_rsi6": "RSI6",
    "f_std20": "20 日收益标准差 %",
    "f_gap_open": "当日跳空开盘 %",
    "f_dist_limit": "距涨停价 %",
    "f_breadth": "当日上涨家数占比 %",
}


@dataclass(frozen=True, slots=True)
class Gates:
    amount_min: float = 30_000_000.0
    price_min: float = 3.0
    min_listed_days: int = 60
    warmup_bars: int = 70


def _pct(x: np.ndarray) -> float:
    return float(np.mean(x, dtype="float64") * 100.0)


def _load_universe(
    conn: sqlite3.Connection, *, boards: set[str]
) -> tuple[list[str], dict[str, str]]:
    """当前 instruments 快照。上市日按票返回，由调用方逐日屏蔽次新。"""
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
    """一次算好全部 PIT 面板。所有 ``f_*`` 因子只用截至 T 日的已完成 K。"""
    close, high, low, open_ = qfq["close"], qfq["high"], qfq["low"], qfq["open"]
    raw_close, raw_high, raw_low = raw["close"], raw["high"], raw["low"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]

    prev_close = REF(close, 1)
    raw_prev_close = REF(raw_close, 1)
    pct_chg = (close / prev_close - 1.0) * 100.0
    rng = high - low
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
    # 逐日屏蔽次新：上市未满 min_listed_days 自然日的格子整格排除。
    # 用 datetime64 相减而非「除以纳秒常数」——pandas 3 会把日期推断成微秒分辨率，
    # 固定纳秒常数会把 20090 天算成 20 天，整张表恒为假。
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
    # T 日尾盘要买得到：不能封板、不能停牌、要有量、不是次新。
    tradable = (
        (volume > 0)
        & amount.ge(gates.amount_min)
        & close.gt(0)
        & raw_close.ge(gates.price_min)
        & seasoned
        & ~sealed
        & ~one_word
    ).fillna(False)

    nxt = {f"nxt_{k}": qfq[k].shift(-1) for k in ("open", "high", "low", "close")}
    nxt_one_word = pd.DataFrame(
        np.isclose(raw_high.shift(-1), raw_low.shift(-1), equal_nan=False),
        index=close.index,
        columns=close.columns,
    )
    # T+1 要卖得掉：必须有下一根 K，且次日不是一字（无论涨跌，一字都成交不了）。
    sellable = (nxt["nxt_close"].notna() & nxt["nxt_high"].notna() & ~nxt_one_word).fillna(False)

    # 本想用 close/VWAP 当尾盘强度代理，但库内 amount 有九成来自腾讯源的
    # ``amount = close * volume`` 合成值（``src/market/README.md`` 第 76 行），
    # 于是 amount/volume 恒等于 close，这个因子在本机是常数 0。改用 CLV 代替，
    # 合成占比由 ``synthetic_amount_ratio`` 量化后写进报告。
    feats: dict[str, pd.DataFrame] = {
        "entry": close,
        "tradable": tradable,
        "sellable": sellable,
        "amount_ratio": amount / (raw_close * volume.replace(0.0, np.nan)),
        **nxt,
        "f_clv": ((close - low) / rng.replace(0.0, np.nan)).clip(0.0, 1.0),
        "f_pct_chg": pct_chg,
        "f_vol_ratio": (volume / MA(volume, 20)).clip(upper=15.0),
        # 库内 turnover 是小数（中位数 0.024），换成百分比才与阈值同量纲。
        "f_turnover": turnover * 100.0,
        "f_log_amount": np.log10(amount.clip(lower=1.0)),
        "f_atr_pct": (ATR(high, low, close, 14) / close) * 100.0,
        "f_range_pct": (rng / prev_close) * 100.0,
        "f_range_contract": rng / MA(rng, 20).replace(0.0, np.nan),
        "f_ma5_bias": (close / MA(close, 5) - 1.0) * 100.0,
        "f_ma20_bias": (close / MA(close, 20) - 1.0) * 100.0,
        "f_roc5": (close / REF(close, 5) - 1.0) * 100.0,
        "f_hhv60_pos": close / HHV(high, 60),
        "f_rsi6": RSI(close, 6),
        "f_std20": STD(pct_chg, 20),
        "f_gap_open": (open_ / prev_close - 1.0) * 100.0,
        "f_dist_limit": (raw_prev_close * (1.0 + ratios) / raw_close - 1.0) * 100.0,
    }
    breadth = (pct_chg.where(tradable) > 0).sum(axis=1) / tradable.sum(axis=1).replace(0, np.nan)
    feats["f_breadth"] = pd.DataFrame(
        np.repeat((breadth * 100.0).to_numpy(dtype="float32")[:, None], close.shape[1], axis=1),
        index=close.index,
        columns=close.columns,
    )
    return feats


PRICE_KEYS = ("entry", "nxt_open", "nxt_high", "nxt_low", "nxt_close")


def flatten_chunk(
    feats: dict[str, pd.DataFrame], seg: list[str], day_offset: int
) -> dict[str, np.ndarray]:
    """把一个时间分块的面板压成一维样本。``day_offset`` 让 ``day_idx`` 在全窗口内连续。"""
    keep = feats["tradable"].loc[seg].to_numpy() & feats["sellable"].loc[seg].to_numpy()
    rows, cols = np.nonzero(keep)
    out: dict[str, np.ndarray] = {"day_idx": (rows + day_offset).astype("int32")}
    for key in (*PRICE_KEYS, "amount_ratio"):
        out[key] = feats[key].loc[seg].to_numpy()[rows, cols].astype("float64")
    for key in feats:
        if key.startswith("f_"):
            out[key] = feats[key].loc[seg].to_numpy()[rows, cols].astype("float32")
    return out


class Book:
    """把逐块压平的样本拼成一份全窗口样本集；之后所有统计都在扁平数组上做。"""

    def __init__(self, parts: list[dict[str, np.ndarray]], window: list[str]) -> None:
        keys = parts[0].keys()
        merged = {k: np.concatenate([p[k] for p in parts]) for k in keys}
        parts.clear()
        self.day_idx = merged.pop("day_idx")
        self.n_days = len(window)
        self.window = window
        self.half = self.day_idx >= self.n_days // 2
        self.entry = merged.pop("entry")
        self.nxt_open = merged.pop("nxt_open")
        self.nxt_high = merged.pop("nxt_high")
        self.nxt_low = merged.pop("nxt_low")
        self.nxt_close = merged.pop("nxt_close")
        # 合成成交额占比：腾讯源 amount = close*volume，这类行的 amount 不是真成交额。
        self.synthetic_amount_ratio = float(
            np.mean(np.isclose(merged.pop("amount_ratio"), 1.0, atol=1e-5))
        )
        self.factors = merged
        self.hit = self.nxt_high >= self.entry * (1.0 + TARGET)
        self.ret_close = (self.nxt_close / self.entry - 1.0).astype("float32")
        self.ret_open = (self.nxt_open / self.entry - 1.0).astype("float32")
        self.ret_high = (self.nxt_high / self.entry - 1.0).astype("float32")
        self.ret_low = (self.nxt_low / self.entry - 1.0).astype("float32")
        # ATR% 的逐日横截面十分位，供波动率匹配对照使用。
        vol_rank = self.cs_rank(self.factors["f_atr_pct"])
        self.vol_bucket = np.where(
            np.isfinite(vol_rank), np.clip(np.nan_to_num(vol_rank) * 10.0, 0, 9), -1
        ).astype("int16")

    def size(self) -> int:
        return int(self.entry.size)

    def cs_rank(self, vals: np.ndarray) -> np.ndarray:
        """逐日横截面分位（0-1）。用当日截面而非全样本，避免把市场整体波动当成因子。"""
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

    def exit_touch(self, target: float = TARGET, stop: float | None = None) -> np.ndarray:
        """T+1 限价止盈模拟。

        跳空高开越过目标价时按**开盘价**成交（真实限价单如此，比按目标价成交更好）；
        盘中触及按目标价成交；全天没摸到按 T+1 收盘了结。

        带止损时先后约定与 ``src/backtest`` 引擎一致：开盘价直接越过任一边界的按开盘价成交
        （时点无歧义），两边都只在盘中触及时**记止损**（保守）。
        """
        tgt = self.entry * (1.0 + target)
        fill = np.where(
            self.nxt_open >= tgt,
            self.nxt_open,
            np.where(self.nxt_high >= tgt, tgt, self.nxt_close),
        )
        if stop is not None:
            stp = self.entry * (1.0 - stop)
            gap_up = self.nxt_open >= tgt
            gap_dn = (~gap_up) & (self.nxt_open <= stp)
            intraday_stop = (~gap_up) & (~gap_dn) & (self.nxt_low <= stp)
            fill = np.where(gap_dn, self.nxt_open, np.where(intraday_stop, stp, fill))
        return (fill / self.entry - 1.0 - ROUND_TRIP_COST).astype("float32")


def metrics(book: Book, net: np.ndarray, sel: np.ndarray, *, full: bool = True) -> dict[str, Any]:
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
        "hit_rate": round(_pct(book.hit[sel]), 3),
        "win_rate": round(_pct(part > 0), 3),
        "mean_pct": round(_pct(part), 4),
        "median_pct": round(float(np.median(part)) * 100.0, 4),
        "pl_ratio": round(mean_win / mean_loss, 3) if mean_loss > 0 else None,
        "front_mean_pct": round(_pct(part[~half]), 4) if (~half).any() else None,
        "back_mean_pct": round(_pct(part[half]), 4) if half.any() else None,
    }
    out["both_halves_positive"] = bool(
        out["front_mean_pct"] is not None
        and out["back_mean_pct"] is not None
        and out["front_mean_pct"] > 0
        and out["back_mean_pct"] > 0
    )
    # 「冲高按涨幅算」：次日最高涨幅本身的分布，与出场方式无关。
    out["spike_mean_pct"] = round(_pct(book.ret_high[sel]), 4)
    out["spike_median_pct"] = round(float(np.median(book.ret_high[sel])) * 100.0, 4)
    if full:
        out["profit_factor"] = (
            round(float(wins.sum() / -losses.sum()), 3) if losses.size and losses.sum() else None
        )
        out["p25_pct"] = round(float(np.percentile(part, 25)) * 100.0, 4)
        out["p75_pct"] = round(float(np.percentile(part, 75)) * 100.0, 4)
        out["mean_atr_pct"] = round(float(np.nanmean(book.factors["f_atr_pct"][sel])), 3)
    return out


def day_demean(book: Book, net: np.ndarray) -> np.ndarray:
    """减掉当日全池均值。剩下的才是横截面 alpha，不含"那天大盘涨了"。"""
    counts = np.bincount(book.day_idx, minlength=book.n_days).astype("float64")
    sums = np.bincount(book.day_idx, weights=net, minlength=book.n_days)
    return net - (sums / np.maximum(counts, 1.0))[book.day_idx]


def vol_matched(book: Book, sel: np.ndarray, net_all: np.ndarray) -> dict[str, float]:
    """把池子基准按 ATR% 十分位重加权成这条臂的波动率结构。臂实际值减它才是超额。"""
    total = int(sel.sum())
    out = {"expected_mean_pct": 0.0, "expected_hit_rate": 0.0}
    if total == 0:
        return out
    for b in range(10):
        pool = book.vol_bucket == b
        w = int((sel & pool).sum()) / total
        if w == 0 or not pool.any():
            continue
        out["expected_mean_pct"] += w * _pct(net_all[pool])
        out["expected_hit_rate"] += w * _pct(book.hit[pool])
    return {k: round(v, 4) for k, v in out.items()}


def decile_scan(book: Book, net: np.ndarray, factors: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in factors:
        vals = book.factors[name]
        ranks = book.cs_rank(vals)
        ok = np.isfinite(ranks)
        if ok.sum() < 5000:
            continue
        edges = np.nanpercentile(vals[np.isfinite(vals)], np.arange(0, 101, 10))
        for d in range(10):
            lo, hi = d / 10.0, (d + 1) / 10.0 + (1e-6 if d == 9 else 0.0)
            sel = ok & (ranks >= lo) & (ranks < hi)
            if sel.sum() < 500:
                continue
            m = metrics(book, net, sel, full=False)
            m.update(
                factor=name,
                note=FACTOR_NOTE.get(name, ""),
                decile=d,
                value_lo=round(float(edges[d]), 4),
                value_hi=round(float(edges[d + 1]), 4),
            )
            rows.append(m)
    return rows


@dataclass(frozen=True, slots=True)
class Cond:
    factor: str
    op: str
    value: float

    def label(self) -> str:
        return f"{self.factor[2:]}{'≥' if self.op == 'ge' else '≤'}{self.value:g}"


GRID: tuple[Cond, ...] = tuple(
    Cond(f, op, v)
    for f, op, values in (
        ("f_clv", "ge", (0.5, 0.7, 0.85, 0.95)),
        ("f_pct_chg", "ge", (-3.0, 0.0, 2.0)),
        ("f_pct_chg", "le", (3.0, 5.0, 7.0)),
        ("f_vol_ratio", "ge", (1.0, 1.5, 2.5)),
        ("f_atr_pct", "le", (2.5, 3.5, 4.5)),
        ("f_atr_pct", "ge", (3.5, 5.0)),
        ("f_ma20_bias", "ge", (0.0, 3.0)),
        ("f_hhv60_pos", "ge", (0.85, 0.95)),
        ("f_breadth", "ge", (45.0, 55.0)),
        ("f_turnover", "ge", (1.0, 3.0)),
        ("f_turnover", "le", (8.0, 15.0)),
        ("f_rsi6", "le", (60.0, 75.0)),
        ("f_range_contract", "le", (0.8, 1.2)),
    )
    for v in values
)


def _combo_ok(combo: tuple[Cond, ...]) -> bool:
    seen: dict[tuple[str, str], float] = {}
    for c in combo:
        if (c.factor, c.op) in seen:
            return False
        seen[(c.factor, c.op)] = c.value
    for (factor, op), value in seen.items():
        if op == "ge" and (factor, "le") in seen and seen[(factor, "le")] <= value:
            return False
    return True


def grid_search(book: Book, net: np.ndarray, *, min_trades: int, max_k: int) -> list[dict[str, Any]]:
    masks = {
        c: (book.factors[c.factor] >= c.value if c.op == "ge" else book.factors[c.factor] <= c.value)
        & np.isfinite(book.factors[c.factor])
        for c in GRID
    }
    rows: list[dict[str, Any]] = []
    for k in range(1, max_k + 1):
        for combo in combinations(GRID, k):
            if not _combo_ok(combo):
                continue
            sel = masks[combo[0]]
            for c in combo[1:]:
                sel = sel & masks[c]
            if int(sel.sum()) < min_trades:
                continue
            row = metrics(book, net, sel, full=False)
            row["label"] = " & ".join(c.label() for c in combo)
            row["k"] = k
            rows.append(row)
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    gates = Gates(amount_min=args.amount_min, price_min=args.price_min)
    conn = _read_only_connection(Path(args.db))
    try:
        days = _load_days(conn)
        window = [d for d in days if args.start <= d <= args.end]
        if len(window) < 60:
            raise SystemExit(f"窗口太短：{len(window)} 个交易日")
        codes, list_date = _load_universe(conn, boards=set(args.boards.split(",")))
        print(f"票池 {len(codes)} 只 / 窗口 {window[0]}~{window[-1]} 共 {len(window)} 日", flush=True)
        # 按块加载：全窗口一次性建面板要十几 GB。分块只影响面板驻留量，不影响结果——
        # 每块都带 warmup_bars 预热，且复权比例只在块内做相对换算，块间从不比价格绝对值。
        parts: list[dict[str, np.ndarray]] = []
        for offset in range(0, len(window), args.chunk_days):
            seg = window[offset : offset + args.chunk_days]
            head, tail = days.index(seg[0]), days.index(seg[-1])
            qfq, raw = _load_panels(
                conn,
                load_start=days[max(head - gates.warmup_bars, 0)],
                load_end=days[min(tail + 1, len(days) - 1)],
                dates=days,
                codes=codes,
            )
            feats = build_features(qfq, raw, list_date, gates)
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

    exits = {
        "touch": book.exit_touch(),
        "tp2": book.exit_touch(target=0.02),
        "tp3": book.exit_touch(target=0.03),
        "hold_close": book.ret_close - np.float32(ROUND_TRIP_COST),
        "hold_open": book.ret_open - np.float32(ROUND_TRIP_COST),
        # 不可实现的上界：假设总能卖在次日最高价。没人做得到，只用来给
        # 「按冲高涨幅算盈亏比」这个口径一个天花板。
        "sell_high_ideal": book.ret_high - np.float32(ROUND_TRIP_COST),
    }
    neutral = {k: day_demean(book, v) for k, v in exits.items()}
    years = np.asarray([d[:4] for d in window])[book.day_idx]
    everyone = np.ones(book.size(), dtype=bool)
    report: dict[str, Any] = {
        "window": [window[0], window[-1]],
        "trading_days": len(window),
        "universe": len(codes),
        "samples": book.size(),
        "target_pct": TARGET * 100,
        "round_trip_cost_pct": ROUND_TRIP_COST * 100,
        "synthetic_amount_ratio": round(book.synthetic_amount_ratio, 4),
        "baseline": {k: metrics(book, v, everyone) for k, v in exits.items()},
        "path_independent": {
            "median_next_high_pct": round(float(np.median(book.ret_high)) * 100, 4),
            "median_next_low_pct": round(float(np.median(book.ret_low)) * 100, 4),
            "median_next_close_pct": round(float(np.median(book.ret_close)) * 100, 4),
            "mean_next_close_pct": round(_pct(book.ret_close), 4),
            "mean_overnight_pct": round(_pct(book.ret_open), 4),
            "mean_ret_close_if_hit_pct": round(_pct(book.ret_close[book.hit]), 4),
            "mean_ret_close_if_miss_pct": round(_pct(book.ret_close[~book.hit]), 4),
            "median_ret_close_if_hit_pct": round(float(np.median(book.ret_close[book.hit])) * 100, 4),
        },
        "yearly_baseline": [
            {
                "year": y,
                "touch": metrics(book, exits["touch"], years == y, full=False),
                "hold_close": metrics(book, exits["hold_close"], years == y, full=False),
            }
            for y in sorted(set(years.tolist()))
        ],
        "threshold_curve": [
            {
                "target_pct": round(t * 100, 2),
                "hit_rate": round(_pct(book.nxt_high >= book.entry * (1 + t)), 3),
                "mean_pct": round(_pct(book.exit_touch(target=t)), 4),
                "median_pct": round(float(np.median(book.exit_touch(target=t))) * 100, 4),
            }
            for t in (0.003, 0.005, 0.01, 0.02, 0.03, 0.05)
        ],
    }
    print("基准完成，开始单因子十分位", flush=True)
    report["deciles"] = decile_scan(
        book, exits["touch"], sorted(k for k in book.factors)
    )

    print(f"开始组合网格（按 {args.rank_exit} 排序）", flush=True)
    combos = grid_search(book, exits[args.rank_exit], min_trades=args.min_trades, max_k=args.max_k)
    combos.sort(key=lambda r: r["mean_pct"], reverse=True)
    report["combos_total"] = len(combos)
    report["combos_both_halves_positive"] = sum(1 for r in combos if r["both_halves_positive"])

    # 只给前若干名补算波动率匹配与完整分位统计——这两项贵。
    conds_by_label = {}
    for k in range(1, args.max_k + 1):
        for combo in combinations(GRID, k):
            if _combo_ok(combo):
                conds_by_label[" & ".join(c.label() for c in combo)] = combo
    detail: list[dict[str, Any]] = []
    for row in combos[: args.detail_top]:
        combo = conds_by_label[row["label"]]
        sel = np.ones(book.size(), dtype=bool)
        for c in combo:
            v = book.factors[c.factor]
            sel &= (v >= c.value if c.op == "ge" else v <= c.value) & np.isfinite(v)
        entry: dict[str, Any] = {"label": row["label"]}
        for name, net in exits.items():
            entry[name] = metrics(book, net, sel)
        # 止盈阶梯：把"+0.5% 就跑"和更宽的止盈放在同一批样本上直接比。
        entry["tp_ladder"] = [
            {"target_pct": round(t * 100, 2), **metrics(book, book.exit_touch(target=t), sel)}
            for t in (0.005, 0.01, 0.02, 0.03, 0.05)
        ]
        entry["vol_matched_touch"] = vol_matched(book, sel, exits["touch"])
        entry["excess_vs_vol_matched_pct"] = round(
            entry["touch"]["mean_pct"] - entry["vol_matched_touch"]["expected_mean_pct"], 4
        )
        entry["day_neutral_mean_pct"] = {
            name: round(_pct(dn[sel]), 4) for name, dn in neutral.items()
        }
        entry["yearly"] = [
            {
                "year": y,
                "touch": metrics(book, exits["touch"], sel & (years == y), full=False),
                "hold_close": metrics(book, exits["hold_close"], sel & (years == y), full=False),
            }
            for y in sorted(set(years.tolist()))
            if int((sel & (years == y)).sum()) >= 100
        ]
        detail.append(entry)
    report["combos_top"] = combos[: args.top]
    report["detail"] = detail

    if args.csv:
        pd.DataFrame(combos).to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"网格明细 → {args.csv}", flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="尾盘买入 + 次日冲高 0.5% 研究")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--start", default="2021-01-04")
    ap.add_argument("--end", default="2026-08-11")
    ap.add_argument("--boards", default="main,chi_next")
    ap.add_argument("--amount-min", type=float, default=30_000_000.0)
    ap.add_argument("--price-min", type=float, default=3.0)
    ap.add_argument("--chunk-days", type=int, default=250)
    ap.add_argument("--min-trades", type=int, default=3000)
    ap.add_argument("--max-k", type=int, default=3)
    ap.add_argument(
        "--rank-exit",
        default="hold_close",
        choices=["touch", "tp2", "tp3", "hold_close", "hold_open", "sell_high_ideal"],
        help="网格按哪种出场的均净排序。默认 hold_close（不封顶、持到次日收盘）。",
    )
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--detail-top", type=int, default=8)
    ap.add_argument("--csv", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    report = run(args)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=float)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告 → {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
