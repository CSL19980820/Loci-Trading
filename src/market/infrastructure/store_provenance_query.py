"""MarketStore 来源证据查询（只读路径）。"""
from __future__ import annotations

import json
import calendar
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_provenance_window import cached_quote_evidence, INVALID_OHLC_SQL
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW

# SQLite 默认变量上限约 999；code/receipt IN 列表统一按此分片。
_SQL_IN_CHUNK = 900
_SUMMARY_FIELDS = (
    "code", "source_id", "first_date", "last_date", "last_fetched_at", "rows",
    "open_rows", "high_rows", "low_rows", "close_rows", "volume_rows", "amount_rows",
    "turnover_rows", "share_rows", "legacy_rows", "missing_receipt_metadata_rows",
    "unresolved_source_rows", "invalid_ohlc",
)


def _merge_summary_values(left: tuple, right: tuple) -> tuple:
    return (
        *left[:2], min(left[2], right[2]),
        *(max((value for value in pair if value is not None), default=None)
          for pair in zip(left[3:5], right[3:5])),
        *(int(a or 0) + int(b or 0) for a, b in zip(left[5:], right[5:])),
    )


@dataclass
class _SourceSummaryMonth:
    """Compact code/source aggregates for one exact portion of a month."""

    start: str
    end: str
    codes: set[str] = field(default_factory=set)
    rows: dict[tuple[str, str | None], tuple] = field(default_factory=dict)
    row_bytes: int = 0
    code_bytes: int = 0

    def add_codes(self, codes: Sequence[str]) -> None:
        for code in codes:
            if code not in self.codes:
                self.codes.add(code)
                self.code_bytes += sys.getsizeof(code)

    def add(self, row: sqlite3.Row) -> None:
        item = tuple(row[name] for name in _SUMMARY_FIELDS)
        key = item[:2]
        previous = self.rows.get(key)
        if previous is not None:
            self.row_bytes -= self._row_bytes(key, previous)
            item = _merge_summary_values(previous, item)
        self.rows[key] = item
        self.row_bytes += self._row_bytes(key, item)

    @staticmethod
    def _row_bytes(key: tuple, row: tuple) -> int:
        return (sys.getsizeof(key) + sys.getsizeof(row)
                + sum(sys.getsizeof(value) for value in (*key, *row)))

    def bytes_used(self) -> int:
        return (sys.getsizeof(self) + sys.getsizeof(self.__dict__)
                + sys.getsizeof(self.start) + sys.getsizeof(self.end)
                + sys.getsizeof(self.codes) + self.code_bytes
                + sys.getsizeof(self.rows) + self.row_bytes)


@dataclass
class _SourceSummaryMonths:
    """Reuse complete interior months; rebuild only a moving left boundary."""

    start: str
    end: str
    months: dict[str, _SourceSummaryMonth] = field(default_factory=dict)

    def bytes_used(self) -> int:
        return (sys.getsizeof(self) + sys.getsizeof(self.__dict__)
                + sys.getsizeof(self.start) + sys.getsizeof(self.end)
                + sys.getsizeof(self.months)
                + sum(sys.getsizeof(key) + month.bytes_used()
                      for key, month in self.months.items()))

    @staticmethod
    def parts(start: str, end: str) -> list[tuple[str, str]]:
        current, final = date.fromisoformat(start), date.fromisoformat(end)
        result = []
        while current <= final:
            last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
            result.append((current.isoformat(), min(last, final).isoformat()))
            if last >= final:
                break
            current = date.fromordinal(last.toordinal() + 1)
        return result


@dataclass
class _SourceSummaryWindow:
    """A bounded code/source aggregate, extended only by later quote dates."""

    start: str
    end: str
    codes: set[str] = field(default_factory=set)
    rows: dict[tuple[str, str | None], dict[str, object]] = field(default_factory=dict)
    row_bytes: int = 0
    code_bytes: int = 0

    def add_codes(self, codes: Sequence[str]) -> None:
        for code in codes:
            if code not in self.codes:
                self.codes.add(code)
                self.code_bytes += sys.getsizeof(code)

    def add(self, row: sqlite3.Row, *, budget: int) -> bool:
        item = dict(row)
        key = (str(item["code"]), item["source_id"])
        existing = self.rows.get(key)
        if existing is None:
            self.rows[key] = item
            # Count every row's keys/values even when Python shares objects. This
            # upper bound includes the actual dict, tuple and string allocations.
            self.row_bytes += self._row_bytes(key, item)
        else:
            self.row_bytes -= self._row_bytes(key, existing)
            for name, value in item.items():
                if name in {"code", "source_id"}:
                    continue
                if name == "first_date":
                    existing[name] = min(existing[name], value)
                elif name in {"last_date", "last_fetched_at"}:
                    existing[name] = max((part for part in (existing[name], value)
                                          if part is not None), default=None)
                else:
                    existing[name] = int(existing[name] or 0) + int(value or 0)
            self.row_bytes += self._row_bytes(key, existing)
        return self.bytes_used() <= budget

    @staticmethod
    def _row_bytes(key: tuple[str, str | None], row: dict[str, object]) -> int:
        return (sys.getsizeof(key) + sys.getsizeof(row)
                + sum(sys.getsizeof(part) for part in key)
                + sum(sys.getsizeof(name) + sys.getsizeof(value) for name, value in row.items()))

    def bytes_used(self) -> int:
        return (sys.getsizeof(self) + sys.getsizeof(self.__dict__)
                + sys.getsizeof(self.start) + sys.getsizeof(self.end)
                + sys.getsizeof(self.codes) + self.code_bytes
                + sys.getsizeof(self.rows) + self.row_bytes)


