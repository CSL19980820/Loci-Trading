"""Render existing system-account equity; never rerun a strategy or account.

Run from the repo: .venv/Scripts/python.exe docs/research/assets/plot_impulse_tail_fixed10_account.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2026-09-11")
YEAR = pd.Timestamp("2026-01-01")
HALF = pd.Timestamp("2026-07-01")
COLORS = {"0.003": "#1766A7", "0.006": "#C17B28"}
INK = "#172B43"
MUTED = "#62738A"


def read_book(directory: Path, cost: str) -> tuple[pd.DataFrame, dict]:
    csv_path = directory / f"system_account_{cost}_daily.csv"
    json_path = directory / f"system_account_{cost}.json"
    frame = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
    metadata = json.loads(json_path.read_text(encoding="utf8"))["metrics"]
    frame = frame.loc[START:END].copy()
    if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Account dates must be unique and ordered")
    if not np.isfinite(frame.equity).all() or (frame.equity <= 0).any():
        raise ValueError("Account equity must be finite and positive")
    initial = float(metadata["initial_capital"])
    if initial != 200_000 or frame.index[-1] != END:
        raise ValueError("Unexpected account capital or observation endpoint")
    peak = frame.equity.cummax().clip(lower=initial)
    frame["drawdown_pct"] = (frame.equity / peak - 1) * 100
    final = float(frame.equity.iloc[-1])
    total = (final / initial - 1) * 100
    worst = float(frame.drawdown_pct.min())
    if abs(final - float(metadata["final_equity"])) > .0001:
        raise ValueError("CSV and JSON ending equity disagree")
    if abs(total - float(metadata["return_pct"])) > .0001:
        raise ValueError("CSV and JSON return disagree")
    if abs(worst - float(metadata["max_drawdown_pct"])) > .0001:
        raise ValueError("CSV and JSON maximum drawdown disagree")
    before_h2 = frame.loc[frame.index < HALF, "equity"].iloc[-1]
    summary = {
        "round_trip_cost": float(cost), "initial_capital": initial,
        "first_observation": frame.index[0].date().isoformat(),
        "last_observation": frame.index[-1].date().isoformat(), "observations": len(frame),
        "final_equity": final, "return_pct": total, "max_drawdown_pct": worst,
        "max_drawdown_date": frame.drawdown_pct.idxmin().date().isoformat(),
        "historical_peak_equity": float(peak.iloc[-1]),
        "historical_peak_date": frame.equity.idxmax().date().isoformat(),
        "ending_drawdown_pct": float(frame.drawdown_pct.iloc[-1]),
        "continuous_account_h2_return_pct": (final / float(before_h2) - 1) * 100,
        "closed_trades": int(metadata["closed_trades"]),
        "ending_open_positions": int(frame.open_positions.iloc[-1]),
        "source_sha256": {
            csv_path.name: hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            json_path.name: hashlib.sha256(json_path.read_bytes()).hexdigest(),
        },
    }
    return frame, summary


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor("white")
    for edge in ("top", "right"):
        ax.spines[edge].set_visible(False)
    for edge in ("left", "bottom"):
        ax.spines[edge].set_color("#D7DFE9")
    ax.tick_params(colors=MUTED, labelsize=11, length=0, pad=8)
    ax.grid(axis="y", color="#E9EDF3", linewidth=.8)
    ax.set_axisbelow(True)
    ax.axvspan(YEAR, HALF, color="#EEF3FA", alpha=.42, linewidth=0, zorder=0)
    ax.axvspan(HALF, END, color="#FFF0DD", alpha=.64, linewidth=0, zorder=0)
    ax.axvline(YEAR, color="#8596AA", linewidth=1, linestyle=(0, (4, 4)), zorder=1)
    ax.axvline(HALF, color="#CDA879", linewidth=.9, linestyle=(0, (3, 4)), zorder=1)
    ax.set_xlim(START, END + pd.Timedelta(days=38))


def render(directory: Path, destination: Path) -> dict:
    font = fm.findfont(fm.FontProperties(family="Microsoft YaHei"), fallback_to_default=False)
    plt.rcParams.update({
        "font.family": fm.FontProperties(fname=font).get_name(),
        "axes.unicode_minus": False, "svg.fonttype": "path",
        "svg.hashsalt": "impulse-tail-fixed10-account", "font.size": 11,
    })
    books = {cost: read_book(directory, cost) for cost in COLORS}
    fig = plt.figure(figsize=(15.8, 10.6), facecolor="#F7F9FC")
    fig.text(.075, .958, "十日持有｜系统账户历史回放", fontsize=25, weight="bold", color=INK)
    fig.text(.075, .919, "2025-01-01 至 2026-09-11   ·   初始20万元   ·   5仓 / 100股整手", fontsize=12.5, color=MUTED)
    fig.text(.075, .883, "证据范围：系统引擎历史回放，不代表线上完整研究流程已验收。", fontsize=11.5, color="#775B30")

    for i, (cost, (_, stats)) in enumerate(books.items()):
        x = .075 + i * .44
        card = FancyBboxPatch((x, .768), .41, .093, boxstyle="round,pad=0.006,rounding_size=0.009",
                             transform=fig.transFigure, facecolor="white", edgecolor="#DCE4EE", linewidth=.8)
        fig.add_artist(card)
        color = COLORS[cost]
        fig.text(x + .016, .835, f"往返成本 {float(cost)*100:.1f}%", fontsize=11.5, color=color, weight="bold")
        fig.text(x + .015, .791, f"+{stats['return_pct']:.2f}%", fontsize=25, color=color, weight="bold")
        fig.text(x + .174, .823, f"期末资金  {stats['final_equity']/10000:.2f} 万元", fontsize=13.5, color=INK)
        fig.text(x + .174, .790, f"最大回撤 {abs(stats['max_drawdown_pct']):.2f}%", fontsize=10.5, color=MUTED)

    equity_ax = fig.add_axes([.075, .391, .85, .31])
    dd_ax = fig.add_axes([.075, .147, .85, .174], sharex=equity_ax)
    style_axis(equity_ax)
    style_axis(dd_ax)
    fig.text(.075, .728, "日收盘账户权益 / 万元", fontsize=13, weight="bold", color=INK)
    fig.text(.075, .349, "相对各自历史高点的回撤", fontsize=13, weight="bold", color=INK)
    for cost, (frame, stats) in books.items():
        color = COLORS[cost]
        dash = "-" if cost == "0.003" else (0, (5, 2.5))
        equity_ax.plot(frame.index, frame.equity / 10000, color=color, linewidth=2.25,
                       linestyle=dash, label=f"往返成本 {float(cost)*100:.1f}%")
        equity_ax.scatter([END], [stats["final_equity"]/10000], s=22, color=color, zorder=5)
        equity_ax.annotate(f"{stats['final_equity']/10000:.2f}万", xy=(END, stats["final_equity"]/10000),
                           xytext=(8, 0), textcoords="offset points", va="center", fontsize=11.5,
                           color=color, weight="bold")
        dd_ax.plot(frame.index, frame.drawdown_pct, color=color, linewidth=1.65, linestyle=dash)
        dd_ax.scatter([END], [stats["ending_drawdown_pct"]], s=18, color=color, zorder=5)
        offset = -18 if cost == "0.003" else 15
        dd_ax.annotate(f"{stats['ending_drawdown_pct']:.2f}%", xy=(END, stats["ending_drawdown_pct"]),
                       xytext=(9, offset), textcoords="offset points", fontsize=10.5, color=color,
                       va="center", weight="bold", arrowprops={"arrowstyle":"-", "color":color, "lw":.8})

    main_frame, main = books["0.003"]
    dd_ax.fill_between(main_frame.index, main_frame.drawdown_pct, 0, color=COLORS["0.003"], alpha=.055)
    equity_ax.axhline(20, color="#B0BAC8", linewidth=.8, linestyle=(0, (2, 3)))
    equity_ax.set_ylim(18.5, 38)
    equity_ax.set_yticks([20, 25, 30, 35])
    equity_ax.legend(loc="upper right", bbox_to_anchor=(1, 1.135), ncol=2, frameon=False,
                     fontsize=11, handlelength=3, columnspacing=2)
    equity_ax.tick_params(labelbottom=False)
    equity_ax.annotate("2026年分界", xy=(YEAR, .97), xycoords=("data", "axes fraction"),
                       xytext=(7, 0), textcoords="offset points", color=MUTED, fontsize=10.5, va="top")
    equity_ax.annotate("2026下半年", xy=(pd.Timestamp("2026-07-10"), .97),
                       xycoords=("data", "axes fraction"), color="#946E3A", fontsize=10.5, va="top")
    peak_day = pd.Timestamp(main["historical_peak_date"])
    equity_ax.annotate(f"{peak_day.month}/{peak_day.day} 高点 {main['historical_peak_equity']/10000:.2f}万",
                       xy=(peak_day, main["historical_peak_equity"]/10000), xytext=(-125, 28),
                       textcoords="offset points", color=INK, fontsize=10.5,
                       bbox={"boxstyle":"round,pad=.3", "facecolor":"white", "edgecolor":"#DCE4EE"},
                       arrowprops={"arrowstyle":"-", "color":"#8B9BAF", "lw":.8})
    dd_ax.axhline(0, color="#BBC6D3", linewidth=.9)
    dd_ax.set_ylim(-13.5, .6)
    dd_ax.set_yticks([0, -3, -6, -9, -12])
    dd_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    ticks = pd.to_datetime(["2025-01-01","2025-04-01","2025-07-01","2025-10-01",
                            "2026-01-01","2026-04-01","2026-07-01","2026-09-11"])
    dd_ax.set_xticks(ticks)
    dd_ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    labels = [value.strftime("%Y-%m") for value in ticks]
    labels[-1] = "09-11"
    dd_ax.set_xticklabels(labels)
    worst = pd.Timestamp(main["max_drawdown_date"])
    dd_ax.annotate(f"全期最大回撤\n{worst.date().isoformat()}", xy=(worst, main["max_drawdown_pct"]),
                   xytext=(-104, 29), textcoords="offset points", fontsize=10, color=MUTED,
                   bbox={"boxstyle":"round,pad=.25", "facecolor":"white", "edgecolor":"#DCE4EE"},
                   arrowprops={"arrowstyle":"-", "color":"#8B9BAF", "lw":.8})

    pressure = books["0.006"][1]
    peak_label = f"各自{peak_day.month}月{peak_day.day}日" if pressure["historical_peak_date"] == main["historical_peak_date"] else "各自"
    fig.text(.075, .081, f"近期回撤｜{END.month}月{END.day}日距{peak_label}历史高点：主成本 {main['ending_drawdown_pct']:.2f}%  /  压力成本 {pressure['ending_drawdown_pct']:.2f}%", fontsize=11.5, color=INK, weight="bold")
    fig.text(.075, .045, "口径：次日开盘入场，持有10个交易日（买入日算第1日）；逐日收盘盯市，回撤不按半年重置。", fontsize=10.4, color=MUTED)
    fig.text(.075, .020, "来源：已保存的系统账户账册；412个交易日。仅使用实际权益及由其计算的回撤，不采用旧资金利用率指标。", fontsize=9.5, color=MUTED)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination.with_suffix(".png"), dpi=180, facecolor=fig.get_facecolor())
    fig.savefig(destination.with_suffix(".svg"), facecolor=fig.get_facecolor(), metadata={"Date":None})
    plt.close(fig)
    report = {"data_kind":"saved_system_engine_historical_replay", "online_full_research_accepted":False,
              "display_range":[START.date().isoformat(), END.date().isoformat()],
              "accounts":{cost:stats for cost,(_,stats) in books.items()},
              "outputs":[str(destination.with_suffix(suffix)) for suffix in (".png",".svg")]}
    destination.with_suffix(".metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPO/".local"/"profit-optimization-20260912")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("impulse-tail-fixed10-account"))
    args = parser.parse_args()
    print(json.dumps(render(args.data_dir, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
