"""重同步后的生产库验收：来源、成交额真实性、覆盖、回执。"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\my_space\stock-analyzer")
from src.shared import paths

conn = sqlite3.connect(
    "file:%s?mode=ro" % Path(paths.market_db()).as_posix(), uri=True, timeout=60
)
conn.execute("PRAGMA query_only=1")


def q(label, sql, params=()):
    began = time.perf_counter()
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        print("[ ERR ] %s: %s" % (label, exc))
        return []
    print("[%5.1fs] %s" % (time.perf_counter() - began, label))
    for row in rows[:10]:
        print("          %s" % (row,))
    return rows


q("来源构成（全库）", "SELECT source, COUNT(*) FROM quotes_daily GROUP BY 1 ORDER BY 2 DESC")
q("watermark 来源", "SELECT source, status, COUNT(*) FROM ingest_watermark GROUP BY 1,2 ORDER BY 3 DESC")
q("最后 3 个交易日行数", "SELECT trade_date, COUNT(*) FROM quotes_daily"
  " WHERE trade_date >= (SELECT MIN(trade_date) FROM (SELECT trade_date"
  " FROM trading_calendar ORDER BY trade_date DESC LIMIT 3)) GROUP BY 1 ORDER BY 1")
q("近 90 日缺 receipt_id", "SELECT COUNT(*) FROM quotes_daily"
  " WHERE trade_date >= date('now','-90 day') AND receipt_id IS NULL")
q("北交所覆盖（近 30 日）", "SELECT COUNT(DISTINCT code) FROM quotes_daily"
  " WHERE trade_date >= date('now','-30 day') AND code >= '920000' AND code <= '929999'")
q("仍是合成成交额（腾讯行内）", "SELECT COUNT(*) FROM quotes_daily"
  " WHERE source LIKE 'tencent%' AND amount IS NOT NULL AND volume > 0"
  " AND close > 0 AND ABS(amount - close*volume) < 1.0")
q("真实成交额抽样（近日 tdx 行，amount/(close*vol) 应偏离 1）",
  "SELECT code, trade_date, ROUND(amount/(close*volume), 4) FROM quotes_daily"
  " WHERE source='tdx' AND trade_date >= date('now','-10 day')"
" AND volume > 0 AND close > 0 LIMIT 8")
q("坏 OHLC 按来源", "SELECT source, COUNT(*) FROM quotes_daily"
  " WHERE high < low OR close <= 0 OR open <= 0 GROUP BY 1 ORDER BY 2 DESC")
q("坏 OHLC 按年代", "SELECT substr(trade_date,1,4) y, COUNT(*) FROM quotes_daily"
  " WHERE high < low OR close <= 0 OR open <= 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("坏 OHLC 样例", "SELECT code, trade_date, open, high, low, close, volume, source"
  " FROM quotes_daily WHERE high < low OR close <= 0 OR open <= 0 LIMIT 6")
q("未走通达信的票", "SELECT code, source, status, last_trade_date, message"
  " FROM ingest_watermark WHERE source <> 'tdx'")
conn.close()