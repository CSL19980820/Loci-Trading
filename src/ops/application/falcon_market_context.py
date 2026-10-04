"""猎隼盘面上下文只返回聚合读数，不返回个股排名或提供自由选股SQL。"""
from datetime import datetime
import math
import time

from src.market import query_agent_market


def read_falcon_market_context(*, cutoff: str, days: int = 5, checkpoint=None, deadline=None, path=None) -> dict:
    if type(days) is not int or not 1 <= days <= 20:
        raise ValueError("盘面窗口为1—20个已入库交易日")
    options = {"cutoff": cutoff, "checkpoint": checkpoint, "deadline": deadline, "path": path}
    # 多取一日只为计算第一个研究日的涨跌；缺昨收样本显式计数，不默认为平盘。
    prefix = f"""WITH dates AS (
        SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT {days + 1}
    ), prices AS (
        SELECT p.trade_date,p.code,p.close,p.amount,s.industry,s.instrument_type,
               LAG(p.close) OVER (PARTITION BY p.code ORDER BY p.trade_date) AS previous_close
        FROM daily_prices p JOIN dates d ON p.trade_date=d.trade_date
        LEFT JOIN securities s ON p.code=s.code
    ), stock_prices AS (
        SELECT * FROM prices WHERE instrument_type='STOCK' AND close>0
    ) """
    daily = query_agent_market(sql=prefix + """
        SELECT trade_date,COUNT(*) AS coverage,
               SUM(CASE WHEN previous_close>0 THEN 1 ELSE 0 END) AS comparable,
               SUM(CASE WHEN close>previous_close AND previous_close>0 THEN 1 ELSE 0 END) AS advancing,
               SUM(CASE WHEN close<previous_close AND previous_close>0 THEN 1 ELSE 0 END) AS declining,
               SUM(CASE WHEN close=previous_close AND previous_close>0 THEN 1 ELSE 0 END) AS unchanged,
               AVG(CASE WHEN previous_close>0 THEN (close/previous_close-1)*100 END) AS average_return_pct,
               SUM(CASE WHEN previous_close>0 AND close/previous_close>=1.05 THEN 1 ELSE 0 END) AS gains_ge_5pct,
               SUM(CASE WHEN previous_close>0 AND close/previous_close<=0.95 THEN 1 ELSE 0 END) AS losses_ge_5pct,
               SUM(amount) AS amount FROM stock_prices GROUP BY trade_date ORDER BY trade_date DESC
    """, limit=days, **options)
    sectors = query_agent_market(sql=prefix + """
        SELECT COALESCE(NULLIF(industry,''),'行业缺失') AS industry,COUNT(*) AS coverage,
               SUM(CASE WHEN previous_close>0 THEN 1 ELSE 0 END) AS comparable,
               AVG(CASE WHEN previous_close>0 THEN (close/previous_close-1)*100 END) AS average_return_pct,
               SUM(amount) AS amount FROM stock_prices
        WHERE trade_date=(SELECT MAX(trade_date) FROM stock_prices)
        GROUP BY industry ORDER BY industry
    """, limit=1000, **options)
    return {"cutoff": daily["cutoff"], "source": daily["source"], "daily_breadth": daily["rows"],
            "industry_aggregates": sectors["rows"], "industry_truncated": sectors.get("next_offset") is not None,
            "stock_discovery": False, "live": False,
            "note": "这些是截止日可见的已入库日线聚合，不是实时盘面；缺昨收不计涨跌。原始未复权价格可能受除权影响，成交额沿用原库口径。行业为当前元数据，历史复盘不推定当时行业归属已知。股票明细与新机会榜单不对本智能体开放。"}


def read_falcon_market_emotion(*, as_of: str, checkpoint=None, deadline=None) -> dict:
    """读取系统已配置的盘面情绪线路，只投影统计值，绝不透传上游个股列表。"""
    from src.market import TapeRequest, fetch_tape

    day = datetime.fromisoformat(as_of).date().isoformat()

    def check():
        if checkpoint:
            checkpoint()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("盘面查询已超过研究预算")

    check()
    result = fetch_tape(TapeRequest(lane="market_emotion", requested_date=day, as_of_date=day,
                                    tool="short_term_emotion", arguments={"date": day},
                                    context={"quota_pool": "guardian"}))
    check()
    provenance = result.provenance
    values = {}
    for key in ("temperature", "breadth", "promotion_rate", "broken_rate", "limit_up_count", "limit_down_count"):
        value = getattr(result.data, key, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            values[key] = value
    observed_date = getattr(result.data, "trade_date", None) or provenance.as_of_date
    return {"requested_date": day, "observed_date": observed_date, "metrics": values,
            "available": bool(values) and observed_date == day and not provenance.degraded and not provenance.stale,
            "provider": provenance.provider_id, "fetched_at": provenance.fetched_at,
            "stale": provenance.stale or observed_date != day, "degraded": provenance.degraded,
            "from_cache": provenance.from_cache, "warnings": list(provenance.warnings), "error": result.error,
            "stock_discovery": False,
            "note": "仅市场聚合情绪，不返回上游payload中的个股/热点榜单。缺失、陈旧和降级明确标注，不能当作当前盘面证据；日期相同也需核对抓取时间。"}
