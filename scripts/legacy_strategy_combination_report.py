"""归档战法组合回测的稳健组合提取与 Markdown 报告。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from scripts.qianlong_v1_backtest_report import stats
from scripts.legacy_strategy_combination_common import (
    BOARD_ORDER,
    BREADTH_ORDER,
    COMBO_COLUMNS,
    GAP_COARSE_ORDER,
    GAP_ORDER,
    HOLDS,
    MARKET_DAY_ORDER,
    REGIME_ORDER,
    SIGNAL_RETURN_ORDER,
    STRATEGIES,
    TURNOVER_ORDER,
)


def robust_combinations(combinations: pd.DataFrame, min_n: int) -> pd.DataFrame:
    key_columns = ["strategy", "strategy_name", *COMBO_COLUMNS]
    eligible = combinations[combinations["n"] >= min_n]
    rows: list[dict[str, Any]] = []
    for key, group in eligible.groupby(key_columns, dropna=False):
        if set(group["hold_days"]) != set(HOLDS):
            continue
        row = dict(zip(key_columns, key))
        for hold in HOLDS:
            item = group[group["hold_days"] == hold].iloc[0]
            row[f"n_h{hold}"] = int(item["n"])
            row[f"win_rate_h{hold}"] = float(item["win_rate"])
            row[f"avg_net_h{hold}"] = float(item["avg_net_return_pct"])
            row[f"profit_factor_h{hold}"] = item["profit_factor"]
        win_rates = [row[f"win_rate_h{hold}"] for hold in HOLDS]
        returns = [row[f"avg_net_h{hold}"] for hold in HOLDS]
        row["min_win_rate"] = round(min(win_rates), 2)
        row["avg_win_rate"] = round(float(np.mean(win_rates)), 2)
        row["min_avg_net_return_pct"] = round(min(returns), 4)
        row["avg_net_return_pct"] = round(float(np.mean(returns)), 4)
        row["positive_net_all_holds"] = all(value > 0 for value in returns)
        row["win_rate_over_50_all_holds"] = all(value > 50 for value in win_rates)
        rows.append(row)
    return pd.DataFrame(rows)


def _table(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    if frame.empty:
        return "（无样本）"
    return frame.loc[:, list(columns)].to_markdown(index=False)


def render_report(
    *, output_dir: Path, config: dict[str, Any], events: pd.DataFrame,
    factors: pd.DataFrame, combinations: pd.DataFrame, robust: pd.DataFrame,
) -> Path:
    overall_rows: list[dict[str, Any]] = []
    for spec in STRATEGIES.values():
        subset = events[events["strategy"] == spec.key]
        for hold in HOLDS:
            overall_rows.append(
                {"strategy": spec.name, "hold_days": hold, **stats(subset[subset["hold_days"] == hold])}
            )
    overall = pd.DataFrame(overall_rows)
    lines = [
        "# 海底捞月、筹码峰突破、三外有三老版本多条件组合回测", "",
        "> 这是历史数据统计，不是当前买卖指令。细组合优先看样本数、净收益和 1/3/5 日是否同向。", "",
        "## 回测口径", "",
        f"- 行情库：`{config['db']}`；复权：`{config['adjust']}`；信号区间：`{config['signal_start']} ~ {config['signal_end']}`。",
        f"- 数据快照：`quotes_last_date={config['data_snapshot'].get('quotes_last_date', '-')}`；`market_revision={config['data_snapshot'].get('market_revision', '-')}`；`quotes_revision={config['data_snapshot'].get('quotes_revision', '-')}`。",
        "- 策略：`lugaowen-legacy.py` 中归档的海底捞月、筹码峰突破、三外有三；T 日收盘后出信号，T+1 开盘买入。",
        f"- 成本：往返 `{config['cost_pct']:.2f}%`（26bp）；不设止损止盈，胜率按净收益 `> 0` 计算。",
        "- A 股 T+1：`1/3/5` 表示买入后第 1/3/5 个可卖交易日收盘退出；买入日开收收益单独保留在逐笔 CSV，不作为可执行胜率。",
        "- 次日缺开盘、停牌或一字板不可成交的信号不进入胜率分母；完整组合 CSV 保留空组合。",
        "- 换手率按仓内小数口径：`0.05 = 5%`。大盘环境按沪深 300 `000300` 的 20 日收益与收盘是否站上 MA20 划分；另计算上涨家数比例。", "",
        "## 覆盖与总览", "",
        f"- 股票池：主板 + 创业板，剔除当前 `ST/退市/停牌`，上市不足 `{config['min_list_days']}` 日的标的；当前代码数 `{config['stock_codes']}`。",
        f"- 完整矩阵：每个战法 `{len(BOARD_ORDER) * len(TURNOVER_ORDER) * len(REGIME_ORDER) * len(GAP_ORDER)}` 组 × `{len(HOLDS)}` 个持有期；本次共 `{len(combinations)}` 行。", "",
        _table(overall, ["strategy", "hold_days", "n", "wins_net", "win_rate", "gross_win_rate", "avg_net_return_pct", "profit_factor", "avg_alpha_pct"]), "",
        "字段说明：`win_rate` 是扣成本后的胜率；`avg_net_return_pct` 是单笔净收益均值；`avg_alpha_pct` 是相对沪深 300 同期收益的净超额。", "",
        "## 单因子切片", "",
    ]
    factor_specs = [
        ("板块", "board"), ("换手率", "turnover_band"), ("大盘环境", "market_regime"),
        ("上涨家数", "breadth_band"), ("次日开盘方向", "gap_coarse"),
        ("次日开盘细档", "gap_band"), ("信号日涨幅", "signal_return_band"),
        ("大盘当日涨跌", "market_day_band"),
    ]
    factor_columns = ["strategy", "hold_days", "condition", "n", "win_rate", "avg_net_return_pct", "median_net_return_pct", "profit_factor", "avg_alpha_pct"]
    for title, key in factor_specs:
        lines.extend([f"### {title}", "", _table(factors[factors["factor"] == key], factor_columns), ""])

    combo_columns = ["strategy_name", "hold_days", *COMBO_COLUMNS, "n", "wins_net", "win_rate", "avg_net_return_pct", "median_net_return_pct", "profit_factor", "avg_alpha_pct"]
    lines.extend(["## 完整四维组合", "", f"完整维度为：`战法 × 板块 × 换手率 × 大盘环境 × 次日开盘细档`。下面展示每个战法、每个持有期样本数不少于 `{config['display_combo_n']}` 的高低组合；全部组合见 `legacy-strategy-combinations.csv`。", ""])
    for spec in STRATEGIES.values():
        lines.extend([f"### {spec.name}", ""])
        subset = combinations[combinations["strategy"] == spec.key]
        for hold in HOLDS:
            eligible = subset[(subset["hold_days"] == hold) & (subset["n"] >= config["display_combo_n"])]
            top = eligible.sort_values(["win_rate", "avg_net_return_pct", "n"], ascending=[False, False, False]).head(15)
            bottom = eligible.sort_values(["win_rate", "avg_net_return_pct", "n"], ascending=[True, True, False]).head(10)
            lines.extend([
                f"#### 持有 {hold} 个可卖交易日：高胜率组合", "", _table(top, combo_columns), "",
                f"#### 持有 {hold} 个可卖交易日：低胜率组合", "", _table(bottom, combo_columns), "",
            ])

    robust_columns = ["strategy_name", *COMBO_COLUMNS, "n_h1", "win_rate_h1", "avg_net_h1", "n_h3", "win_rate_h3", "avg_net_h3", "n_h5", "win_rate_h5", "avg_net_h5", "min_win_rate", "avg_win_rate", "min_avg_net_return_pct", "avg_net_return_pct", "positive_net_all_holds", "win_rate_over_50_all_holds"]
    robust_display = robust.sort_values(["positive_net_all_holds", "win_rate_over_50_all_holds", "min_win_rate", "avg_net_return_pct"], ascending=[False, False, False, False]).head(40) if not robust.empty else robust
    lines.extend([
        "## 三个持有期都可比较的组合", "",
        f"以下只保留每个持有期样本数都不少于 `{config['min_combo_n']}` 的组合，再按 1/3/5 日共同表现排序；完整结果见 `legacy-strategy-robust-combinations.csv`。", "",
        _table(robust_display, robust_columns) if not robust_display.empty else "（没有满足样本阈值的组合）", "",
        "## 使用边界", "",
        "- 不要只按最高胜率的一行下结论；组合越细，样本越小，优先看 `n`、平均净收益、profit factor 以及 1/3/5 日是否同向。",
        "- 高开样本可能包含强势股选择效应，低开样本可能包含盘中反转效应；逐笔 CSV 可核对具体代码和日期。",
        "- 股票池使用当前行情库标的列表，存在当前存活标的偏差；没有把历史退市股票补回股票池。", "",
        "## 产物", "",
        "- `legacy-strategy-combinations.csv`：三战法全部 300 组 × 3 持有期组合。",
        "- `legacy-strategy-events.csv`：每个可成交信号的逐笔 1/3/5 日结果。",
        "- `legacy-strategy-factor-slices.csv`：单因子切片。",
        "- `legacy-strategy-robust-combinations.csv`：三个持有期都达到样本阈值的组合。",
        "- `legacy-strategy-config.json`：数据快照、参数、信号与不可成交计数。", "",
    ])
    report = output_dir / "legacy-strategy-combination-report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
