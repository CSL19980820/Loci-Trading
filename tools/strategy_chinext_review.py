"""Read-only, reproducible ChiNext Top-2 breakout strategy review.

Run from the repository root, for example::

    .venv/Scripts/python.exe tools/strategy_chinext_review.py --db SNAPSHOT.db

The source database is opened with SQLite mode=ro and query_only. This script
reuses the system's signal preparation and classic execution engine. It does
not synchronize quotes, persist candidates, or write trading/account databases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.metrics import compute_metrics  # noqa: E402
from src.backtest.application.runner import (  # noqa: E402
    execute_backtest_context,
    prepare_backtest_context,
)
from src.backtest.domain.models import BacktestConfig, Trade  # noqa: E402
from src.market import MarketStore  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402

STRATEGIES = ("contraction-rebreakout-v1", "impulse-inside-breakout-v1")
UNIVERSE = {"preset": "default_a_share", "boards": ["chi_next"], "min_list_days": 0}


class ReadOnlyMarketStore(MarketStore):
    """MarketStore read methods without its schema migration constructor."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve(strict=True)
        self._keep_receipt_index = False
        self.conn = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.execute("PRAGMA busy_timeout=60000")
        # One consistent read snapshot across quotes, factors and metadata.
        self.conn.execute("BEGIN")

    def _quotes_daily_snapshot_fast(self) -> dict[str, object]:
        # Exported meta retains source revisions, including a potentially stale
        # whole-store row cache. The bounded research copy has its own row count.
        row = self.conn.execute(
            "SELECT COUNT(*) AS rows,MAX(trade_date) AS last_date,"
            "MAX(fetched_at) AS fetched_at FROM quotes_daily"
        ).fetchone()
        return dict(row)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def wilson_interval(metrics: dict[str, Any]) -> list[float] | None:
    n = metrics.get("trades", 0)
    if not n:
        return None
    p, z = metrics.get("wins", 0) / n, 1.959963984540054
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round((center - radius) * 100, 2), round((center + radius) * 100, 2)]


def table_metrics(trades: list[Trade]) -> dict[str, Any]:
    metrics = compute_metrics(trades)
    metrics["win_rate_wilson_95_pct"] = wilson_interval(metrics)
    return metrics


def input_digest(ctx: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for name, panel in sorted(ctx["execution_panels"].items()):
        if not isinstance(panel, pd.DataFrame):
            continue
        digest.update(name.encode())
        digest.update("\n".join(map(str, panel.columns)).encode())
        digest.update(pd.util.hash_pandas_object(panel, index=True).values.tobytes())
    digest.update(json.dumps(ctx["resolved"].meta, ensure_ascii=False,
                             sort_keys=True).encode())
    benchmark = ctx.get("benchmark_close")
    if isinstance(benchmark, pd.Series):
        digest.update(pd.util.hash_pandas_object(benchmark, index=True).values.tobytes())
    return digest.hexdigest()


def code_digests(slug: str) -> dict[str, str]:
    files = ["tools/strategy_chinext_review.py", "src/backtest/application/runner.py",
             "src/backtest/application/engine.py", "src/backtest/application/metrics.py",
             "src/backtest/application/execution_contract.py",
             "src/backtest/domain/models.py", "src/market/infrastructure/store_panel.py",
             "src/strategy/application/" + (
                 "contraction_rebreakout.py" if slug == STRATEGIES[0]
                 else "impulse_inside_breakout.py")]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}


