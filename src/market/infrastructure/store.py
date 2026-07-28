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
from pathlib import Path
import sqlite3

from src.market.infrastructure.store_codes import (
    INDEX_MARKETS,
    MarketError,
    guess_market,
    normalize_code,
    to_sina_symbol,
)
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


class MarketStore(MarketRwMixin, MarketPanelMixin):
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
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(SCHEMA_VERSION),),
            )
