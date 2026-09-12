"""MarketStore：全市场面板加载与内存块合并。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import sqlite3

import pandas as pd

from src.market.infrastructure.duckdb_panel import (
    duckdb_panel_enabled,
    read_quotes_flat_duckdb,
)
from src.market.infrastructure.polars_panel import (
    polars_panel_enabled,
    read_quotes_flat_polars,
)
from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_panel_window import cached_raw_panels
from src.market.infrastructure.store_schema import PANEL_FIELDS, PRICE_FIELDS


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


def _require_bounded_range(
    codes: Sequence[str] | None,
    start: str | None,
    end: str | None,
) -> None:
    """拒绝无范围的面板查询：codes / start / end 一个都不给 = 全库扫。

    `quotes_daily` 按 `(trade_date, code)` 聚簇、生产库 1600 万+ 行。三个范围
    参数全空时 where 子句是空串，SQL 退化成 `SELECT ... FROM quotes_daily
    WHERE 1=1`——全表一次性进 pandas（8 列 × 千万行），既吃穿内存又在写锁存在
    时把库拖成 `disk I/O error`。README「查询纪律」里的「选股必须传 codes+窗口」
    在这里从约定变成硬约束：小库上跑得通不代表生产库上跑得通，默认值不该是
    「扫全库」。
    """
    if codes or start or end:
        return
    raise MarketError(
        "load_panel 必须限定范围：codes（股票池）、start、end 至少给一个。"
        "三者全空会退化成对 quotes_daily（千万行）的无 LIMIT 全表扫描并整表进 pandas。"
        "选股/回测请传 codes + start + end；确需全市场截面时至少传 start（可再加 end）。"
    )


class MarketPanelMixin:
    """load_panel / 复权比例矩阵。依赖宿主提供 conn。"""

    conn: sqlite3.Connection

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

        **必须限定范围**：codes / start / end 至少给一个，否则直接报错，
        见 `_require_bounded_range`——这不是参数校验洁癖，是这张表的物理约束。
        """
        unknown = [field for field in fields if field not in PANEL_FIELDS]
        if unknown:
            raise MarketError(f"不支持的面板字段：{unknown}")
        _require_bounded_range(codes, start, end)

        needed = list(dict.fromkeys(fields))
        # 复权要用 close 之外的价格列时，仍只需按 code 取因子，与字段无关。
        columns = ", ".join(["trade_date", "code", *needed])
        where_sql = ""
        params: list[Any] = []
        if start:
            where_sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            where_sql += " AND trade_date <= ?"
            params.append(end)
        if codes:
            normalized = [normalize_code(code) for code in codes]
            where_sql += f" AND code IN ({','.join('?' * len(normalized))})"
            params.extend(normalized)

        if not needed:
            exists = self.conn.execute(
                f"SELECT 1 FROM quotes_daily WHERE 1=1{where_sql} LIMIT 1", params,
            ).fetchone()
            if exists and min_bars > 0:
                raise StopIteration
            return {}

        panels = cached_raw_panels(self, needed, codes=codes, start=start, end=end)
        if panels is None:
            panels = self._read_raw_panels(needed, columns, where_sql, params)
        if not panels or all(panel.empty for panel in panels.values()):
            return panels

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
        # 合并放在列筛选和复权之后，避免重新生成逐列内存块。
        return {field: _consolidate(panel) for field, panel in panels.items()}

    def _read_raw_panels(
        self, needed: list[str], columns: str, where_sql: str, params: list[Any],
    ) -> dict[str, pd.DataFrame]:
        flat: pd.DataFrame | None = None
        if polars_panel_enabled():
            flat = read_quotes_flat_polars(
                self.conn,
                columns_sql=columns,
                where_sql=where_sql,
                params=params,
            )
        if flat is None and duckdb_panel_enabled():
            flat = read_quotes_flat_duckdb(
                self.conn,
                columns_sql=columns,
                where_sql=where_sql,
                params=params,
            )
        if flat is None:
            sql = f"SELECT {columns} FROM quotes_daily WHERE 1=1{where_sql}"
            flat = pd.read_sql_query(sql, self.conn, params=params)
        if flat.empty:
            return {field: pd.DataFrame() for field in needed}

        # 日历与证券索引只编码/排序一次；逐字段 pivot 会重复这份全量工作。
        wide = flat.pivot(index="trade_date", columns="code", values=needed)
        return {field: wide[field] for field in needed}

    def _factor_panel(self, reference: pd.DataFrame, adjust: str) -> pd.DataFrame:
        """构造与面板同形的复权比例矩阵，一次性乘上去。"""
        ratio = pd.DataFrame(1.0, index=reference.index, columns=reference.columns)
        codes = list(dict.fromkeys(str(code) for code in reference.columns))
        if reference.empty or not codes:
            return ratio

        first_date = str(reference.index[0])
        last_date = str(reference.index[-1])
        requested_values = ", ".join("(?)" for _ in codes)
        # 只取足以把稀疏因子对齐到请求窗口的三部分：窗口起点前最后一条、
        # 窗口内变化，以及完全没有较早因子时的首个后续值（保留原 bfill 语义）。
        rows = self.conn.execute(
            f"""
            WITH requested(code) AS (VALUES {requested_values}),
            anchor AS (
                SELECT factors.code, MAX(factors.trade_date) AS trade_date
                FROM adjust_factors AS factors
                JOIN requested ON requested.code = factors.code
                WHERE factors.trade_date <= ?
                GROUP BY factors.code
            ),
            later AS (
                SELECT factors.code, MIN(factors.trade_date) AS trade_date
                FROM adjust_factors AS factors
                JOIN requested ON requested.code = factors.code
                WHERE factors.trade_date > ?
                GROUP BY factors.code
            )
            SELECT factors.code AS code, factors.trade_date AS trade_date, factors.hfq_factor AS hfq_factor
            FROM adjust_factors AS factors
            JOIN anchor ON anchor.code = factors.code AND anchor.trade_date = factors.trade_date
            UNION ALL
            SELECT factors.code, factors.trade_date, factors.hfq_factor
            FROM adjust_factors AS factors
            JOIN requested ON requested.code = factors.code
            WHERE factors.trade_date > ? AND factors.trade_date <= ?
            UNION ALL
            SELECT factors.code, factors.trade_date, factors.hfq_factor
            FROM adjust_factors AS factors
            JOIN later ON later.code = factors.code AND later.trade_date = factors.trade_date
            WHERE NOT EXISTS (
                SELECT 1 FROM adjust_factors AS known
                WHERE known.code = factors.code AND known.trade_date <= ?
            )
            ORDER BY code, trade_date
            """,
            [*codes, first_date, last_date, first_date, last_date, last_date],
        ).fetchall()
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