def verify_ranking(ctx: dict[str, Any], computed: Any) -> dict[str, Any]:
    signals = ctx["signals"]
    window = signals.loc[ctx["start"]:ctx["end"]]
    if any(not str(code).startswith("30") or len(str(code)) != 6 for code in window):
        raise AssertionError("Non-ChiNext code in ranking universe")
    if int(window.sum(axis=1).max()) > 2:
        raise AssertionError("More than two selected stocks on one day")
    score = computed.factors["score"].reindex_like(window)
    if np.isinf(score.to_numpy()).any():
        raise AssertionError("Infinite ranking score")
    expected = score.reindex(columns=sorted(score.columns)).rank(
        axis=1, ascending=False, method="first").le(2).reindex(columns=score.columns)
    if not expected.equals(window.astype(bool)):
        raise AssertionError("Selected signals do not equal global finite-score Top 2")
    cutoffs = [window.index[len(window) // 3], window.index[2 * len(window) // 3]]
    checked = []
    for cutoff in cutoffs:
        prefix = {name: panel.loc[:cutoff] if isinstance(panel, pd.DataFrame) else panel
                  for name, panel in ctx["panels"].items()}
        sliced = ctx["engine"].compute(prefix, ctx["resolved_params"])
        if not sliced.signals.equals(computed.signals.loc[:cutoff]):
            raise AssertionError(f"Signal causality mismatch at {cutoff}")
        pd.testing.assert_frame_equal(sliced.factors["score"],
                                      computed.factors["score"].loc[:cutoff])
        checked.append(str(cutoff))
    return {"chi_next_only": True, "global_daily_top_2": True,
            "maximum_daily_picks": int(window.sum(axis=1).max()),
            "signal_and_score_prefix_consistency_cutoffs": checked}


def coverage(store: ReadOnlyMarketStore, start: str, end: str) -> dict[str, Any]:
    where = "trade_date BETWEEN ? AND ? AND code GLOB '30[0-9][0-9][0-9][0-9]'"
    rows = [dict(row) for row in store.conn.execute(
        f"SELECT trade_date,COUNT(*) AS quote_codes,SUM(close>0 AND volume>0) AS tradable_codes "
        f"FROM quotes_daily WHERE {where} GROUP BY trade_date ORDER BY trade_date", (start, end))]
    sources = [dict(row) for row in store.conn.execute(
        "SELECT q.source,COUNT(*) AS rows, "
        "SUM(q.receipt_id IS NOT NULL AND q.receipt_id!='') AS with_receipt_id, "
        "SUM(r.receipt_id IS NOT NULL) AS with_existing_receipt, "
        "SUM(r.receipt_id IS NULL) AS missing_receipt_metadata "
        "FROM quotes_daily q LEFT JOIN source_route_receipts r ON q.receipt_id=r.receipt_id "
        "WHERE q.trade_date BETWEEN ? AND ? AND q.code GLOB '30[0-9][0-9][0-9][0-9]' "
        "GROUP BY q.source", (start, end))]
    catalog = dict(store.conn.execute(
        "SELECT COUNT(*) AS codes,SUM(name LIKE '%ST%') AS current_st_codes,"
        "SUM(list_date='') AS missing_list_dates,SUM(delist_date!='') AS known_delist_dates "
        "FROM instruments WHERE code GLOB '30[0-9][0-9][0-9][0-9]' AND instrument_type='STOCK'"
    ).fetchone())
    quote_orphans = [str(row[0]) for row in store.conn.execute(
        f"SELECT DISTINCT code FROM quotes_daily WHERE {where} "
        "AND NOT EXISTS(SELECT 1 FROM instruments i WHERE i.code=quotes_daily.code)", (start, end))]
    return {"current_catalog": catalog, "daily": rows, "sources": sources,
            "quote_codes_missing_from_current_catalog": quote_orphans,
            "historical_membership_available": False,
            "survivorship_and_current_name_bias": True}


def selected_frame(ctx: dict[str, Any], computed: Any) -> pd.DataFrame:
    records = []
    signals = ctx["signals"]
    for row, col in zip(*np.nonzero(signals.to_numpy(dtype=bool))):
        day, code = signals.index[row], signals.columns[col]
        records.append({"signal_date": str(day), "code": str(code),
                        "name": ctx["resolved"].meta.get(code, {}).get("name", ""),
                        "score": float(computed.factors["score"].iloc[row, col]),
                        "rank": float(computed.factors["候选排名"].iloc[row, col])})
    return pd.DataFrame(records, columns=["signal_date", "code", "name", "score", "rank"]).sort_values(
        ["signal_date", "rank", "code"], ignore_index=True)


def stock_case(ctx: dict[str, Any], computed: Any, signal_frame: pd.DataFrame,
               code: str) -> dict[str, Any]:
    day = "2026-09-29"
    if day not in computed.signals.index or code not in computed.signals.columns:
        return {"date": day, "code": code, "available": False}
    factors = {}
    for name, panel in computed.factors.items():
        if isinstance(panel, pd.DataFrame) and day in panel.index and code in panel.columns:
            value = panel.loc[day, code]
            factors[name] = value.item() if hasattr(value, "item") else value
    return {"date": day, "code": code, "available": True,
            "name": ctx["resolved"].meta.get(code, {}).get("name", ""),
            "formula_candidate": bool(computed.factors["条件候选"].loc[day, code]),
            "selected_top2": bool(computed.signals.loc[day, code]),
            "factors": clean_json(factors),
            "selected_that_day": signal_frame.loc[signal_frame.signal_date.eq(day)].to_dict("records")}


def sept29_candidates(ctx: dict[str, Any], computed: Any) -> dict[str, Any]:
    """Audit old six-condition candidates before the new close-limit gate."""
    day = "2026-09-29"
    panels, factors = ctx["panels"], computed.factors
    if day not in computed.signals.index:
        return {"available": False, "date": day}
    close, open_, high, low, volume = (panels[name] for name in ("close", "open", "high", "low", "volume"))
    valid = (np.isfinite(close) & np.isfinite(open_) & np.isfinite(high) & np.isfinite(low)
             & np.isfinite(volume) & volume.gt(0) & close.gt(0) & open_.gt(0) & low.gt(0)
             & high.ge(close) & high.ge(open_) & low.le(close) & low.le(open_)).rolling(14).sum().eq(14)
    original = valid.loc[day] & factors["有效日K根数"].loc[day].gt(30)
    shape_names = ("前期强阳", "两日回调", "回调缩量", "收盘突破前五日高点", "当日放量", "阳线涨幅确认")
    for name in shape_names:
        original &= factors[name].loc[day]
    weights = {"回调缩量分(15)": 15, "回调深度分(15)": 15,
               "再突破放量分(10)": 10, "收盘位置分(20)": 20}
    rows = []
    for code in original.index[original]:
        original_parts = {name.rsplit("(", 1)[0] + "(25)": float(factors[name].loc[day, code] / weight * 25)
                          for name, weight in weights.items()}
        new_parts = {name: float(factors[name].loc[day, code])
                     for name in ("10日动量分(40)", *weights)}
        before_limit = round(sum(new_parts.values()), 4)
        current_rank = factors["候选排名"].loc[day, code]
        rows.append({"code": str(code), "name": ctx["resolved"].meta.get(code, {}).get("name", ""),
                     "old_formula_candidate": True,
                     "six_conditions": {name: bool(factors[name].loc[day, code]) for name in shape_names},
                     "old_score": round(sum(original_parts.values()), 4), "old_components": original_parts,
                     "new_score_before_limit": before_limit, "new_components": new_parts,
                     "new_rank": current_rank,
                     "close_at_limit": not bool(factors["收盘非涨停"].loc[day, code]),
                     "raw_close": float(factors["未复权收盘价"].loc[day, code]),
                     "raw_limit_up": float(factors["涨停价"].loc[day, code]),
                     "selected_top2": bool(computed.signals.loc[day, code])})
    rows.sort(key=lambda row: (-row["old_score"], row["code"]))
    for rank, row in enumerate(rows, 1):
        row["old_rank"] = rank
    return clean_json({"available": True, "date": day, "old_formula_candidates": len(rows),
                       "removed_close_limit_candidates": sum(row["close_at_limit"] for row in rows),
                       "rows": rows})


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}" if isinstance(value, (float, np.floating)) else str(value)


def render_report(summary: dict[str, Any]) -> str:
    start, end = summary["range"]["actual_start"], summary["range"]["actual_end"]
    daily = summary["coverage"]["daily"]
    lines = ["# 创业板双突破策略回测复盘", "", f"生成时间：{summary['created_at']}。",
             f"信号区间：{start} 至 {end}，共 {len(daily)} 个市场交易日；仅创业板完整股票池内每日评分前 2 只。",
             "当前新策略版本为 v1.1 / revision 2：剔除收盘涨停，评分改为 10 日动量 40、缩量 15、浅回调 15、放量 10、收盘位置 20 分。"
             "权重根据 9 月 29 日已知案例校准，本区间属于样本内复盘，尚无独立样本外验证。",
             "", "## 统一执行口径", "",
             "盘后日 K 确认，次一市场交易日开盘成交。主比较沿用系统默认：入场后经过 3 个交易日（入场日为第 1 日，第 4 日收盘退出），止损 -6%，不设止盈。",
             "固定持有观察分别在入场第 5、10、20 个市场交易日收盘退出，不设止损止盈；这些为预先声明的比较窗口，未挑选最优窗口或调参。",
             "形态使用前复权价格，成交记录使用未复权价格，收益与止损线使用显式后复权因子换算的经济权益价格；除权分红不按裸价格跳变计亏。",
             "按 A 股 T+1 撮合。涨停开盘拒绝入场；停牌不可成交；退出收盘跌停时延期，跳空穿越止损按更差的开盘价成交。截止日仍未平仓单独列为 data_end，不计入胜率和盈亏比。",
             "双边佣金各 3 bps、双边滑点各 5 bps、卖出印花税 5 bps，合计一趟 0.21%。"
             "印花税减半依据：[财政部 税务总局 2023 年第 39 号公告](https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html)。"
             "采用经典引擎，未使用加速近似。",
             "信号独立评估，可能持有重叠股票或连续信号；未设组合资金、最大持仓或仓位，平均单笔收益和单笔收益总和均不是账户收益率。",
             "", "## 主结果与固定持有期对照", "",
             "胜率=净收益>0的已平仓交易数/已平仓交易数；盈亏比=平均盈利/平均亏损绝对值（payoff_ratio）；利润因子=盈利总和/亏损总和绝对值（profit_factor）。期望为平均每笔净收益。",
             "", "|策略|口径|已平仓|胜率|盈亏比|利润因子|平均盈利|平均亏损|单笔净期望|右端未成熟|跳过|",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for strategy in summary["strategies"]:
        for name, run in strategy["runs"].items():
            m = run["metrics"]
            lines.append(f"|{strategy['name']}|{name}|{m.get('trades', 0)}|{fmt(m.get('win_rate'))}%|"
                         f"{fmt(m.get('payoff_ratio'), 3)}|{fmt(m.get('profit_factor'), 3)}|"
                         f"{fmt(m.get('avg_win'))}%|{fmt(m.get('avg_loss'))}%|{fmt(m.get('avg_net_return'))}%|"
                         f"{m.get('data_end_trades', 0)}|{sum(run['skipped'].values())}|")
    lines += ["", "## 如何解读本次表现", ""]
    for strategy in summary["strategies"]:
        m = strategy["runs"]["主口径"]["metrics"]
        if not m.get("trades"):
            lines.append(f"{strategy['name']}没有已平仓样本，无法判断胜率与盈亏比。")
            continue
        payoff = m.get("payoff_ratio")
        breakeven = 100 / (1 + payoff) if payoff is not None else None
        direction = "正" if m["avg_net_return"] > 0 else "负"
        lines += [f"{strategy['name']}主口径平均每笔净收益为{direction}："
                  f"{fmt(m['avg_net_return'], 4)}%，净盈利/亏损总额比 {fmt(m.get('profit_factor'), 3)}。"
                  f"按本样本平均赢亏反推的收支平衡胜率约 {fmt(breakeven)}%，"
                  f"观察胜率 {fmt(m.get('win_rate'))}%。该反推依赖本样本赢亏幅度，不能当作未来门槛保证。",
                  f"单笔最好 {fmt(m.get('best'))}%，最差 {fmt(m.get('worst'))}%；"
                  f"净收益中位数 {fmt(m.get('median_net_return'))}%，"
                  f"最长连续亏损 {m.get('max_consecutive_losses')} 笔。"]
        removed = strategy["runs"]["主口径"]["largest_winner_removed"]
        lines.append(f"只作集中度诊断，剔除最大盈利一笔后剩余 {removed.get('trades', 0)} 笔，"
                     f"平均净收益 {fmt(removed.get('avg_net_return'), 4)}%，"
                     f"利润因子 {fmt(removed.get('profit_factor'), 3)}。此诊断不替换主结果或选股规则。")
        worst = strategy["runs"]["主口径"]["worst_closed_trade"]
        if worst:
            lines.append(f"最差交易明细：{worst['code']}，信号 {worst['signal_date']}，"
                         f"{worst['entry_date']} 按原始价 {fmt(worst['entry_price'], 4)} 入场，"
                         f"{worst['exit_date']} 按 {fmt(worst['exit_price'], 4)} 退出，"
                         f"退出原因 `{worst['exit_reason']}`。-6% 是止损触发线；"
                         "T+1、跳空和跌停限制会使实际损失超过该值，不能理解为最大亏损上限。")
    lines += ["固定 5/10/20 日窗口提供同一选股信号的持有期敏感性。主口径与固定窗口同时改变了持有期和止损规则，"
              "不能把两者差异全部归因于止损。不同策略的命中日期和个股也不同，此比较未隔离市场阶段因果。",
              "当前评分用于规则排序，不把 70 分等分数解释为 70% 胜率。原六项形态阈值保留，"
              "本次按已知案例重新校准评分并增加收盘涨停过滤；改分后在相同区间重跑，结果仍是样本内。"
              "没有未来函数不能消除案例选择和参数选择偏差。本次未择优替换预先声明的退出口径。"]
    comparison = summary.get("score_v1_comparison")
    if comparison:
        lines += ["", "## 新策略原评分与当前评分比较", "",
                  "两版使用相同冻结行情、创业板范围、退出和费用；当前版同时增加收盘涨停过滤并改评分，"
                  "无法把结果差异全部归因于其中一项。比较保留四个原定窗口，不择优选取持有期。",
                  "", "|口径|版本|已平仓|胜率|盈亏比|利润因子|单笔净期望|",
                  "|---|---|---:|---:|---:|---:|---:|"]
        current = summary["strategies"][0]
        for label, old_run in comparison["runs"].items():
            for version, metrics in (("原评分 v1", old_run["metrics"]),
                                     ("当前 v1.1", current["runs"][label]["metrics"])):
                lines.append(f"|{label}|{version}|{metrics.get('trades', 0)}|{fmt(metrics.get('win_rate'))}%|"
                             f"{fmt(metrics.get('payoff_ratio'), 3)}|{fmt(metrics.get('profit_factor'), 3)}|"
                             f"{fmt(metrics.get('avg_net_return'), 4)}%|")
    lines += ["", "## 月度与分段稳定性", "", "月度按信号产生月份归属，仅统计截止日前实际已平仓交易，右端未成熟另列。"]
    for strategy in summary["strategies"]:
        run = strategy["runs"]["主口径"]
        lines += ["", f"### {strategy['name']}", "",
                  f"策略版本：`{strategy['revision']}`。选中 {strategy['signal_count']} 个信号，"
                  f"{strategy['active_signal_days']} 个信号日，"
                  f"{strategy['panel_columns']} 只股票进入统一排名面板。",
                  f"主口径胜率 Wilson 95% 区间：{run['metrics'].get('win_rate_wilson_95_pct')}；"
                  "它只反映该有限样本内的二项计数，不消除交易相关性或股票池偏差。",
                  "", "|信号月份|已平仓|胜率|盈亏比|利润因子|单笔净期望|未成熟|",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for month, m in run["by_signal_month"].items():
            lines.append(f"|{month}|{m.get('trades', 0)}|{fmt(m.get('win_rate'))}%|"
                         f"{fmt(m.get('payoff_ratio'), 3)}|{fmt(m.get('profit_factor'), 3)}|"
                         f"{fmt(m.get('avg_net_return'))}%|{m.get('data_end_trades', 0)}|")
        lines += ["", "分段结果（固定按 6 月 1 日划分，不根据表现划分）：", "",
                  "|信号时段|已平仓|胜率|盈亏比|单笔净期望|",
                  "|---|---:|---:|---:|---:|"]
        for phase, m in run["phases"].items():
            lines.append(f"|{phase}|{m.get('trades', 0)}|{fmt(m.get('win_rate'))}%|"
                         f"{fmt(m.get('payoff_ratio'), 3)}|{fmt(m.get('avg_net_return'))}%|")
        lines += ["", f"跳过原因：`{json.dumps(run['skipped'], ensure_ascii=False)}`。",
                  f"退出原因：`{json.dumps(run['metrics'].get('exit_reasons', {}), ensure_ascii=False)}`。",
                  f"排名与因果性检查：`{json.dumps(strategy['verification'], ensure_ascii=False)}`。"]
    lines += ["", "## 9 月 29 日广康生化与芒果超媒案例", ""]
    cases = [summary["strategies"][0][key] for key in ("guangkang_20260929", "mango_20260929")]
    day_case = summary["strategies"][0]["case_day_20260929"]
    if all(case["available"] for case in cases):
        for case in cases:
            lines.append(f"{case['code']} {case['name']}当天当前候选：{'是' if case['formula_candidate'] else '否'}；"
                         f"评分 {fmt(case['factors'].get('score'), 4)}，全创业板候选排名 "
                         f"{fmt(case['factors'].get('候选排名'))}，进入每日前 2：{'是' if case['selected_top2'] else '否'}。")
        lines += ["广康生化代码为 300804；301513 为尚水智能，不能混用。", "",
                  "", "当日最终前 2：", "", "|代码|名称|评分|排名|", "|---|---|---:|---:|"]
        for pick in cases[0]["selected_that_day"]:
            lines.append(f"|{pick['code']}|{pick['name']}|{fmt(pick['score'], 4)}|{fmt(pick['rank'])}|")
        lines += ["", "当日原六项形态合格候选全部列出；新评分的滤板前分数单独列示，封板股不占排名名额。",
                  "", "|代码|名称|原评分|原排名|新评分(滤板前)|原始收盘|涨停价|收盘涨停|新排名|前2|",
                  "|---|---|---:|---:|---:|---:|---:|---|---:|---|"]
        for row in day_case["rows"]:
            lines.append(f"|{row['code']}|{row['name']}|{fmt(row['old_score'],4)}|{row['old_rank']}|"
                         f"{fmt(row['new_score_before_limit'],4)}|{fmt(row['raw_close'])}|{fmt(row['raw_limit_up'])}|"
                         f"{'是' if row['close_at_limit'] else '否'}|{fmt(row['new_rank'])}|"
                         f"{'是' if row['selected_top2'] else '否'}|")
        for case in cases:
            lines += ["", f"{case['name']}逐项因子：`{json.dumps(case['factors'], ensure_ascii=False)}`。"]
        lines += ["", "该权重按这两个已知案例校准；命中它们说明实现满足已声明的排序规则，"
                  "不能称作未知样本预测成功。统计分段和信号截断检查也不构成独立样本外验证。"]
    else:
        lines += ["当前输入未覆盖 9 月 29 日或芒果超媒，不能核实此案例。"]
    cov = summary["coverage"]
    lines += ["", "## 数据证据与实质限制", "",
              f"数据文件：`{summary['database']}`；来源库实际最大创业板日 K：{summary['range']['database_latest']}。",
              f"当前证券目录创业板 {cov['current_catalog']['codes']} 只；回测日每日原始行情覆盖 "
              f"{min(row['quote_codes'] for row in daily)} 至 {max(row['quote_codes'] for row in daily)} 只。",
              f"来源分布：`{json.dumps(cov['sources'], ensure_ascii=False)}`。",
              f"超额收益参考使用指数代码 `{summary['strategies'][0]['benchmark']['code']}`。"
              + ("本次采用沪深 300（000300），与创业板风格不同。" if
                 summary['strategies'][0]['benchmark']['code'] == "000300" else "")
              + ("本次源行情输入没有创业板指数（399006）。" if summary["missing_chinext_benchmark"] else "")
              + "超额仅作市场参考；核心胜率和盈亏比完全按策略净收益计算。",
              "receipt_id 字段存在不等于对应收据仍存在。上表单独列出实际可连接的收据和缺失收据行；"
              "源库部分历史收据已经清理，隔离导出保留实际剩余收据，未伪造补齐。缺失收据的历史行情"
              "仍按真实已落盘 OHLC 回放，但无法逐行完整追溯来源，因此不能声称严格 PIT 或完整回执审计通过。",
              "证券目录为当前快照，未提供历史名称/ST状态/完整退市成员，因此全期间使用当前名称过滤，有幸存者偏差和名称时间偏差。"
              "动态上市由每只股票当时可见的有效 K 线数限制，但不能据此宣称严格历史股票池。此处是真实行情的探索性回测，不能当作严格 PIT 或未来胜率保证。",
              "复权因子按行情仓现有回执使用，未独立重建现金分红/配股现金流；严格涨跌停采用系统创业板 20% 规则，策略新股有效 K 线门槛会排除上市初始无涨跌幅限制期。",
              "原始行情未做网络补全，不把缺失 OHLC/成交量填成可交易；仅基准序列允许向前填充。未核实历史行情对所有退市/暂停上市标的的完整性。",
              "策略由已知案例提出且此区间参与检视，未获得独立未来或锁定样本外绩效。固定多个窗口只用于稳健性观察，不作为历史择优后的生产默认。",
              "佣金和滑点为明确实验假设，未模拟最低佣金、过户费、实际成交深度和大资金冲击；每趟增加 5 bps 卖出费（兼容旧 10 bps 配置）会令每笔净收益与期望再减少 0.05 个百分点，接近零的交易可能改变胜负。",
              "", "## 复现", "", "```powershell", summary["command"], "```", "",
              "本目录保存 summary.json、coverage.csv，以及每策略信号 CSV 和四种口径的成交 CSV。"
              "summary.json 记录策略/引擎源码 SHA-256、执行输入 SHA-256、行情版本、全量配置、加载预热范围和基准覆盖。"
              "源数据库通过 mode=ro、query_only 打开并在单一读取事务中计算；脚本未写真实行情库或账本。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/market.db")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--benchmark", default="000300")
    parser.add_argument("--previous-summary", type=Path,
                        help="Frozen score-v1 summary for same-input comparison")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/research/2026-10-03-chinext-breakout-review")
    args = parser.parse_args()
    previous = json.loads(args.previous_summary.read_text(encoding="utf-8")) if args.previous_summary else None
    args.output.mkdir(parents=True, exist_ok=True)
    cfg = BacktestConfig(stamp_duty_bps=5, strict_limit_prices=True,
                         economic_returns=True, benchmark=args.benchmark)
    with ReadOnlyMarketStore(args.db) as store:
        latest = str(store.conn.execute(
            "SELECT MAX(trade_date) FROM quotes_daily WHERE code GLOB '30[0-9][0-9][0-9][0-9]'"
        ).fetchone()[0])
        end = min(args.end, latest)
        days = store.trading_days(start=args.start, end=end)
        if not days or (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days < 183:
            raise ValueError("回测数据必须实际覆盖至少六个月")
        cfg = replace(cfg, valuation_end=end)
        meta = {str(row[0]): str(row[1]) for row in store.conn.execute("SELECT key,value FROM meta")}
        summary = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                   "database": str(args.db.resolve()), "meta": meta,
                   "range": {"requested_start": args.start, "requested_end": args.end,
                             "actual_start": days[0], "actual_end": days[-1],
                             "database_latest": latest, "trading_days": len(days)},
                   "coverage": coverage(store, days[0], end), "strategies": [],
                   "missing_chinext_benchmark": store.conn.execute(
                       "SELECT 1 FROM quotes_daily WHERE code='399006' AND trade_date BETWEEN ? AND ? LIMIT 1",
                       (args.start, end)).fetchone() is None,
                   "command": ".\\.venv\\Scripts\\python.exe -X utf8 tools/strategy_chinext_review.py "
                   f'--db "{args.db.resolve()}" --start {args.start} --end {args.end} '
                   f'--benchmark {args.benchmark} --output "{args.output.resolve()}"'}
        if args.previous_summary:
            summary["command"] += f' --previous-summary "{args.previous_summary.resolve()}"'
            old = next(record for record in previous["strategies"] if record["slug"] == STRATEGIES[0])
            if old["revision"] != "builtin:contraction-rebreakout-v1:1" or previous["range"] != summary["range"]:
                raise ValueError("原评分比较必须是相同区间的 revision 1 冻结结果")
            summary["score_v1_comparison"] = {"path": str(args.previous_summary.resolve()),
                "summary_sha256": hashlib.sha256(args.previous_summary.read_bytes()).hexdigest(),
                "revision": old["revision"], "input_sha256": old["input_sha256"], "runs": old["runs"]}
        pd.DataFrame(summary["coverage"]["daily"]).to_csv(args.output / "coverage.csv", index=False)
        for slug in STRATEGIES:
            engine = get(slug)
            print(f"Preparing {slug}: {days[0]} .. {end}", flush=True)
            ctx = prepare_backtest_context(store, engine, start=args.start, end=end,
                                           universe=UNIVERSE, config=cfg, source_evidence_mode="compact")
            computed = engine.compute(ctx["panels"], ctx["resolved_params"])
            verification = verify_ranking(ctx, computed)
            signal_frame = selected_frame(ctx, computed)
            signal_frame.to_csv(args.output / f"{slug}-signals.csv", index=False)
            benchmark = ctx["benchmark_close"]
            record = {"slug": slug, "name": engine.name,
                      "revision": getattr(engine, "strategy_revision", ""),
                      "panel_columns": len(ctx["signals"].columns),
                      "signal_count": len(signal_frame),
                      "active_signal_days": int(ctx["signals"].any(axis=1).sum()),
                      "load_start": ctx["load_start"], "load_end": ctx["load_end"],
                      "input_sha256": input_digest(ctx), "source_sha256": code_digests(slug),
                      "verification": verification,
                      "benchmark": {"code": args.benchmark,
                                    "available": benchmark is not None,
                                    "valid_days": int(benchmark.notna().sum()) if benchmark is not None else 0,
                                    "load_days": len(ctx["signals"])},
                      "mango_20260929": stock_case(ctx, computed, signal_frame, "300413"),
                      "guangkang_20260929": stock_case(ctx, computed, signal_frame, "300804"),
                      "case_day_20260929": sept29_candidates(ctx, computed) if slug == STRATEGIES[0] else None,
                      "runs": {}}
            if slug == STRATEGIES[0] and previous and record["input_sha256"] != summary["score_v1_comparison"]["input_sha256"]:
                raise ValueError("新旧评分的冻结执行行情输入不一致，不能直接比较")
            scenarios = [("主口径", cfg), *[(f"固定{hold}日", replace(
                cfg, hold_days=hold - 1, stop_loss_pct=None, take_profit_pct=None)) for hold in (5, 10, 20)]]
            for label, scenario in scenarios:
                result = execute_backtest_context(store, {**ctx, "config": scenario}, use_fast=False)
                frame = result.to_frame()
                frame = frame.merge(signal_frame, on=["signal_date", "code"], how="left") if len(frame) else frame
                stem = "main" if label == "主口径" else f"fixed-{scenario.hold_days + 1}"
                frame.to_csv(args.output / f"{slug}-{stem}-trades.csv", index=False)
                if label == "主口径":
                    write_json(args.output / f"{slug}-main-api.json", {
                        "strategy": result.strategy_slug, "mode": "trade", "config": result.config,
                        "metrics": result.metrics, "performance": result.performance,
                        "skipped": result.skipped,
                        "trades": [{**t.to_dict(include_factors=True), "alpha_pct": t.alpha_pct}
                                   for t in result.trades],
                    })
                monthly = {str(month): table_metrics([t for t in result.trades if t.signal_date.startswith(str(month))])
                           for month in pd.period_range(days[0], end, freq="M")}
                phases = {"上段(1–5月)": table_metrics([t for t in result.trades if t.signal_date < "2026-06-01"]),
                          "下段(6月至截止)": table_metrics([t for t in result.trades if t.signal_date >= "2026-06-01"])}
                if len(result.trades) + sum(result.skipped.values()) != len(signal_frame):
                    raise AssertionError("Signal-to-trade/skip accounting mismatch")
                closed = [t for t in result.trades if t.exit_reason != "data_end"]
                winner_removed = list(closed)
                if winner_removed:
                    winner_removed.remove(max(winner_removed, key=lambda t: t.net_return_pct))
                removed_metrics = table_metrics(winner_removed)
                record["runs"][label] = {"metrics": table_metrics(result.trades),
                                         "skipped": result.skipped, "config": result.config,
                                         "worst_closed_trade": min(closed, key=lambda t: t.net_return_pct).to_dict(
                                             include_factors=True) if closed else None,
                                         "largest_winner_removed": {key: removed_metrics.get(key) for key in (
                                             "trades", "avg_net_return", "win_rate", "profit_factor", "payoff_ratio")},
                                         "by_signal_month": monthly, "phases": phases}
                compact = {key: record["runs"][label]["metrics"].get(key) for key in (
                    "trades", "win_rate", "payoff_ratio", "profit_factor", "avg_net_return", "data_end_trades")}
                print(f"{slug} {label}: {json.dumps(compact, ensure_ascii=False)}", flush=True)
            summary["strategies"].append(record)
            write_json(args.output / "summary.json", summary)
        (args.output / "report.md").write_text(render_report(summary), encoding="utf-8")
        print(f"Saved report: {args.output / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
