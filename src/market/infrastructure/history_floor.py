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

from datetime import date
import os

#: 旧代码兼容常量。生产 PostgreSQL 使用 ``trade_date_floor()`` 的滚动三年边界。
MIN_TRADE_DATE: str = os.environ.get("PALACE_MARKET_MIN_TRADE_DATE", "2023-01-01")


def _three_years_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 3)
    except ValueError:
        # 2 月 29 日回落到同年的 2 月 28 日。
        return day.replace(year=day.year - 3, day=28)


def trade_date_floor(day: date | None = None) -> str:
    """Return the active history floor.

    An explicit ``PALACE_MARKET_MIN_TRADE_DATE`` remains authoritative.  The
    production PostgreSQL backend otherwise rolls daily, retaining three
    calendar years of daily bars.  SQLite tests and local development keep the
    historical fixed floor so an upgrade does not silently change their
    fixtures.
    """
    configured = (os.environ.get("PALACE_MARKET_MIN_TRADE_DATE") or "").strip()
    if configured:
        return configured[:10]
    backend = (os.environ.get("LOCI_DATABASE_BACKEND") or "").strip().lower()
    if backend == "postgres":
        return _three_years_before(day or date.today()).isoformat()
    return MIN_TRADE_DATE


def clamp_start(start: str | None) -> str:
    """把请求起点夹到地板之后；空起点直接返回地板。

    日期都是 ``YYYY-MM-DD`` 文本，字典序即时间序，可直接比较。
    """
    floor = trade_date_floor()
    if not start:
        return floor
    return start if start >= floor else floor


def within_floor(trade_date: str | None) -> bool:
    """单个交易日是否落在地板之内（含）。空值视为不合法。"""
    return bool(trade_date) and str(trade_date)[:10] >= trade_date_floor()
