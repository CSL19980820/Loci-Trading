"""热度尾盘选股器的「第 0 步」证伪回测（ADR-011 决策 1）。

同花顺热度榜没有历史，东财人气榜的历史又只能逐票查（重建每日榜要扫全市场），
本机到两家的 TLS 还都是断的。所以这里**不用外部热度**，改用 Barber & Odean (2008)
原始的注意力代理——异常成交量与极端日收益，加上换手率与成交额——在本地全量
``market.db`` 上重建一个"热度前 50"，把 ADR-011 的闸门链一比一搬进回测。

代理的局限必须与结论一并阅读：它测的是**散户注意力这个机制**，不是同花顺 ``rate``
这个具体黑箱分。若代理口径下为负期望，"换成同花顺就会转正"缺乏依据；若为正，
才值得投入去接同花顺直连。

七条对照臂各隔离一个可疑决策，见 ``ARMS``。脚本只读行情库，不写任何业务表。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import (  # noqa: E402
    BacktestConfig,
    PortfolioResearchConfig,
    analyze_portfolio,
    run_backtest,
)
from src.formula import MA, REF, limit_up_flags  # noqa: E402
from src.market.domain.universe import classify_board, is_st_name  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

PRICE_FIELDS = ("open", "high", "low", "close")
RAW_FIELDS = ("volume", "amount", "turnover", "outstanding_share")
ALL_FIELDS = PRICE_FIELDS + RAW_FIELDS

#: 20% 涨跌幅板：创业板与科创板。其余按 10% 判涨停。
WIDE_LIMIT_PREFIXES = ("300", "301", "688", "689")


@dataclass(frozen=True, slots=True)
class Gates:
    """ADR-011 决策 6 / 7 的阈值，默认值即 ADR 定稿的中性档。"""

    float_mv_max: float = 400e8
    """流通市值上限（元）。决策 6。"""

    outstanding_share_max: float = 20e8
    """流通股本上限（股）。决策 6 挡"低价 × 巨股本"的僵尸票。"""

    pct_chg_min: float = -3.0
    """当日涨幅下限（%）。决策 7 的回调低吸旁池下沿。"""

    pct_chg_max: float = 7.0
    """当日涨幅上限（%）。决策 7：涨超 7% 次日高开即套。"""

    amount_min: float = 30_000_000.0
    """成交额下限（元）。所有对照臂共用的可交易底线。

    反向臂（低注意力）尤其需要它：低关注度的极端是停牌僵尸票，
    不设流动性底线的话"低关注次日涨"会被根本买不进的票污染。
    """

    hot_top_n: int = 50
    """热度池大小。决策 3 的"前 50"。"""

    pick_top_n: int = 3
    """每日出票上限。决策 11。"""


def _load_universe(
    conn: sqlite3.Connection, *, as_of: str, boards: set[str]
) -> tuple[list[str], dict[str, str]]:
    """当前 instruments 快照，非严格历史成分（存活偏差已在 summary 标注）。"""
    rows = conn.execute(
        "SELECT code,name,list_date,status,industry FROM instruments "
        "WHERE instrument_type='STOCK'"
    ).fetchall()
    as_of_date = pd.Timestamp(as_of)
    codes: list[str] = []
    industry: dict[str, str] = {}
    for code_raw, name_raw, listed_raw, status_raw, industry_raw in rows:
        code = str(code_raw).zfill(6)
        name = str(name_raw or "")
        if classify_board(code) not in boards or is_st_name(name):
            continue
        if str(status_raw or "normal") in {"suspended", "delisted"}:
            continue
        listed = str(listed_raw or "")[:10]
        if listed:
            try:
                if (as_of_date - pd.Timestamp(listed)).days < 60:
                    continue
            except (TypeError, ValueError):
                pass
        codes.append(code)
        industry[code] = str(industry_raw or "")
    return sorted(set(codes)), industry


def _panel_from_flat(
    flat: pd.DataFrame, *, dates: Iterable[str], codes: list[str], field: str
) -> pd.DataFrame:
    if flat.empty:
        return pd.DataFrame(index=pd.Index(list(dates), name="trade_date"), columns=codes)
    panel = flat.pivot(index="trade_date", columns="code", values=field)
    panel.index = panel.index.astype(str)
    panel.columns = panel.columns.astype(str).str.zfill(6)
    return panel.reindex(index=list(dates), columns=codes).astype("float32")


def _load_panels(
    conn: sqlite3.Connection,
    *,
    load_start: str,
    load_end: str,
    dates: list[str],
    codes: list[str],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """返回 (qfq, raw)。价格类按后复权比例折到区间末日，量额与股本不换算。"""
    date_index = [day for day in dates if load_start <= day <= load_end]
    placeholders = ",".join("?" for _ in codes)
    raw: dict[str, pd.DataFrame] = {}
    for field in ALL_FIELDS:
        flat = pd.read_sql_query(
            f"SELECT trade_date,code,{field} FROM quotes_daily "
            f"WHERE trade_date>=? AND trade_date<=? AND code IN ({placeholders})",
            conn,
            params=[load_start, load_end, *codes],
            dtype={field: "float32"},
        )
        flat["code"] = flat["code"].astype(str).str.zfill(6)
        raw[field] = _panel_from_flat(flat, dates=date_index, codes=codes, field=field)
        del flat

    factors = pd.read_sql_query(
        "SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE trade_date<=?",
        conn,
        params=[load_end],
    )
    factors["code"] = factors["code"].astype(str).str.zfill(6)
    factors = factors[factors["code"].isin(set(codes))]
    if factors.empty:
        ratio = pd.DataFrame(1.0, index=date_index, columns=codes, dtype="float32")
    else:
        sparse = factors.pivot(index="trade_date", columns="code", values="hfq_factor")
        sparse.index = sparse.index.astype(str)
        sparse.columns = sparse.columns.astype(str).str.zfill(6)
        aligned = (
            sparse.reindex(sparse.index.union(pd.Index(date_index)))
            .sort_index()
            .ffill()
            .bfill()
            .reindex(date_index)
            .reindex(columns=codes)
            .astype("float32")
            .fillna(1.0)
        )
        ratio = aligned.div(aligned.iloc[-1].replace(0.0, 1.0), axis=1)
    qfq = {field: raw[field].copy() for field in ALL_FIELDS}
    for field in PRICE_FIELDS:
        qfq[field] = raw[field] * ratio
    return qfq, raw


def _safe_rank(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.rank(axis=1, pct=True, method="first").fillna(0.0)


def build_context(
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    industry: dict[str, str],
    gates: Gates,
) -> dict[str, pd.DataFrame]:
    """一次算好所有对照臂共享的 PIT 面板；不引用任何未来行。"""
    close, high, low = qfq["close"], qfq["high"], qfq["low"]
    raw_close, raw_high = raw["close"], raw["high"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]
    shares = raw["outstanding_share"]

    pct_chg = (close / REF(close, 1) - 1.0) * 100.0
    vol_ratio = volume / MA(volume, 20)

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
        np.isclose(raw_high, raw["low"], equal_nan=False),
        index=close.index,
        columns=close.columns,
    )
    del high, low

    # 可交易底线：所有臂共用，保证正反两组来自同一个票池。
    tradable = (
        (volume > 0)
        & amount.ge(gates.amount_min)
        & turnover.notna()
        & close.notna()
        & ~sealed
        & ~one_word
    )

    # 注意力代理。前两项是 Barber & Odean (2008) 的原始代理（异常成交量、极端收益），
    # 后两项补上散户参与度与绝对关注量。只在可交易票内做横截面排名，
    # 否则停牌僵尸票会占满"低注意力"那一端。
    attention_raw = (
        _safe_rank(turnover.where(tradable)) * 0.30
        + _safe_rank(vol_ratio.clip(upper=8.0).where(tradable)) * 0.30
        + _safe_rank(amount.where(tradable)) * 0.25
        + _safe_rank(pct_chg.abs().where(tradable)) * 0.15
    )
    attention = attention_raw.where(tradable)
    hot_rank = attention.rank(axis=1, ascending=False, method="first")
    cold_rank = attention.rank(axis=1, ascending=True, method="first")
    hot_pool = hot_rank.le(gates.hot_top_n).fillna(False)
    cold_pool = cold_rank.le(gates.hot_top_n).fillna(False)

    # 决策 4：注意力增量。排名变小=升温，故 delta = 昨日排名 - 今日排名。
    rank_delta = (REF(hot_rank, 1) - hot_rank).fillna(0.0)
    # shift 会把 bool 面板降成 object，object 上的 ~True 是 -2、~False 是 -1，两个都为真。
    # 少一个 astype(bool)，fresh 就会恒真、退化成 hot_pool 本身。
    prev_hot = hot_pool.shift(1, fill_value=False).astype(bool)
    fresh = (hot_pool & ~prev_hot).fillna(False)

    float_mv = raw_close * shares
    cap_ok = float_mv.le(gates.float_mv_max) & shares.le(gates.outstanding_share_max)
    pct_ok = pct_chg.ge(gates.pct_chg_min) & pct_chg.le(gates.pct_chg_max)

    # 决策 5 的本地代理：同花顺 concept_tag 本地没有，用 instruments.industry 顶。
    # 617/5540 只票没有行业，它们的抱团确认恒为假——这是代理的已知缺口。
    ind_series = pd.Series(
        [industry.get(code, "") for code in close.columns], index=close.columns
    )
    named = ind_series[ind_series != ""]
    cluster_n = pd.DataFrame(0.0, index=close.index, columns=close.columns, dtype="float32")
    for cols in named.groupby(named).groups.values():
        members = list(cols)
        if len(members) < 2:
            continue
        counts = hot_pool[members].sum(axis=1)
        cluster_n.loc[:, members] = np.repeat(
            counts.to_numpy(dtype="float32")[:, None], len(members), axis=1
        )

    return {
        "tradable": tradable,
        "attention": attention,
        "hot_pool": hot_pool,
        "cold_pool": cold_pool,
        "rank_delta": rank_delta,
        "fresh_pool": fresh,
        "cap_ok": cap_ok.fillna(False),
        "pct_ok": pct_ok.fillna(False),
        "cluster_ok": cluster_n.ge(2.0),
        "pct_chg": pct_chg,
        "float_mv": float_mv,
    }


@dataclass(frozen=True, slots=True)
class Arm:
    """一条对照臂。每条只改一个变量，用来隔离 ADR-011 里某一条可疑决策。"""

    label: str
    note: str
    pool_key: str
    with_cap: bool
    order: str | None
    """``None`` 表示不选 top3，池内全取。"""
    backtest: bool = True
    """全取臂的信号量可达数千/日，跑障碍回测会产生百万级交易；
    这类臂只取路径无关的标签统计，基准结论一样成立。"""


ARMS: tuple[Arm, ...] = (
    Arm("A_hot_incr_top3", "热度前50 + 市值闸 + 增量排序 top3（ADR 定稿方案）", "hot_pool", True, "incr"),
    Arm("B_cold_all", "热度后50 + 市值闸 全取（反向：低关注度）", "cold_pool", True, None, False),
    Arm("C_hot_all", "热度前50 + 市值闸 全取（隔离 top3 选择的影响）", "hot_pool", True, None, False),
    Arm("D_pool_all", "不设热度闸，仅市值+涨幅闸 全取（池子基准）", "tradable", True, None, False),
    Arm("E_hot_level_top3", "热度前50 + 市值闸 + 存量排序 top3（对比决策 4）", "hot_pool", True, "level"),
    Arm("F_hot_nocap_top3", "热度前50 + 增量排序 top3，不设市值闸（测决策 6 逆向选择）", "hot_pool", False, "incr"),
    Arm("G_hot_cluster_top3", "A + 同行业热度股≥2 抱团确认（测决策 5）", "hot_pool", True, "cluster"),
    Arm(
        "H_fresh_top3",
        "首次进前50 + 市值闸 + 增量排序 top3（注意力冲击刚开始，理论支撑最强）",
        "fresh_pool",
        True,
        "incr",
    ),
)


#: (entry_timing, hold_days) 执行网格。
#:
#: A 股 T+1：当日买入当日不可卖，引擎也从 ``entry_idx + 1`` 起才找出场。因此
#: "次日开盘买、次日收盘卖"这个组合**不合法**，"只要次日盘中那一段"是不可交易的。
#: 要在 T+1 盘中卖出，就必须在 T 日尾盘先持有，隔夜跳空躲不开——这是本轮
#: 最重要的约束，网格就是用来量化"躲不开的话还有没有别的活路"。
EXECUTION_VARIANTS: tuple[tuple[str, int], ...] = (
    ("close", 1),      # 尾盘买、T+1 卖：用户原方案
    ("close", 2),      # 尾盘买、T+2 卖：给一天缓冲
    ("close", 3),      # 尾盘买、T+3 卖
    ("next_open", 1),  # T+1 开盘买、T+2 卖：sanyuan-tail-v1 的执行模式
    ("next_open", 2),  # T+1 开盘买、T+3 卖
)

#: 表格与 ADR 对照用的基准格：即用户原方案。
BASELINE_VARIANT = "close_h1"


def _select(ctx: dict[str, pd.DataFrame], arm: Arm, gates: Gates) -> pd.DataFrame:
    pool_key, with_cap, order = arm.pool_key, arm.with_cap, arm.order
    mask = ctx[pool_key] & ctx["tradable"] & ctx["pct_ok"]
    if with_cap:
        mask = mask & ctx["cap_ok"]
    if order == "cluster":
        mask = mask & ctx["cluster_ok"]
    mask = mask.fillna(False)
    if order is None:
        return mask
    if order == "level":
        score = _safe_rank(ctx["attention"])
    else:
        score = _safe_rank(ctx["rank_delta"]) * 0.7 + _safe_rank(ctx["attention"]) * 0.3
    ranked = score.where(mask).rank(axis=1, ascending=False, method="first")
    return (mask & ranked.le(gates.pick_top_n)).fillna(False)


def _label_stats(
    mask: pd.DataFrame, qfq: dict[str, pd.DataFrame], window: list[str]
) -> dict[str, Any]:
    """次日结果的**路径无关**统计，不假设先触止损还是先触止盈。

    带障碍的回测里，引擎按仓规先判止损（`engine.py` 的 stop 分支在 take 之前），
    同日两边都触时一律记亏。这个约定对高波动标的的惩罚远重于低波动标的——正是
    热度组与冷门组的系统性差异所在。所以对照必须同时看这一组无偏数字，
    否则会把约定造成的偏差读成"热度无效"。
    """
    base = qfq["close"].loc[window]
    nxt_high = qfq["high"].shift(-1).loc[window]
    nxt_low = qfq["low"].shift(-1).loc[window]
    nxt_open = qfq["open"].shift(-1).loc[window]
    nxt_close = qfq["close"].shift(-1).loc[window]
    valid = (
        mask.loc[window]
        & base.gt(0)
        & nxt_high.notna()
        & nxt_low.notna()
        & nxt_close.notna()
    )
    sel = valid.to_numpy()
    n = int(sel.sum())
    if n == 0:
        return {"signals": 0}
    base_a = base.to_numpy()
    up3 = (nxt_high.to_numpy() >= base_a * 1.03)[sel]
    up5 = (nxt_high.to_numpy() >= base_a * 1.05)[sel]
    dn3 = (nxt_low.to_numpy() <= base_a * 0.97)[sel]
    ret_close = ((nxt_close.to_numpy() / base_a - 1.0) * 100.0)[sel]
    ret_open = ((nxt_open.to_numpy() / base_a - 1.0) * 100.0)[sel]
    return {
        "signals": n,
        # 决策 2 的标签本身：次日盘中给不给 +3% 的出货机会。
        "p_next_high_ge_3pct": round(float(np.nanmean(up3) * 100), 2),
        "p_next_high_ge_5pct": round(float(np.nanmean(up5) * 100), 2),
        "p_next_low_le_neg3pct": round(float(np.nanmean(dn3) * 100), 2),
        # 同日两边都触：带障碍回测里这部分全被记成止损，是约定偏差的影响面。
        "p_both_barriers": round(float(np.nanmean(up3 & dn3) * 100), 2),
        # 无障碍的次日收益（今收 → 次收），完全不含路径假设。
        "mean_next_close_pct": round(float(np.nanmean(ret_close)), 4),
        "median_next_close_pct": round(float(np.nanmedian(ret_close)), 4),
        # 隔夜溢价（今收 → 次开）。A 股该项通常为负，见 ADR-011 决策 2。
        "mean_overnight_gap_pct": round(float(np.nanmean(ret_open)), 4),
    }


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    valid = frame[frame["exit_reason"] != "data_end"]
    if valid.empty:
        return {"trades": 0, "data_end_trades": int(len(frame))}
    net = valid["net_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    exits = valid["exit_reason"].value_counts().to_dict()
    return {
        "trades": int(len(valid)),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "avg_net_return_pct": round(float(net.mean()), 4),
        "median_net_return_pct": round(float(net.median()), 4),
        "payoff_ratio": (
            None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 4)
        ),
        "profit_factor": (
            None
            if losses.empty or losses.sum() == 0
            else round(float(wins.sum() / abs(losses.sum())), 4)
        ),
        "exit_reasons": {str(k): int(v) for k, v in exits.items()},
        "data_end_trades": int(len(frame) - len(valid)),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    gates = Gates()
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
    if args.start not in days:
        raise SystemExit(f"起始日 {args.start} 不是交易日；库内最近为 {days[-1]}")
    start_pos = days.index(args.start)
    load_start = days[max(0, start_pos - 40)]
    with _read_only_connection(db_path) as conn:
        codes, industry = _load_universe(
            conn, as_of=args.end, boards={"main", "chi_next", "star"}
        )
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=args.end, dates=days, codes=codes
        )
    ctx = build_context(qfq, raw, industry, gates)

    # 决策 10：次日 -3% 止损 / +3% 止盈 / 都不触则次日收盘卖。
    config = BacktestConfig(
        hold_days=1, stop_loss_pct=-3.0, take_profit_pct=3.0, benchmark=None
    )
    window = [day for day in ctx["tradable"].index if args.start <= day <= args.end]
    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]

    rows: list[dict[str, Any]] = []
    for arm in ARMS:
        selected = _select(ctx, arm, gates)
        scoped = pd.DataFrame(False, index=selected.index, columns=selected.columns)
        scoped.loc[window] = selected.loc[window]
        row: dict[str, Any] = {
            "arm": arm.label,
            "note": arm.note,
            "signals_per_day": round(float(scoped.loc[window].sum(axis=1).mean()), 3),
            "labels": _label_stats(scoped, qfq, window),
        }
        if arm.backtest:
            variants: dict[str, dict[str, Any]] = {}
            for timing, hold in EXECUTION_VARIANTS:
                cfg = BacktestConfig(
                    hold_days=hold,
                    stop_loss_pct=-3.0,
                    take_profit_pct=3.0,
                    benchmark=None,
                )
                result = run_backtest(
                    scoped,
                    price_panels,
                    entry_timing=timing,
                    config=cfg,
                    strategy_slug=f"heat-tail-proxy:{arm.label}:{timing}-h{hold}",
                )
                key = f"{timing}_h{hold}"
                variants[key] = _metrics(result.to_frame())
                if arm.order is not None:
                    variants[key]["portfolio"] = analyze_portfolio(
                        result.trades,
                        config=PortfolioResearchConfig(
                            initial_capital=200_000.0,
                            max_positions=gates.pick_top_n,
                            period="month",
                        ),
                        trading_dates=window,
                        strategy_slug=f"heat-tail-proxy:{arm.label}",
                    ).to_dict()
            row["execution"] = variants
            row["barrier_metrics"] = variants[BASELINE_VARIANT]
        rows.append(row)

    summary = {
        "purpose": "ADR-011 决策 1 第 0 步：注意力代理下的证伪回测",
        "attention_proxy": (
            "0.30*rank(换手率) + 0.30*rank(量比 volume/MA20) "
            "+ 0.25*rank(成交额) + 0.15*rank(|当日涨幅|)，仅在可交易票内做横截面排名"
        ),
        "proxy_caveat": (
            "代理测的是散户注意力机制，不是同花顺 rate 这个黑箱分；"
            "板块抱团用 instruments.industry 顶替同花顺 concept_tag，617/5540 只票缺行业"
        ),
        "entry": "基准 entry_timing=close（当日尾盘按收盘价成交）；另跑 next_open 对照",
        "exit": asdict(config),
        "execution_grid": [f"{timing}_h{hold}" for timing, hold in EXECUTION_VARIANTS],
        "t1_constraint": (
            "A 股 T+1 且引擎从 entry_idx+1 起找出场，"
            "「次日开盘买、次日收盘卖」不合法；要在 T+1 盘中卖必须 T 日尾盘先持有"
        ),
        "gates": asdict(gates),
        "data": {
            "db": str(db_path),
            "load_start": load_start,
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes": len(codes),
            "boards": ["main", "chi_next", "star"],
            "survivorship_note": "当前 instruments 快照，非严格历史成分",
            "price_panels": "qfq（复权）用于收益；市值与涨停判定用不复权价",
        },
        "arms": rows,
    }
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(_render_table(summary))
    return summary


def _render_table(summary: dict[str, Any]) -> str:
    """压成两张窄表：组合明细留在 summary.json，终端只看结论。"""
    meta = summary["data"]
    lines = [
        f"区间 {meta['range'][0]} .. {meta['range'][1]}  交易日={meta['trading_days']}  票池={meta['codes']}",
        "",
        "【路径无关】次日结果（不含先止损/先止盈假设）",
        f"{'臂':<20}{'日均':>8}{'样本':>8}{'高≥+3%':>9}{'高≥+5%':>9}{'低≤-3%':>9}"
        f"{'两边都触':>9}{'次收均值%':>10}{'次收中位%':>10}{'隔夜%':>8}",
    ]

    def fmt(value: Any, nd: int = 2) -> str:
        return "-" if value is None else f"{float(value):.{nd}f}"

    for row in summary["arms"]:
        lab = row["labels"]
        lines.append(
            f"{row['arm']:<20}{row['signals_per_day']:>8.2f}{lab.get('signals', 0):>8}"
            f"{fmt(lab.get('p_next_high_ge_3pct')):>9}{fmt(lab.get('p_next_high_ge_5pct')):>9}"
            f"{fmt(lab.get('p_next_low_le_neg3pct')):>9}{fmt(lab.get('p_both_barriers')):>9}"
            f"{fmt(lab.get('mean_next_close_pct'), 3):>10}"
            f"{fmt(lab.get('median_next_close_pct'), 3):>10}"
            f"{fmt(lab.get('mean_overnight_gap_pct'), 3):>8}"
        )
    lines += [
        "",
        "【带障碍】-3% 止损 / +3% 止盈 / 次日收盘卖（同日两边都触按先止损计）",
        f"{'臂':<20}{'笔数':>8}{'胜率%':>8}{'均净%':>9}{'盈亏比':>8}{'盈利因子':>9}{'出场归因':>28}",
    ]
    for row in summary["arms"]:
        met = row.get("barrier_metrics")
        if not met:
            lines.append(f"{row['arm']:<20}{'（全取臂只取路径无关统计）':>20}")
            continue
        exits = met.get("exit_reasons") or {}
        brief = " ".join(f"{k}={v}" for k, v in sorted(exits.items()))
        lines.append(
            f"{row['arm']:<20}{met.get('trades', 0):>8}{fmt(met.get('win_rate_pct')):>8}"
            f"{fmt(met.get('avg_net_return_pct'), 3):>9}{fmt(met.get('payoff_ratio')):>8}"
            f"{fmt(met.get('profit_factor')):>9}  {brief}"
        )
    grid = summary.get("execution_grid") or []
    if grid:
        lines += [
            "",
            "【执行网格】均净% / 胜率% （-3% 止损、+3% 止盈，同日两边都触按先止损计）",
            f"{'臂':<20}" + "".join(f"{key:>18}" for key in grid),
        ]
        for row in summary["arms"]:
            variants = row.get("execution")
            if not variants:
                continue
            cells = ""
            for key in grid:
                met = variants.get(key) or {}
                if not met.get("trades"):
                    cells += f"{'-':>18}"
                    continue
                cells += (
                    f"{fmt(met.get('avg_net_return_pct'), 2)}/"
                    f"{fmt(met.get('win_rate_pct'), 1)}".rjust(18)
                )
            lines.append(f"{row['arm']:<20}{cells}")

    lines += ["", "臂说明："]
    lines += [f"  {row['arm']:<20}{row['note']}" for row in summary["arms"]]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB)
    )
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output", default="output/heat-tail-attention-proxy-2024-01-02_2026-07-31"
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
