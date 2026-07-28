"""潜龙出海指标引擎 — 由通达信公式翻译为 Python。

核心信号:
- 辰星线 / 牵牛线 / 等待: 趋势结构
- 红色持股 / 青色观望: 多空状态机
- 短买: 观望转上涨 (VAR19)
- 品红离场: 持股转下跌 (VAR1A)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ytsl(df: pd.DataFrame) -> pd.Series:
    """典型价加权: (3*C + L + O + H) / 6"""
    c = df["收盘"].astype(float)
    return (3 * c + df["最低"] + df["开盘"] + df["最高"]) / 6


def chenxing_line(y: pd.Series) -> pd.Series:
    """辰星线: YTSL 的近期加权均线, 当天权重最大。

    忠实翻译通达信潜龙出海主图辰星线原式::

        (20*YTSL + 19*REF(YTSL,1) + ... + 2*REF(YTSL,18) + REF(YTSL,20)) / 211

    原式有两处怪异构造, 这里照抄而不"修正", 以保证与通达信同源:

    1. 跳过 REF(YTSL,19), 却纳入 REF(YTSL,20) 且权重为 1;
    2. 分母 211 与权重之和 210 (= 20 + [19+18+...+2] + 1) 不等,
       即原式并非严格归一化, 结果比真加权均值低约 0.47%。

    改成 210 归一属于策略口径变更, 需要单独决策, 不在翻译层擅自处理。

    因此第一个有效值需要 21 根 K 线 (offset 0..20)。
    """
    y = y.astype(float)
    total = y * 20.0
    for offset in range(1, 19):  # REF 1..18 -> 权重 19..2
        total = total + y.shift(offset) * (20 - offset)
    total = total + y.shift(20)  # REF 20 -> 权重 1; 原式跳过 REF 19
    return total / 211.0


def calc_state_chains(close: pd.Series) -> dict[str, pd.Series]:
    """计算红色持股 / 青色观望状态链及买卖信号。"""
    c = close.astype(float)
    c1 = c.shift(1)
    c2 = c.shift(2)

    var1 = (c > c1) & (c > c2)
    var2 = var1.shift(1) & (c <= c1) & (c >= c2)
    var3 = var2.shift(1) & (c >= c1) & (c <= c2)
    var4 = var3.shift(1) & (c <= c1) & (c >= c2)
    var5 = var4.shift(1) & (c >= c1) & (c <= c2)
    var6 = var5.shift(1) & (c <= c1) & (c >= c2)
    var7 = var6.shift(1) & (c >= c1) & (c <= c2)
    var8 = var7.shift(1) & (c <= c1) & (c >= c2)
    var9 = var8.shift(1) & (c >= c1) & (c <= c2)
    vara = var9.shift(1) & (c <= c1) & (c >= c2)
    varb = vara.shift(1) & (c >= c1) & (c <= c2)
    varc = varb.shift(1) & (c <= c1) & (c >= c2)

    vard = (c < c1) & (c < c2)
    vare = vard.shift(1) & (c >= c1) & (c <= c2)
    varf = vare.shift(1) & (c <= c1) & (c >= c2)
    var10 = varf.shift(1) & (c >= c1) & (c <= c2)
    var11 = var10.shift(1) & (c <= c1) & (c >= c2)
    var12 = var11.shift(1) & (c >= c1) & (c <= c2)
    var13 = var12.shift(1) & (c <= c1) & (c >= c2)
    var14 = var13.shift(1) & (c >= c1) & (c <= c2)
    var15 = var14.shift(1) & (c <= c1) & (c >= c2)
    var16 = var15.shift(1) & (c >= c1) & (c <= c2)
    var17 = var16.shift(1) & (c <= c1) & (c >= c2)
    var18 = var17.shift(1) & (c >= c1) & (c <= c2)

    red_hold = (
        var1 | var2 | var3 | var4 | var5 | var6 | var7 | var8 | var9 | vara | varb | varc
    )
    cyan_watch = (
        vard | vare | varf | var10 | var11 | var12 | var13 | var14 | var15 | var16 | var17 | var18
    )

    short_buy = cyan_watch.shift(1).fillna(False) & var1
    pink_exit = red_hold.shift(1).fillna(False) & vard

    oversold = (c - c.rolling(34).mean()) / c.rolling(34).mean() * 100 < -14

    return {
        "红色持股": red_hold,
        "青色观望": cyan_watch,
        "短买": short_buy,
        "品红离场": pink_exit,
        "急速超跌": oversold,
    }


def add_qianlong(df: pd.DataFrame) -> pd.DataFrame:
    """在 OHLCV DataFrame 上附加潜龙出海全套指标。"""
    out = df.copy()
    y = ytsl(out)
    out["YTSL"] = y
    out["辰星线"] = chenxing_line(y)
    out["牵牛线"] = out["收盘"].rolling(26).mean()
    out["MA3"] = out["收盘"].rolling(3).mean()
    out["等待"] = np.where(out["MA3"] > out["辰星线"], out["辰星线"], out["MA3"])

    chains = calc_state_chains(out["收盘"])
    for k, v in chains.items():
        out[k] = v

    out["辰星升"] = out["辰星线"] > out["辰星线"].shift(1)
    out["牵牛升"] = out["牵牛线"] > out["牵牛线"].shift(1)
    out["等待升"] = out["等待"] > pd.Series(out["等待"]).shift(1)
    out["量能共振"] = out["成交量"] > out["成交量"].rolling(5).mean() * 1.3
    out["突破20日高"] = out["收盘"] >= out["最高"].rolling(20).max().shift(1)
    return out


def latest_signals(df: pd.DataFrame) -> dict:
    """取最后一根 K 线的潜龙信号快照。"""
    if df is None or len(df) < 35:
        return {"ok": False, "reason": "K线不足"}

    enriched = add_qianlong(df)
    row = enriched.iloc[-1]
    prev = enriched.iloc[-2]

    def _b(col: str) -> bool:
        v = row.get(col)
        return bool(v) if pd.notna(v) else False

    return {
        "ok": True,
        "日期": str(row.get("日期", "")),
        "收盘": round(float(row["收盘"]), 2),
        "短买": _b("短买"),
        "品红离场": _b("品红离场"),
        "红色持股": _b("红色持股"),
        "青色观望": _b("青色观望"),
        "急速超跌": _b("急速超跌"),
        "辰星升": _b("辰星升"),
        "牵牛升": _b("牵牛升"),
        "等待升": _b("等待升"),
        "量能共振": _b("量能共振"),
        "突破20日高": _b("突破20日高"),
        "昨青色今阳": bool(prev.get("青色观望")) and float(row["收盘"]) > float(prev["收盘"]),
        "辰星线": round(float(row["辰星线"]), 3) if pd.notna(row["辰星线"]) else None,
        "牵牛线": round(float(row["牵牛线"]), 3) if pd.notna(row["牵牛线"]) else None,
    }


def score_signals(sig: dict, *, sector_rank: int = 99, tail_accel: float | None = None) -> dict:
    """潜龙出海尾盘量化打分 (满分 100)。"""
    if not sig.get("ok"):
        return {"总分": 0, "分项": {}, "命中": []}

    parts: dict[str, float] = {}
    hits: list[str] = []

    if sig["短买"]:
        parts["短买"] = 35
        hits.append("短买")
    elif sig["红色持股"]:
        parts["持股"] = 20
        hits.append("红色持股")
    elif sig["昨青色今阳"]:
        parts["转强"] = 15
        hits.append("观望转阳")

    if sig["辰星升"]:
        parts["辰星升"] = 12
        hits.append("辰星升")
    if sig["牵牛升"]:
        parts["牵牛升"] = 8
        hits.append("牵牛升")
    if sig["等待升"]:
        parts["等待升"] = 8
        hits.append("等待升")
    if sig["量能共振"]:
        parts["量能"] = 10
        hits.append("量能共振")
    if sig["突破20日高"]:
        parts["突破"] = 10
        hits.append("突破20日高")

    if sector_rank <= 3:
        parts["主线"] = 15
        hits.append(f"主线TOP{sector_rank}")
    elif sector_rank <= 8:
        parts["主线"] = 8
        hits.append(f"板块TOP{sector_rank}")

    if tail_accel is not None:
        if tail_accel >= 1.0:
            parts["尾盘"] = 15
            hits.append("尾盘加速")
        elif tail_accel >= 0.3:
            parts["尾盘"] = 8
            hits.append("尾盘走强")

    total = min(100, round(sum(parts.values()), 1))
    return {"总分": total, "分项": parts, "命中": hits}
