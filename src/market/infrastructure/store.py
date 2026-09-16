"""行情仓连接、schema 生命周期与可复现快照。"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3

from src.market.infrastructure.store_board_page import MarketBoardPageMixin
from src.market.infrastructure.store_codes import (
    INDEX_MARKETS,
    MarketError,
    guess_market,
    normalize_code,
    to_sina_symbol,
)
from src.market.infrastructure.store_panel import MarketPanelMixin
from src.market.infrastructure.store_provenance import MarketProvenanceMixin
from src.market.infrastructure.store_rw import MarketRwMixin
from src.market.infrastructure.store_summary import MarketSummaryMixin
from src.market.infrastructure.store_schema import (
    DEFAULT_DB,
    PANEL_FIELDS,
    PRICE_FIELDS,
    RAW_FIELDS,
    SCHEMA_VERSION,
    _INTEL_SNAPSHOTS_DDL,
    _SCHEMA,
    _SCHEMA_READY,
)

__all__ = [
    "DEFAULT_DB",
    "INDEX_MARKETS",
    "MarketError",
    "MarketStore",
    "PANEL_FIELDS",
    "PRICE_FIELDS",
    "RAW_FIELDS",
    "SCHEMA_VERSION",
    "guess_market",
    "normalize_code",
    "to_sina_symbol",
]


class MarketStore(
    MarketRwMixin,
    MarketSummaryMixin,
    MarketProvenanceMixin,
    MarketBoardPageMixin,
    MarketPanelMixin,
):
    """行情仓连接。每个请求或同步 worker 持有独立连接。"""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        keep_receipt_index: bool = False,
    ) -> None:
        """``keep_receipt_index`` 只有热库该开。

        ``idx_quotes_receipt`` 唯一的热路径消费者是 ``store_hot._purge_orphan_receipts``
        的 ``NOT EXISTS`` 逐行探测，而那段只跑在热库。在权威库上它实测占
        **1,049 MB**（2026-08-25 dbstat，全库 5,740 MB 的 18%），却只服务
        「无范围 DISTINCT receipt_id」这一条本就被禁止的全库扫。
        见 docs/research/2026-08-mainstream-quant-benchmark.md §2.1。
        """
        self._keep_receipt_index = bool(keep_receipt_index)
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 选股与同步可能并发碰同一 market.db；60s busy 比默认 30s 更扛得住短写锁。
        self.conn = sqlite3.connect(self.db_path, timeout=60.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=60000")
        # 已是 WAL 就不要再 PRAGMA journal_mode=WAL（那是写锁）；否则同步占库时
        # 连「只读打开选股」都会在 init 阶段卡死。
        mode = ""
        try:
            mode = str(self.conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
        except sqlite3.Error:
            mode = ""
        if mode != "wal":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        key = str(self.db_path.resolve())
        if key not in _SCHEMA_READY:
            # schema 已是当前版本则跳过迁移写事务，避免与长同步抢写锁。
            if not self._schema_is_current():
                self.init_schema()
            _SCHEMA_READY.add(key)

    def _schema_is_current(self) -> bool:
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", ("schema_version",)
            ).fetchone()
            return bool(row) and str(row[0]) == str(SCHEMA_VERSION)
        except sqlite3.Error:
            return False

    def close(self) -> None:
        self.conn.close()

    def data_snapshot(
        self,
        *,
        codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        include_source_details: bool = True,
    ) -> dict[str, object]:
        """返回研究可复现的行情仓摘要，不暴露本地缓存路径。"""
        quotes = self._time_series_snapshot("quotes_daily", timestamp_column="fetched_at")
        adjust_factors = self._time_series_snapshot(
            "adjust_factors", timestamp_column="fetched_at"
        )
        adjust_factors["content_digest"] = self._revision_digest("adjust_factors_revision")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "rows": int(quotes["rows"]),
            "last_date": str(quotes["last_date"]),
            "fetched_at": str(quotes["fetched_at"]),
            "quotes": quotes,
            "adjust_factors": adjust_factors,
            "instruments": self._instrument_snapshot(),
            "source_evidence": self.source_evidence(
                codes=codes, start=start, end=end,
                **({"include_details": False} if not include_source_details else {}),
            ),
        }
        return {**payload, "market_revision": self._revision_digest("market_revision")}

    def market_revision(self) -> str:
        """行情仓内容版本号，只读一行 meta。

        只想判断"这份结果是不是在当前行情快照上算的"时用它，不要为此调
        ``data_snapshot()``——后者会连带跑无范围的 ``source_evidence``，那是
        对 quotes_daily 的 DISTINCT 全表扫描加全量回执装载。
        """
        return self._revision_digest("market_revision")

    def __enter__(self) -> MarketStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            # IMMEDIATE：所有 _transaction 都是写事务。用默认的 DEFERRED 时，
            # WAL 下「先读后写」的事务在别的连接中途提交后升级写锁会直接
            # SQLITE_BUSY，且 busy_timeout 对这种快照失效无效。
            cursor.execute("BEGIN IMMEDIATE")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def ensure_intel_snapshots_schema(self) -> None:
        """intel 域 MCP 快照表（可重建）；旧库首次访问 intel 缓存时幂等补齐。"""
        for sql in _INTEL_SNAPSHOTS_DDL:
            self.conn.execute(sql)

    def init_schema(self) -> None:
        with self._transaction() as cursor:
            cursor.executescript(_SCHEMA)
            self._migrate_schema(cursor)
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(SCHEMA_VERSION),),
            )
            for key in (
                "market_revision",
                "quotes_revision",
                "adjust_factors_revision",
                "instruments_revision",
            ):
                cursor.execute(
                    "INSERT INTO meta(key, value, updated_at) VALUES(?, '0', datetime('now'))"
                    " ON CONFLICT(key) DO NOTHING",
                    (key,),
                )

    def _time_series_snapshot(self, table: str, *, timestamp_column: str) -> dict[str, object]:
        # quotes_daily 千万行：禁止每次 data_snapshot 全表 COUNT/MAX。
        if table == "quotes_daily":
            return self._quotes_daily_snapshot_fast()
        row = self.conn.execute(
            f"SELECT COUNT(*) AS rows, MAX(trade_date) AS last_date, "
            f"MAX({timestamp_column}) AS last_updated_at FROM {table}"
        ).fetchone()
        return {
            "rows": int(row["rows"] or 0),
            "last_date": str(row["last_date"] or ""),
            "fetched_at": str(row["last_updated_at"] or ""),
        }

    def _quotes_daily_snapshot_fast(self) -> dict[str, object]:
        """日 K 水位：日历末日 + 行数 meta 缓存 + quotes_revision 时间戳。"""
        cal = self.conn.execute(
            "SELECT MAX(trade_date) AS last_date FROM trading_calendar"
        ).fetchone()
        last_date = str(cal["last_date"] or "") if cal else ""
        if not last_date:
            row = self.conn.execute(
                "SELECT COUNT(*) AS rows, MAX(trade_date) AS last_date, "
                "MAX(fetched_at) AS last_updated_at FROM quotes_daily"
            ).fetchone()
            return {
                "rows": int(row["rows"] or 0),
                "last_date": str(row["last_date"] or ""),
                "fetched_at": str(row["last_updated_at"] or ""),
            }
        rev = self.conn.execute(
            "SELECT value, updated_at FROM meta WHERE key = 'quotes_revision'"
        ).fetchone()
        fetched_at = str(rev["updated_at"] or "") if rev else ""
        return {
            "rows": self._cached_quote_row_count(last_date),
            "last_date": last_date,
            "fetched_at": fetched_at,
        }

    def _instrument_snapshot(self) -> dict[str, object]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS rows, MAX(updated_at) AS last_updated_at FROM instruments"
        ).fetchone()
        return {
            "rows": int(row["rows"] or 0),
            "updated_at": str(row["last_updated_at"] or ""),
            "content_digest": self._revision_digest("instruments_revision"),
        }

    def _revision_digest(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        revision = str(row["value"] if row else "0")
        return hashlib.sha256(f"{key}:{revision}".encode("utf-8")).hexdigest()

    def _migrate_schema(self, cursor: sqlite3.Cursor) -> None:
        """兼容旧库的追加式列迁移；receipt 表的完整 DDL 位于 store_schema。"""
        instrument_cols = {str(row[1]) for row in cursor.execute("PRAGMA table_info(instruments)")}
        if "industry" not in instrument_cols:
            cursor.execute("ALTER TABLE instruments ADD COLUMN industry TEXT NOT NULL DEFAULT ''")
        quote_cols = {str(row[1]) for row in cursor.execute("PRAGMA table_info(quotes_daily)")}
        if "receipt_id" not in quote_cols:
            cursor.execute("ALTER TABLE quotes_daily ADD COLUMN receipt_id TEXT")
        # 权威库上这个索引实测 1,049 MB 却没有热路径消费者，schema v8 起只在热库建。
        # DROP 只把页归还给库内空闲链；要真正缩小文件得 `python -m cli.market reclaim`。
        if self._keep_receipt_index:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_quotes_receipt ON quotes_daily(receipt_id)"
            )
        else:
            cursor.execute("DROP INDEX IF EXISTS idx_quotes_receipt")
        receipt_cols = {
            str(row[1]) for row in cursor.execute("PRAGMA table_info(source_route_receipts)")
        }
        for column in (
            "coverage_start",
            "coverage_end",
            "request_start",
            "request_end",
            "source_url",
            "published_at",
            "fetched_at",
            "as_of",
            "payload_sha256",
            "parser_revision",
            "available_at",
        ):
            if column not in receipt_cols:
                cursor.execute(
                    f"ALTER TABLE source_route_receipts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        for column in ("publication_status", "availability_status"):
            if column not in receipt_cols:
                cursor.execute(
                    f"ALTER TABLE source_route_receipts ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT 'not_observed'"
                )
        attempt_cols = {
            str(row[1]) for row in cursor.execute("PRAGMA table_info(source_route_attempts)")
        }
        for column in (
            "source_url",
            "published_at",
            "fetched_at",
            "as_of",
            "payload_sha256",
            "parser_revision",
            "available_at",
        ):
            if column not in attempt_cols:
                cursor.execute(
                    f"ALTER TABLE source_route_attempts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        for column in ("publication_status", "availability_status"):
            if column not in attempt_cols:
                cursor.execute(
                    f"ALTER TABLE source_route_attempts ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT 'not_observed'"
                )
        # 旧库补索引（CREATE IF NOT EXISTS，可重复执行；receipt 列已在上面补齐）
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_receipts_lane_state "
            "ON source_route_receipts(lane, state, unresolved)"
        )
        for sql in _INTEL_SNAPSHOTS_DDL:
            cursor.execute(sql)
