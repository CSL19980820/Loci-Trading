"""杨氏尾盘选股 V1：素材原文六条闸门 + 当日涨幅降序 Top1。

来源是用户资料里 `【股市百科全书】.doc` 段 1127–1132 的「9：尾盘选股法」整章，原文六条：

    1:流通股本小于20000万股  2:现价小于12元  3:涨幅大于1%  4:涨幅小于5%
    5:换手率大于2%  6:净资产收益率大于0.001%

**第 6 条未实现**——本仓行情库没有财务数据，`market.db` 只有 OHLCV 与股本换手。

## 为什么入场是 next_open 而不是 close

素材名字叫「尾盘选股法」，但把买入放在尾盘会亏钱。全市场 439 万样本实测：尾盘买相对次日
开盘买，每笔固定多付约 0.11pp，且该代价随信号「热度」放大（换手率最热十分位 −0.66%）。
同一条 T28 闸门，尾盘买版本在 2022 与 2026 两个弱市年为负，次开买版本六年零负年。
用户素材自己也是这个结论：冯国盛《独孤八式》6/6 把买点写在次日早盘，《一线定乾坤》原文
「尾盘先选好，第二天找低开平开的里面挑」。详见
`docs/research/2026-08-yule-materials-tail-close-feasibility.md`。

**所以「尾盘」在本战法里是选股时点，不是买入时点。**

## 排序因子怎么定的

闸门参数全部照抄素材原文，未调参。只搜索了执行维度：11 个排序因子 × 4 个 Top-N ×
2 个宽度闸门 × 2 个持有期 = 176 组，判据固定在事前（逐年零负年 + 前后两段皆正）。
**7 组通过，全部来自「当日涨幅降序」**，其余 10 个因子 0/16——集中度本身就是证据。
明细见 `docs/research/_scratch_yangshi_rank_portfolio.json`。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import REF, limit_ratio_panel, limit_up_flags, one_word_flags
from src.strategy.domain.base import SignalResult, merge_params, register

#: 市场上涨家数占比低于该阈值时整日空仓。网格实测：加这道闸门把 Top1 持 3 日的
#: 组合回撤从 -46.3% 压到 -32.6%，逐笔均净从 +0.5903% 升到 +0.6955%。
WEAK_BREADTH_SKIP = 0.40


def _once_schedule(hour: int, minute: int) -> dict[str, Any]:
    return {
        "mode": "once",
        "run_hour": hour,
        "run_minute": minute,
        "interval_minutes": 10,
        "window_start_hour": 9,
        "window_start_minute": 30,
        "window_end_hour": hour,
        "window_end_minute": minute,
    }


_YANGSHI_GATES = (
    "闸门：流通股本 < 2 亿股、未复权收盘价 < 12 元且 ≥ 3 元、"
    "当日涨幅 1% < pct < 5%、换手率 > 2%、成交额 ≥ 3000 万、"
    "当日未封涨停且非一字。原文第 6 条「净资产收益率 > 0.001%」因本仓无财务数据未实现。"
    "若当日市场上涨家数占比 < 40%，整日空仓；闸门前合格的 Top1 进入 watch_signals 观察，"
    "观察不进入回测也不生成次日预案。"
    "否则按当日涨幅降序取第一只。"
    "T+1 按开盘价买入（一字涨停买不进则跳过），持有 2 个交易日后于 T+3 收盘卖出；"
    "不设止损、不追高、不补仓，信号日收盘前不得使用次日数据。"
)


class YangshiTailPickerV1:
    """六条闸门过滤后按当日涨幅降序取第一只；极弱市空仓。"""

    slug = "yangshi-tail-v1"
    name = "杨氏尾盘选股（15:30）"
    description = (
        "V1：流通股本<2亿股 + 现价<12元 + 涨幅 1%~5% + 换手>2% 四条素材闸门，"
        "叠加成交额/价格/非封板可交易底线；上涨家数<40% 整日空仓，"
        "否则按当日涨幅降序取第一只；次日开盘买入，持有 2 日"
    )
    entry_instructions = (
        "T 日收盘后 15:30 执行（素材原文是尾盘选股：用已定型的收盘价选股，不在尾盘买入）。"
        + _YANGSHI_GATES
    )
    entry_timing = "next_open"
    execution_adjust = "none"
    requires_raw_limit_price = True
    requires_instrument_names = True
    screen_force_spot_refresh = False
    screen_top_n = 1
    screen_rank_factor = "当日涨幅(%)"
    # 回测器的 hold_days 从实际买入日计：T+1 买入、T+3 收盘卖出是 2 个持仓日。
    screen_hold_days = 2
    screen_stop_loss_pct = None
    strategy_revision = "builtin:yangshi-tail-v1"
    version = "v1"
    version_history = [{"version": "v1", "status": "active", "source": "builtin"}]
    backtest_metrics: dict[str, Any] | None = {
        # 全样本 5.6 年逐笔口径；组合层为每日一票、重叠持仓分 3 份资金串行连乘。
        "trades": 828,
        "win_rate": 48.309,
        "avg_net_return": 0.6955,
        "profit_factor": 1.371,
        "payoff_ratio": 1.467,
        "completed_trades": 828,
        "portfolio_return_pct": 328.4,
        "max_drawdown_pct": -32.6,
        "occupancy_pct": 60.97,
        "by_year_avg_net_return": {
            "2021": 0.770,
            "2022": 0.754,
            "2023": 0.314,
            "2024": 0.753,
            "2025": 0.748,
            "2026": 0.949,
        },
    }
    backtest_config = {
        "start": "2021-01-04",
        "end": "2026-08-11",
        "adjust": "qfq",
        "execution_adjust": "none",
        "hold_days": 2,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "commission_bps": 3.0,
        "stamp_duty_bps": 5.0,
        "slippage_bps": 10.0,
        "benchmark": None,
        "portfolio_model": "per_signal_day_equal_weight_one_slot",
        "portfolio_return_pct": 328.4,
        "max_drawdown_pct": -32.6,
        "occupancy_pct": 60.97,
        "completed_trades": 828,
        "signal_days": 828,
        "trading_days": 1358,
        "weak_breadth_skip": WEAK_BREADTH_SKIP,
        "screen_top_n": 1,
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        "research_script": "scripts/yangshi_tail_rank_portfolio_research.py",
        "research_doc": "docs/research/2026-08-yule-materials-tail-close-feasibility.md",
        "unimplemented_source_rule": "原文第6条 净资产收益率>0.001%（本仓无财务数据）",
        "live_clock": "15:30",
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}
    warmup_bars = 40

    def default_params(self) -> dict[str, Any]:
        return {
            "shares_max": 2e8,
            "price_max": 12.0,
            "price_min": 3.0,
            "pct_chg_min": 1.0,
            "pct_chg_max": 5.0,
            # 库内 turnover 是小数（中位数约 0.024），与素材的「2%」同量纲需除以 100。
            "turnover_min": 0.02,
            "amount_min": 30_000_000.0,
            "weak_breadth_skip": WEAK_BREADTH_SKIP,
            "top_n": 1,
        }

    def required_fields(self) -> tuple[str, ...]:
        return (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
            "outstanding_share",
        )

    def min_bars(self) -> int:
        # 只需前一根算涨幅；取 40 根是为了把上市不足约两个月的次新挡在外面，
        # 与回测研究里「上市满 60 自然日」的口径近似对齐。
        return 40

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, high, low = panels["close"], panels["high"], panels["low"]
        volume, amount = panels["volume"], panels["amount"]
        turnover = panels["turnover"].astype(float)
        shares = panels["outstanding_share"].astype(float)

        # 「现价 < 12 元」是绝对价格条件，必须用未复权价，否则前复权会让老票整体偏移。
        raw_close = panels.get("__raw_close")
        if not isinstance(raw_close, pd.DataFrame):
            raw_close = close
        else:
            raw_close = raw_close.reindex(index=close.index, columns=close.columns)

        previous_close = REF(close, 1)
        pct_chg = (close / previous_close - 1.0) * 100.0

        # ── 素材原文四条（第 6 条 ROE 本仓无数据，未实现）──
        small_float = shares.lt(float(p["shares_max"]))
        cheap = raw_close.lt(float(p["price_max"]))
        gain_band = pct_chg.gt(float(p["pct_chg_min"])) & pct_chg.lt(float(p["pct_chg_max"]))
        active = turnover.gt(float(p["turnover_min"]))
        source_gate = (small_float & cheap & gain_band & active).fillna(False)

        # ── 可交易底线：买得进、不是仙股、不是封板/一字 ──
        names = panels.get("__instrument_names__")
        ratios = limit_ratio_panel(raw_close, names if isinstance(names, dict) else None)
        # 只传未复权收盘价当 high，把共用谓词退化成「收盘价正好在涨停价」的精确判定，
        # 避免把前复权的 high 与未复权的 close 混在一个等式里比。同 qianlong 的处理。
        # 涨幅带已把 1%~5% 之外全挡掉，这两条实际是冗余防线，留着是为了口径显式。
        sealed = limit_up_flags(raw_close, raw_close, ratios, tolerance=1.0)
        one_word = one_word_flags(high, low)
        tradable = (
            volume.gt(0)
            & amount.ge(float(p["amount_min"]))
            & raw_close.ge(float(p["price_min"]))
            & ~sealed
            & ~one_word
        ).fillna(False)

        eligible = (source_gate & tradable).fillna(False)

        valid_close = close.notna() & previous_close.notna()
        advancing = (close > previous_close) & valid_close
        valid_count = valid_close.sum(axis=1)
        breadth = advancing.sum(axis=1).div(valid_count.where(valid_count > 0))
        breadth_panel = pd.DataFrame(
            {code: breadth for code in close.columns}, index=close.index
        )
        weak_skip = p.get("weak_breadth_skip")
        if weak_skip is None:
            market_ok = pd.DataFrame(True, index=close.index, columns=close.columns)
        else:
            market_ok = breadth_panel.ge(float(weak_skip)).fillna(False)

        # 排序因子：闸门已把涨幅锁在 1%~5%，降序取的是这个窄带里最靠上的那一只，
        # 不是全市场追涨。176 组网格里唯一能做到「逐年零负年 + 两段皆正」的排序。
        strength = pct_chg
        top_n = int(p.get("top_n") or 0)
        tradable_today = (eligible & market_ok).fillna(False)
        watch_pool = (eligible & ~market_ok).fillna(False)
        if top_n > 0:
            rank = strength.where(tradable_today).rank(
                axis=1, ascending=False, method="first"
            )
            selected = (tradable_today & rank.le(top_n)).fillna(False)
            watch_rank = strength.where(watch_pool).rank(
                axis=1, ascending=False, method="first"
            )
            watch_selected = (watch_pool & watch_rank.le(top_n)).fillna(False)
        else:
            selected = tradable_today
            watch_selected = watch_pool

        return SignalResult(
            signals=selected,
            watch_signals=watch_selected,
            factors={
                "流通股本(亿股)": shares / 1e8,
                "未复权收盘价": raw_close,
                "当日涨幅(%)": pct_chg,
                "换手率(%)": turnover * 100.0,
                "闸门_流通股本<2亿股": small_float,
                "闸门_现价<12元": cheap,
                "闸门_涨幅1%~5%": gain_band,
                "闸门_换手>2%": active,
                "素材四条闸门": source_gate,
                "可交易底线": tradable,
                "条件候选": eligible,
                "市场上涨家数占比": breadth_panel,
                "弱市可交易_上涨家数>=40%": market_ok,
                "每日前一": selected,
                "弱市低吸观察": watch_selected,
            },
        )


register(YangshiTailPickerV1())
