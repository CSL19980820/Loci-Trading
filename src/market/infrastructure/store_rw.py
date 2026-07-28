"""MarketStore：写入与基础读取（证券 / 日线 / 日历 / 单票历史）。"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
import sqlite3

import pandas as pd

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_schema import PANEL_FIELDS, PRICE_FIELDS


class MarketRwMixin:
    """instruments / quotes / factors / watermark / calendar / history。"""

    conn: sqlite3.Connection
    db_path: Any

    def upsert_instruments(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [
            (
                normalize_code(row["code"]),
                str(row.get("name", "")),
                str(row.get("market", "")),
                str(row.get("board", "")),
                str(row.get("instrument_type", "STOCK")),
                str(row.get("list_date", "")),
                str(row.get("delist_date", "")),
                str(row.get("status", "normal")),
            )
            for row in rows
        ]
        if not payload:
            return 0
        with self._transaction() as cursor:
            cursor.executemany(
                """
                INSERT INTO instruments(code, name, market, board, instrument_type,
                                        list_date, delist_date, status, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name, market=excluded.market, board=excluded.board,
                    instrument_type=excluded.instrument_type,
                    list_date=CASE WHEN excluded.list_date <> '' THEN excluded.list_date
                                   ELSE instruments.list_date END,
                    delist_date=excluded.delist_date, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        return len(payload)

    def upsert_quotes(self, code: str, frame: pd.DataFrame, *, source: str = "") -> int:
        """写入单只证券的不复权日线。frame 需含 date/open/high/low/close 等列。"""
        code = normalize_code(code)
        if frame is None or frame.empty:
            return 0
        prepared = self._prepare_quote_frame(frame)
        payload = [
            (
                row.trade_date,
                code,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.amount,
                row.outstanding_share,
                row.turnover,
                source,
            )
            for row in prepared.itertuples(index=False)
        ]
        with self._transaction() as cursor:
            cursor.executemany(
                """
                INSERT INTO quotes_daily(trade_date, code, open, high, low, close,
                                         volume, amount, outstanding_share, turnover,
                                         source, fetched_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(trade_date, code) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                    outstanding_share=excluded.outstanding_share,
                    turnover=excluded.turnover, source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                payload,
            )
            # 同一事务内维护日历，保证两张表不会出现"行情写进去了但日历没更新"。
            cursor.executemany(
                "INSERT INTO trading_calendar(trade_date, updated_at)"
                " VALUES(?, datetime('now')) ON CONFLICT(trade_date) DO NOTHING",
                [(row[0],) for row in payload],
            )
        return len(payload)

    def rebuild_calendar(self) -> int:
        """从 quotes_daily 重建交易日历。用于老库补齐或怀疑日历漂移时。"""
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM trading_calendar")
            cursor.execute(
                "INSERT INTO trading_calendar(trade_date, updated_at)"
                " SELECT DISTINCT trade_date, datetime('now') FROM quotes_daily"
            )
        return int(self.conn.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0])

    @staticmethod
    def _prepare_quote_frame(frame: pd.DataFrame) -> pd.DataFrame:
        """把数据源返回的列名归一，并把日期统一成 YYYY-MM-DD 文本。"""
        out = frame.copy()
        out.columns = [str(col).strip().lower() for col in out.columns]
        if "date" in out.columns:
            out = out.rename(columns={"date": "trade_date"})
        if "trade_date" not in out.columns:
            raise MarketError("行情数据缺少日期列")
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
        for column in PANEL_FIELDS:
            if column not in out.columns:
                out[column] = None
        keep = ["trade_date", *PANEL_FIELDS]
        out = out[keep].drop_duplicates(subset=["trade_date"], keep="last")
        # sqlite3 不认 NaN，会存成一个不等于自身的浮点毒值；显式转 NULL。
        return out.astype(object).where(pd.notna(out), None)

    def upsert_adjust_factors(self, code: str, frame: pd.DataFrame, *, source: str = "") -> int:
        """写入稀疏的后复权因子。frame 需含 date 与 hfq_factor 两列。"""
        code = normalize_code(code)
        if frame is None or frame.empty:
            return 0
        out = frame.copy()
        out.columns = [str(col).strip().lower() for col in out.columns]
        if "date" in out.columns:
            out = out.rename(columns={"date": "trade_date"})
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
        payload = [
            (code, str(row.trade_date), float(row.hfq_factor), source)
            for row in out.itertuples(index=False)
            if pd.notna(row.hfq_factor)
        ]
        if not payload:
            return 0
        with self._transaction() as cursor:
            cursor.executemany(
                """
                INSERT INTO adjust_factors(code, trade_date, hfq_factor, source, fetched_at)
                VALUES(?, ?, ?, ?, datetime('now'))
                ON CONFLICT(code, trade_date) DO UPDATE SET
                    hfq_factor=excluded.hfq_factor, source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                payload,
            )
        return len(payload)

    def set_watermark(
        self,
        code: str,
        *,
        last_trade_date: str = "",
        status: str = "ok",
        message: str = "",
        source: str = "",
    ) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO ingest_watermark(code, last_trade_date, last_synced_at,
                                             status, message, source)
                VALUES(?, ?, datetime('now'), ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    last_trade_date=CASE WHEN excluded.last_trade_date <> ''
                                         THEN excluded.last_trade_date
                                         ELSE ingest_watermark.last_trade_date END,
                    last_synced_at=excluded.last_synced_at,
                    status=excluded.status, message=excluded.message,
                    source=excluded.source
                """,
                (normalize_code(code), last_trade_date, status, message[:500], source),
            )

    def watermark(self, code: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM ingest_watermark WHERE code = ?", (normalize_code(code),)
        ).fetchone()

    def list_instruments(
        self, *, instrument_type: str | None = None, status: str = "normal"
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM instruments WHERE 1=1"
        params: list[Any] = []
        if instrument_type:
            sql += " AND instrument_type = ?"
            params.append(instrument_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY code"
        return [dict(row) for row in self.conn.execute(sql, params)]

    def page_instruments(
        self,
        *,
        q: str = "",
        instrument_type: str | None = "STOCK",
        status: str = "normal",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[int, list[dict[str, Any]]]:
        """分页列出证券，供行情台列表。q 同时匹配代码与名称。"""
        where = ["1=1"]
        params: list[Any] = []
        if instrument_type:
            where.append("instrument_type = ?")
            params.append(instrument_type)
        if status:
            where.append("status = ?")
            params.append(status)
        needle = q.strip()
        if needle:
            where.append("(code LIKE ? OR name LIKE ?)")
            like = f"%{needle}%"
            params.extend([like, like])
        clause = " AND ".join(where)
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM instruments WHERE {clause}", params
            ).fetchone()[0]
        )
        rows = self.conn.execute(
            f"SELECT * FROM instruments WHERE {clause} ORDER BY code LIMIT ? OFFSET ?",
            [*params, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        return total, [dict(row) for row in rows]

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
        placeholders = ",".join("?" * len(normalized))
        sql = f"""
            WITH ranked AS (
                SELECT code, trade_date, open, high, low, close, volume, amount,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn
                FROM quotes_daily
                WHERE code IN ({placeholders})
            )
            SELECT a.code, a.trade_date, a.open, a.high, a.low, a.close,
                   a.volume, a.amount, b.close AS prev_close
            FROM ranked a
            LEFT JOIN ranked b ON a.code = b.code AND b.rn = 2
            WHERE a.rn = 1
        """
        out: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(sql, normalized):
            close = float(row["close"] or 0)
            prev = float(row["prev_close"] or 0) if row["prev_close"] is not None else None
            pct = None
            change = None
            if prev and prev > 0 and close > 0:
                change = round(close - prev, 3)
                pct = round(change / prev * 100, 2)
            out[str(row["code"])] = {
                "code": str(row["code"]),
                "trade_date": str(row["trade_date"] or ""),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "amount": row["amount"],
                "prev_close": prev,
                "change": change,
                "pct": pct,
            }
        return out

    def coverage(self) -> dict[str, Any]:
        """仓库现状概览，供健康检查与前端"数据新鲜度"展示。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT code) AS codes,"
            " MIN(trade_date) AS first_date, MAX(trade_date) AS last_date FROM quotes_daily"
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

    def trading_days(self, start: str | None = None, end: str | None = None) -> list[str]:
        """交易日列表。走日历小表，不扫 quotes_daily。"""
        sql = "SELECT trade_date FROM trading_calendar WHERE 1=1"
        params: list[Any] = []
        if start:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            params.append(end)
        sql += " ORDER BY trade_date"
        days = [row[0] for row in self.conn.execute(sql, params)]
        if not days and self.conn.execute("SELECT 1 FROM quotes_daily LIMIT 1").fetchone():
            # 老库还没有日历表：自动补一次，之后走快路径。
            self.rebuild_calendar()
            return self.trading_days(start, end)
        return days

    def shift_trading_days(self, trade_date: str, offset: int) -> str | None:
        """在交易日历上前后移动 N 个交易日。

        T+N 复盘、回测的持有期计算都要它——按自然日加 5 天会跨过周末与
        长假，算出来的"T+5 收益"根本不是第 5 个交易日的收益。
        """
        days = self.trading_days()
        try:
            position = days.index(trade_date)
        except ValueError:
            return None
        target = position + offset
        if 0 <= target < len(days):
            return days[target]
        return None

    def history(
        self,
        code: str,
        *,
        start: str | None = None,
        end: str | None = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """单票日线，按需复权。用于 K 线展示与单票分析。"""
        code = normalize_code(code)
        sql = "SELECT * FROM quotes_daily WHERE code = ?"
        params: list[Any] = [code]
        if start:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            params.append(end)
        sql += " ORDER BY trade_date"
        frame = pd.read_sql_query(sql, self.conn, params=params)
        if frame.empty or adjust == "none":
            return frame
        factors = self._factor_series(code, frame["trade_date"])
        ratio = self._adjust_ratio(factors, adjust)
        for column in PRICE_FIELDS:
            frame[column] = frame[column] * ratio.to_numpy()
        return frame

    def _factor_series(self, code: str, dates: pd.Series) -> pd.Series:
        """把稀疏的除权因子前向填充到给定交易日序列上。"""
        rows = self.conn.execute(
            "SELECT trade_date, hfq_factor FROM adjust_factors WHERE code = ? ORDER BY trade_date",
            (code,),
        ).fetchall()
        index = pd.Index(dates, name="trade_date")
        if not rows:
            return pd.Series(1.0, index=index)
        sparse = pd.Series(
            [float(row["hfq_factor"]) for row in rows],
            index=pd.Index([str(row["trade_date"]) for row in rows]),
        )
        # 除权日之前用最早一个因子；之后逐段前向填充。
        merged = sparse.reindex(sparse.index.union(index)).ffill().bfill()
        return merged.reindex(index)

    @staticmethod
    def _adjust_ratio(factors: pd.Series, adjust: str) -> pd.Series:
        if adjust == "hfq":
            return factors
        if adjust == "qfq":
            # 前复权 = 后复权价 / 最新因子，使最新一根等于真实成交价。
            latest = float(factors.iloc[-1]) if len(factors) else 1.0
            return factors / (latest or 1.0)
        raise MarketError(f"不支持的复权方式：{adjust}")
