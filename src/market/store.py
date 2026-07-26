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
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = PROJECT_ROOT / ".market" / "market.db"

SCHEMA_VERSION = 1

#: 面板字段 -> quotes_daily 列名。价格类字段会按复权方式换算，量额类不换算。
PRICE_FIELDS = ("open", "high", "low", "close")
RAW_FIELDS = ("volume", "amount", "turnover", "outstanding_share")
PANEL_FIELDS = PRICE_FIELDS + RAW_FIELDS


class MarketError(RuntimeError):
    """行情仓自身的可预期错误，调用方应转成 4xx 而不是 500。"""


def normalize_code(value: str) -> str:
    """统一成 6 位数字代码。接受 '600519' / 'sh600519' / '600519.SH'。"""
    text = str(value).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    text = text.split(".")[0]
    if not (len(text) == 6 and text.isdigit()):
        raise MarketError(f"非法证券代码：{value}")
    return text


#: 指数代码无法只靠前缀判断（000300 在上交所，而 000001 既是上证指数
#: 也是平安银行的代码）。把要用的基准指数显式列出来，避免猜错。
INDEX_MARKETS = {
    "000001": "sh",  # 上证指数
    "000300": "sh",  # 沪深300
    "000905": "sh",  # 中证500
    "000852": "sh",  # 中证1000
    "000016": "sh",  # 上证50
    "399001": "sz",  # 深证成指
    "399006": "sz",  # 创业板指
    "399005": "sz",  # 中小板指
}


def guess_market(code: str, *, instrument_type: str = "STOCK") -> str:
    """由代码前缀推断交易所，仅用于拼接数据源需要的带前缀符号。"""
    code = normalize_code(code)
    if instrument_type == "INDEX":
        if code in INDEX_MARKETS:
            return INDEX_MARKETS[code]
        return "sz" if code.startswith("39") else "sh"
    if code.startswith(("60", "68", "90")):  # 主板 / 科创板 / B股
        return "sh"
    if code.startswith(("4", "8", "92")):  # 北交所
        return "bj"
    return "sz"  # 00 主板 / 30 创业板 / 20 B股


def to_sina_symbol(code: str, *, instrument_type: str = "STOCK") -> str:
    """'600519' -> 'sh600519'。新浪与通达信都用这种带前缀的写法。"""
    code = normalize_code(code)
    return f"{guess_market(code, instrument_type=instrument_type)}{code}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    market          TEXT NOT NULL DEFAULT '',
    board           TEXT NOT NULL DEFAULT '',
    instrument_type TEXT NOT NULL DEFAULT 'STOCK'
                    CHECK (instrument_type IN ('STOCK', 'INDEX')),
    list_date       TEXT NOT NULL DEFAULT '',
    delist_date     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'normal'
                    CHECK (status IN ('normal', 'suspended', 'delisted')),
    updated_at      TEXT NOT NULL
);

-- 不复权原始价。按 (trade_date, code) 聚簇，让全市场日期区间扫描变顺序读。
CREATE TABLE IF NOT EXISTS quotes_daily (
    trade_date          TEXT NOT NULL,
    code                TEXT NOT NULL,
    open                REAL,
    high                REAL,
    low                 REAL,
    close               REAL,
    volume              REAL,
    amount              REAL,
    outstanding_share   REAL,
    turnover            REAL,
    source              TEXT NOT NULL DEFAULT '',
    fetched_at          TEXT NOT NULL,
    PRIMARY KEY (trade_date, code)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_quotes_code_date ON quotes_daily(code, trade_date);

-- 稀疏表：只有除权除息日才有行。读时前向填充。
CREATE TABLE IF NOT EXISTS adjust_factors (
    code        TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    hfq_factor  REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (code, trade_date)
) WITHOUT ROWID;

-- 交易日历。看似冗余（日期都在 quotes_daily 里），但 SELECT DISTINCT
-- trade_date 是全表扫描：400 只票时 0.6s，全市场会涨到近 10s，而选股、
-- T+N 复盘、回测每次都要问"有哪些交易日"。单独一张几千行的小表，
-- 把这个高频问题从 O(行数) 降到 O(交易日数)。
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date  TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL
) WITHOUT ROWID;

-- 增量同步的断点：全量回填中断后可从这里续跑。
CREATE TABLE IF NOT EXISTS ingest_watermark (
    code            TEXT PRIMARY KEY,
    last_trade_date TEXT NOT NULL DEFAULT '',
    last_synced_at  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'ok',
    message         TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_watermark_status ON ingest_watermark(status);
"""


#: 进程内已建过 schema 的库路径。仅用于省掉重复 DDL，不是正确性依赖：
#: 表全部是 CREATE ... IF NOT EXISTS，重复执行也只是浪费一次锁。
_SCHEMA_READY: set[str] = set()


def _consolidate(panel: pd.DataFrame) -> pd.DataFrame:
    """把面板压成单块连续内存。**这是整个引擎最关键的一行性能代码。**

    ``DataFrame.pivot()`` 返回的对象内部是**每列一个 block**：全市场面板
    有 5509 列，就有 5509 个块。此后每一次 shift / 加减乘除，pandas 都要
    在 Python 层遍历这 5509 个块，而不是对一整块内存做一次向量运算。

    实测 60×5509 的面板（才 330 万个浮点数，numpy 做一次加法是微秒级）：

        操作          pivot 产物    合并后
        shift(1)       98.55 ms    0.60 ms   （164 倍）
        乘常数         79.98 ms    0.60 ms   （133 倍）
        逐元素相加    138.86 ms    1.00 ms   （139 倍）

    合并后与裸 numpy 完全同速。不做这一步，"面板向量化"的全部优势都会被
    块遍历的开销吃光——全市场选股会从秒级退化到半分钟。
    """
    values = panel.to_numpy(dtype=float)
    return pd.DataFrame(values, index=panel.index, columns=panel.columns)


class MarketStore:
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

    # ---- 生命周期 -------------------------------------------------

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

    # ---- 写入 -----------------------------------------------------

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

    # ---- 读取 -----------------------------------------------------

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

    # ---- 面板：向量化引擎的输入 -----------------------------------

    def load_panel(
        self,
        *,
        fields: Sequence[str] = ("open", "high", "low", "close", "volume", "turnover"),
        codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        adjust: str = "qfq",
        min_bars: int = 0,
    ) -> dict[str, pd.DataFrame]:
        """加载全市场面板：{字段: DataFrame(index=trade_date, columns=code)}。

        这是选股与回测的统一输入。之所以要这个形状，是因为通达信公式里的
        REF/MA/HHV/COUNT 在它上面都是一次 pandas 操作就覆盖全市场，
        而不是对每只票跑一遍 Python 循环——数量级的差别就在这里。

        min_bars: 丢弃有效 K 线不足该根数的票（次新股会让指标全是 NaN，
                  留着只会污染筛选结果）。
        """
        unknown = [field for field in fields if field not in PANEL_FIELDS]
        if unknown:
            raise MarketError(f"不支持的面板字段：{unknown}")

        needed = list(dict.fromkeys(fields))
        # 复权要用 close 之外的价格列时，仍只需按 code 取因子，与字段无关。
        columns = ", ".join(["trade_date", "code", *needed])
        sql = f"SELECT {columns} FROM quotes_daily WHERE 1=1"
        params: list[Any] = []
        if start:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            params.append(end)
        if codes:
            normalized = [normalize_code(code) for code in codes]
            sql += f" AND code IN ({','.join('?' * len(normalized))})"
            params.extend(normalized)

        flat = pd.read_sql_query(sql, self.conn, params=params)
        if flat.empty:
            return {field: pd.DataFrame() for field in needed}

        panels: dict[str, pd.DataFrame] = {}
        for field in needed:
            panel = flat.pivot(index="trade_date", columns="code", values=field)
            panel.index = pd.Index(panel.index, name="trade_date")
            panels[field] = panel.sort_index()

        if min_bars > 0:
            reference = panels.get("close")
            if reference is None:
                reference = next(iter(panels.values()))
            keep = reference.notna().sum(axis=0) >= min_bars
            kept = reference.columns[keep]
            panels = {field: panel[kept] for field, panel in panels.items()}

        price_fields = [field for field in needed if field in PRICE_FIELDS]
        if price_fields and adjust != "none":
            ratio = _consolidate(self._factor_panel(panels[price_fields[0]], adjust))
            for field in price_fields:
                panels[field] = panels[field] * ratio
        # 合并必须放在**所有**变换之后：pivot、列筛选、复权乘法中的任何一步
        # 都会让结果重新变成每列一个内存块。见 _consolidate 的说明。
        return {field: _consolidate(panel) for field, panel in panels.items()}

    def _factor_panel(self, reference: pd.DataFrame, adjust: str) -> pd.DataFrame:
        """构造与面板同形的复权比例矩阵，一次性乘上去。"""
        rows = self.conn.execute(
            "SELECT code, trade_date, hfq_factor FROM adjust_factors ORDER BY code, trade_date"
        ).fetchall()
        ratio = pd.DataFrame(1.0, index=reference.index, columns=reference.columns)
        if not rows:
            return ratio
        sparse = pd.DataFrame(
            [(str(row["code"]), str(row["trade_date"]), float(row["hfq_factor"])) for row in rows],
            columns=["code", "trade_date", "hfq_factor"],
        )
        sparse = sparse[sparse["code"].isin(set(reference.columns))]
        if sparse.empty:
            return ratio
        wide = sparse.pivot(index="trade_date", columns="code", values="hfq_factor")
        aligned = (
            wide.reindex(wide.index.union(reference.index))
            .sort_index()
            .ffill()
            .bfill()
            .reindex(reference.index)
            .reindex(columns=reference.columns)
        )
        aligned = aligned.astype(float).fillna(1.0)
        if adjust == "hfq":
            return aligned
        if adjust == "qfq":
            latest = aligned.iloc[-1].replace(0.0, 1.0)
            return aligned.div(latest, axis=1)
        raise MarketError(f"不支持的复权方式：{adjust}")
