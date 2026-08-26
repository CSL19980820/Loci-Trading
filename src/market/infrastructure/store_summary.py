"""MarketStore：行情概览与最近日线查询。"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
import sqlite3

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.turnover_math import compute_turnover


class MarketSummaryMixin:
    """latest_bars / coverage 等概览查询。依赖宿主提供连接与事务。"""

    conn: sqlite3.Connection
    db_path: Path

    #: 列表取最近两根日线时，先只扫日历近窗（走 code+date 索引），避免
    #: 对每只票做全历史窗口函数（千万行库上可达数秒）。
    _LATEST_BARS_LOOKBACK_DAYS = 20

    def latest_bars(self, codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        """批量取每只证券最近两根日线，拼出现价/昨收（不复权）。"""
        normalized: list[str] = []
        for raw in codes:
            try:
                normalized.append(normalize_code(raw))
            except MarketError:
                continue
        if not normalized:
            return {}

        days = [
            str(row[0])
            for row in self.conn.execute(
                "SELECT trade_date FROM trading_calendar"
                " ORDER BY trade_date DESC LIMIT ?",
                (self._LATEST_BARS_LOOKBACK_DAYS,),
            )
        ]
        out: dict[str, dict[str, Any]] = {}
        if days:
            out.update(self._latest_bars_from_window(normalized, days))
        missing = [code for code in normalized if code not in out]
        if missing:
            out.update(self._latest_bars_by_max(missing))
        return out

    def _latest_bars_from_window(
        self, codes: Sequence[str], days: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        """日历近窗内按 code 取最近两根（ORDER BY date DESC，Python 侧截断）。"""
        code_ph = ",".join("?" * len(codes))
        day_ph = ",".join("?" * len(days))
        sql = f"""
            SELECT code, trade_date, open, high, low, close, volume, amount,
                   outstanding_share, turnover
            FROM quotes_daily
            WHERE code IN ({code_ph}) AND trade_date IN ({day_ph})
            ORDER BY code ASC, trade_date DESC
        """
        buckets: dict[str, list[sqlite3.Row]] = {}
        for row in self.conn.execute(sql, [*codes, *days]):
            code = str(row["code"])
            bucket = buckets.setdefault(code, [])
            if len(bucket) < 2:
                bucket.append(row)
        return {
            code: self._bar_payload(bars[0], bars[1] if len(bars) > 1 else None)
            for code, bars in buckets.items()
        }

    def _latest_bars_by_max(self, codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        """无日历近窗命中时的回退：MAX(trade_date) 联表（仍远快于全历史窗口函数）。"""
        placeholders = ",".join("?" * len(codes))
        sql = f"""
            WITH last_dates AS (
                SELECT code, MAX(trade_date) AS trade_date
                FROM quotes_daily
                WHERE code IN ({placeholders})
                GROUP BY code
            ),
            prev_dates AS (
                SELECT q.code, MAX(q.trade_date) AS trade_date
                FROM quotes_daily q
                INNER JOIN last_dates d
                    ON q.code = d.code AND q.trade_date < d.trade_date
                WHERE q.code IN ({placeholders})
                GROUP BY q.code
            )
            SELECT a.code, a.trade_date, a.open, a.high, a.low, a.close,
                   a.volume, a.amount, a.outstanding_share, a.turnover,
                   b.close AS prev_close
            FROM quotes_daily a
            INNER JOIN last_dates d ON a.code = d.code AND a.trade_date = d.trade_date
            LEFT JOIN quotes_daily b
                ON b.code = a.code
               AND b.trade_date = (
                    SELECT p.trade_date FROM prev_dates p WHERE p.code = a.code
               )
        """
        out: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(sql, [*codes, *codes]):
            prev = float(row["prev_close"] or 0) if row["prev_close"] is not None else None
            out[str(row["code"])] = self._bar_payload(row, prev_close=prev)
        return out

    @staticmethod
    def _bar_payload(
        latest: sqlite3.Row,
        prev: sqlite3.Row | None = None,
        *,
        prev_close: float | None = None,
    ) -> dict[str, Any]:
        close = float(latest["close"] or 0)
        if prev_close is None and prev is not None and prev["close"] is not None:
            prev_close = float(prev["close"] or 0)
        pct = None
        change = None
        if prev_close and prev_close > 0 and close > 0:
            change = round(close - prev_close, 3)
            pct = round(change / prev_close * 100, 2)
        turnover = None
        keys = latest.keys()
        shares = None
        if "outstanding_share" in keys and latest["outstanding_share"] is not None:
            try:
                shares = float(latest["outstanding_share"])
            except (TypeError, ValueError):
                shares = None
        stored = None
        if "turnover" in keys and latest["turnover"] is not None:
            try:
                stored = float(latest["turnover"])
            except (TypeError, ValueError):
                stored = None
        volume = None
        if "volume" in keys and latest["volume"] is not None:
            try:
                volume = float(latest["volume"])
            except (TypeError, ValueError):
                volume = None
        amount = None
        if "amount" in keys and latest["amount"] is not None:
            try:
                amount = float(latest["amount"])
            except (TypeError, ValueError):
                amount = None
        turnover = compute_turnover(
            volume=volume,
            amount=amount,
            close=close if close > 0 else None,
            shares=shares,
            stored=stored,
        )
        return {
            "code": str(latest["code"]),
            "trade_date": str(latest["trade_date"] or ""),
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "close": latest["close"],
            "volume": latest["volume"],
            "amount": latest["amount"],
            "turnover": turnover,
            "prev_close": prev_close,
            "change": change,
            "pct": pct,
        }

    def recent_amounts(self, code: str, *, limit: int = 5) -> list[float]:
        """最近 N 根日线成交额（新→旧），供容量校验；勿在 review 直捅 .conn。"""
        if limit <= 0:
            return []
        try:
            normalized = normalize_code(code)
        except MarketError:
            return []
        rows = self.conn.execute(
            """
            SELECT amount FROM quotes_daily
            WHERE code = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (normalized, limit),
        ).fetchall()
        return [float(row["amount"]) for row in rows if row["amount"] is not None]

    def coverage(self) -> dict[str, Any]:
        """仓库现状概览，供健康检查与前端"数据新鲜度"展示。"""
        cal = self.conn.execute(
            "SELECT MIN(trade_date) AS first_date, MAX(trade_date) AS last_date"
            " FROM trading_calendar"
        ).fetchone()
        first_date = str(cal["first_date"] or "") if cal else ""
        last_date = str(cal["last_date"] or "") if cal else ""
        if not last_date:
            row = self.conn.execute(
                "SELECT COUNT(*) AS rows, COUNT(DISTINCT code) AS codes,"
                " MIN(trade_date) AS first_date, MAX(trade_date) AS last_date"
                " FROM quotes_daily"
            ).fetchone()
            failed = self.conn.execute(
                "SELECT COUNT(*) FROM ingest_watermark WHERE status <> 'ok'"
            ).fetchone()[0]
            return {
                "rows": int(row["rows"] or 0),
                "codes": int(row["codes"] or 0),
                "first_date": row["first_date"] or "",
                "last_date": row["last_date"] or "",
                "failed_codes": int(failed),
                "db_path": str(self.db_path),
                "db_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            }

        codes = int(self.conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0])
        failed = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM ingest_watermark WHERE status <> 'ok'"
            ).fetchone()[0]
        )
        rows = self._cached_quote_row_count(last_date)
        return {
            "rows": rows,
            "codes": codes,
            "first_date": first_date,
            "last_date": last_date,
            "failed_codes": failed,
            "db_path": str(self.db_path),
            "db_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }

    def _cached_quote_row_count(self, last_date: str) -> int:
        """按日历末日与行情 revision 缓存行情行数，避免每次全表 COUNT。"""
        revision_row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'quotes_revision'"
        ).fetchone()
        revision = str(revision_row[0] if revision_row else "0")
        cached = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'quotes_daily_rows_v1'"
        ).fetchone()
        if cached and cached[0]:
            raw = str(cached[0])
            parts = raw.split("|")
            if len(parts) == 3:
                stamp, cached_revision, count_s = parts
                if stamp == last_date and cached_revision == revision:
                    try:
                        return int(count_s)
                    except ValueError:
                        pass
        count = int(self.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0])
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO meta(key, value, updated_at)
                VALUES('quotes_daily_rows_v1', ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at
                """,
                (f"{last_date}|{revision}|{count}",),
            )
        return count
