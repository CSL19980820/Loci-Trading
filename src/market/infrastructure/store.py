"""行情仓的存储层：schema、写入、面板加载。

设计上的三个关键决定：

1. **存不复权原始价 + 稀疏复权因子，不存固化的复权价。**
   前复权价会随每一次新的除权除息整体变化。若入库时就把复权价算死，
   下一次除权后全部历史缓存都会静默错误（"应该变但没变"）。
   改为存原始价，另存一张只在除权日有行的 adjust_factors，读时前向填充
   再算复权价——历史永不失效，新的除权只追加一行。

2. **quotes_daily 按 (trade_date, code) 聚簇（WITHOUT ROWID）。**
   最热的查询是"取某个日期区间、全市场所有票"来做向量化选股，按日期
   聚簇能让它变成顺序扫描。按代码取单票历史的场景走二级索引。

3. **面板 (panel) 是引擎的输入格式：DataFrame(index=trade_date, columns=code)。**
   通达信公式在这个形状上全部可以向量化：REF 是 shift、MA 是 rolling.mean，
   一次操作覆盖全市场几千只票，走 pandas 的 C 路径而不是 Python 循环。
   这是"通达信选得快、我们选得慢"这个问题的根本解法。

实现拆分：
- ``store_codes`` — normalize_code / guess_market / to_sina_symbol
- ``store_schema`` — DDL 与字段常量
- ``store_rw`` — 写入与基础读取
- ``store_panel`` — 全市场面板
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3

from src.market.infrastructure.store_codes import (
    INDEX_MARKETS,
    MarketError,
    guess_market,
    normalize_code,
    to_sina_symbol,
)
from src.market.infrastructure.store_board_page import MarketBoardPageMixin
from src.market.infrastructure.store_panel import MarketPanelMixin
from src.market.infrastructure.store_rw import MarketRwMixin
from src.market.infrastructure.store_schema import (
    DEFAULT_DB,
    PANEL_FIELDS,
    PRICE_FIELDS,
    RAW_FIELDS,
    SCHEMA_VERSION,
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


class MarketStore(MarketRwMixin, MarketBoardPageMixin, MarketPanelMixin):
    """行情仓连接。与 PalaceStore 一样，每个请求/任务持有独立连接。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        # busy_timeout 必须最先设：切 WAL 本身要拿排他锁，多个 worker 同时
        # 建连接时会撞上，没有 timeout 就是立刻 "database is locked"。
        self.conn.execute("PRAGMA busy_timeout=30000")
        # WAL：批量写行情与读面板可以并行，不互相阻塞。
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        # 同一进程内只跑一次 DDL：同步任务会开几十条连接，让每条都执行
        # 一遍 executescript 纯属自找锁竞争。
        key = str(self.db_path.resolve())
        if key not in _SCHEMA_READY:
            self.init_schema()
            _SCHEMA_READY.add(key)

    def close(self) -> None:
        self.conn.close()

    def data_snapshot(self) -> dict[str, object]:
        """返回可复现但不暴露本地路径的行情仓版本摘要。"""
        quotes = self._time_series_snapshot(
            "quotes_daily",
            timestamp_column="fetched_at",
        )
        adjust_factors = self._time_series_snapshot(
            "adjust_factors",
            timestamp_column="fetched_at",
        )
        adjust_factors["content_digest"] = self._revision_digest("adjust_factors_revision")
        instruments = self._instrument_snapshot()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "rows": int(quotes["rows"]),
            "last_date": str(quotes["last_date"]),
            "fetched_at": str(quotes["fetched_at"]),
            "quotes": quotes,
            "adjust_factors": adjust_factors,
            "instruments": instruments,
        }
        return {
            **payload,
            "market_revision": self._revision_digest("market_revision"),
        }

    def __enter__(self) -> MarketStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

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

    def _time_series_snapshot(
        self,
        table: str,
        *,
        timestamp_column: str,
        revision_key: str | None = None,
    ) -> dict[str, object]:
        row = self.conn.execute(
            f"SELECT COUNT(*) AS rows, MAX(trade_date) AS last_date, "
            f"MAX({timestamp_column}) AS last_updated_at FROM {table}"
        ).fetchone()
        snapshot = {
            "rows": int(row["rows"] or 0),
            "last_date": str(row["last_date"] or ""),
            "fetched_at": str(row["last_updated_at"] or ""),
        }
        if revision_key is not None:
            snapshot["content_digest"] = self._revision_digest(revision_key)
        return snapshot

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

    @staticmethod
    def _migrate_schema(cursor: sqlite3.Cursor) -> None:
        """兼容旧库：补列（IF NOT EXISTS 语义用 pragma 判断）。"""
        cols = {str(row[1]) for row in cursor.execute("PRAGMA table_info(instruments)")}
        if "industry" not in cols:
            cursor.execute(
                "ALTER TABLE instruments ADD COLUMN industry TEXT NOT NULL DEFAULT ''"
            )
