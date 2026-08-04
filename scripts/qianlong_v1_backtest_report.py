"""潜龙组合回测的统计、组合展开与报告渲染。"""
from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

HOLDS = (1, 3, 5)
BOARD_ORDER = ("主板", "创业板")
TURNOVER_ORDER = ("<2%", "2-5%", "5-8%", "8-12%", "12-20%", ">=20%")
REGIME_ORDER = ("强牛", "偏强", "震荡", "偏弱", "弱熊")
GAP_ORDER = ("低开>=3%", "低开1-3%", "平开±1%", "高开1-3%", "高开>=3%")
GAP_COARSE_ORDER = ("低开", "平开", "高开")
BREADTH_ORDER = ("弱势<40%", "中性40-60%", "强势>=60%")
SIGNAL_RETURN_ORDER = ("<1%", "1-3%", ">=3%")
MARKET_DAY_ORDER = ("<=-1%", "-1%~1%", ">=1%")
COMBO_COLUMNS = ("board", "turnover_band", "market_regime", "gap_band")


def stats(frame: pd.DataFrame) -> dict[str, Any]:
    empty = {
        "n": 0, "wins_net": 0, "win_rate": None, "gross_win_rate": None,
        "avg_net_return_pct": None, "median_net_return_pct": None,
        "p10_net_return_pct": None, "p90_net_return_pct": None,
        "profit_factor": None, "avg_alpha_pct": None, "avg_mfe_pct": None,
        "avg_mae_pct": None,
    }
    if frame.empty:
        return empty
    net = frame["net_return_pct"].astype(float).to_numpy()
    gross = frame["gross_return_pct"].astype(float).to_numpy()
    wins = net > 0
    positives = net[net > 0].sum()
    negatives = net[net < 0].sum()
    factor = None if negatives == 0 else positives / abs(negatives)
    return {
        "n": int(len(frame)), "wins_net": int(wins.sum()),
        "win_rate": round(float(wins.mean() * 100), 2),
        "gross_win_rate": round(float((gross > 0).mean() * 100), 2),
        "avg_net_return_pct": round(float(net.mean()), 4),
        "median_net_return_pct": round(float(np.median(net)), 4),
        "p10_net_return_pct": round(float(np.percentile(net, 10)), 4),
        "p90_net_return_pct": round(float(np.percentile(net, 90)), 4),
        "profit_factor": None if factor is None else round(float(factor), 3),
        "avg_alpha_pct": round(float(frame["alpha_pct"].mean()), 4),
        "avg_mfe_pct": round(float(frame["mfe_pct"].mean()), 4),
        "avg_mae_pct": round(float(frame["mae_pct"].mean()), 4),
    }


