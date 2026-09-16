"""MarketStore：写入与基础读取（证券 / 日线 / 日历 / 单票历史）。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
import sqlite3

import pandas as pd

from src.market.infrastructure.store_codes import MarketError, guess_market, normalize_code
from src.market.infrastructure.store_quote_payload import (
    partition_valid_ohlc_rows,
    quote_payload_from_bars,
    quote_value_columns,
    write_quote_payload,
)
from src.market.infrastructure.store_schema import PANEL_FIELDS, PRICE_FIELDS

class MarketRwMixin:
    """instruments / quotes / factors / watermark / calendar / history。"""

    conn: sqlite3.Connection
    db_path: Any
    @staticmethod
    def _bump_revisions(cursor: sqlite3.Cursor, *scopes: str) -> None:
        keys = ("market_revision", *(f"{scope}_revision" for scope in scopes))
        for key in keys:
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES(?, '1', datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value = CAST(meta.value AS INTEGER) + 1,"
                " updated_at = excluded.updated_at",
                (key,),
            )

    def upsert_instruments(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [
            (
                normalize_code(row["code"]),
                str(row.get("name", "")),
                str(row.get("market", "")),
                str(row.get("board", "")),
                str(row.get("industry", "")),
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
                INSERT INTO instruments(code, name, market, board, industry, instrument_type,
                                        list_date, delist_date, status, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name, market=excluded.market, board=excluded.board,
                    industry=CASE WHEN excluded.industry <> '' THEN excluded.industry
                                  ELSE instruments.industry END,
                    instrument_type=excluded.instrument_type,
                    list_date=CASE WHEN excluded.list_date <> '' THEN excluded.list_date
                                   ELSE instruments.list_date END,
                    delist_date=excluded.delist_date, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
            self._bump_revisions(cursor, "instruments")
        return len(payload)

    def reconcile_instrument_snapshot(
        self,
        active_codes: Iterable[str],
        *,
        complete_markets: Iterable[str],
        snapshot_date: str,
    ) -> dict[str, Any]:
        """用完整交易所快照停用已消失的普通股票，不删除其历史行情。

        ``complete_markets`` 只含本次明确拉全的交易所；部分列表失败时绝不能
        把整所旧票误判为退市。大市场快照若骤减超过 20% 同样拒绝淘汰。
        """
        supported = {"sh", "sz", "bj"}
        requested = {
            str(market).strip().lower()
            for market in complete_markets
            if str(market).strip().lower() in supported
        }
        active = {normalize_code(code) for code in active_codes}
        rows = self.conn.execute(
            "SELECT code FROM instruments"
            " WHERE instrument_type = 'STOCK' AND status = 'normal'"
        ).fetchall()
        existing = {str(row[0]) for row in rows}
        accepted: set[str] = set()
        rejected: set[str] = set()
        retired: list[str] = []

        for market in sorted(requested):
            current = {code for code in existing if guess_market(code) == market}
            incoming = {code for code in active if guess_market(code) == market}
            if not incoming or (
                len(current) >= 20 and len(incoming) < int(len(current) * 0.8)
            ):
                rejected.add(market)
                continue
            accepted.add(market)
            retired.extend(sorted(current - incoming))

        with self._transaction() as cursor:
            if retired:
                cursor.executemany(
                    "UPDATE instruments SET status = 'delisted', updated_at = datetime('now')"
                    " WHERE code = ? AND instrument_type = 'STOCK' AND status = 'normal'",
                    [(code,) for code in retired],
                )
                self._bump_revisions(cursor, "instruments")
            # 刷新时间表示「今天已成功拿到并核验至少一个交易所快照」。
            # 某所失败/骤减时保留其旧目录；不应让 5 分钟任务当天反复重打全列表。
            if accepted:
                cursor.execute(
                    "INSERT INTO meta(key, value, updated_at)"
                    " VALUES('instruments_snapshot_date', ?, datetime('now'))"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                    " updated_at=excluded.updated_at",
                    (str(snapshot_date)[:10],),
                )
        return {
            "retired": len(retired),
            "accepted_markets": sorted(accepted),
            "rejected_markets": sorted(rejected),
        }

    def instrument_snapshot_date(self) -> str:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'instruments_snapshot_date'"
        ).fetchone()
        return str(row[0] or "")[:10] if row else ""

    def upsert_quotes(
        self,
        code: str,
        frame: pd.DataFrame,
        *,
        source: str = "",
        receipt_id: str | None = None,
    ) -> int:
        """写入单只证券的不复权日线。frame 需含 date/open/high/low/close 等列。"""
        return self._write_quote_payload(
            self._quote_payload_from_frame(code, frame, source=source, receipt_id=receipt_id)
        )

    def upsert_quote_bars(
        self,
        bars: Iterable[dict[str, Any]],
        *,
        source: str = "",
        receipt_ids: Mapping[str, str] | None = None,
    ) -> int:
        """批量写入多只证券日 K（单事务）。每条需含 code 与 date/OHLCV。

        全市场 spot 约五千行：必须一次 DataFrame 归一，禁止逐票建表（会慢到
        中途覆盖率只剩个位数）。去重键是 (code, trade_date)。
        """
        return self._write_quote_payload(
            self._quote_payload_from_bars(bars, source=source, receipt_ids=receipt_ids)
        )

    def _quote_payload_from_frame(
        self,
        code: str,
        frame: pd.DataFrame,
        *,
        source: str,
        receipt_id: str | None = None,
    ) -> list[tuple[Any, ...]]:
        code = normalize_code(code)
        if frame is None or frame.empty: return []
        prepared, _rejected = partition_valid_ohlc_rows(self._prepare_quote_frame(frame))
        if prepared.empty:
            return []
        return [
            (trade_date, code, *values, source, receipt_id)
            for trade_date, values in zip(
                prepared["trade_date"].tolist(),
                zip(*quote_value_columns(prepared), strict=True),
                strict=True,
            )
        ]

    def _quote_payload_from_bars(
        self,
        bars: Iterable[dict[str, Any]],
        *,
        source: str,
        receipt_ids: Mapping[str, str] | None = None,
    ) -> list[tuple[Any, ...]]:
        return quote_payload_from_bars(bars, source=source, receipt_ids=receipt_ids)

    def _write_quote_payload(
        self,
        payload: list[tuple[Any, ...]],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        if not payload: return 0
        if cursor is None:
            with self._transaction() as tx:
                return self._write_quote_payload(payload, cursor=tx)
        written = write_quote_payload(cursor, payload)
        self._bump_revisions(cursor, "quotes")
        return written

    def set_watermarks(
        self,
        rows: Iterable[tuple[str, str]],
        *,
        status: str = "ok",
        source: str = "",
        sources: Mapping[str, str] | None = None,
        message: str = "",
    ) -> int:
        """批量更新 ingest_watermark（code, last_trade_date）。

        ``last_synced_at`` 按本地交易日写入，需与同步侧的 ``date.today()``
        使用同一个日历，避免 UTC 午夜后把刚同步的数据误判为昨天。

        ``sources`` 给每票单独指定来源。粘性竞速会让同一批里 tdx / tencent 混着
        出现,只有一个标量 ``source`` 表达不了——同步侧真正需要的就是这个重载,
        缺了它就只能退回逐票写,一次全市场同步 = 5500 多个独立事务。
        """
        by_code = dict(sources or {})
        payload = [
            (
                normalize_code(code),
                trade_date,
                status,
                message[:500],
                by_code.get(code, by_code.get(normalize_code(code), source)),
            )
            for code, trade_date in rows
            if code and trade_date
        ]
        if not payload:
            return 0
        with self._transaction() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingest_watermark(code, last_trade_date, last_synced_at,
                                             status, message, source)
                VALUES(?, ?, datetime('now', 'localtime'), ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    last_trade_date=CASE WHEN excluded.last_trade_date <> ''
                                         THEN excluded.last_trade_date
                                         ELSE ingest_watermark.last_trade_date END,
                    last_synced_at=excluded.last_synced_at,
                    status=excluded.status, message=excluded.message,
                    source=excluded.source
                """,
                payload,
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
        """把数据源返回的列名归一，并把日期统一成 YYYY-MM-DD 文本。

        只挑要落库的列重建一张帧，不先 ``copy()`` 整张源表再裁：源表常带一堆用不上
        的列，250 行帧上实测 1.05 ms → 0.65 ms。数值列保持原 dtype，NaN → NULL 留给
        ``quote_value_columns``——整帧 ``astype(object).where(...)`` 自身要 0.44 ms，
        还会让随后 OHLC 校验的 ``to_numeric`` 多花 0.27 ms。
        """
        columns = {str(column).strip().lower(): column for column in frame.columns}
        date_column = columns.get("date") or columns.get("trade_date")
        if date_column is None:
            raise MarketError("行情数据缺少日期列")
        # 各源的 date 列要么是 ``datetime.date`` 对象（sina/tencent/eastmoney），
        # 要么是 ``YYYY-MM-DD`` 文本（tdx/baostock/daily_merge 归一后），一律
        # year-first。显式 format 跳过逐值推断，同时避免「按首值定格式、其余静默
        # 变 NaT」；真遇到非 ISO 的日期这里会直接抛，而不是安静丢一整列。
        data: dict[str, Any] = {
            "trade_date": pd.to_datetime(
                frame[date_column], format="ISO8601"
            ).dt.strftime("%Y-%m-%d")
        }
        for field in PANEL_FIELDS:
            # 缺列的源补 NULL；写入 SQL 的 COALESCE 保证它不会抹掉库里已有的值。
            source_column = columns.get(field)
            data[field] = frame[source_column] if source_column is not None else None
        out = pd.DataFrame(data, index=frame.index)
        return out.drop_duplicates(subset=["trade_date"], keep="last")

    def upsert_adjust_factors(self, code: str, frame: pd.DataFrame, *, source: str = "") -> int:
        """写入稀疏的后复权因子。frame 需含 date 与 hfq_factor 两列。"""
        code = normalize_code(code)
        if frame is None or frame.empty: return 0
        out = frame.copy()
        out.columns = [str(col).strip().lower() for col in out.columns]
        if "date" in out.columns:
            out = out.rename(columns={"date": "trade_date"})
        # 复权因子的 date 同样是 ``datetime.date``（sina 侧已 ``.dt.date``）或
        # ``YYYY-MM-DD`` 文本；理由同 _prepare_quote_frame。
        out["trade_date"] = pd.to_datetime(
            out["trade_date"], format="ISO8601"
        ).dt.strftime("%Y-%m-%d")
        payload = [
            (code, str(row.trade_date), float(row.hfq_factor), source)
            for row in out.itertuples(index=False)
            if pd.notna(row.hfq_factor)
        ]
        if not payload: return 0
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
            self._bump_revisions(cursor, "adjust_factors")
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
                VALUES(?, ?, datetime('now', 'localtime'), ?, ?, ?)
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

    def instruments_meta(self, codes: Iterable[str]) -> dict[str, dict[str, str]]:
        """按代码批量取名称/板块/行业，返回 ``{code: {...}}``。

        给跨上下文的调用方用：它们既不该直连 ``market.conn``，也不该为了几十个
        代码去拉 `list_instruments()` 的全表（约 5500 行）。逐 code 单查同样不行，
        日终复盘那种几十票的场景会打出几十次查询。
        """
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        if not wanted:
            return {}
        out: dict[str, dict[str, str]] = {}
        for offset in range(0, len(wanted), 900):
            chunk = wanted[offset : offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT code, name, board, industry FROM instruments"
                f" WHERE code IN ({placeholders})",
                chunk,
            )
            for row in rows:
                out[str(row["code"])] = {
                    "name": str(row["name"] or ""),
                    "board": str(row["board"] or ""),
                    "industry": str(row["industry"] or ""),
                }
        return out

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
        if days:
            return days
        # 带 start/end 的空结果只表示窗口内无交易日（例如热库尚未写入下一交易日），
        # 绝不能当成「日历表缺失」去 SELECT DISTINCT 全表重建——会把日终/预案拖死数十分钟。
        if start or end:
            has_calendar = self.conn.execute(
                "SELECT 1 FROM trading_calendar LIMIT 1"
            ).fetchone()
            if has_calendar:
                return []
        if self.conn.execute("SELECT 1 FROM quotes_daily LIMIT 1").fetchone():
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
        limit: int | None = None,
    ) -> pd.DataFrame:
        """单票日线，按需复权。用于 K 线展示与单票分析。

        ``limit``：只取截止 ``end``（或缺省时最新）最近 N 根，避免龙头地图等热路径
        拉全量历史再 Python ``tail``。
        """
        code = normalize_code(code)
        params: list[Any] = [code]
        where = "code = ?"
        if start:
            where += " AND trade_date >= ?"
            params.append(start)
        if end:
            where += " AND trade_date <= ?"
            params.append(end)
        if limit is not None and int(limit) > 0:
            # 先按日期倒序截断，再升序还原，保证复权与下游时序假定。
            sql = (
                "SELECT * FROM ("
                f"SELECT * FROM quotes_daily WHERE {where} "
                "ORDER BY trade_date DESC LIMIT ?"
                ") AS recent ORDER BY trade_date"
            )
            params.append(int(limit))
        else:
            sql = f"SELECT * FROM quotes_daily WHERE {where} ORDER BY trade_date"
        frame = pd.read_sql_query(sql, self.conn, params=params)
        if frame.empty or adjust == "none":
            return frame
        factors = self._factor_series(code, frame["trade_date"])
        ratio = self._adjust_ratio(factors, adjust)
        for column in PRICE_FIELDS:
            frame[column] = frame[column] * ratio.to_numpy()
        return frame

    def history_many(
        self,
        codes: list[str],
        *,
        end: str | None = None,
        adjust: str = "qfq",
        limit: int = 80,
    ) -> dict[str, pd.DataFrame]:
        """批量最近 N 根日 K：一次 ``code IN (...)`` 再按票截断。

        缺票不出现在返回 dict；调用方再走 routed 补齐。复权按票独立算。
        """
        cleaned = [normalize_code(code) for code in codes if str(code or "").strip()]
        cleaned = list(dict.fromkeys(cleaned))
        if not cleaned or int(limit) <= 0:
            return {}
        placeholders = ",".join("?" for _ in cleaned)
        params: list[Any] = list(cleaned)
        where = f"code IN ({placeholders})"
        if end:
            where += " AND trade_date <= ?"
            params.append(end)
        # 窗口函数按票倒序编号，一次取出每票最近 limit 根。
        sql = (
            "SELECT * FROM ("
            f"SELECT q.*, ROW_NUMBER() OVER ("
            "PARTITION BY code ORDER BY trade_date DESC"
            f") AS rn FROM quotes_daily q WHERE {where}"
            ") AS ranked WHERE rn <= ? ORDER BY code, trade_date"
        )
        params.append(int(limit))
        frame = pd.read_sql_query(sql, self.conn, params=params)
        if frame.empty:
            return {}
        if "rn" in frame.columns:
            frame = frame.drop(columns=["rn"])
        out: dict[str, pd.DataFrame] = {}
        for code, group in frame.groupby("code", sort=False):
            part = group.reset_index(drop=True)
            if adjust != "none" and not part.empty:
                factors = self._factor_series(str(code), part["trade_date"])
                ratio = self._adjust_ratio(factors, adjust)
                for column in PRICE_FIELDS:
                    part[column] = part[column] * ratio.to_numpy()
            out[str(code)] = part
        return out

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
        merged = sparse.reindex(sparse.index.union(index.unique())).ffill().bfill()
        return merged.reindex(index.unique()).reindex(index)

    @staticmethod
    def _adjust_ratio(factors: pd.Series, adjust: str) -> pd.Series:
        if adjust == "hfq":
            return factors
        if adjust == "qfq":
            # 前复权 = 后复权价 / 最新因子，使最新一根等于真实成交价。
            latest = float(factors.iloc[-1]) if len(factors) else 1.0
            return factors / (latest or 1.0)
        raise MarketError(f"不支持的复权方式：{adjust}")