class MarketProvenanceQueryMixin:
    """source_evidence 与范围回执查询；不发网络请求。"""

    conn: sqlite3.Connection

    def source_evidence(
        self,
        *,
        codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        include_details: bool = True,
        summary_only: bool = False,
        mode: Literal["full", "compact"] = "full",
    ) -> dict[str, object]:
        """按范围读取来源事实；compact 直接生成既有全文压缩后的消费契约。"""
        if mode not in {"full", "compact"}:
            raise MarketError("source_evidence mode 必须是 full 或 compact")
        requested_codes, unparsed_codes = self._requested_codes(codes)
        if summary_only:
            result = self._source_evidence_summary(
                requested_codes, unparsed_codes, start=start, end=end,
            )
            if mode == "compact":
                from src.shared.evidence_compact import compact_source_evidence

                compact_source_evidence(result)
            return result
        if mode == "compact":
            from src.market.infrastructure.store_provenance_compact import read_compact_source_evidence

            return read_compact_source_evidence(
                self, requested_codes, unparsed_codes, start=start, end=end,
                include_details=include_details,
            )
        detailed_quote_rows = include_details
        if include_details:
            quote_rows = self._quote_evidence_rows(requested_codes, start=start, end=end)
        else:
            quote_rows = self._cached_source_summary_rows(requested_codes, start=start, end=end)
            if quote_rows is None:
                quote_rows = list(self._iter_source_summary_rows(requested_codes, start=start, end=end))
            if any(int(row["missing_receipt_metadata_rows"] or 0) for row in quote_rows):
                # 冷归档可能仍持有关联回执的 selected_source。只有存在这一
                # 缺口时才保留逐 receipt 报价分组，供下面的归档回查补齐来源。
                quote_rows = self._quote_evidence_rows(requested_codes, start=start, end=end)
                detailed_quote_rows = True
        linked_ids = (
            list(dict.fromkeys(str(row["receipt_id"]) for row in quote_rows if row["receipt_id"]))
            if detailed_quote_rows else self._linked_receipt_ids(requested_codes, start=start, end=end)
        )
        quote_summary = self._aggregate_quote_rows(quote_rows)
        observed_codes = quote_summary["observed_codes"]
        legacy_codes = quote_summary["legacy_codes"]
        receipt_rows = self._receipt_rows(
            requested_codes, start=start, end=end,
            linked_ids=linked_ids,
            **({"include_unlinked": False} if not include_details else {}),
        )
        receipt_ids = [str(row["receipt_id"]) for row in receipt_rows]
        attempts_by_receipt = self._attempts_by_receipt(receipt_ids)

        receipts: list[dict[str, object]] = []
        attempts: list[dict[str, object]] = []
        missing_attempt_receipts: list[dict[str, object]] = []
        for row in receipt_rows:
            receipt_id = str(row["receipt_id"])
            receipt_attempts = attempts_by_receipt[receipt_id]
            detail = self._receipt_detail(row, receipt_attempts)
            receipts.append(detail)
            if not receipt_attempts:
                missing_attempt_receipts.append(detail)
            attempts.extend(
                {"receipt_id": receipt_id, "code": detail["code"], **attempt}
                for attempt in receipt_attempts
            )
        sources = self._source_summaries(
            quote_rows,
            receipt_map=({str(row["receipt_id"]): row for row in receipt_rows}
                         if detailed_quote_rows else None),
        )
        if not sources and requested_codes and not receipts:
            sources.append(
                {"source_id": "market.db", "state": "failed", "rows": 0, "codes": 0,
                 "error": "查询范围没有落盘行情"}
            )
        missing_attempt_codes = {
            *legacy_codes,
            *(str(item["code"]) for item in missing_attempt_receipts),
        }
        result = {
            "lane": "hist_daily",
            "requested_codes": requested_codes,
            "observed_codes": sorted(observed_codes),
            "unresolved_codes": (
                sorted(set(requested_codes) - observed_codes) if requested_codes else []
            ),
            "unparsed_codes": unparsed_codes,
            "unresolved_receipt_codes": sorted(
                {str(item["code"]) for item in receipts if item["unresolved"]}
            ),
            "sources": sources,
            "receipts": receipts,
            "attempts": attempts,
            "field_coverage": quote_summary["field_coverage"],
            "invalid_ohlc_rows": quote_summary["invalid_ohlc_rows"],
            "attempts_not_observed": bool(missing_attempt_codes),
            "attempts_not_observed_codes": sorted(missing_attempt_codes),
            "attempts_not_observed_receipt_ids": sorted(
                str(item["receipt_id"]) for item in missing_attempt_receipts
            ),
        }
        if not include_details:
            result.update({
                "receipt_details_omitted": True,
                "receipt_detail_basis": "all_quote_linked_receipts",
                "historical_failure_scope": self._failure_scope_summary(requested_codes, start=start, end=end),
                "evidence_scope": {"codes": requested_codes, "start": start, "end": end},
                "detail_note": "保留所有实际报价关联回执及attempt；额外历史失败回执仅汇总，不能作为完整严格PIT证据。",
            })
        return result

    def _source_evidence_summary(
        self, codes: Sequence[str], unparsed_codes: Sequence[str], *,
        start: str | None, end: str | None,
    ) -> dict[str, object]:
        """显式轻量摘要：SQL 聚合报价事实，不装载逐回执明细或冷归档。"""
        rows = self._cached_source_summary_rows(codes, start=start, end=end)
        if rows is None:
            rows = list(self._iter_source_summary_rows(codes, start=start, end=end))
        summary = self._aggregate_quote_rows(rows)
        observed = summary["observed_codes"]
        missing_receipt_metadata = sum(int(row["missing_receipt_metadata_rows"] or 0) for row in rows)
        unresolved_source_rows = sum(int(row["unresolved_source_rows"] or 0) for row in rows)
        return {
            "lane": "hist_daily",
            "requested_codes": list(codes),
            "observed_codes": sorted(observed),
            "unresolved_codes": sorted(set(codes) - observed) if codes else [],
            "unparsed_codes": list(unparsed_codes),
            "rows": sum(int(row["rows"] or 0) for row in rows),
            "sources": self._source_summaries(rows),
            "field_coverage": summary["field_coverage"],
            "invalid_ohlc_rows": summary["invalid_ohlc_rows"],
            "legacy_quote_rows": sum(int(row["legacy_rows"] or 0) for row in rows),
            "legacy_quote_codes": sorted(summary["legacy_codes"]),
            "missing_receipt_metadata_rows": missing_receipt_metadata,
            "unresolved_source_rows": unresolved_source_rows,
            "source_summary_incomplete": bool(unresolved_source_rows),
            "receipts": [],
            "attempts": [],
            "receipt_details_omitted": True,
            "attempt_details_omitted": True,
            "receipt_detail_basis": "quote_source_sql_summary_only",
            "attempts_not_observed": None,
            "attempt_observation_status": "not_evaluated",
            "evidence_scope": {"codes": list(codes), "start": start, "end": end},
            "details_source": "market.db:source_route_receipts/source_route_attempts and provenance archive",
            "detail_note": (
                "仅汇总本范围报价行、SQLite可用回执的来源及字段覆盖；未读取逐回执/attempt明细或冷归档。"
                "SQLite未关联到的回执可能已归档，不能据此判定凭证缺失；摘要不等于完整来源或严格PIT验证。"
            ),
        }

    def _iter_source_summary_rows(
        self, codes: Sequence[str], *, start: str | None, end: str | None,
        after: str | None = None,
    ) -> Iterator[sqlite3.Row]:
        # Large bounded scopes should scan the date-clustered quote table once.
        # Forcing this path on each 900-code chunk would repeat the whole range.
        if (len(codes) > _SQL_IN_CHUNK and end and (start or after)
                and self._date_source_summary_available()):
            clauses = ["q.code IN (SELECT value FROM json_each(?))"]
            params = [json.dumps(list(codes), separators=(",", ":"))]
            if start:
                clauses.append("q.trade_date >= ?")
                params.append(str(start))
            clauses.append("q.trade_date <= ?")
            params.append(str(end))
            if after is not None:
                clauses.append("q.trade_date > ?")
                params.append(str(after))
            sql = self._quote_source_summary_sql(" WHERE " + " AND ".join(clauses), date_major=True)
            cursor = self.conn.execute(sql, params)
            try:
                yield from cursor
            finally:
                cursor.close()
            return
        chunks = [codes[i:i + _SQL_IN_CHUNK] for i in range(0, len(codes), _SQL_IN_CHUNK)] or [()]
        for chunk in chunks:
            where, params = self._quote_where(chunk, start=start, end=end, alias="q")
            if after is not None:
                where += " AND q.trade_date > ?" if where else " WHERE q.trade_date > ?"
                params.append(after)
            cursor = self.conn.execute(self._quote_source_summary_sql(where), params)
            try:
                yield from cursor
            finally:
                cursor.close()

    def _date_source_summary_available(self) -> bool:
        """Probe JSON and the existing date primary key without changing schema."""
        try:
            cursor = self.conn.execute("SELECT value FROM json_each(?) LIMIT 1", ('["source_summary"]',))
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None or row[0] != "source_summary":
                return False
            cursor = self.conn.execute(
                "SELECT 1 FROM quotes_daily INDEXED BY sqlite_autoindex_quotes_daily_1 WHERE 0"
            )
            cursor.close()
        except sqlite3.Error:
            return False
        return True

    def _cached_source_summary_rows(
        self, codes: Sequence[str], *, start: str | None, end: str | None,
    ) -> list[dict[str, object]] | None:
        state = _ACTIVE_WINDOW.get()
        if (state is None or state.store is not self or state.conn is not self.conn
                or not codes or not start or not end or start > end
                or start < state.start or end > state.end or not state.refresh()
                or state.source_summary_declined):
            return None
        version = state.version
        cached = state.source_summary
        if cached is not None and (start < cached.start or end < cached.end):
            # Reverse requests retain the ordinary reader's exact semantics.
            state.source_summary = None
            state.source_summary_declined = True
            return None
        if (isinstance(cached, _SourceSummaryMonths)
                or cached is not None and cached.start != start):
            if not isinstance(cached, _SourceSummaryMonths):
                # Drop both references before constructing the replacement.
                state.source_summary = None
                cached = None
            return self._cached_monthly_source_summary_rows(codes, start=start, end=end)
        candidate = cached or _SourceSummaryWindow(start, end)
        known_codes = sorted(candidate.codes)
        new_codes = sorted(set(codes) - candidate.codes)
        candidate.add_codes(new_codes)
        # Summary groups remain small even for full history. A separate 64 MB
        # ceiling also bounds this cache when detailed evidence is used later.
        budget = min(state.max_evidence_bytes, 64_000_000)
        try:
            if candidate.bytes_used() > budget:
                state.source_summary = None
                state.source_summary_declined = True
                return None
            requests = []
            if known_codes and end > candidate.end:
                requests.append((known_codes, None, candidate.end))
            if new_codes:
                requests.append((new_codes, start, None))
            for requested, first, after in requests:
                rows = self._iter_source_summary_rows(requested, start=first, end=end, after=after)
                try:
                    for row in rows:
                        if not candidate.add(row, budget=budget):
                            state.source_summary = None
                            state.source_summary_declined = True
                            return None
                finally:
                    rows.close()
            if self.conn.in_transaction or version != state.current_version():
                state.clear()
                return None
        except Exception:
            state.source_summary = None
            raise
        candidate.end = end
        state.source_summary = candidate
        wanted = set(codes)
        return [row for (code, _source), row in candidate.rows.items() if code in wanted]

    def _cached_monthly_source_summary_rows(
        self, codes: Sequence[str], *, start: str, end: str,
    ) -> list[dict[str, object]] | None:
        state = _ACTIVE_WINDOW.get()
        version = state.version
        candidate = state.source_summary
        if not isinstance(candidate, _SourceSummaryMonths):
            candidate = _SourceSummaryMonths(start, end)
        budget = min(state.max_evidence_bytes, 64_000_000)
        try:
            parts = candidate.parts(start, end)
        except ValueError:
            state.source_summary = None
            state.source_summary_declined = True
            return None
        wanted_months = {first[:7] for first, _last in parts}
        candidate.months = {key: value for key, value in candidate.months.items()
                            if key in wanted_months}
        try:
            for first, last in parts:
                key = first[:7]
                month = candidate.months.get(key)
                if month is None or month.start != first:
                    month = _SourceSummaryMonth(first, last)
                    candidate.months[key] = month
                known_codes = sorted(month.codes)
                new_codes = sorted(set(codes) - month.codes)
                month.add_codes(new_codes)
                if candidate.bytes_used() > budget:
                    state.source_summary = None
                    state.source_summary_declined = True
                    return None
                requests = []
                if known_codes and last > month.end:
                    requests.append((known_codes, None, month.end))
                if new_codes:
                    requests.append((new_codes, first, None))
                for requested, lower, after in requests:
                    rows = self._iter_source_summary_rows(
                        requested, start=lower, end=last, after=after,
                    )
                    try:
                        for row in rows:
                            month.add(row)
                            if candidate.bytes_used() > budget:
                                state.source_summary = None
                                state.source_summary_declined = True
                                return None
                    finally:
                        rows.close()
                month.end = last
            if self.conn.in_transaction or version != state.current_version():
                state.clear()
                return None
        except Exception:
            state.source_summary = None
            raise
        candidate.start, candidate.end = start, end
        state.source_summary = candidate
        wanted = set(codes)
        combined: dict[tuple[str, str | None], tuple] = {}
        for month in candidate.months.values():
            for key, row in month.rows.items():
                if key[0] in wanted:
                    previous = combined.get(key)
                    combined[key] = row if previous is None else _merge_summary_values(previous, row)
        return [dict(zip(_SUMMARY_FIELDS, row)) for row in combined.values()]

    @staticmethod
    def _quote_source_summary_sql(where: str, *, date_major: bool = False) -> str:
        # 历史回执往往覆盖整段日 K。先聚合报价，再连接回执，避免为同一
        # receipt 的每个交易日反复查 metadata；最终仍只输出 code/source。
        return (
            "SELECT q.code, CASE WHEN q.receipt_id IS NULL "
            "THEN q.legacy_source ELSE r.selected_source END AS source_id, "
            "MIN(q.first_date) AS first_date, MAX(q.last_date) AS last_date, "
            "MAX(q.last_fetched_at) AS last_fetched_at, SUM(q.rows) AS rows, "
            "SUM(q.open_rows) AS open_rows, SUM(q.high_rows) AS high_rows, "
            "SUM(q.low_rows) AS low_rows, SUM(q.close_rows) AS close_rows, "
            "SUM(q.volume_rows) AS volume_rows, SUM(q.amount_rows) AS amount_rows, "
            "SUM(q.turnover_rows) AS turnover_rows, SUM(q.share_rows) AS share_rows, "
            "SUM(q.legacy_rows) AS legacy_rows, "
            "SUM(CASE WHEN q.receipt_id IS NOT NULL AND r.receipt_id IS NULL THEN q.rows ELSE 0 END) "
            "AS missing_receipt_metadata_rows, "
            "SUM(CASE WHEN q.receipt_id IS NOT NULL AND "
            "(r.selected_source IS NULL OR r.selected_source = '') THEN q.rows ELSE 0 END) "
            "AS unresolved_source_rows, "
            "SUM(q.invalid_ohlc) AS invalid_ohlc FROM ("
            + MarketProvenanceQueryMixin._quote_grouped_sql(where, date_major=date_major, alias="q")
            + ") q"
            + " LEFT JOIN source_route_receipts r ON r.receipt_id = q.receipt_id"
            + " GROUP BY q.code, source_id"
        )

    @staticmethod
    def _requested_codes(codes: Sequence[str] | None) -> tuple[list[str], list[str]]:
        requested: list[str] = []
        unparsed: list[str] = []
        for code in codes or ():
            raw = str(code).strip()
            if not raw:
                continue
            try:
                requested.append(normalize_code(raw))
            except MarketError:
                requested.append(raw)
                unparsed.append(raw)
        return list(dict.fromkeys(requested)), list(dict.fromkeys(unparsed))

    @staticmethod
    def _quote_where(
        codes: Sequence[str], *, start: str | None, end: str | None, alias: str = ""
    ) -> tuple[str, list[str]]:
        prefix = f"{alias}." if alias else ""
        clauses: list[str] = []
        params: list[str] = []
        if codes:
            clauses.append(prefix + "code IN (" + ",".join("?" for _ in codes) + ")")
            params.extend(codes)
        if start:
            clauses.append(prefix + "trade_date >= ?")
            params.append(str(start))
        if end:
            clauses.append(prefix + "trade_date <= ?")
            params.append(str(end))
        return (" WHERE " + " AND ".join(clauses) if clauses else "", params)

    def _receipt_rows(
        self,
        codes: Sequence[str],
        *,
        start: str | None,
        end: str | None,
        include_unlinked: bool = True,
        linked_ids: Sequence[str] | None = None,
    ) -> list[sqlite3.Row]:
        """按范围收集回执。

        旧实现对每条 receipt 做 ``EXISTS (quotes_daily WHERE receipt_id=…)``，
        在千万行日 K 上会把选股拖成 disk I/O。改为：
        1) 有 code/日期过滤时，先从 quotes_daily 取 DISTINCT receipt_id（走 code+date 索引）
        2) 并上未挂日 K 的失败/skip 回执
        3) 再按 id 批量取 r.*
        """
        if linked_ids is None:
            linked_ids = self._linked_receipt_ids(codes, start=start, end=end)
        unlinked_ids = self._unlinked_receipt_ids(codes, start=start, end=end) if include_unlinked else []
        receipt_ids = list(dict.fromkeys([*linked_ids, *unlinked_ids]))
        if not receipt_ids:
            return []
        rows: list[sqlite3.Row | dict[str, object]] = []
        for offset in range(0, len(receipt_ids), _SQL_IN_CHUNK):
            chunk = receipt_ids[offset : offset + _SQL_IN_CHUNK]
            chunk_rows = self.conn.execute(
                "SELECT r.* FROM source_route_receipts r WHERE r.receipt_id IN ("
                + ",".join("?" for _ in chunk)
                + ") ORDER BY r.generated_at, r.receipt_id",
                chunk,
            ).fetchall()
            rows.extend(chunk_rows)
        found = {str(row["receipt_id"]) for row in rows}
        missing = [receipt_id for receipt_id in receipt_ids if receipt_id not in found]
        if missing:
            # 旧 selected 回执已经从 SQLite 热窗口移入 Parquet/Zstd 冷归档；
            # 只按本次范围实际关联的 receipt_id 回查，不扫描整个归档目录。
            from src.market.application.provenance_archive import (
                default_archive_root,
                query_archived_receipts,
            )

            rows.extend(query_archived_receipts(default_archive_root(self.db_path), missing))
        rows.sort(key=lambda row: (str(row["generated_at"] or ""), str(row["receipt_id"])))
        return rows

    def _failure_scope_summary(
        self, codes: Sequence[str], *, start: str | None, end: str | None,
    ) -> dict[str, object]:
        chunks = [codes[i:i + _SQL_IN_CHUNK] for i in range(0, len(codes), _SQL_IN_CHUNK)] or [()]
        counts: dict[str, int] = {}
        for chunk in chunks:
            scope, params = self._unlinked_receipt_scope(chunk, start=start, end=end)
            rows = self.conn.execute(
                "SELECT r.state, COUNT(*) AS total FROM source_route_receipts r WHERE "
                + scope + " GROUP BY r.state", params,
            ).fetchall()
            for row in rows:
                state = str(row["state"])
                counts[state] = counts.get(state, 0) + int(row["total"])
        return {
            "receipt_count": sum(counts.values()), "by_state": counts,
            "may_overlap_quote_linked_receipts": True,
            "detail_rows_materialized": False,
        }

    def _linked_receipt_ids(
        self,
        codes: Sequence[str],
        *,
        start: str | None,
        end: str | None,
    ) -> list[str]:
        """从日 K 反查关联回执 id；无 code 且无日期时退回 receipt 索引侧，避免扫全表。"""
        if not codes and not (start or end):
            # 全局 DISTINCT 仍可能重；选股必须传 codes/start/end。
            rows = self.conn.execute(
                "SELECT DISTINCT receipt_id FROM quotes_daily "
                "WHERE receipt_id IS NOT NULL AND receipt_id <> ''"
            ).fetchall()
            return [str(row[0]) for row in rows if row[0]]

        if not codes:
            where, params = self._quote_where((), start=start, end=end)
            sql = (
                "SELECT DISTINCT receipt_id FROM quotes_daily"
                + where
                + " AND receipt_id IS NOT NULL AND receipt_id <> ''"
            )
            return [
                str(row[0])
                for row in self.conn.execute(sql, params).fetchall()
                if row[0]
            ]

        found: list[str] = []
        seen: set[str] = set()
        code_list = list(codes)
        for offset in range(0, len(code_list), _SQL_IN_CHUNK):
            chunk = code_list[offset : offset + _SQL_IN_CHUNK]
            where, params = self._quote_where(chunk, start=start, end=end)
            sql = (
                "SELECT DISTINCT receipt_id FROM quotes_daily"
                + where
                + " AND receipt_id IS NOT NULL AND receipt_id <> ''"
            )
            for row in self.conn.execute(sql, params).fetchall():
                rid = str(row[0] or "")
                if rid and rid not in seen:
                    seen.add(rid)
                    found.append(rid)
        return found

    def _unlinked_receipt_ids(
        self,
        codes: Sequence[str],
        *,
        start: str | None,
        end: str | None,
    ) -> list[str]:
        if not codes:
            receipt_scope, scope_params = self._unlinked_receipt_scope(
                (), start=start, end=end
            )
            rows = self.conn.execute(
                "SELECT r.receipt_id FROM source_route_receipts r WHERE " + receipt_scope,
                scope_params,
            ).fetchall()
            return [str(row[0]) for row in rows if row[0]]

        found: list[str] = []
        seen: set[str] = set()
        code_list = list(codes)
        for offset in range(0, len(code_list), _SQL_IN_CHUNK):
            chunk = code_list[offset : offset + _SQL_IN_CHUNK]
            receipt_scope, scope_params = self._unlinked_receipt_scope(
                chunk, start=start, end=end
            )
            rows = self.conn.execute(
                "SELECT r.receipt_id FROM source_route_receipts r WHERE " + receipt_scope,
                scope_params,
            ).fetchall()
            for row in rows:
                rid = str(row[0] or "")
                if rid and rid not in seen:
                    seen.add(rid)
                    found.append(rid)
        return found

    @staticmethod
    def _unlinked_receipt_scope(
        codes: Sequence[str], *, start: str | None, end: str | None
    ) -> tuple[str, list[str]]:
        clauses = [
            "r.lane IN ('hist_daily', 'spot_batch')",
            "(r.unresolved = 1 OR r.state IN ('failed', 'skipped'))",
        ]
        params: list[str] = []
        if codes:
            clauses.insert(0, "r.code IN (" + ",".join("?" for _ in codes) + ")")
            params.extend(codes)
        if not (start or end):
            return "(" + " AND ".join(clauses) + ")", params
        coverage: list[str] = []
        request: list[str] = []
        coverage_params: list[str] = []
        request_params: list[str] = []
        if start:
            coverage.append("r.coverage_end >= ?")
            request.append("r.request_end >= ?")
            coverage_params.append(str(start))
            request_params.append(str(start))
        if end:
            coverage.append("r.coverage_start <= ?")
            request.append("r.request_start <= ?")
            coverage_params.append(str(end))
            request_params.append(str(end))
        clauses.append(
            "((r.coverage_start <> '' AND r.coverage_end <> '' AND "
            + " AND ".join(coverage)
            + ") OR (r.request_start <> '' AND r.request_end <> '' AND "
            + " AND ".join(request)
            + "))"
        )
        return "(" + " AND ".join(clauses) + ")", [
            *params,
            *coverage_params,
            *request_params,
        ]

    def _attempts_by_receipt(
        self, receipt_ids: Sequence[str], *, max_rows: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        if max_rows is not None and (len(receipt_ids) != 1 or max_rows < 1):
            raise ValueError("有界 attempt 明细必须限定单个 receipt 和正数 max_rows")
        grouped = {receipt_id: [] for receipt_id in receipt_ids}
        if not receipt_ids:
            return grouped
        fields_cache: dict[str, tuple[str, ...]] = {}

        def attempt_fields(value: object) -> list[object]:
            payload = str(value or "[]")
            cached = fields_cache.get(payload)
            if cached is not None:
                return list(cached)
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                return []
            if not isinstance(decoded, list):
                return []
            # 字段列表通常全仓相同；缓存仅限不可变字符串，返回独立列表。
            # 不缓存任意嵌套 JSON，避免两个 attempt 共享可变子对象。
            if len(fields_cache) < 128 and all(isinstance(item, str) for item in decoded):
                fields_cache[payload] = tuple(decoded)
            return decoded

        for offset in range(0, len(receipt_ids), 900):
            chunk = list(receipt_ids[offset : offset + 900])
            rows = self.conn.execute(
                "SELECT receipt_id, attempt_no, source_id, state, checked_at, rows, fields_json, "
                "source_url, published_at, publication_status, fetched_at, as_of, payload_sha256, "
                "parser_revision, available_at, availability_status, error "
                "FROM source_route_attempts WHERE receipt_id IN ("
                + ",".join("?" for _ in chunk)
                + ") ORDER BY receipt_id, attempt_no"
                + (" LIMIT ?" if max_rows is not None else ""),
                [*chunk, max_rows] if max_rows is not None else chunk,
            ).fetchall()
            for row in rows:
                grouped[str(row["receipt_id"])].append(
                    {"source_id": str(row["source_id"]), "state": str(row["state"]),
                     "checked_at": str(row["checked_at"] or ""), "rows": row["rows"],
                     "fields": attempt_fields(row["fields_json"]),
                     "source_url": str(row["source_url"] or ""),
                     "published_at": str(row["published_at"] or ""),
                     "publication_status": str(row["publication_status"] or "not_observed"),
                     "fetched_at": str(row["fetched_at"] or ""),
                     "as_of": str(row["as_of"] or ""),
                     "payload_sha256": str(row["payload_sha256"] or ""),
                     "parser_revision": str(row["parser_revision"] or ""),
                     "available_at": str(row["available_at"] or ""),
                     "availability_status": str(row["availability_status"] or "not_observed"),
                     "error": str(row["error"] or "")}
                )
        missing = [receipt_id for receipt_id, attempts in grouped.items() if not attempts]
        if missing:
            from src.market.application.provenance_archive import (
                default_archive_root,
                query_archived_attempts,
                query_archived_attempt_sample,
            )

            archived = (query_archived_attempt_sample(default_archive_root(self.db_path), missing[0], max_rows)
                        if max_rows is not None else query_archived_attempts(default_archive_root(self.db_path), missing))
            for row in archived:
                grouped[str(row["receipt_id"])].append(
                    {
                        "source_id": str(row.get("source_id") or ""),
                        "state": str(row.get("state") or ""),
                        "checked_at": str(row.get("checked_at") or ""),
                        "rows": row.get("rows"),
                        "fields": attempt_fields(row.get("fields_json")),
                        "source_url": str(row.get("source_url") or ""),
                        "published_at": str(row.get("published_at") or ""),
                        "publication_status": str(row.get("publication_status") or "not_observed"),
                        "fetched_at": str(row.get("fetched_at") or ""),
                        "as_of": str(row.get("as_of") or ""),
                        "payload_sha256": str(row.get("payload_sha256") or ""),
                        "parser_revision": str(row.get("parser_revision") or ""),
                        "available_at": str(row.get("available_at") or ""),
                        "availability_status": str(row.get("availability_status") or "not_observed"),
                        "error": str(row.get("error") or ""),
                    }
                )
        return grouped

    def _receipt_detail(self, row: sqlite3.Row, attempts: list[dict[str, object]]) -> dict[str, object]:
        try:
            coverage = json.loads(str(row["coverage_json"] or "{}"))
        except json.JSONDecodeError:
            coverage = {}
        return {
            "receipt_id": str(row["receipt_id"]), "code": str(row["code"]),
            "lane": str(row["lane"]), "requested_sources": self._json_list(row["requested_sources_json"]),
            "selected_source": str(row["selected_source"] or ""),
            "fallback_used": bool(row["fallback_used"]), "unresolved": bool(row["unresolved"]),
            "state": str(row["state"]), "coverage": coverage if isinstance(coverage, dict) else {},
            "error": str(row["error"] or ""), "generated_at": str(row["generated_at"]),
            "source_url": str(row["source_url"] or ""),
            "published_at": str(row["published_at"] or ""),
            "publication_status": str(row["publication_status"] or "not_observed"),
            "fetched_at": str(row["fetched_at"] or ""),
            "as_of": str(row["as_of"] or ""),
            "payload_sha256": str(row["payload_sha256"] or ""),
            "parser_revision": str(row["parser_revision"] or ""),
            "available_at": str(row["available_at"] or ""),
            "availability_status": str(row["availability_status"] or "not_observed"),
            "coverage_start": str(row["coverage_start"] or ""),
            "coverage_end": str(row["coverage_end"] or ""),
            "request_start": str(row["request_start"] or ""),
            "request_end": str(row["request_end"] or ""), "attempts": attempts,
        }

    def _quote_evidence_rows(
        self, codes: Sequence[str], *, start: str | None, end: str | None,
    ) -> list[sqlite3.Row]:
        """同一范围只扫描一次日 K；先压缩到 code/receipt/source，再关联回执。"""
        cached = cached_quote_evidence(self, codes, start=start, end=end)
        if cached is not None:
            return cached
        chunks = [codes[i:i + _SQL_IN_CHUNK] for i in range(0, len(codes), _SQL_IN_CHUNK)] or [()]
        rows: list[sqlite3.Row] = []
        for chunk in chunks:
            where, params = self._quote_where(chunk, start=start, end=end)
            rows.extend(self.conn.execute(self._quote_evidence_sql(where), params).fetchall())
        return rows

    @staticmethod
    def _quote_evidence_sql(where: str) -> str:
        return (
            "SELECT q.*, CASE WHEN q.receipt_id IS NULL THEN q.legacy_source "
            "ELSE r.selected_source END AS source_id FROM ("
            + MarketProvenanceQueryMixin._quote_grouped_sql(where)
            + ") q LEFT JOIN source_route_receipts r ON r.receipt_id = q.receipt_id"
        )

    @staticmethod
    def _quote_grouped_sql(where: str, *, date_major: bool = False, alias: str = "") -> str:
        return (
            "SELECT code, receipt_id, CASE WHEN receipt_id IS NULL "
            "THEN COALESCE(NULLIF(source, ''), 'unknown') ELSE '' END AS legacy_source, "
            "MIN(trade_date) AS first_date, MAX(trade_date) AS last_date, "
            "MAX(fetched_at) AS last_fetched_at, COUNT(*) AS rows, "
            "SUM(CASE WHEN open IS NOT NULL THEN 1 ELSE 0 END) AS open_rows, "
            "SUM(CASE WHEN high IS NOT NULL THEN 1 ELSE 0 END) AS high_rows, "
            "SUM(CASE WHEN low IS NOT NULL THEN 1 ELSE 0 END) AS low_rows, "
            "SUM(CASE WHEN close IS NOT NULL THEN 1 ELSE 0 END) AS close_rows, "
            "SUM(CASE WHEN volume IS NOT NULL THEN 1 ELSE 0 END) AS volume_rows, "
            "SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) AS amount_rows, "
            "SUM(CASE WHEN turnover IS NOT NULL THEN 1 ELSE 0 END) AS turnover_rows, "
            "SUM(CASE WHEN outstanding_share IS NOT NULL THEN 1 ELSE 0 END) AS share_rows, "
            "SUM(CASE WHEN receipt_id IS NULL THEN 1 ELSE 0 END) AS legacy_rows, "
            f"SUM(CASE WHEN {INVALID_OHLC_SQL} THEN 1 ELSE 0 END) AS invalid_ohlc "
            "FROM quotes_daily" + (" " + alias if alias else "")
            + (" INDEXED BY sqlite_autoindex_quotes_daily_1" if date_major else "")
            + where + " GROUP BY code, receipt_id, legacy_source"
        )

    @staticmethod
    def _aggregate_quote_rows(rows: Sequence[sqlite3.Row]) -> dict[str, object]:
        total = sum(int(row["rows"] or 0) for row in rows)
        columns = {
            "open": "open_rows",
            "high": "high_rows",
            "low": "low_rows",
            "close": "close_rows",
            "volume": "volume_rows",
            "amount": "amount_rows",
            "turnover": "turnover_rows",
            "outstanding_share": "share_rows",
        }
        return {
            "observed_codes": {str(row["code"]) for row in rows},
            "legacy_codes": {
                str(row["code"]) for row in rows if int(row["legacy_rows"] or 0)
            },
            "field_coverage": {
                field: {
                    "rows": sum(int(row[column] or 0) for row in rows),
                    "ratio": round(
                        sum(int(row[column] or 0) for row in rows) / total, 6
                    )
                    if total
                    else 0.0,
                }
                for field, column in columns.items()
            },
            "invalid_ohlc_rows": sum(int(row["invalid_ohlc"] or 0) for row in rows),
        }

    @staticmethod
    def _source_summaries(
        rows: Sequence[sqlite3.Row],
        *,
        receipt_map: dict[str, sqlite3.Row | dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        buckets: dict[str, dict[str, object]] = {}
        source_codes: dict[str, set[str]] = {}
        for row in rows:
            # 空/孤儿关联不能变成 legacy；原 SQL 只接纳 NULL receipt 或非空 selected_source。
            source_value = row["source_id"]
            if (source_value is None or source_value == "") and receipt_map:
                receipt = receipt_map.get(str(row["receipt_id"] or ""))
                source_value = receipt["selected_source"] if receipt else None
            if source_value is None or source_value == "":
                continue
            source_id = str(source_value)
            bucket = buckets.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "state": "selected",
                    "rows": 0,
                    "codes": 0,
                    "first_date": "",
                    "last_date": "",
                    "last_fetched_at": "",
                    "legacy_rows": 0,
                },
            )
            bucket["rows"] = int(bucket["rows"]) + int(row["rows"] or 0)
            source_codes.setdefault(source_id, set()).add(str(row["code"]))
            bucket["codes"] = len(source_codes[source_id])
            bucket["legacy_rows"] = int(bucket["legacy_rows"]) + int(
                row["legacy_rows"] or 0
            )
            first = str(row["first_date"] or "")
            last = str(row["last_date"] or "")
            fetched = str(row["last_fetched_at"] or "")
            if first and (not bucket["first_date"] or first < str(bucket["first_date"])):
                bucket["first_date"] = first
            if last and (not bucket["last_date"] or last > str(bucket["last_date"])):
                bucket["last_date"] = last
            if fetched and (
                not bucket["last_fetched_at"]
                or fetched > str(bucket["last_fetched_at"])
            ):
                bucket["last_fetched_at"] = fetched

        result: list[dict[str, object]] = []
        for source_id in sorted(buckets):
            bucket = buckets[source_id]
            legacy = int(bucket.pop("legacy_rows"))
            item = dict(bucket)
            if legacy:
                item["attempts_not_observed"] = True
            result.append(item)
        return result

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []
