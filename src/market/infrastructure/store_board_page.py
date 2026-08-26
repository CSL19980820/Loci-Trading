"""行情台证券分页：关键词 / 所属行业 / 换手率排序。"""
from __future__ import annotations

from typing import Any


class MarketBoardPageMixin:
    """``page_instruments`` / 按换手排序；依赖连接与 ``_LATEST_BARS_LOOKBACK_DAYS``。"""

    def page_instruments(
        self,
        *,
        q: str = "",
        instrument_type: str | None = "STOCK",
        status: str = "normal",
        industry: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[int, list[dict[str, Any]]]:
        """分页列出证券，供行情台列表。q 同时匹配代码与名称。"""
        where, params = self._instrument_where(
            q=q, instrument_type=instrument_type, status=status, industry=industry
        )
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

    def page_instruments_by_turnover(
        self,
        *,
        q: str = "",
        instrument_type: str | None = "STOCK",
        status: str = "normal",
        industry: str | None = None,
        turnover_min: float | None = None,
        sort: str = "turnover_desc",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[int, list[dict[str, Any]]]:
        """按最近一根日线换手率过滤后分页；可按换手或代码排序（日历近窗）。"""
        where, params = self._instrument_where(
            q=q,
            instrument_type=instrument_type,
            status=status,
            industry=industry,
            table="i",
        )
        lookback = int(getattr(self, "_LATEST_BARS_LOOKBACK_DAYS", 20))
        join_where = list(where)
        join_params: list[Any] = [lookback, *params]
        if turnover_min is not None:
            join_where.append(
                "("
                "CASE "
                "WHEN q.amount IS NOT NULL AND q.amount > 0 "
                " AND q.close IS NOT NULL AND q.close > 0 "
                " AND q.outstanding_share IS NOT NULL AND q.outstanding_share > 0 "
                "THEN q.amount / (q.close * q.outstanding_share) "
                "WHEN q.turnover IS NOT NULL AND q.turnover > 0 AND q.turnover <= 0.5 "
                "THEN q.turnover "
                "ELSE NULL END"
                ") >= ?"
            )
            join_params.append(float(turnover_min))
        clause = " AND ".join(join_where)
        sort_key = (sort or "turnover_desc").strip().lower()
        eff = (
            "CASE "
            "WHEN q.amount IS NOT NULL AND q.amount > 0 "
            " AND q.close IS NOT NULL AND q.close > 0 "
            " AND q.outstanding_share IS NOT NULL AND q.outstanding_share > 0 "
            "THEN q.amount / (q.close * q.outstanding_share) "
            "WHEN q.turnover IS NOT NULL AND q.turnover > 0 AND q.turnover <= 0.5 "
            "THEN q.turnover "
            "ELSE NULL END"
        )
        if sort_key == "turnover_asc":
            order = f"CASE WHEN ({eff}) IS NULL THEN 1 ELSE 0 END, ({eff}) ASC, i.code"
        elif sort_key == "code":
            order = "i.code"
        else:
            order = f"CASE WHEN ({eff}) IS NULL THEN 1 ELSE 0 END, ({eff}) DESC, i.code"
        base_from = f"""
            FROM instruments i
            LEFT JOIN (
                SELECT code, MAX(trade_date) AS trade_date
                FROM quotes_daily
                WHERE trade_date IN (
                    SELECT trade_date FROM trading_calendar
                    ORDER BY trade_date DESC LIMIT ?
                )
                GROUP BY code
            ) d ON i.code = d.code
            LEFT JOIN quotes_daily q
                ON q.code = d.code AND q.trade_date = d.trade_date
            WHERE {clause}
        """
        total = int(
            self.conn.execute(f"SELECT COUNT(*) {base_from}", join_params).fetchone()[0]
        )
        rows = self.conn.execute(
            f"SELECT i.* {base_from} ORDER BY {order} LIMIT ? OFFSET ?",
            [*join_params, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        return total, [dict(row) for row in rows]

    def page_instruments_by_pct(
        self,
        *,
        q: str = "",
        instrument_type: str | None = "STOCK",
        status: str = "normal",
        industry: str | None = None,
        sort: str = "pct_desc",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[int, list[dict[str, Any]]]:
        """按最近一根日线相对前收涨跌幅排序分页（库内口径，非全市场实时扫盘）。"""
        where, params = self._instrument_where(
            q=q,
            instrument_type=instrument_type,
            status=status,
            industry=industry,
            table="i",
        )
        lookback = int(getattr(self, "_LATEST_BARS_LOOKBACK_DAYS", 20))
        clause = " AND ".join(where)
        sort_key = (sort or "pct_desc").strip().lower()
        if sort_key == "pct_asc":
            order = (
                "CASE WHEN p.pct_chg IS NULL THEN 1 ELSE 0 END, p.pct_chg ASC, i.code"
            )
        else:
            order = (
                "CASE WHEN p.pct_chg IS NULL THEN 1 ELSE 0 END, p.pct_chg DESC, i.code"
            )
        base_from = f"""
            FROM instruments i
            LEFT JOIN (
                SELECT
                    cur.code AS code,
                    CASE
                        WHEN prev.close IS NOT NULL AND prev.close > 0
                             AND cur.close IS NOT NULL
                        THEN (cur.close - prev.close) / prev.close * 100.0
                        ELSE NULL
                    END AS pct_chg
                FROM (
                    SELECT q.code, q.close, q.trade_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY q.code ORDER BY q.trade_date DESC
                           ) AS rn
                    FROM quotes_daily q
                    WHERE q.trade_date IN (
                        SELECT trade_date FROM trading_calendar
                        ORDER BY trade_date DESC LIMIT ?
                    )
                ) cur
                LEFT JOIN (
                    SELECT q.code, q.close, q.trade_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY q.code ORDER BY q.trade_date DESC
                           ) AS rn
                    FROM quotes_daily q
                    WHERE q.trade_date IN (
                        SELECT trade_date FROM trading_calendar
                        ORDER BY trade_date DESC LIMIT ?
                    )
                ) prev
                    ON prev.code = cur.code AND prev.rn = 2
                WHERE cur.rn = 1
            ) p ON i.code = p.code
            WHERE {clause}
        """
        join_params: list[Any] = [lookback, lookback, *params]
        total = int(
            self.conn.execute(f"SELECT COUNT(*) {base_from}", join_params).fetchone()[0]
        )
        rows = self.conn.execute(
            f"SELECT i.* {base_from} ORDER BY {order} LIMIT ? OFFSET ?",
            [*join_params, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        return total, [dict(row) for row in rows]

    def instruments_by_codes(
        self, codes: list[str], *, instrument_type: str | None = "STOCK"
    ) -> list[dict[str, Any]]:
        """按给定代码顺序取证券行（供首页叠价）；缺行跳过。"""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in codes:
            code = str(raw or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            cleaned.append(code)
        if not cleaned:
            return []
        placeholders = ",".join("?" * len(cleaned))
        where = [f"code IN ({placeholders})"]
        params: list[Any] = list(cleaned)
        if instrument_type:
            where.append("instrument_type = ?")
            params.append(instrument_type)
        rows = self.conn.execute(
            f"SELECT * FROM instruments WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
        by_code = {str(row["code"]): dict(row) for row in rows}
        return [by_code[c] for c in cleaned if c in by_code]

    def list_industries(self, *, instrument_type: str | None = "STOCK") -> list[str]:
        """已入库的所属行业名（去空、按频次降序）。"""
        where = ["industry <> ''"]
        params: list[Any] = []
        if instrument_type:
            where.append("instrument_type = ?")
            params.append(instrument_type)
        clause = " AND ".join(where)
        rows = self.conn.execute(
            f"SELECT industry, COUNT(*) AS c FROM instruments WHERE {clause}"
            " GROUP BY industry ORDER BY c DESC, industry ASC",
            params,
        ).fetchall()
        return [str(row["industry"]) for row in rows]

    @staticmethod
    def _instrument_where(
        *,
        q: str,
        instrument_type: str | None,
        status: str,
        industry: str | None,
        table: str = "",
    ) -> tuple[list[str], list[Any]]:
        prefix = f"{table}." if table else ""
        where = ["1=1"]
        params: list[Any] = []
        if instrument_type:
            where.append(f"{prefix}instrument_type = ?")
            params.append(instrument_type)
        if status:
            where.append(f"{prefix}status = ?")
            params.append(status)
        needle = q.strip()
        if needle:
            where.append(f"({prefix}code LIKE ? OR {prefix}name LIKE ?)")
            like = f"%{needle}%"
            params.extend([like, like])
        industry_needle = (industry or "").strip()
        if industry_needle:
            where.append(f"{prefix}industry LIKE ?")
            params.append(f"%{industry_needle}%")
        return where, params
