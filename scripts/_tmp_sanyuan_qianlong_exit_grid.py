"""三源 vs 潜龙：卖出规则网格（持有 × 止盈 × 止损），验证「高抛」是否可兑现。

与 ``_tmp_sanyuan_qianlong_exit_compare.py`` 同口径：2026 YTD、逐笔、T+1 开盘买入。
止损档含各策略声明值（三源无、潜龙 -7%），止盈档模拟触价高抛。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import BacktestConfig  # noqa: E402
from src.backtest.application.runner import (  # noqa: E402
    execute_backtest_context,
    prepare_backtest_context,
)
from src.market import MarketStore  # noqa: E402

STRATEGIES = {"sanyuan-tail-v1": "三源", "qianlong-close-v3": "潜龙"}
HOLDS = (1, 2)
TARGETS: tuple[float | None, ...] = (None, 3.0, 5.0, 8.0)
STOPS: tuple[float | None, ...] = (None, -7.0)
START = "2026-01-01"


def main() -> int:
    store = MarketStore()
    end = store.trading_days()[-(1 + max(HOLDS) + 1)]
    print(f"信号区间 {START} ~ {end}  逐笔口径  T+1 开盘买入\n")
    header = (
        f"{'战法':<6}{'卖出':<10}{'止盈':>6}{'止损':>7}"
        f"{'笔数':>6}{'胜率':>8}{'净均值':>9}{'累计':>10}{'盈亏比':>8}{'超额':>8}"
    )

    for slug, label in STRATEGIES.items():
        ctx = prepare_backtest_context(
            store, slug, start=START, end=end,
            config=BacktestConfig(hold_days=max(HOLDS), stop_loss_pct=None),
        )
        print(header)
        print("-" * 78)
        for hold in HOLDS:
            for target in TARGETS:
                for stop in STOPS:
                    run_ctx = dict(ctx)
                    run_ctx["config"] = BacktestConfig(
                        hold_days=hold,
                        stop_loss_pct=stop,
                        take_profit_pct=target,
                        benchmark="000300",
                    )
                    m = execute_backtest_context(store, run_ctx).metrics
                    if not m.get("trades"):
                        continue
                    print(
                        f"{label:<6}{f'T+{hold + 1} 收盘':<10}"
                        f"{('%.0f%%' % target) if target else '—':>6}"
                        f"{('%.0f%%' % stop) if stop else '—':>7}"
                        f"{m['trades']:>6}{m['win_rate']:>7.1f}%"
                        f"{m['avg_net_return']:>+8.2f}%{m['total_net_return']:>+9.1f}%"
                        f"{(m['profit_factor'] or 0):>8.3f}"
                        f"{m.get('avg_alpha', 0):>+7.2f}%"
                    )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