def factor_table(events: pd.DataFrame, column: str, order: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for hold in HOLDS:
        subset = events[events["hold_days"] == hold]
        for value in order:
            rows.append({"hold_days": hold, "condition": value,
                         **stats(subset[subset[column] == value])})
    return pd.DataFrame(rows)


def combination_table(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for hold in HOLDS:
        subset = events[events["hold_days"] == hold]
        groups = {tuple(key): value for key, value in subset.groupby(
            list(COMBO_COLUMNS), dropna=False
        )}
        for values in product(BOARD_ORDER, TURNOVER_ORDER, REGIME_ORDER, GAP_ORDER):
            group = groups.get(values, subset.iloc[0:0])
            rows.append({"hold_days": hold, **dict(zip(COMBO_COLUMNS, values)), **stats(group)})
    return pd.DataFrame(rows)


def _table(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    if frame.empty:
        return "（无样本）"
    return frame.loc[:, list(columns)].to_markdown(index=False)


def render_report(
    *, output_dir: Path, config: dict[str, Any], events: pd.DataFrame,
    factors: dict[str, pd.DataFrame], combinations: pd.DataFrame,
) -> Path:
    overall = pd.DataFrame([
        {"hold_days": hold, **stats(events[events["hold_days"] == hold])}
        for hold in HOLDS
    ])
    lines = [
        "# 潜龙老版本多条件组合回测", "",
        "> 这是历史数据统计，不是当前买卖指令。组合越细，样本越容易变小；优先看样本数、净收益和不同持有期是否一致。",
        "", "## 回测口径", "",
        f"- 行情库快照：`{config['db']}`；复权：`{config['adjust']}`；信号区间：`{config['signal_start']} ~ {config['signal_end']}`。",
        f"- 数据版本：`market_revision={config['data_snapshot'].get('market_revision', '-')}`；行情行版本：`quotes_revision={config['data_snapshot'].get('quotes_revision', '-')}`。",
        "- 策略：归档的潜龙老版本 `QianlongCloseePicker`，T 日收盘后出信号，T+1 开盘买入。",
        f"- 成本：往返 `{config['cost_pct']:.2f}%`（26bp）；不设止损止盈，净胜率按净收益 `> 0` 计算。",
        "- A 股 T+1：`1/3/5` 表示买入后第 `1/3/5` 个可卖交易日收盘退出；次日买入日的开收收益另保留在逐笔明细中。",
        "- 次日不可买入样本（停牌、缺开盘、一字板）不进入胜率分母；组合表保留全部理论组合，空组合的 `n=0`。",
        "- 换手率按仓内小数口径：`0.05 = 5%`。大盘环境以沪深 300 `000300` 的 20 日收益与收盘是否站上 MA20 划分，另有上涨家数比例切片。",
        "", "## 覆盖与总览", "",
        f"- 股票池：主板 + 创业板，剔除当前 `ST/退市/停牌`，上市不足 `{config['min_list_days']}` 日的标的；当前代码数 `{config['stock_codes']}`。",
        f"- 原始信号 `{config['signals_total']}` 个；次日可按开盘成交 `{config['buyable_signals']}` 个；不可成交 `{config['unbuyable_signals']}` 个。",
        f"- 可成交但至少有一个退出结果 `{config['events_with_results']}` 个；完全没有退出收盘价 `{config['no_exit_signals']}` 个；只有部分持有期可结算 `{config['partial_exit_signals']}` 个；完整 H5 `{config['complete_h5_signals']}` 个。",
        f"- 可成交信号中缺换手率 `{config['missing_turnover_signals']}` 个；这些记录不会进入换手率分档，但仍保留在总览。",
        "",
        _table(overall, ["hold_days", "n", "wins_net", "win_rate", "gross_win_rate",
                        "avg_net_return_pct", "profit_factor", "avg_alpha_pct"]),
        "", "字段说明：`win_rate` 是扣成本后的胜率；`avg_net_return_pct` 是单笔净收益均值；`avg_alpha_pct` 是相对沪深 300 同期收益的净超额。",
        "", "## 单因子切片", "",
    ]
    factor_specs = [
        ("板块", factors["board"]), ("换手率", factors["turnover_band"]),
        ("大盘环境", factors["market_regime"]), ("上涨家数", factors["breadth_band"]),
        ("次日开盘方向", factors["gap_coarse"]), ("次日开盘细档", factors["gap_band"]),
        ("信号日涨幅", factors["signal_return_band"]), ("大盘当日涨跌", factors["market_day_band"]),
    ]
    factor_columns = ["hold_days", "condition", "n", "win_rate", "avg_net_return_pct",
                      "median_net_return_pct", "profit_factor", "avg_alpha_pct"]
    for title, table in factor_specs:
        lines.extend([f"### {title}", "", _table(table, factor_columns), ""])

    lines.extend([
        "## 完整四维组合", "",
        "完整组合维度为：`板块 × 换手率 × 大盘环境 × 次日开盘细档`。下面只展示每个持有期样本数不少于 30 的前 20 组和后 10 组；全部 300 组 × 3 个持有期见 `qianlong-v1-combinations.csv`。",
        "",
    ])
    combo_columns = ["hold_days", *COMBO_COLUMNS, "n", "wins_net", "win_rate",
                     "avg_net_return_pct", "median_net_return_pct", "profit_factor", "avg_alpha_pct"]
    for hold in HOLDS:
        eligible = combinations[(combinations["hold_days"] == hold) & (combinations["n"] >= 30)]
        top = eligible.sort_values(["win_rate", "avg_net_return_pct", "n"],
                                   ascending=[False, False, False]).head(20)
        bottom = eligible.sort_values(["win_rate", "avg_net_return_pct", "n"],
                                      ascending=[True, True, False]).head(10)
        lines.extend([
            f"### 持有 {hold} 个可卖交易日：高胜率组合", "",
            _table(top, combo_columns) if not top.empty else "（没有样本数 >= 30 的组合）", "",
            f"### 持有 {hold} 个可卖交易日：低胜率组合", "",
            _table(bottom, combo_columns) if not bottom.empty else "（没有样本数 >= 30 的组合）", "",
        ])
    lines.extend([
        "## 使用建议", "",
        "- 不要只按胜率最高的一行下结论；`n` 小于 30 的组合只作为观察，优先检查 1/3/5 日方向是否同向。",
        "- 高开样本可能天然包含强势股的选择效应，低开样本也可能混入限价/停牌边界；逐笔 CSV 可核对具体代码和日期。",
        "- 本报告使用当前行情库标的列表，存在当前存活标的偏差；没有把历史退市股票补回股票池。",
        "", "## 产物", "",
        "- `qianlong-v1-combinations.csv`：全部组合（含 `n=0`）。",
        "- `qianlong-v1-events.csv`：每个可成交信号的 1/3/5 日逐笔结果。",
        "- `qianlong-v1-config.json`：数据快照、参数与不可成交计数。", "",
    ])
    report = output_dir / "qianlong-v1-combination-report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
