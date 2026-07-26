"""持仓诊断 + 三档情景观察规则引擎

输入: 价格 + 成本 + 指标 + 资金流
输出: 结构化诊断 + 三档情景观察 (含关键价位和风险暴露)

注意: 本模块基于历史数据的经验规则生成参考方案, 不构成投资建议.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def diagnose_position(
    cost: float, shares: int, kline: pd.DataFrame,
) -> dict[str, Any]:
    """持仓状态诊断

    返回: 包含浮盈亏、回本涨幅、成本位分位等的字典.
    """
    current = float(kline.iloc[-1]["收盘"])
    total_cost = cost * shares
    market_value = current * shares
    pnl = market_value - total_cost
    pnl_pct = (current / cost - 1) * 100
    need_up = (cost / current - 1) * 100

    # 成本在近 90 日区间的分位
    d90 = kline.tail(90)
    lo, hi = d90["最低"].min(), d90["最高"].max()
    cost_pct = (cost - lo) / (hi - lo) * 100 if hi > lo else 50.0

    # 深浅套等级
    if pnl_pct >= 0:
        level = "浮盈"
    elif pnl_pct >= -5:
        level = "浅套"
    elif pnl_pct >= -15:
        level = "中套"
    elif pnl_pct >= -30:
        level = "深套"
    else:
        level = "重度套牢"

    return {
        "current": current,
        "cost": cost,
        "shares": shares,
        "total_cost": total_cost,
        "market_value": market_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "need_up_pct": need_up,
        "cost_percentile_90d": cost_pct,
        "level": level,
    }


def classify_trend(kline: pd.DataFrame) -> dict[str, Any]:
    """趋势分类

    基于 MA5/MA10/MA20/MA60 和 MACD 的相对位置.
    返回: {'trend': 'uptrend'/'sideways'/'downtrend', 'strength': 'strong'/'weak',
           'macd_signal': 'golden'/'dead'/'neutral'}
    """
    last = kline.iloc[-1]
    close = last["收盘"]
    ma5, ma10, ma20, ma60 = last.get("MA5"), last.get("MA10"), last.get("MA20"), last.get("MA60")

    # MA 空头/多头排列
    if pd.notna(ma20) and pd.notna(ma60):
        if ma5 > ma10 > ma20 > ma60 and close > ma5:
            trend, strength = "uptrend", "strong"
        elif close > ma20 > ma60:
            trend, strength = "uptrend", "weak"
        elif ma5 < ma10 < ma20 < ma60:
            trend, strength = "downtrend", "strong"
        elif close < ma20 and close < ma60:
            trend, strength = "downtrend", "weak"
        else:
            trend, strength = "sideways", "weak"
    else:
        trend, strength = "sideways", "weak"

    # MACD 信号
    macd_hist = last.get("MACD")
    dif, dea = last.get("DIF"), last.get("DEA")
    if pd.notna(macd_hist) and pd.notna(dif) and pd.notna(dea):
        prev = kline.iloc[-2] if len(kline) >= 2 else None
        prev_hist = prev.get("MACD") if prev is not None else None
        if pd.notna(prev_hist):
            if prev_hist < 0 and macd_hist > 0:
                macd_signal = "golden"
            elif prev_hist > 0 and macd_hist < 0:
                macd_signal = "dead"
            elif macd_hist > 0:
                macd_signal = "above_zero"
            else:
                macd_signal = "below_zero"
        else:
            macd_signal = "above_zero" if macd_hist > 0 else "below_zero"
    else:
        macd_signal = "unknown"

    return {
        "trend": trend, "strength": strength,
        "macd_signal": macd_signal,
    }


def identify_key_levels(kline: pd.DataFrame, cost: float) -> dict[str, float]:
    """识别关键价位: 均线、近期高低、推荐止损、止盈位

    返回: dict 按价格高低排序, 前端渲染时可直接用.
    """
    last = kline.iloc[-1]
    current = float(last["收盘"])
    d30 = kline.tail(30)
    d60 = kline.tail(60)

    levels = {
        "current": current,
        "cost": cost,
        "MA5": float(last.get("MA5")) if pd.notna(last.get("MA5")) else None,
        "MA10": float(last.get("MA10")) if pd.notna(last.get("MA10")) else None,
        "MA20": float(last.get("MA20")) if pd.notna(last.get("MA20")) else None,
        "MA60": float(last.get("MA60")) if pd.notna(last.get("MA60")) else None,
        "BOLL_UP": float(last.get("BOLL_UP")) if pd.notna(last.get("BOLL_UP")) else None,
        "BOLL_DN": float(last.get("BOLL_DN")) if pd.notna(last.get("BOLL_DN")) else None,
        "d30_high": float(d30["最高"].max()),
        "d30_low": float(d30["最低"].min()),
        "d60_high": float(d60["最高"].max()),
        "d60_low": float(d60["最低"].min()),
    }

    # 推荐止损: MA20 下方 3% 或 现价下方 5%, 取较远者
    ma20 = levels["MA20"] or current
    stop_loss_a = ma20 * 0.97
    stop_loss_b = current * 0.93
    levels["recommend_stop_loss"] = round(min(stop_loss_a, stop_loss_b), 2)

    # 推荐止盈: 优先选近期高点、其次 BOLL 上轨
    tp_candidates = [v for v in [levels["d30_high"], levels["d60_high"], levels["BOLL_UP"]]
                     if v is not None and v > current]
    levels["recommend_take_profit"] = round(max(tp_candidates), 2) if tp_candidates else round(current * 1.1, 2)

    return levels


def analyze_fund_flow(fund_df: pd.DataFrame | None,
                      days: int = 5) -> dict[str, Any]:
    """资金流最近 days 日汇总 + 态势判断"""
    if fund_df is None or fund_df.empty:
        return {"available": False}
    df = fund_df.tail(days)
    main_sum = float(df["主力净流入-净额"].sum()) if "主力净流入-净额" in df else 0.0
    big_sum = float(df["超大单净流入-净额"].sum()) if "超大单净流入-净额" in df else 0.0
    small_sum = float(df["小单净流入-净额"].sum()) if "小单净流入-净额" in df else 0.0

    if main_sum > 5e8:
        stance = "强流入"
    elif main_sum > 0:
        stance = "温和流入"
    elif main_sum > -5e8:
        stance = "温和流出"
    else:
        stance = "大幅流出"

    # 主力出 vs 散户接的形态 (需要警惕)
    divergence = main_sum < 0 and small_sum > 0 and abs(small_sum) > abs(main_sum) * 0.5

    return {
        "available": True,
        "days": days,
        "main_sum": main_sum,
        "big_sum": big_sum,
        "small_sum": small_sum,
        "stance": stance,
        "divergence_warning": divergence,
    }


def generate_strategies(
    position: dict, levels: dict, trend: dict,
) -> list[dict[str, Any]]:
    """基于持仓状态+关键价位+趋势, 生成三档情景观察框架。"""
    cost = position["cost"]
    current = position["current"]
    shares = position["shares"]
    ma20 = levels.get("MA20") or current * 0.97
    d30_high = levels["d30_high"]
    d60_high = levels["d60_high"]
    stop_loss = levels["recommend_stop_loss"]

    strategies: list[dict[str, Any]] = []

    # ---------- 情景 A: 趋势延续 ----------
    recovery_watch = round(max(cost, current * 1.02), 2)
    strength_watch = round(max(d30_high, d60_high), 2)
    downside_exposure = (stop_loss - cost) * shares
    upside_reference = (strength_watch - cost) * shares
    strategies.append({
        "name": "A. 趋势延续情景",
        "suitable": "用于观察价格能否维持在关键均线之上，并逐步修复到成本区或近期高点。",
        "actions": [
            {"condition": "当前状态", "action": f"持仓暴露为 {shares} 股，需跟踪趋势、量能和公告变化"},
            {"condition": f"若跌破 {stop_loss:.2f} 元", "action": f"风险暴露可能扩大，按成本测算参考损益约 {downside_exposure:+.0f} 元"},
            {"condition": f"若修复至 {recovery_watch:.2f} 元附近", "action": "观察成本区抛压、成交量和资金流是否同步改善"},
            {"condition": f"若突破 {strength_watch:.2f} 元附近", "action": f"观察是否形成强势延续，按全仓测算参考损益约 {upside_reference:+.0f} 元"},
        ],
        "expected": {
            "worst": round(downside_exposure, 2),
            "mid": round((recovery_watch - cost) * shares, 2),
            "best": round(upside_reference, 2),
        },
    })

    # ---------- 情景 B: 震荡修复 ----------
    one_third = shares // 3
    two_thirds = shares - one_third
    current_reference = (current - cost) * shares
    strategies.append({
        "name": "B. 震荡修复情景",
        "suitable": "用于观察横盘、均线反复和成本区压力，重点是风险暴露与机会成本。",
        "actions": [
            {"condition": "若围绕现价震荡", "action": f"当前全仓参考损益约 {current_reference:+.0f} 元，需评估资金占用和机会成本"},
            {"condition": f"若跌破 {ma20:.2f} (MA20)", "action": "短中期结构可能转弱，需核验是否伴随放量和资金流出"},
            {"condition": f"若修复至 {recovery_watch:.2f} 附近", "action": "观察成本区压力是否释放，以及基本面信息是否支持继续修复"},
            {"condition": "若回落至 MA60 附近企稳", "action": "观察 3-5 个交易日的缩量、止跌和公告/行业数据，不做单一指标判断"},
        ],
        "expected": {
            "worst": round((stop_loss - cost) * shares, 2),
            "mid": round((current - cost) * two_thirds, 2),
            "best": round((recovery_watch - cost) * shares, 2),
        },
    })

    # ---------- 情景 C: 风险优先 ----------
    mark_to_market = (current - cost) * shares
    strategies.append({
        "name": "C. 风险优先情景",
        "suitable": "用于评估本金回撤承受力、流动性需求和趋势继续走弱时的压力测试。",
        "actions": [
            {"condition": "按当前价重估", "action": f"当前全仓参考损益为 {mark_to_market:+.0f} 元 / {position['pnl_pct']:+.2f}%"},
            {"condition": f"若继续跌至 {stop_loss:.2f} 元", "action": f"压力测试参考损益约 {(stop_loss - cost) * shares:+.0f} 元"},
            {"condition": "若存在短期用款或高集中度", "action": "需优先核验资金期限、组合集中度和可承受最大回撤"},
        ],
        "expected": {
            "worst": round((stop_loss - cost) * shares, 2),
            "mid": round(mark_to_market, 2),
            "best": round((current * 1.05 - cost) * shares, 2),
        },
    })

    return strategies


def recommend_scheme(position: dict, trend: dict, fund_stance: dict) -> str:
    """规则观察 (仅用于研究辅助, 不构成投资建议)"""
    level = position["level"]
    trend_type = trend["trend"]
    main_stance = fund_stance.get("stance", "未知")

    if level in ("重度套牢", "深套"):
        if trend_type == "downtrend":
            return "C 情景需重点压力测试（趋势走弱且回撤较深）"
        return "B 情景需重点观察（回撤较深但趋势未完全破坏）"
    if level == "中套":
        if trend_type == "downtrend":
            return "B/C 情景需重点观察（趋势疲弱，风险暴露偏高）"
        return "B 情景需重点观察（成本区修复与资金占用并存）"
    # 浅套/浮盈
    if trend_type == "uptrend":
        return "A 情景需重点观察（趋势偏强，仍需跟踪止损位与量能）"
    if trend_type == "sideways":
        return "B 情景需重点观察（震荡期，确认方向前风险收益不对称）"
    return "B/C 情景需重点观察（趋势偏弱，先核验风险承受力）"
