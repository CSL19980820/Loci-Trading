"""大阳三日缩量突破：用户提供的五根 K 线形态与未涨停过滤。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.formula import ABS, BARSCOUNT, HHV, LLV, MA, REF, ZTPRICE
from src.market import classify_board, is_st_name
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult, StrategyError, merge_params, register


DAILY_PICK_LIMIT = 2
BREAKOUT_VOLUME_SATURATION = 3.0
CHINEXT_PREFIXES = ("300", "301")


def _ranked_result(
    candidates: pd.DataFrame, factors: dict[str, pd.DataFrame], *,
    close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame,
    volume: pd.DataFrame, prior_volume: pd.DataFrame,
) -> SignalResult:
    """原形态合格股的规则评分；只在同日完整股票范围内取前二。"""
    anchor_range = REF(high, 4) - REF(low, 4)
    inside_range = REF(HHV(high, 3), 1) - REF(LLV(low, 3), 1)
    anchor_volume = REF(volume, 4)
    day_range = high - low
    components = {
        "整理收敛分(30)": (1 - inside_range / anchor_range.where(anchor_range.gt(0))).clip(0, 1) * 30,
        "三日缩量分(25)": (1 - prior_volume / anchor_volume.where(anchor_volume.gt(0))).clip(0, 1) * 25,
        "突破放量分(25)": ((factors["突破量比"] - 1) / (BREAKOUT_VOLUME_SATURATION - 1)).clip(0, 1) * 25,
        "收盘位置分(20)": ((close - low) / day_range.where(day_range.gt(0))).clip(0, 1) * 20,
    }
    # 使用与展示相同的四位总分裁决；无效分数不占名额，不把缺失值当成零分。
    score = sum(components.values()).where(candidates & np.isfinite(factors["突破量比"]))
    score = score.where(np.isfinite(score)).clip(0, 100).round(4)
    rank = score.reindex(columns=sorted(score.columns)).rank(
        axis=1, ascending=False, method="first",
    ).reindex(columns=score.columns)
    selected = (candidates & rank.le(DAILY_PICK_LIMIT)).fillna(False).astype(bool)
    return SignalResult(
        signals=selected,
        factors={"score": score, **components, "候选排名": rank,
                 "条件候选": candidates, "每日前二": selected, **factors},
    )


class ImpulseInsideBreakoutV1:
    slug = "impulse-inside-breakout-v1"
    name = "大阳三日缩量突破"
    description = (
        "仅创业板（300/301）非 ST、非退市股，至少 180 根有效日 K；"
        "大阳线后连续三日高低点内包、实体收缩且均量下降，再阳线放量突破大阳线高点；"
        "未复权收盘价须至少低于涨停价 2 分钱；合格股按形态评分每日最多选前 2 只。"
    )
    entry_instructions = (
        "以收盘后完整日 K 确认信号。第 T-4 日阳线实体大于此前 20 日平均实体，"
        "且收盘高于当日 20 日均线；T-3 至 T-1 三日的最高价严格低于大阳线高点、"
        "最低价严格高于其低点、各日实体严格小于大阳线实体，三日均量低于大阳线成交量。"
        "T 日收阳、收盘突破大阳线高点，成交量大于前三日均量。"
        "只保留创业板 300/301、名称非空且不含 ST/退的股票；要求当日及前日成交量为正，"
        "当日未复权高低价在涨跌停范围内，收盘至少距涨停 0.02 元。"
        "形态默认使用前复权日 K，涨跌停一律使用未复权 OHLC；可手动选择不复权。"
        "合格股按 0–100 分形态评分降序，每日最多选前 2 只，不足两只不补足；同分按代码升序。"
        "整理收敛 30 分=30×(1−三日高低范围/大阳线高低范围)；"
        "三日缩量 25 分=25×(1−三日均量/大阳线成交量)；"
        "突破放量 25 分=25×(突破量比−1)/2，量比达到 3 倍封顶；"
        "收盘位置 20 分=20×(收盘−最低)/(最高−最低)。各项按 0 至满分截断，"
        "总分保留四位；评分表示规则匹配程度，不代表胜率或预期收益。"
        "盘中结果是未完成日 K 的预览，须收盘后确认。"
        "本指标只生成选股信号，未设持有期、止盈止损或业绩假设；回测按用户设置执行，"
        "最早在次日开盘入场。"
    )
    entry_timing = "next_open"
    adjust = "qfq"
    execution_adjust = "none"
    requires_raw_limit_price = True
    requires_raw_limit_ohlc = True
    requires_instrument_names = True
    source_evidence_summary = True
    screen_managed_job = False
    screen_top_n = DAILY_PICK_LIMIT
    screen_rank_factor = "score"
    strategy_revision = "builtin:impulse-inside-breakout-v1:3"
    version = "v1.2"
    version_history = [
        {"version": "v1", "status": "archived", "source": "builtin:impulse-inside-breakout-v1:1"},
        {"version": "v1.1", "status": "archived", "source": "builtin:impulse-inside-breakout-v1:2"},
        {"version": "v1.2", "status": "active", "source": "builtin"},
    ]
    default_universe = {"preset": "default_a_share", "boards": ["chi_next"]}
    # 每日滑动窗口的起点与 qfq 锚点不同，未来区间预计算不能替代实际每日输入。
    # 2026-10-03 核验的历史复盘快照；只用于展示和回测模板，不改变选股计算。
    backtest_metrics = {'trades': 118,
     'win_rate': 44.07,
     'avg_net_return': 0.6322,
     'payoff_ratio': 1.558,
     'profit_factor': 1.228,
     'avg_win': 7.7303,
     'avg_loss': -4.9602}
    backtest_config = {'hold_days': 3,
     'stop_loss_pct': -6.0,
     'take_profit_pct': None,
     'commission_bps': 3.0,
     'stamp_duty_bps': 5,
     'slippage_bps': 5.0,
     'benchmark': '000300',
     'strict_limit_prices': True,
     'economic_returns': True,
     'valuation_end': '2026-09-30',
     'mode': 'trade',
     'start': '2026-01-01',
     'end': '2026-09-30',
     'universe': {'preset': 'default_a_share', 'boards': ['chi_next'], 'min_list_days': 0},
     'hold_days_convention': '入场后经过3个交易日，即入场第4日收盘；先触及止损则提前退出',
     'review_note': '2026年1至9月真实行情探索性回测；每日全池评分前2，已平仓统计；当前证券目录存在历史成员偏差，未做独立样本外验证'}

    range_prime_enabled = False

    def default_params(self) -> dict[str, Any]:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 180

    def execution_profile(self, params: dict[str, Any] | None = None) -> ExecutionProfile:
        merge_params(self, params)
        # BARSCOUNT 因子依赖实际加载起点，不能按有限窗口截断后复用。
        return ExecutionProfile(
            pure=True, causal=True, column_mode="coupled", origin="sensitive",
            metadata_fields=("__raw_open", "__raw_high", "__raw_low", "__raw_close",
                             "__instrument_names__"),
        )

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None,
    ) -> SignalResult:
        merge_params(self, params)
        close, open_ = panels["close"], panels["open"]
        high, low, volume = panels["high"], panels["low"], panels["volume"]
        raw: dict[str, pd.DataFrame] = {}
        for field in ("open", "high", "low", "close"):
            panel = panels.get(f"__raw_{field}")
            if not isinstance(panel, pd.DataFrame):
                raise StrategyError("大阳三日缩量突破需要未复权 OHLC，不能用复权价格判断涨跌停")
            raw[field] = panel.reindex(index=close.index, columns=close.columns)
        names = panels.get("__instrument_names__")
        if not isinstance(names, dict):
            raise StrategyError("大阳三日缩量突破需要证券名称，不能跳过 ST/退市过滤")

        boards = pd.Series({code: classify_board(str(code)) for code in close.columns})
        # 股票池是计算约束，显式 codes 或混合板块输入也不能绕过创业板范围。
        pool = pd.Series({
            code: len(str(code)) == 6 and str(code).isascii() and str(code).isdigit()
            and str(code).startswith(CHINEXT_PREFIXES)
            for code in close.columns
        })
        clean = pd.Series({
            code: bool(str(names.get(str(code)) or "").strip())
            and not is_st_name(str(names.get(str(code)) or ""))
            and "退" not in str(names.get(str(code)) or "")
            for code in close.columns
        })
        ratios = pd.DataFrame(
            np.broadcast_to(np.where(boards.eq("chi_next"), 0.20, 0.10), close.shape),
            index=close.index, columns=close.columns,
        )
        previous_close = REF(raw["close"], 1)
        limit_up = ZTPRICE(previous_close, ratios)
        # DTPRICE 与涨停价采用相同的逢五进一到分规则。
        limit_down = ZTPRICE(previous_close, -ratios)
        close_cents = np.floor(raw["close"] * 100 + 0.5 + 1e-9)
        limit_cents = np.floor(limit_up * 100 + 0.5 + 1e-9)
        below_limit = close_cents.le(limit_cents - 2)
        bars = BARSCOUNT(close.where(np.isfinite(close) & close.gt(0)))
        valid = (
            np.isfinite(close) & np.isfinite(open_) & np.isfinite(high) & np.isfinite(low)
            & np.isfinite(volume) & volume.ge(0) & close.gt(0) & open_.gt(0) & low.gt(0)
            & high.ge(close) & high.ge(open_) & low.le(close) & low.le(open_)
            & np.isfinite(raw["close"]) & np.isfinite(raw["open"])
            & np.isfinite(raw["high"]) & np.isfinite(raw["low"])
            & raw["close"].gt(0) & raw["open"].gt(0) & raw["low"].gt(0)
            & raw["high"].ge(raw["close"]) & raw["high"].ge(raw["open"])
            & raw["low"].le(raw["close"]) & raw["low"].le(raw["open"])
        ).rolling(5).sum().eq(5)
        base = (
            valid & pool & clean & bars.ge(180) & volume.gt(0) & REF(volume, 1).gt(0)
            & previous_close.gt(0) & raw["high"].le(limit_up + 0.001)
            & raw["low"].ge(limit_down - 0.001) & below_limit
        )

        body = ABS(close - open_)
        impulse = close.gt(open_) & body.gt(REF(MA(body, 20), 1)) & close.gt(MA(close, 20))
        inside = REF(HHV(high, 3), 1).lt(REF(high, 4)) & REF(LLV(low, 3), 1).gt(REF(low, 4))
        small_body = REF(HHV(body, 3), 1).lt(REF(body, 4))
        prior_volume = REF(MA(volume, 3), 1)
        contraction = prior_volume.lt(REF(volume, 4))
        breakout = close.gt(REF(high, 4)) & close.gt(open_) & volume.gt(prior_volume)
        pattern = REF(impulse, 4).fillna(False).astype(bool) & inside & small_body & contraction & breakout
        return _ranked_result(
            (base & pattern).fillna(False).astype(bool),
            factors={
                "基础过滤": base,
                "大阳线成立": REF(impulse, 4).fillna(False).astype(bool),
                "三日高低点内包": inside,
                "三日实体收缩": small_body,
                "三日缩量": contraction,
                "阳线放量突破": breakout,
                "距涨停至少2分钱": below_limit,
                "有效日K根数": bars,
                "大阳线高点": REF(high, 4),
                "突破幅度(%)": (close / REF(high, 4) - 1) * 100,
                "突破量比": volume / prior_volume.where(prior_volume.gt(0)),
                "未复权收盘价": raw["close"],
                "涨停价": limit_up,
                "跌停价": limit_down,
                "距涨停(元)": limit_up - raw["close"],
            },
            close=close, high=high, low=low, volume=volume, prior_volume=prior_volume,
        )

    def compute_projection(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None,
        dates: list[str],
    ) -> SignalResult:
        """保留完整均线/计数起点，其余五根形态只计算请求日期所需的上下文。"""
        from src.strategy.application.compute_runtime import project_result

        merge_params(self, params)
        full_close, full_open = panels["close"], panels["open"]
        requested = list(dict.fromkeys(day for day in dates if day in full_close.index))
        if not requested or not full_close.index.is_unique:
            return project_result(self.compute(panels, params), requested)
        positions = full_close.index.get_indexer(requested)
        context = slice(max(0, int(positions.min()) - 4), int(positions.max()) + 1)
        close, open_ = full_close.iloc[context], full_open.iloc[context]
        high, low = panels["high"].iloc[context], panels["low"].iloc[context]
        volume = panels["volume"].iloc[context]
        raw: dict[str, pd.DataFrame] = {}
        for field in ("open", "high", "low", "close"):
            panel = panels.get(f"__raw_{field}")
            if not isinstance(panel, pd.DataFrame):
                raise StrategyError("大阳三日缩量突破需要未复权 OHLC，不能用复权价格判断涨跌停")
            raw[field] = panel.reindex(index=close.index, columns=close.columns)
        names = panels.get("__instrument_names__")
        if not isinstance(names, dict):
            raise StrategyError("大阳三日缩量突破需要证券名称，不能跳过 ST/退市过滤")

        # pandas 滚动均值使用补偿求和；从较短窗口重起算可能改变严格阈值的信号。
        # 每条均线和 BARSCOUNT 都先保留原始输入起点，再复制小上下文释放全量结果。
        full_body = ABS(full_close - full_open)
        previous_body_mean = REF(MA(full_body, 20), 1).iloc[context].copy()
        body = full_body.iloc[context].copy()
        del full_body
        close_mean = MA(full_close, 20).iloc[context].copy()
        prior_volume = REF(MA(panels["volume"], 3), 1).iloc[context].copy()
        bars = BARSCOUNT(full_close.where(np.isfinite(full_close) & full_close.gt(0))).iloc[context].copy()

        boards = pd.Series({code: classify_board(str(code)) for code in close.columns})
        pool = pd.Series({
            code: len(str(code)) == 6 and str(code).isascii() and str(code).isdigit()
            and str(code).startswith(CHINEXT_PREFIXES)
            for code in close.columns
        })
        clean = pd.Series({
            code: bool(str(names.get(str(code)) or "").strip())
            and not is_st_name(str(names.get(str(code)) or ""))
            and "退" not in str(names.get(str(code)) or "")
            for code in close.columns
        })
        ratios = pd.DataFrame(
            np.broadcast_to(np.where(boards.eq("chi_next"), 0.20, 0.10), close.shape),
            index=close.index, columns=close.columns,
        )
        previous_close = REF(raw["close"], 1)
        limit_up = ZTPRICE(previous_close, ratios)
        limit_down = ZTPRICE(previous_close, -ratios)
        close_cents = np.floor(raw["close"] * 100 + 0.5 + 1e-9)
        limit_cents = np.floor(limit_up * 100 + 0.5 + 1e-9)
        below_limit = close_cents.le(limit_cents - 2)
        valid = (
            np.isfinite(close) & np.isfinite(open_) & np.isfinite(high) & np.isfinite(low)
            & np.isfinite(volume) & volume.ge(0) & close.gt(0) & open_.gt(0) & low.gt(0)
            & high.ge(close) & high.ge(open_) & low.le(close) & low.le(open_)
            & np.isfinite(raw["close"]) & np.isfinite(raw["open"])
            & np.isfinite(raw["high"]) & np.isfinite(raw["low"])
            & raw["close"].gt(0) & raw["open"].gt(0) & raw["low"].gt(0)
            & raw["high"].ge(raw["close"]) & raw["high"].ge(raw["open"])
            & raw["low"].le(raw["close"]) & raw["low"].le(raw["open"])
        ).rolling(5).sum().eq(5)
        base = (
            valid & pool & clean & bars.ge(180) & volume.gt(0) & REF(volume, 1).gt(0)
            & previous_close.gt(0) & raw["high"].le(limit_up + 0.001)
            & raw["low"].ge(limit_down - 0.001) & below_limit
        )
        impulse = close.gt(open_) & body.gt(previous_body_mean) & close.gt(close_mean)
        inside = REF(HHV(high, 3), 1).lt(REF(high, 4)) & REF(LLV(low, 3), 1).gt(REF(low, 4))
        small_body = REF(HHV(body, 3), 1).lt(REF(body, 4))
        contraction = prior_volume.lt(REF(volume, 4))
        breakout = close.gt(REF(high, 4)) & close.gt(open_) & volume.gt(prior_volume)
        anchor_impulse = REF(impulse, 4).fillna(False).astype(bool)
        result = _ranked_result(
            (base & anchor_impulse & inside & small_body & contraction & breakout).fillna(False).astype(bool),
            factors={
                "基础过滤": base,
                "大阳线成立": anchor_impulse,
                "三日高低点内包": inside,
                "三日实体收缩": small_body,
                "三日缩量": contraction,
                "阳线放量突破": breakout,
                "距涨停至少2分钱": below_limit,
                "有效日K根数": bars,
                "大阳线高点": REF(high, 4),
                "突破幅度(%)": (close / REF(high, 4) - 1) * 100,
                "突破量比": volume / prior_volume.where(prior_volume.gt(0)),
                "未复权收盘价": raw["close"],
                "涨停价": limit_up,
                "跌停价": limit_down,
                "距涨停(元)": limit_up - raw["close"],
            },
            close=close, high=high, low=low, volume=volume, prior_volume=prior_volume,
        )
        return project_result(result, requested)


register(ImpulseInsideBreakoutV1())
