"""把《娱乐》素材里的纯日线尾盘规则，放到「尾盘买 vs 次日开盘买」两种执行下实测。

素材台账见 `docs/research/_scratch_2026-08-yule-tail-material-inventory.md`。本脚本只取其中
**不需要分钟线、不需要盘口**的那几条，逐条做成预注册的对照臂——不做 4,000 组网格搜索，
因为姊妹篇 `2026-08-tail-1450-next-day-touch-backtest.md` 已经证明那样只会放大多重比较。

每条臂同时回答两个问题：

1. **这条规则本身有没有 alpha？** 用日中性化（减当日全池均值）与波动率匹配对照两把尺子。
   前者剔掉「踩对了大盘」，后者剔掉「只是选了高波动票」。
2. **该在尾盘买，还是尾盘只选票、次日开盘买？** 两臂共用同一批信号与同一个卖出日，
   差额就是隔夜那一跳。素材里 6 份独孤八式、一线定乾坤、潜龙出海原文都选了后者。

审计口径：所有信号只用 T 日 **收盘价 / 开盘价 / 成交量 / 换手率 / 流通股本** 与历史 K，
**不使用当日 high/low**——按 `src/strategy/README.md`，`entry_timing=close` 下裸用当日
极值是 block。ATR% 只作波动率分层，不进任何信号。

数据限制与姊妹篇一致：本机无分钟线；`amount` 95.48% 为 `close*volume` 合成；
`instruments` 是当前快照（存活偏差，方向上让结果偏乐观）。

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
from typing import Any, Callable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.formula import ATR, HHV, MA, REF, SUM, limit_up_flags  # noqa: E402
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
HORIZONS = (1, 2, 3)


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

    ma5 = MA(close, 5)
    turnover_pct = turnover * 100.0
    feats: dict[str, pd.DataFrame] = {
        "entry_close": close,
        "entry_next_open": open_.shift(-1),
        "tradable": tradable,
        "next_open_ok": (open_.shift(-1).notna() & ~one_word.shift(-1).fillna(True)).fillna(False),
        # ── 素材规则用到的原始量（全部不含当日 high/low）──
        # T36 近 5 日累计换手（%）
        "f_turnover_sum5": SUM(turnover_pct, 5),
        # T38 信号日成交量是否为近 20 日最大
        "f_vol_is_max20": (volume >= HHV(volume, 20)).astype("float32"),
        # T39 收盘相对 MA5 的位置
        "f_ma5_ratio": close / ma5,
        # T28 杨氏闸门
        "f_shares_yi": shares / 1e8,
        "f_price": raw_close,
        "f_turnover": turnover_pct,
        "f_pct_chg": pct_chg,
        # T43 旭日东升：昨阴 + 今收 > 昨开
        "f_sunrise": (
            (REF(close, 1) < REF(open_, 1)) & (close > REF(open_, 1)) & (close > open_)
        ).astype("float32"),
        # T44 连 3 阴后首根阳线
        "f_after_3red": (
            (close > open_)
            & (REF(close, 1) < REF(open_, 1))
            & (REF(close, 2) < REF(open_, 2))
            & (REF(close, 3) < REF(open_, 3))
        ).astype("float32"),
        # 仅作波动率分层，不进信号（用到当日 high/low，已在文档披露）
        "f_atr_pct": (ATR(high, low, close, 14) / close) * 100.0,
    }
    for h in HORIZONS:
        feats[f"exit_{h}"] = close.shift(-h)
        feats[f"exit_ok_{h}"] = (
            close.shift(-h).notna() & ~one_word.shift(-h).fillna(True)
        ).fillna(False)
    return feats


PRICE_KEYS = ("entry_close", "entry_next_open", *[f"exit_{h}" for h in HORIZONS])


def flatten_chunk(
    feats: dict[str, pd.DataFrame], seg: list[str], day_offset: int
) -> dict[str, np.ndarray]:
    keep = feats["tradable"].loc[seg].to_numpy() & feats["next_open_ok"].loc[seg].to_numpy()
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
        self.entry_close = merged.pop("entry_close")
        self.entry_next_open = merged.pop("entry_next_open")
        self.exits = {h: merged.pop(f"exit_{h}") for h in HORIZONS}
        self.f = merged
        vol_rank = self._cs_rank(self.f["f_atr_pct"])
        self.vol_bucket = np.where(
            np.isfinite(vol_rank), np.clip(np.nan_to_num(vol_rank) * 10.0, 0, 9), -1
        ).astype("int16")

    def size(self) -> int:
        return int(self.entry_close.size)

    def _cs_rank(self, vals: np.ndarray) -> np.ndarray:
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

    def net(self, *, entry: str, horizon: int) -> np.ndarray:
        base = self.entry_close if entry == "close" else self.entry_next_open
        return (self.exits[horizon] / base - 1.0 - ROUND_TRIP_COST).astype("float32")

    def day_demean(self, net: np.ndarray) -> np.ndarray:
        sums = np.bincount(self.day_idx, weights=net.astype("float64"), minlength=self.n_days)
        counts = np.bincount(self.day_idx, minlength=self.n_days)
        means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
        return (net - means[self.day_idx]).astype("float32")

    def vol_matched_expectation(self, net: np.ndarray, sel: np.ndarray) -> float:
        """按该臂的 ATR% 十分位结构给全池重新加权，得到「只有波动率、没有 alpha」时的应得值。"""
        total = 0.0
        weight = 0.0
        for bucket in range(10):
            in_arm = sel & (self.vol_bucket == bucket)
            n_arm = int(in_arm.sum())
            if n_arm == 0:
                continue
            pool = self.vol_bucket == bucket
            if not pool.any():
                continue
            total += n_arm * float(np.mean(net[pool], dtype="float64"))
            weight += n_arm
        return round(total / weight * 100.0, 4) if weight else float("nan")


def metrics(book: Book, net: np.ndarray, sel: np.ndarray) -> dict[str, Any]:
    part = net[sel]
    n = int(part.size)
    if n == 0:
        return {"n": 0}
    wins, losses = part[part > 0], part[part < 0]
    mean_win = float(wins.mean()) if wins.size else 0.0
    mean_loss = float(-losses.mean()) if losses.size else 0.0
    half = book.half[sel]
    front, back = part[~half], part[half]
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
        "day_neutral_mean_pct": round(_pct(book.day_demean(net)[sel]), 4),
        "vol_matched_mean_pct": book.vol_matched_expectation(net, sel),
    }
    out["both_halves_positive"] = bool(
        out["front_mean_pct"] is not None
        and out["back_mean_pct"] is not None
        and out["front_mean_pct"] > 0
        and out["back_mean_pct"] > 0
    )
    out["excess_vs_vol_matched_pp"] = round(out["mean_pct"] - out["vol_matched_mean_pct"], 4)
    return out


def by_year(book: Book, net: np.ndarray, sel: np.ndarray) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    years, part = book.years[sel], net[sel]
    for year in sorted(set(years.tolist())):
        chunk = part[years == year]
        out[year] = {
            "n": int(chunk.size),
            "mean_pct": round(_pct(chunk), 4),
            "win_rate": round(_pct(chunk > 0), 3),
        }
    return out


#: 预注册的对照臂。每条都注明素材编号，避免事后挑选。
ARMS: dict[str, tuple[str, Callable[[dict[str, np.ndarray]], np.ndarray]]] = {
    "S0_全池基线": ("对照", lambda f: np.ones(f["f_turnover"].size, dtype=bool)),
    "S1_T36_5日累计换手≥40": (
        "T36",
        lambda f: f["f_turnover_sum5"] >= 40.0,
    ),
    "S2_T38_量能近20日最大": ("T38", lambda f: f["f_vol_is_max20"] > 0.5),
    "S3_T36+T38": (
        "T36+T38",
        lambda f: (f["f_turnover_sum5"] >= 40.0) & (f["f_vol_is_max20"] > 0.5),
    ),
    "S4_T36+T38+T39贴MA5": (
        "T36+T38+T39",
        lambda f: (f["f_turnover_sum5"] >= 40.0)
        & (f["f_vol_is_max20"] > 0.5)
        & (f["f_ma5_ratio"] > 1.005)
        & (f["f_ma5_ratio"] <= 1.12),
    ),
    "S5_S4+温和涨幅1~5": (
        "T36+T38+T39+T28涨幅带",
        lambda f: (f["f_turnover_sum5"] >= 40.0)
        & (f["f_vol_is_max20"] > 0.5)
        & (f["f_ma5_ratio"] > 1.005)
        & (f["f_ma5_ratio"] <= 1.12)
        & (f["f_pct_chg"] > 1.0)
        & (f["f_pct_chg"] < 5.0),
    ),
    "S6_T28杨氏六条": (
        "T28",
        lambda f: (f["f_shares_yi"] < 2.0)
        & (f["f_price"] < 12.0)
        & (f["f_pct_chg"] > 1.0)
        & (f["f_pct_chg"] < 5.0)
        & (f["f_turnover"] > 2.0),
    ),
    "S7_T28+T38": (
        "T28+T38",
        lambda f: (f["f_shares_yi"] < 2.0)
        & (f["f_price"] < 12.0)
        & (f["f_pct_chg"] > 1.0)
        & (f["f_pct_chg"] < 5.0)
        & (f["f_turnover"] > 2.0)
        & (f["f_vol_is_max20"] > 0.5),
    ),
    "S8_基线甜区_温和涨幅+中换手": (
        "本仓基线发现（非素材）",
        lambda f: (f["f_pct_chg"] > 0.0)
        & (f["f_pct_chg"] < 4.0)
        & (f["f_turnover"] > 1.0)
        & (f["f_turnover"] < 6.0),
    ),
    "S9_T44连三阴后首阳": ("T44", lambda f: f["f_after_3red"] > 0.5),
    "S10_T43旭日东升": ("T43", lambda f: f["f_sunrise"] > 0.5),
}


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
            print(f"  {seg[0]}~{seg[-1]} 样本 {parts[-1]['day_idx'].size:,}", flush=True)
    finally:
        conn.close()

    book = Book(parts, window)
    gc.collect()
    print(f"可交易样本 {book.size():,}\n", flush=True)

    report: dict[str, Any] = {
        "window": [window[0], window[-1]],
        "trading_days": len(window),
        "universe": len(codes),
        "samples": book.size(),
        "round_trip_cost_bps": ROUND_TRIP_COST * 1e4,
        "arms": {},
    }
    nets = {
        (entry, h): book.net(entry=entry, horizon=h)
        for entry in ("close", "next_open")
        for h in HORIZONS
    }
    for name, (source, fn) in ARMS.items():
        sel = fn(book.f) & np.isfinite(book.entry_close)
        entry_report: dict[str, Any] = {"source": source, "signals": int(sel.sum())}
        for (entry, h), net in nets.items():
            entry_report[f"{entry}_h{h}"] = metrics(book, net, sel)
        for h in HORIZONS:
            entry_report[f"tail_edge_h{h}_pp"] = round(
                entry_report[f"close_h{h}"]["mean_pct"]
                - entry_report[f"next_open_h{h}"]["mean_pct"],
                4,
            )
        for (entry, h), net in nets.items():
            entry_report[f"by_year_{entry}_h{h}"] = by_year(book, net, sel)
        report["arms"][name] = entry_report
        print(f"  {name}: {int(sel.sum()):,} 笔", flush=True)
    return report


def format_summary(report: dict[str, Any], horizon: int) -> str:
    lines: list[str] = []
    w = report["window"]
    lines.append(
        f"窗口 {w[0]}~{w[1]}　交易日 {report['trading_days']}　样本 {report['samples']:,}"
        f"　成本 {report['round_trip_cost_bps']:.0f}bps　持有 {horizon} 日（T+{horizon} 收盘卖）"
    )
    lines.append("")
    header = (
        f"{'臂':<26}{'笔数':>9}{'日均':>7}{'胜率%':>8}{'尾盘买均净%':>12}"
        f"{'次开买均净%':>12}{'尾盘代价pp':>11}{'日中性%':>9}{'超波动率%':>10}{'两段皆正':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for name, arm in report["arms"].items():
        c = arm[f"close_h{horizon}"]
        o = arm[f"next_open_h{horizon}"]
        if not c.get("n"):
            continue
        lines.append(
            f"{name:<26}{c['n']:>9,}{c['per_day']:>7.1f}{c['win_rate']:>8.2f}"
            f"{c['mean_pct']:>12.4f}{o['mean_pct']:>12.4f}"
            f"{arm[f'tail_edge_h{horizon}_pp']:>11.4f}{c['day_neutral_mean_pct']:>9.4f}"
            f"{c['excess_vs_vol_matched_pp']:>10.4f}{('是' if c['both_halves_positive'] else '否'):>9}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="素材尾盘规则实测：尾盘买 vs 次开买")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--start", default="2021-01-04")
    parser.add_argument("--end", default="2026-08-11")
    parser.add_argument("--boards", default="main,chi_next")
    parser.add_argument("--amount-min", type=float, default=30_000_000.0)
    parser.add_argument("--price-min", type=float, default=3.0)
    parser.add_argument("--chunk-days", type=int, default=250)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = run(args)
    for horizon in HORIZONS:
        print()
        print(format_summary(report, horizon))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n完整报告写出 {args.out}")


if __name__ == "__main__":
    main()
