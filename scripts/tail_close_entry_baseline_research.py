"""尾盘入场基线：把「T 日收盘买」与「T+1 开盘买」放在同一个卖出日上对比。

任何从民间战法里提炼出来的尾盘规则，都要先跨过一条尺子：**不加任何选股条件、
全市场随便买，尾盘入场本身值多少钱？** 本脚本量的就是这条尺子，并把它拆成三段：

1. 无条件基线：T 日收盘价买入，持有 1/2/3/5 个交易日后按收盘价卖出。
2. **同卖出日对照**：同一批样本、同一个卖出时点，只把入场价从「T 日收盘」换成
   「T+1 开盘」。两臂之差就是**隔夜那一跳的价格**，不掺任何选股能力。
3. 逐年与前后两段：判断基线本身是否稳定，避免把某一年的行情当成结构性结论。

为什么需要这条尺子：`docs/research/2026-08-tail-1450-next-day-touch-backtest.md`
已经证明「尾盘买 + 次日 +0.5% 封顶止盈」是负期望，但那一轮把亏损主因归给了封顶止盈，
**尾盘入场本身的代价只给了单一持有期（T+1 收盘）的一个数**。持有 2–3 日是本轮材料里
反复出现的口径（如「建议持有 2-3 天」），需要独立量化。

数据限制（必须与结论一并阅读）：

- ``market.db`` **不存分钟线**，14:50 的成交价只能用当日收盘价代理。A 股 14:57-15:00
  是收盘集合竞价，收盘价与 14:50 连续竞价价并不相等。
- 库内 ``amount`` 有 95.48% 来自 ``close * volume`` 合成，日线 VWAP 在本机不可算。
- ``instruments`` 是当前快照：已退市票不在池内（存活偏差），ST 判定用当前名称。
  方向上让基线偏乐观。

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

from src.formula import ATR, MA, REF, limit_up_flags  # noqa: E402
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

#: 往返成本：佣金 3bps 双边 + 印花税 10bps 卖出单边 + 滑点 5bps 双边 = 26bps。
#: 与 ``src/backtest`` 的 ``BacktestConfig`` 默认值一致，也与姊妹篇同口径。
ROUND_TRIP_COST = 0.0026

#: 持有期（交易日）。T 日收盘买入，T+h 收盘卖出。
HORIZONS = (1, 2, 3, 5)


@dataclass(frozen=True, slots=True)
class Gates:
    amount_min: float = 30_000_000.0
    price_min: float = 3.0
    min_listed_days: int = 60
    warmup_bars: int = 30


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
    """算出入场/出场价与可交易掩码。所有闸门只用截至 T 日的已完成 K。"""
    close, high, low, open_ = qfq["close"], qfq["high"], qfq["low"], qfq["open"]
    raw_close, raw_high, raw_low = raw["close"], raw["high"], raw["low"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]

    prev_close = REF(close, 1)
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
        np.isclose(raw_high, raw_low, equal_nan=False),
        index=close.index,
        columns=close.columns,
    )
    # 逐日屏蔽次新：上市未满 min_listed_days 自然日的格子整格排除。
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

    feats: dict[str, pd.DataFrame] = {
        "entry_close": close,
        "entry_next_open": open_.shift(-1),
        "tradable": tradable,
        # T+1 一字则次开臂买不进、尾盘臂也卖不出，两臂共用同一份样本才可比。
        "next_open_ok": (open_.shift(-1).notna() & ~one_word.shift(-1).fillna(True)).fillna(False),
        # 波动率分层用，ATR 窗口右端含当根（对 entry_timing=close 是轻度前视，仅作分层不作信号）。
        "f_atr_pct": (ATR(high, low, close, 14) / close) * 100.0,
        "f_turnover": turnover * 100.0,
        "f_vol_ratio": (volume / MA(volume, 20)).clip(upper=15.0),
        "f_pct_chg": (close / prev_close - 1.0) * 100.0,
    }
    for h in HORIZONS:
        feats[f"exit_{h}"] = close.shift(-h)
        # T+h 一字则卖不掉。
        feats[f"exit_ok_{h}"] = (
            close.shift(-h).notna() & ~one_word.shift(-h).fillna(True)
        ).fillna(False)
    return feats


PRICE_KEYS = ("entry_close", "entry_next_open", *[f"exit_{h}" for h in HORIZONS])


def flatten_chunk(
    feats: dict[str, pd.DataFrame], seg: list[str], day_offset: int
) -> dict[str, np.ndarray]:
    """把一个时间分块的面板压成一维样本。

    样本口径：T 日可买 **且** T+1 可开盘成交 **且** 每一个持有期的卖出日都可卖。
    要求全部持有期都可卖，是为了让不同持有期落在同一批交易上——否则短持有期会多出
    一批长持有期不存在的样本，横向比较就不成立。停牌日在面板里是 NaN，只卡最长持有期
    会漏掉「T+2 停牌、T+5 复牌」这类格子。
    """
    keep = (
        feats["tradable"].loc[seg].to_numpy()
        & feats["next_open_ok"].loc[seg].to_numpy()
    )
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
    """把逐块压平的样本拼成全窗口样本集；之后所有统计都在扁平数组上做。"""

    def __init__(self, parts: list[dict[str, np.ndarray]], window: list[str]) -> None:
        keys = list(parts[0].keys())
        merged = {k: np.concatenate([p[k] for p in parts]) for k in keys}
        parts.clear()
        self.day_idx = merged.pop("day_idx")
        self.n_days = len(window)
        self.window = window
        self.half = self.day_idx >= self.n_days // 2
        self.years = np.asarray([d[:4] for d in window])[self.day_idx]
        self.entry_close = merged.pop("entry_close")
        self.entry_next_open = merged.pop("entry_next_open")
        self.exits = {h: merged.pop(f"exit_{h}") for h in HORIZONS}
        self.factors = merged
        # 隔夜毛跳空：T 日收盘 → T+1 开盘，不扣成本。两臂之差的全部来源。
        self.overnight = (self.entry_next_open / self.entry_close - 1.0).astype("float32")

    def size(self) -> int:
        return int(self.entry_close.size)

    def net(self, *, entry: str, horizon: int) -> np.ndarray:
        """扣 26bps 往返成本后的每笔净收益。"""
        base = self.entry_close if entry == "close" else self.entry_next_open
        return (self.exits[horizon] / base - 1.0 - ROUND_TRIP_COST).astype("float32")

    def day_demean(self, net: np.ndarray) -> np.ndarray:
        """减去当日全池均值，剩下的才是选股而不是踩对了大盘。"""
        sums = np.bincount(self.day_idx, weights=net.astype("float64"), minlength=self.n_days)
        counts = np.bincount(self.day_idx, minlength=self.n_days)
        means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
        return (net - means[self.day_idx]).astype("float32")


def metrics(book: Book, net: np.ndarray, sel: np.ndarray) -> dict[str, Any]:
    part = net[sel]
    n = int(part.size)
    if n == 0:
        return {"n": 0}
    wins, losses = part[part > 0], part[part < 0]
    mean_win = float(wins.mean()) if wins.size else 0.0
    mean_loss = float(-losses.mean()) if losses.size else 0.0
    half = book.half[sel]
    front = part[~half]
    back = part[half]
    out: dict[str, Any] = {
        "n": n,
        "win_rate": round(_pct(part > 0), 3),
        "mean_pct": round(_pct(part), 4),
        "median_pct": round(float(np.median(part)) * 100.0, 4),
        "pl_ratio": round(mean_win / mean_loss, 3) if mean_loss > 0 else None,
        "profit_factor": (
            round(float(wins.sum() / -losses.sum()), 3) if losses.size and losses.sum() else None
        ),
        "front_mean_pct": round(_pct(front), 4) if front.size else None,
        "back_mean_pct": round(_pct(back), 4) if back.size else None,
    }
    out["both_halves_positive"] = bool(
        out["front_mean_pct"] is not None
        and out["back_mean_pct"] is not None
        and out["front_mean_pct"] > 0
        and out["back_mean_pct"] > 0
    )
    return out


def by_year(book: Book, net: np.ndarray, sel: np.ndarray) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    years = book.years[sel]
    part = net[sel]
    for year in sorted(set(years.tolist())):
        mask = years == year
        chunk = part[mask]
        out[year] = {
            "n": int(chunk.size),
            "mean_pct": round(_pct(chunk), 4),
            "win_rate": round(_pct(chunk > 0), 3),
        }
    return out


def decile_table(book: Book, net: np.ndarray, factor: str) -> list[dict[str, Any]]:
    """按逐日横截面十分位切，看基线在该因子上的单调性。"""
    vals = book.factors[factor]
    ok = np.isfinite(vals)
    ranks = np.full(vals.size, np.nan, dtype="float32")
    order = np.lexsort((np.where(ok, vals, np.inf), book.day_idx))
    d = book.day_idx[order]
    bounds = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
    for start, end in zip(bounds[:-1], bounds[1:]):
        block = order[start:end]
        good = block[ok[block]]
        if good.size < 20:
            continue
        ranks[good] = np.arange(good.size, dtype="float32") / max(good.size - 1, 1)
    # 必须截断成整数：rank*10 是浮点，直接与桶号比相等只会命中恰好落在整点的样本。
    bucket = np.where(
        np.isfinite(ranks), np.clip(np.nan_to_num(ranks) * 10.0, 0, 9), -1
    ).astype("int16")
    rows: list[dict[str, Any]] = []
    for b in range(10):
        sel = bucket == b
        if not sel.any():
            continue
        row = {"decile": b, "lo": round(float(np.nanmin(vals[sel])), 3),
               "hi": round(float(np.nanmax(vals[sel])), 3)}
        row.update(metrics(book, net, sel))
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
        parts: list[dict[str, np.ndarray]] = []
        for offset in range(0, len(window), args.chunk_days):
            seg = window[offset : offset + args.chunk_days]
            head, tail = days.index(seg[0]), days.index(seg[-1])
            qfq, raw = _load_panels(
                conn,
                load_start=days[max(head - gates.warmup_bars, 0)],
                # 多加载 max(HORIZONS) 天，否则块尾样本的卖出价会缺。
                load_end=days[min(tail + max(HORIZONS), len(days) - 1)],
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

    everyone = np.ones(book.size(), dtype=bool)
    report: dict[str, Any] = {
        "window": [window[0], window[-1]],
        "trading_days": len(window),
        "universe": len(codes),
        "samples": book.size(),
        "round_trip_cost_bps": ROUND_TRIP_COST * 1e4,
        "overnight_gross": {
            "mean_pct": round(_pct(book.overnight), 4),
            "median_pct": round(float(np.median(book.overnight)) * 100.0, 4),
            "positive_share_pct": round(_pct(book.overnight > 0), 3),
            "std_pct": round(float(np.std(book.overnight)) * 100.0, 4),
        },
        "arms": {},
        "by_year": {},
        "deciles": {},
    }

    for horizon in HORIZONS:
        for entry in ("close", "next_open"):
            key = f"{entry}_h{horizon}"
            net = book.net(entry=entry, horizon=horizon)
            report["arms"][key] = metrics(book, net, everyone)
            report["arms"][key]["day_neutral_mean_pct"] = round(
                _pct(book.day_demean(net)), 4
            )
        # 同卖出日、只换入场价：两臂之差 = 隔夜那一跳的价格。
        gap = (
            report["arms"][f"close_h{horizon}"]["mean_pct"]
            - report["arms"][f"next_open_h{horizon}"]["mean_pct"]
        )
        report["arms"][f"tail_edge_h{horizon}_pp"] = round(gap, 4)

    base_net = book.net(entry="close", horizon=args.focus_horizon)
    report["by_year"][f"close_h{args.focus_horizon}"] = by_year(book, base_net, everyone)
    report["by_year"][f"next_open_h{args.focus_horizon}"] = by_year(
        book, book.net(entry="next_open", horizon=args.focus_horizon), everyone
    )
    factors = ("f_atr_pct", "f_turnover", "f_vol_ratio", "f_pct_chg")
    for factor in factors:
        report["deciles"][factor] = decile_table(book, base_net, factor)

    # 尾盘入场的过路费是不是恒定的？逐层看隔夜毛跳空，找它接近零甚至转正的角落。
    # 这是「尾盘策略能不能存在」的关键：过路费为零的地方，尾盘入场才不吃亏。
    report["overnight_deciles"] = {
        factor: decile_table(book, book.overnight, factor) for factor in factors
    }
    return report


def format_summary(report: dict[str, Any]) -> str:
    """人读用的紧凑摘要；完整数字仍以 JSON 为准。"""
    lines: list[str] = []
    w = report["window"]
    lines.append(
        f"窗口 {w[0]}~{w[1]}　交易日 {report['trading_days']}　"
        f"票池 {report['universe']}　样本 {report['samples']:,}　成本 {report['round_trip_cost_bps']:.0f}bps"
    )
    og = report["overnight_gross"]
    lines.append(
        f"隔夜毛跳空（收盘→次开）：均值 {og['mean_pct']:+.4f}%　中位 {og['median_pct']:+.4f}%　"
        f"为正占比 {og['positive_share_pct']:.2f}%　标准差 {og['std_pct']:.2f}%"
    )
    lines.append("")
    header = f"{'臂':<16}{'笔数':>10}{'胜率%':>9}{'均净%':>10}{'中位%':>10}{'盈亏比':>8}{'前段%':>10}{'后段%':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for horizon in HORIZONS:
        for entry in ("close", "next_open"):
            key = f"{entry}_h{horizon}"
            m = report["arms"][key]
            label = ("尾盘买" if entry == "close" else "次开买") + f" 持{horizon}日"
            lines.append(
                f"{label:<16}{m['n']:>10,}{m['win_rate']:>9.2f}{m['mean_pct']:>10.4f}"
                f"{m['median_pct']:>10.4f}{(m['pl_ratio'] or 0):>8.3f}"
                f"{(m['front_mean_pct'] or 0):>10.4f}{(m['back_mean_pct'] or 0):>10.4f}"
            )
        edge = report["arms"][f"tail_edge_h{horizon}_pp"]
        lines.append(f"{'  └ 尾盘入场净贡献':<16}{edge:>+10.4f} pp（同卖出日，只换入场价）")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="尾盘入场基线：收盘买 vs 次开买")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--start", default="2021-01-04")
    parser.add_argument("--end", default="2026-08-11")
    parser.add_argument("--boards", default="main,chi_next")
    parser.add_argument("--amount-min", type=float, default=30_000_000.0)
    parser.add_argument("--price-min", type=float, default=3.0)
    parser.add_argument("--chunk-days", type=int, default=250)
    parser.add_argument("--focus-horizon", type=int, default=2)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = run(args)
    print()
    print(format_summary(report))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n完整报告写出 {args.out}")


if __name__ == "__main__":
    main()
