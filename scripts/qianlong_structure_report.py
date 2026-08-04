"""潜龙结构回测报告渲染（收益率优先）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from scripts.qianlong_v1_backtest_report import factor_table as _factor_table
from scripts.qianlong_v1_backtest_report import stats as _stats
from scripts.qianlong_v1_combination_backtest import (
    BOARD_ORDER,
    BREADTH_ORDER,
    GAP_COARSE_ORDER,
    GAP_ORDER,
    HOLDS,
    MARKET_DAY_ORDER,
    REGIME_ORDER,
    SIGNAL_RETURN_ORDER,
    TURNOVER_ORDER,
)

MIN_N = 30
FOCUS_HOLD = 3
VERSIONS = ("v1", "v2", "v3")

def _md_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "（无样本）"
    return frame.loc[:, columns].to_markdown(index=False)


def _rank_slice(
    events: pd.DataFrame, column: str, order: tuple[str, ...], hold: int
) -> pd.DataFrame:
    table = _factor_table(events, column, order)
    subset = table[table["hold_days"] == hold].copy()
    subset = subset[subset["n"] > 0]
    return subset.sort_values(
        ["avg_net_return_pct", "profit_factor", "n"],
        ascending=[False, False, False],
        na_position="last",
    )


def _practical_filter(events: pd.DataFrame, hold: int) -> pd.DataFrame:
    """V3 说明书口径：跳过 ≥3% 跳空，只保留低开1-3% / 平开 / 高开1-3%。"""
    keep = {"低开1-3%", "平开±1%", "高开1-3%"}
    return events[
        (events["hold_days"] == hold) & (events["gap_band"].isin(keep))
    ]


def render_report(
    *,
    output_path: Path,
    config: dict[str, Any],
    by_version: dict[str, dict[str, Any]],
) -> Path:
    hold = FOCUS_HOLD
    lines = [
        "# 潜龙出海 v1 / v2 / v3 结构回测（收益率优先）",
        "",
        "> 历史统计，不是买卖指令。主排序看 **平均净收益率** 与 **盈亏比(PF)**，"
        "不看胜率。样本 `n < 30` 的结构仅作观察。",
        "",
        "## 回测口径",
        "",
        f"- 行情库：`{config['db']}`；复权：`{config['adjust']}`；"
        f"信号区间：`{config['signal_start']} ~ {config['signal_end']}`。",
        f"- 数据版本：`market_revision={config['data_snapshot'].get('market_revision', '-')}`；"
        f"`quotes_revision={config['data_snapshot'].get('quotes_revision', '-')}`。",
        "- 入场：T 日收盘出信号，T+1 开盘买入（与三版 `next_open` 一致）。",
        f"- 成本：往返 `{config['cost_pct']:.2f}%`；不设止损止盈。",
        f"- 主观察持有期：买入后第 **{hold}** 个可卖交易日收盘退出（与 UI 默认一致）。",
        "- 版本定义：",
        "  - **v1**：归档 `QianlongCloseePicker`（死叉回看 20、价≥6）",
        "  - **v2**：归档 `QianlongCloseePickerV2`（死叉回看 15、价≥8）",
        "  - **v3**：内置 `qianlong-close-v3`（v2 核心 + 换手 2%–8% + 非涨停价）",
        "- 维度映射：「有仓/活跃度」→ 上涨家数比例；「形态」→ 信号日涨幅档；"
        "另含换手率、次日开盘、板块、大盘环境。",
        "",
        "## 一、三版总览（按平均净收益率）",
        "",
    ]
    overview_rows = []
    for version in VERSIONS:
        payload = by_version[version]
        events = payload["events"]
        summary = payload["summary"]
        for h in HOLDS:
            st = _stats(events[events["hold_days"] == h])
            overview_rows.append(
                {
                    "version": version,
                    "hold_days": h,
                    "n": st["n"],
                    "avg_net_return_pct": st["avg_net_return_pct"],
                    "median_net_return_pct": st["median_net_return_pct"],
                    "profit_factor": st["profit_factor"],
                    "signals_total": summary["signals_total"],
                    "buyable": summary["buyable_signals"],
                }
            )
    overview = pd.DataFrame(overview_rows)
    focus = overview[overview["hold_days"] == hold].sort_values(
        ["avg_net_return_pct", "profit_factor"],
        ascending=[False, False],
        na_position="last",
    )
    lines.extend(
        [
            _md_table(
                focus,
                [
                    "version",
                    "hold_days",
                    "n",
                    "avg_net_return_pct",
                    "median_net_return_pct",
                    "profit_factor",
                    "signals_total",
                    "buyable",
                ],
            ),
            "",
            "全部持有期：",
            "",
            _md_table(
                overview,
                [
                    "version",
                    "hold_days",
                    "n",
                    "avg_net_return_pct",
                    "median_net_return_pct",
                    "profit_factor",
                ],
            ),
            "",
            "## 二、单因子收益率排名（持有 3 日）",
            "",
        ]
    )

    factor_specs = [
        ("换手率", "turnover_band", TURNOVER_ORDER),
        ("次日开盘细档", "gap_band", GAP_ORDER),
        ("次日开盘方向", "gap_coarse", GAP_COARSE_ORDER),
        ("形态（信号日涨幅）", "signal_return_band", SIGNAL_RETURN_ORDER),
        ("有仓/活跃度（上涨家数）", "breadth_band", BREADTH_ORDER),
        ("板块", "board", BOARD_ORDER),
        ("大盘环境", "market_regime", REGIME_ORDER),
        ("大盘当日涨跌", "market_day_band", MARKET_DAY_ORDER),
    ]
    for title, column, order in factor_specs:
        lines.extend([f"### {title}", ""])
        for version in VERSIONS:
            ranked = _rank_slice(by_version[version]["events"], column, order, hold)
            ranked.insert(0, "version", version)
            cols = [
                "version",
                "condition",
                "n",
                "avg_net_return_pct",
                "median_net_return_pct",
                "profit_factor",
            ]
            lines.extend([f"**{version}**", "", _md_table(ranked, cols), ""])

    lines.extend(
        [
            "## 三、关键结构交叉（收益率优先，n≥30）",
            "",
            "交叉：`换手率 × 次日开盘细档 × 上涨家数`，主持有期 3 日。",
            "",
        ]
    )
    cross_rows: list[dict[str, Any]] = []
    for version in VERSIONS:
        subset = by_version[version]["events"]
        subset = subset[subset["hold_days"] == hold]
        if subset.empty:
            continue
        grouped = subset.groupby(
            ["turnover_band", "gap_band", "breadth_band"], dropna=False
        )
        for key, group in grouped:
            st = _stats(group)
            if st["n"] < MIN_N:
                continue
            cross_rows.append(
                {
                    "version": version,
                    "turnover_band": key[0],
                    "gap_band": key[1],
                    "breadth_band": key[2],
                    **{
                        k: st[k]
                        for k in (
                            "n",
                            "avg_net_return_pct",
                            "median_net_return_pct",
                            "profit_factor",
                        )
                    },
                }
            )
    cross = pd.DataFrame(cross_rows)
    if cross.empty:
        lines.append("（没有 n≥30 的交叉组合）")
        lines.append("")
    else:
        top = cross.sort_values(
            ["avg_net_return_pct", "profit_factor", "n"],
            ascending=[False, False, False],
        ).head(25)
        lines.extend(
            [
                _md_table(
                    top,
                    [
                        "version",
                        "turnover_band",
                        "gap_band",
                        "breadth_band",
                        "n",
                        "avg_net_return_pct",
                        "median_net_return_pct",
                        "profit_factor",
                    ],
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## 四、执行过滤器模拟（跳过 ≥3% 跳空）",
            "",
            "按 V3 说明书：高开/低开 ≥3% 跳过，只统计低开1-3% / 平开±1% / 高开1-3%。",
            "",
        ]
    )
    filter_rows = []
    for version in VERSIONS:
        filtered = _practical_filter(by_version[version]["events"], hold)
        st = _stats(filtered)
        filter_rows.append({"version": version, "hold_days": hold, **st})
    filter_df = pd.DataFrame(filter_rows).sort_values(
        ["avg_net_return_pct", "profit_factor"],
        ascending=[False, False],
        na_position="last",
    )
    lines.extend(
        [
            _md_table(
                filter_df,
                [
                    "version",
                    "n",
                    "avg_net_return_pct",
                    "median_net_return_pct",
                    "profit_factor",
                ],
            ),
            "",
            "## 五、结论（可行性最高结构）",
            "",
        ]
    )

    # Evidence-based conclusion from focus overview + top cross + gap preference.
    best_version = str(focus.iloc[0]["version"]) if not focus.empty else "—"
    best_ret = focus.iloc[0]["avg_net_return_pct"] if not focus.empty else None
    best_pf = focus.iloc[0]["profit_factor"] if not focus.empty else None

    gap_notes = []
    for version in VERSIONS:
        gap_ranked = _rank_slice(
            by_version[version]["events"], "gap_band", GAP_ORDER, hold
        )
        if not gap_ranked.empty:
            top_gap = gap_ranked.iloc[0]
            gap_notes.append(
                f"- {version} 次日开盘最优档：`{top_gap['condition']}` "
                f"（n={top_gap['n']}, 净收益={top_gap['avg_net_return_pct']}, "
                f"PF={top_gap['profit_factor']}）"
            )

    turn_notes = []
    for version in VERSIONS:
        turn_ranked = _rank_slice(
            by_version[version]["events"], "turnover_band", TURNOVER_ORDER, hold
        )
        if not turn_ranked.empty:
            top_t = turn_ranked.iloc[0]
            turn_notes.append(
                f"- {version} 换手最优档：`{top_t['condition']}` "
                f"（n={top_t['n']}, 净收益={top_t['avg_net_return_pct']}, "
                f"PF={top_t['profit_factor']}）"
            )

    if not cross.empty:
        best_cross = cross.sort_values(
            ["avg_net_return_pct", "profit_factor", "n"],
            ascending=[False, False, False],
        ).iloc[0]
        cross_line = (
            f"交叉最优（n≥30）：**{best_cross['version']}** × "
            f"换手`{best_cross['turnover_band']}` × "
            f"开盘`{best_cross['gap_band']}` × "
            f"活跃度`{best_cross['breadth_band']}` → "
            f"净收益 {best_cross['avg_net_return_pct']} / PF {best_cross['profit_factor']} "
            f"（n={best_cross['n']}）"
        )
    else:
        cross_line = "交叉最优：样本不足"

    lines.extend(
        [
            f"1. **版本层面**（持有 {hold} 日、全样本开盘买入）："
            f"**{best_version}** 平均净收益率最高"
            f"（{best_ret}% / PF {best_pf}）。",
            "2. **开盘结构**（收益率口径）：",
            *gap_notes,
            "3. **换手结构**：",
            *turn_notes,
            f"4. {cross_line}",
            "5. **可执行建议**：优先采用收益率与样本同时站得住的结构——"
            "过滤极端跳空、偏好市场活跃（上涨家数偏强）、换手不过冷；"
            "版本上以总览排名靠前且过滤后仍稳定的一版为主。",
            "",
            "## 产物",
            "",
            f"- 本报告：`{output_path.as_posix()}`",
            f"- 明细目录：`{config['output_dir']}`（各版 events CSV / config JSON）",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


