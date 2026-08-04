"""Screen Formula 的公开函数、字段与模板目录。

这里是编辑器工具栏和编译器共享的事实源；只有列在
``FORMULA_FUNCTIONS`` 中的函数才会出现在 catalog。
"""
from __future__ import annotations

from typing import Any


FORMULA_FUNCTIONS = (
    "REF", "MA", "EMA", "SMA", "WMA", "DMA", "SUM", "HHV", "LLV",
    "STD", "AVEDEV", "COUNT", "EVERY", "EXIST", "FILTER", "BARSLAST",
    "BARSSINCE", "BARSCOUNT", "HHVBARS", "LLVBARS", "IF", "ABS", "MAX",
    "MIN", "CROSS", "ZTPRICE", "TR", "ATR", "RSI", "ROC", "WR", "CCI",
    "OBV", "MACD_DIF", "MACD_DEA", "MACD", "BOLL_MID", "BOLL_UPPER",
    "BOLL_LOWER",
)

_DAILY_FIELDS = (
    ("open", "开盘价", "当日开盘成交价", "market.daily.open"),
    ("high", "最高价", "当日最高成交价", "market.daily.high"),
    ("low", "最低价", "当日最低成交价", "market.daily.low"),
    ("close", "收盘价", "当日收盘成交价", "market.daily.close"),
    ("volume", "成交量", "日成交量", "market.daily.volume"),
    ("amount", "成交额", "日成交额", "market.daily.amount"),
    ("turnover", "换手率", "日换手率，小数口径；公式 HSL 自动转百分比", "market.daily.turnover"),
)

_FUNCTION_ROWS = (
    ("REF", "引用", "REF(X, N)", "取 N 个周期前的值", "X 可为价格或因子；N 为非负整数。", "REF(CLOSE,1)", ["REF(CLOSE,1)"], "REF"),
    ("MA", "均线", "MA(X, N)", "简单移动平均", "最近 N 根的简单均线。", "MA(CLOSE,20)", ["MA(CLOSE,20)"], "MA"),
    ("EMA", "均线", "EMA(X, N)", "指数移动平均", "对最近价格赋予更高权重的移动平均。", "EMA(CLOSE,12)", ["EMA(CLOSE,12)"], "EMA"),
    ("SMA", "均线", "SMA(X, N, M)", "通达信递推均线", "递推公式为 (M*X+(N-M)*Y')/N。", "SMA(CLOSE,6,1)", ["SMA(CLOSE,6,1)"], "SMA"),
    ("WMA", "均线", "WMA(X, N)", "线性加权移动平均", "越近的周期权重越大。", "WMA(CLOSE,10)", ["WMA(CLOSE,10)"], "WMA"),
    ("DMA", "均线", "DMA(X, A)", "动态权重均线", "A 可为常数或随时间变化的数值序列。", "DMA(CLOSE,0.2)", ["DMA(CLOSE,0.2)"], "DMA"),
    ("SUM", "区间统计", "SUM(X, N)", "区间求和", "计算最近 N 根的累计值。", "SUM(VOL,5)", ["SUM(VOL,5)"], "SUM"),
    ("HHV", "区间统计", "HHV(X, N)", "区间最高值", "计算最近 N 根的最高值。", "HHV(HIGH,20)", ["HHV(HIGH,20)"], "HHV"),
    ("LLV", "区间统计", "LLV(X, N)", "区间最低值", "计算最近 N 根的最低值。", "LLV(LOW,20)", ["LLV(LOW,20)"], "LLV"),
    ("STD", "区间统计", "STD(X, N)", "区间标准差", "样本标准差，可用于波动率过滤。", "STD(CLOSE,20)", ["STD(CLOSE,20)"], "STD"),
    ("AVEDEV", "区间统计", "AVEDEV(X, N)", "平均绝对偏差", "计算最近 N 根相对均值的平均绝对偏差。", "AVEDEV(CLOSE,20)", ["AVEDEV(CLOSE,20)"], "AVEDEV"),
    ("COUNT", "条件", "COUNT(COND, N)", "条件成立次数", "统计最近 N 根中条件为真的次数。", "COUNT(CLOSE>OPEN,5)", ["COUNT(CLOSE>OPEN,5)"], "COUNT"),
    ("EVERY", "条件", "EVERY(COND, N)", "连续满足条件", "最近 N 根每一根都满足条件。", "EVERY(CLOSE>MA(CLOSE,20),3)", ["EVERY(CLOSE>MA(CLOSE,20),3)"], "EVERY"),
    ("EXIST", "条件", "EXIST(COND, N)", "区间内出现过", "最近 N 根至少一次满足条件。", "EXIST(CROSS(CLOSE,MA(CLOSE,20)),5)", ["EXIST(CROSS(CLOSE,MA(CLOSE,20)),5)"], "EXIST"),
    ("FILTER", "条件", "FILTER(COND, N)", "信号去重", "条件首次满足后 N 根内不再重复触发。", "FILTER(CROSS(CLOSE,MA(CLOSE,20)),5)", ["FILTER(CROSS(CLOSE,MA(CLOSE,20)),5)"], "FILTER"),
    ("BARSLAST", "位置", "BARSLAST(COND)", "距上次满足的周期", "当日满足为 0，从未满足则为空。", "BARSLAST(CROSS(CLOSE,MA(CLOSE,20)))", ["BARSLAST(CROSS(CLOSE,MA(CLOSE,20)))"], "BARSLAST"),
    ("BARSSINCE", "位置", "BARSSINCE(COND)", "距首次满足的周期", "首次满足后从 0 开始累计。", "BARSSINCE(CLOSE>MA(CLOSE,20))", ["BARSSINCE(CLOSE>MA(CLOSE,20))"], "BARSSINCE"),
    ("BARSCOUNT", "位置", "BARSCOUNT(X)", "有效 K 线数量", "从首个有效值起累计的周期数。", "BARSCOUNT(CLOSE)", ["BARSCOUNT(CLOSE)"], "BARSCOUNT"),
    ("HHVBARS", "位置", "HHVBARS(X, N)", "距区间最高的周期", "最近 N 根内最高值距今的根数。", "HHVBARS(HIGH,20)", ["HHVBARS(HIGH,20)"], "HHVBARS"),
    ("LLVBARS", "位置", "LLVBARS(X, N)", "距区间最低的周期", "最近 N 根内最低值距今的根数。", "LLVBARS(LOW,20)", ["LLVBARS(LOW,20)"], "LLVBARS"),
    ("IF", "逻辑", "IF(COND, A, B)", "条件分支", "按条件逐元素选择 A 或 B。", "IF(CLOSE>OPEN,CLOSE,OPEN)", ["IF(CLOSE>OPEN,CLOSE,OPEN)"], "IF"),
    ("ABS", "逻辑", "ABS(X)", "绝对值", "取数值绝对值。", "ABS(CLOSE-OPEN)", ["ABS(CLOSE-OPEN)"], "ABS"),
    ("MAX", "逻辑", "MAX(A, B)", "逐元素取大", "取两个数值表达式中的较大值。", "MAX(HIGH,REF(CLOSE,1))", ["MAX(HIGH,REF(CLOSE,1))"], "MAX"),
    ("MIN", "逻辑", "MIN(A, B)", "逐元素取小", "取两个数值表达式中的较小值。", "MIN(LOW,REF(CLOSE,1))", ["MIN(LOW,REF(CLOSE,1))"], "MIN"),
    ("CROSS", "逻辑", "CROSS(A, B)", "上穿", "当日 A>B 且前一日 A<=B。", "CROSS(CLOSE,MA(CLOSE,20))", ["CROSS(CLOSE,MA(CLOSE,20))"], "CROSS"),
    ("ZTPRICE", "价格", "ZTPRICE(PREV_CLOSE, RATIO)", "涨停价", "按交易所分价位四舍五入规则计算涨停价。", "ZTPRICE(REF(CLOSE,1),0.1)", ["ZTPRICE(REF(CLOSE,1),0.1)"], "ZTPRICE"),
    ("TR", "趋势", "TR(HIGH, LOW, CLOSE)", "真实波幅", "首根因缺少昨收为空，后续取三种波幅中的最大值。", "TR(HIGH,LOW,CLOSE)", ["TR(HIGH,LOW,CLOSE)"], "TR"),
    ("ATR", "趋势", "ATR(HIGH, LOW, CLOSE, N)", "平均真实波幅", "N 周期真实波幅均值，用于衡量波动与止损距离。", "ATR(HIGH,LOW,CLOSE,14)", ["ATR(HIGH,LOW,CLOSE,14)"], "ATR"),
    ("RSI", "动量", "RSI(X, N)", "相对强弱指标", "按通达信 SMA 递推口径返回 0-100 的动量值。", "RSI(CLOSE,14)", ["RSI(CLOSE,14)"], "RSI"),
    ("ROC", "动量", "ROC(X, N)", "变化率", "与 N 周期前相比的百分比变化。", "ROC(CLOSE,12)", ["ROC(CLOSE,12)"], "ROC"),
    ("WR", "动量", "WR(HIGH, LOW, CLOSE, N)", "威廉指标", "返回 -100 到 0，越接近 0 表示越接近区间高点。", "WR(HIGH,LOW,CLOSE,14)", ["WR(HIGH,LOW,CLOSE,14)"], "WR"),
    ("CCI", "动量", "CCI(HIGH, LOW, CLOSE, N)", "商品通道指标", "以典型价格、均值和平均绝对偏差衡量偏离程度。", "CCI(HIGH,LOW,CLOSE,14)", ["CCI(HIGH,LOW,CLOSE,14)"], "CCI"),
    ("OBV", "量价", "OBV(CLOSE, VOL)", "能量潮", "按收盘涨跌方向累计成交量，首根有效 K 线从 0 起算。", "OBV(CLOSE,VOL)", ["OBV(CLOSE,VOL)"], "OBV"),
    ("MACD_DIF", "趋势", "MACD_DIF(CLOSE, FAST, SLOW)", "MACD 快慢线差", "快 EMA 减慢 EMA。", "MACD_DIF(CLOSE,12,26)", ["MACD_DIF(CLOSE,12,26)"], "MACD_DIF"),
    ("MACD_DEA", "趋势", "MACD_DEA(CLOSE, FAST, SLOW, SIGNAL)", "MACD 信号线", "DIF 的 SIGNAL 周期 EMA。", "MACD_DEA(CLOSE,12,26,9)", ["MACD_DEA(CLOSE,12,26,9)"], "MACD_DEA"),
    ("MACD", "趋势", "MACD(CLOSE, FAST, SLOW, SIGNAL)", "MACD 柱值", "返回 (DIF-DEA)*2，便于公式直接筛选。", "MACD(CLOSE,12,26,9)", ["MACD(CLOSE,12,26,9)"], "MACD"),
    ("BOLL_MID", "波动", "BOLL_MID(X, N)", "布林中轨", "N 周期简单移动平均。", "BOLL_MID(CLOSE,20)", ["BOLL_MID(CLOSE,20)"], "BOLL_MID"),
    ("BOLL_UPPER", "波动", "BOLL_UPPER(X, N, K)", "布林上轨", "中轨加 K 倍 N 周期样本标准差。", "BOLL_UPPER(CLOSE,20,2)", ["BOLL_UPPER(CLOSE,20,2)"], "BOLL_UPPER"),
    ("BOLL_LOWER", "波动", "BOLL_LOWER(X, N, K)", "布林下轨", "中轨减 K 倍 N 周期样本标准差。", "BOLL_LOWER(CLOSE,20,2)", ["BOLL_LOWER(CLOSE,20,2)"], "BOLL_LOWER"),
)


def formula_fields_catalog() -> list[dict[str, str]]:
    return [
        {"name": name, "label": label, "summary": summary, "source": source}
        for name, label, summary, source in _DAILY_FIELDS
    ]


def formula_functions_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "category": category,
            "signature": signature,
            "summary": summary,
            "description": description,
            "insert_text": insert_text,
            "examples": examples,
            "dialects": ["loci", "tdx", "ths"],
            "source": f"src.formula.domain.functions:{source}",
        }
        for name, category, signature, summary, description, insert_text, examples, source in _FUNCTION_ROWS
    ]


def screen_skill_catalog() -> dict[str, Any]:
    """供 Screen Skill 工坊使用的、与实际 runtime 对齐的目录。"""
    return {
        "runtimes": [
            {"id": "formula", "label": "公式", "summary": "向量化日线公式", "dialects": ["loci", "tdx", "ths"]},
            {"id": "python", "label": "Python", "summary": "本地 pandas 策略包", "dialects": ["python"]},
        ],
        "dialects": [
            {"id": "loci", "runtime": "formula", "label": "Loci 公式", "summary": "Loci 公式子集"},
            {"id": "tdx", "runtime": "formula", "label": "通达信", "summary": "兼容已开放函数的通达信风格语法"},
            {"id": "ths", "runtime": "formula", "label": "同花顺", "summary": "兼容已开放函数的同花顺风格语法"},
            {"id": "python", "runtime": "python", "label": "Python", "summary": "strategy.py:compute(panels, params)"},
        ],
        "fields": formula_fields_catalog(),
        "functions": formula_functions_catalog(),
        "snippets": _snippets(),
    }


def _snippets() -> list[dict[str, Any]]:
    params_n = {"N": {"type": "int", "default": 20, "min": 2, "max": 250, "label": "周期"}}
    return [
        _formula_snippet("ma-breakout", "均线突破", "BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;", ["close"], params_n, ["BASE"]),
        _formula_snippet("ema-cross", "EMA 上穿", "FAST:=EMA(CLOSE,12);\nSLOW:=EMA(CLOSE,26);\nPICK: CROSS(FAST,SLOW);", ["close"], {}, ["FAST", "SLOW"]),
        _formula_snippet("volume-breakout", "放量突破", "BASE:=MA(CLOSE,N);\nVOLR:=VOL/MA(VOL,5);\nPICK: CLOSE>BASE AND VOLR>=1.5;", ["close", "volume"], params_n, ["BASE", "VOLR"]),
        _formula_snippet("sma-trend", "SMA 趋势", "TREND:=SMA(CLOSE,6,1);\nPICK: CLOSE>TREND;", ["close"], {}, ["TREND"]),
        _formula_snippet("new-high", "创新高", "PREV_HIGH:=REF(HHV(HIGH,N),1);\nPICK: CLOSE>PREV_HIGH;", ["high", "close"], params_n, ["PREV_HIGH"]),
        _formula_snippet("pullback", "均线回踩", "BASE:=MA(CLOSE,N);\nPICK: LOW<=BASE AND CLOSE>BASE;", ["low", "close"], params_n, ["BASE"]),
        _formula_snippet("limit-up", "涨停触及", "LIMIT:=ZTPRICE(REF(CLOSE,1),0.1);\nPICK: HIGH>=LIMIT;", ["close", "high"], {}, ["LIMIT"]),
        _formula_snippet("signal-cooldown", "信号去重", "RAW:=CROSS(CLOSE,MA(CLOSE,20));\nPICK: FILTER(RAW,5);", ["close"], {}, ["RAW"]),
        _formula_snippet("high-distance", "距阶段高点", "DIST:=HHVBARS(HIGH,N);\nPICK: DIST<=3;", ["high"], params_n, ["DIST"]),
        _formula_snippet("volatility", "波动率收敛", "VOLAT:=STD(CLOSE,N);\nPICK: VOLAT<REF(VOLAT,1);", ["close"], params_n, ["VOLAT"]),
        {
            "id": "python-ma-breakout", "title": "Python 均线突破", "runtime": "python", "dialect": "python", "summary": "pandas 写法的均线突破", "code": "def compute(panels, params):\n    close = panels['close']\n    base = close.rolling(int(params['N'])).mean()\n    return {'signals': close > base, 'factors': {'BASE': base}}\n", "required_fields": ["close"], "params": params_n, "factors": ["BASE"],
        },
        {
            "id": "python-volume-breakout", "title": "Python 放量突破", "runtime": "python", "dialect": "python", "summary": "量比与均线同时过滤", "code": "def compute(panels, params):\n    close, volume = panels['close'], panels['volume']\n    base = close.rolling(int(params['N'])).mean()\n    volr = volume / volume.rolling(5).mean()\n    return {'signals': (close > base) & (volr >= params['VOL_MULT']), 'factors': {'BASE': base, 'VOLR': volr}}\n", "required_fields": ["close", "volume"], "params": {**params_n, "VOL_MULT": {"type": "float", "default": 1.5, "min": 0.1, "max": 10.0, "label": "量比"}}, "factors": ["BASE", "VOLR"],
        },
    ]


def _formula_snippet(
    snippet_id: str, title: str, code: str, required_fields: list[str],
    params: dict[str, Any], factors: list[str],
) -> dict[str, Any]:
    return {"id": snippet_id, "title": title, "runtime": "formula", "dialect": "loci", "summary": title, "code": code + "\n", "required_fields": required_fields, "params": params, "factors": factors}
