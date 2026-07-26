"""技术指标 + 量化分析模块

纯函数设计: 输入 DataFrame 或数值, 返回同类型, 无副作用.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def add_ma(df: pd.DataFrame, periods: tuple[int, ...] = (5, 10, 20, 60),
           col: str = "收盘") -> pd.DataFrame:
    """添加 MA 均线到 df, 原地修改并返回"""
    for p in periods:
        df[f"MA{p}"] = df[col].rolling(p).mean()
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
             signal: int = 9, col: str = "收盘") -> pd.DataFrame:
    """添加 MACD (DIF / DEA / MACD柱)"""
    exp_fast = df[col].ewm(span=fast, adjust=False).mean()
    exp_slow = df[col].ewm(span=slow, adjust=False).mean()
    df["DIF"] = exp_fast - exp_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD"] = 2 * (df["DIF"] - df["DEA"])
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "收盘") -> pd.DataFrame:
    """添加 RSI"""
    delta = df[col].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    df[f"RSI{period}"] = 100 - 100 / (1 + rs)
    return df


def add_boll(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0,
             col: str = "收盘") -> pd.DataFrame:
    """添加布林带 (上/中/下轨)"""
    mid = df[col].rolling(period).mean()
    std = df[col].rolling(period).std()
    df["BOLL_MID"] = mid
    df["BOLL_UP"] = mid + std_mult * std
    df["BOLL_DN"] = mid - std_mult * std
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """一次添加 MA + MACD + RSI + BOLL (常用组合)"""
    df = add_ma(df)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_boll(df)
    return df


def calc_vwap(df: pd.DataFrame, days: int | None = None) -> float:
    """计算 VWAP (成交量加权平均价, 近似筹码成本)

    典型价 = (最高+最低+收盘)/3
    """
    d = df.tail(days).copy() if days else df.copy()
    d["典型价"] = (d["最高"] + d["最低"] + d["收盘"]) / 3
    vol_total = d["成交量"].sum()
    if vol_total == 0:
        return float(d["收盘"].mean())
    return float((d["典型价"] * d["成交量"]).sum() / vol_total)


def calc_chip_distribution(
    df: pd.DataFrame, days: int = 30,
    bins: list[float] | None = None,
) -> pd.DataFrame:
    """成交量在价格区间的分布 (筹码密集区近似)

    返回 DataFrame: 区间 / 成交量 / 占比%
    """
    d = df.tail(days).copy()
    d["典型价"] = (d["最高"] + d["最低"] + d["收盘"]) / 3
    if bins is None:
        lo, hi = d["典型价"].min(), d["典型价"].max()
        step = max((hi - lo) / 8, 0.01)
        bins = list(np.arange(lo, hi + step, step))
        if len(bins) < 2:
            bins = [lo, hi + 0.01]
    d["价格区间"] = pd.cut(d["典型价"], bins=bins, include_lowest=True)
    dist = d.groupby("价格区间", observed=True)["成交量"].sum().reset_index()
    total = dist["成交量"].sum()
    dist["占比"] = dist["成交量"] / total * 100 if total > 0 else 0
    return dist


def calc_volatility(df: pd.DataFrame, days: int = 60, col: str = "收盘") -> dict:
    """日波动率 + 年化波动率 + 近期日均涨幅"""
    d = df.tail(days).copy()
    d["收益率"] = d[col].pct_change()
    daily_vol = float(d["收益率"].std())
    annual_vol = daily_vol * np.sqrt(252)
    recent_drift = float(d["收益率"].tail(20).mean())
    return {
        "daily_vol": daily_vol,
        "annual_vol": annual_vol,
        "recent_drift": recent_drift,
    }


def breakeven_probability(
    current: float, target: float,
    daily_vol: float, daily_drift: float = 0.0,
    days_list: tuple[int, ...] = (5, 10, 20, 40),
) -> list[dict]:
    """估算 N 日内涨至目标价的概率

    基于几何布朗运动假设 + 正态近似 (粗略, 仅供参考).
    返回: [{days, prob_no_drift, prob_with_drift}, ...]
    """
    try:
        from scipy.stats import norm
    except ImportError:
        # 曾经是静默 return []：模板拿到空列表就不渲染回本概率表格，
        # 用户完全无从知道这一节为什么消失。缺依赖必须说出来。
        logger.warning(
            "未安装 scipy，跳过回本概率估算（报告将缺少该章节）。"
            "安装方式：pip install scipy"
        )
        return []
    required = target / current - 1
    out = []
    for n in days_list:
        period_vol = daily_vol * np.sqrt(n)
        if period_vol <= 0:
            p1 = p2 = float("nan")
        else:
            p1 = 1 - norm.cdf(required, loc=0, scale=period_vol)
            p2 = 1 - norm.cdf(required, loc=daily_drift * n, scale=period_vol)
        out.append({
            "days": n,
            "prob_no_drift": float(p1) * 100,
            "prob_with_drift": float(p2) * 100,
        })
    return out


def percentile_of_price(df: pd.DataFrame, price: float,
                        days: int = 90) -> float:
    """某价格在近 days 日价格区间的分位 (0=最低 100=最高)"""
    d = df.tail(days)
    lo, hi = d["最低"].min(), d["最高"].max()
    if hi == lo:
        return 50.0
    return (price - lo) / (hi - lo) * 100
