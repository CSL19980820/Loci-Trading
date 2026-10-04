"""行情历史下限（防回填地板）。

早于 ``MIN_TRADE_DATE`` 的日 K 既不请求、也不落库。这是「请求 / 缺口判定 /
强制同步 / 导入 / 落库」共用的同一个地板：任何一条取数路径把它当作最早起点，
落库前再过滤一次，确保旧行情不会重新进入权威库。

``quotes_daily_floor`` BEFORE INSERT 触发器可作为普通日 K 的最后一道兜底。
稀疏累计复权因子不受该日 K 地板约束：截断日前最后已知因子仍是后续行情的
复权锚点，须允许真实来源提供的更早事件入库。存储维护只删除冗余早期因子，
并在核对完整定义后移除旧部署误加的 ``adjust_factors_floor``；不移除报价地板。
"""
from __future__ import annotations

import os

#: 统一历史起点。默认 2023-01-01；可用环境变量覆盖（测试 / 特殊租户）。
MIN_TRADE_DATE: str = os.environ.get("PALACE_MARKET_MIN_TRADE_DATE", "2023-01-01")


def clamp_start(start: str | None) -> str:
    """把请求起点夹到地板之后；空起点直接返回地板。

    日期都是 ``YYYY-MM-DD`` 文本，字典序即时间序，可直接比较。
    """
    if not start:
        return MIN_TRADE_DATE
    return start if start >= MIN_TRADE_DATE else MIN_TRADE_DATE


def within_floor(trade_date: str | None) -> bool:
    """单个交易日是否落在地板之内（含）。空值视为不合法。"""
    return bool(trade_date) and str(trade_date)[:10] >= MIN_TRADE_DATE
