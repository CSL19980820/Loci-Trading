"""MarketStore 来源证据查询（只读路径）。"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from src.market.infrastructure.store_codes import MarketError, normalize_code

# SQLite 默认变量上限约 999；code/receipt IN 列表统一按此分片。
_SQL_IN_CHUNK = 900


class MarketProvenanceQueryMixin:
    """source_evidence 与范围回执查询；不发网络请求。"""

    conn: sqlite3.Connection

    def source_evidence(
        self,
        *,
        codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        requested_codes, unparsed_codes = self._requested_codes(codes)
        quote_summary = self._quote_summary(requested_codes, start=start, end=end)
        observed_codes = quote_summary["observed_codes"]
        legacy_codes = quote_summary["legacy_codes"]
        receipt_rows = self._receipt_rows(requested_codes, start=start, end=end)
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
        sources = self._source_summaries(requested_codes, start=start, end=end)
        if not sources and requested_codes and not receipts:
            sources.append(
                {"source_id": "market.db", "state": "failed", "rows": 0, "codes": 0,
                 "error": "查询范围没有落盘行情"}
            )
        missing_attempt_codes = {
            *legacy_codes,
            *(str(item["code"]) for item in missing_attempt_receipts),
        }
        return {
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
    ) -> list[sqlite3.Row]:
        """按范围收集回执。

        旧实现对每条 receipt 做 ``EXISTS (quotes_daily WHERE receipt_id=…)``，
        在千万行日 K 上会把选股拖成 disk I/O。改为：
        1) 有 code/日期过滤时，先从 quotes_daily 取 DISTINCT receipt_id（走 code+date 索引）
        2) 并上未挂日 K 的失败/skip 回执
        3) 再按 id 批量取 r.*
        """
        linked_ids = self._linked_receipt_ids(codes, start=start, end=end)
        unlinked_ids = self._unlinked_receipt_ids(codes, start=start, end=end)
        receipt_ids = list(dict.fromkeys([*linked_ids, *unlinked_ids]))
        if not receipt_ids:
            return []
        rows: list[sqlite3.Row] = []
        for offset in range(0, len(receipt_ids), _SQL_IN_CHUNK):
            chunk = receipt_ids[offset : offset + _SQL_IN_CHUNK]
            chunk_rows = self.conn.execute(
                "SELECT r.* FROM source_route_receipts r WHERE r.receipt_id IN ("
                + ",".join("?" for _ in chunk)
                + ") ORDER BY r.generated_at, r.receipt_id",
                chunk,
            ).fetchall()
            rows.extend(chunk_rows)
        rows.sort(key=lambda row: (str(row["generated_at"] or ""), str(row["receipt_id"])))
        return rows

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

    def _attempts_by_receipt(self, receipt_ids: Sequence[str]) -> dict[str, list[dict[str, object]]]:
        grouped = {receipt_id: [] for receipt_id in receipt_ids}
        if not receipt_ids:
            return grouped
        for offset in range(0, len(receipt_ids), 900):
            chunk = list(receipt_ids[offset : offset + 900])
            rows = self.conn.execute(
                "SELECT receipt_id, attempt_no, source_id, state, checked_at, rows, fields_json, "
                "source_url, published_at, publication_status, fetched_at, as_of, payload_sha256, "
                "parser_revision, available_at, availability_status, error "
                "FROM source_route_attempts WHERE receipt_id IN ("
                + ",".join("?" for _ in chunk)
                + ") ORDER BY receipt_id, attempt_no",
                chunk,
            ).fetchall()
            for row in rows:
                try:
                    fields = json.loads(str(row["fields_json"] or "[]"))
                except json.JSONDecodeError:
                    fields = []
                grouped[str(row["receipt_id"])].append(
                    {"source_id": str(row["source_id"]), "state": str(row["state"]),
                     "checked_at": str(row["checked_at"] or ""), "rows": row["rows"],
                     "fields": fields if isinstance(fields, list) else [],
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

    def _quote_summary(
        self,
        codes: Sequence[str],
        *,
        start: str | None,
        end: str | None,
    ) -> dict[str, object]:
        """按 code 分片聚合，避免全宇宙一次 IN 爆变量上限。"""
        if not codes:
            where, params = self._quote_where((), start=start, end=end)
            return self._aggregate_quote_rows(
                self.conn.execute(
                    self._quote_summary_sql(where), list(params)
                ).fetchall()
            )

        rows: list[sqlite3.Row] = []
        code_list = list(codes)
        for offset in range(0, len(code_list), _SQL_IN_CHUNK):
            chunk = code_list[offset : offset + _SQL_IN_CHUNK]
            where, params = self._quote_where(chunk, start=start, end=end)
            rows.extend(
                self.conn.execute(self._quote_summary_sql(where), list(params)).fetchall()
            )
        return self._aggregate_quote_rows(rows)

    @staticmethod
    def _quote_summary_sql(where: str) -> str:
        return (
            "SELECT code, COUNT(*) AS rows, "
            "SUM(CASE WHEN open IS NOT NULL THEN 1 ELSE 0 END) AS open_rows, "
            "SUM(CASE WHEN high IS NOT NULL THEN 1 ELSE 0 END) AS high_rows, "
            "SUM(CASE WHEN low IS NOT NULL THEN 1 ELSE 0 END) AS low_rows, "
            "SUM(CASE WHEN close IS NOT NULL THEN 1 ELSE 0 END) AS close_rows, "
            "SUM(CASE WHEN volume IS NOT NULL THEN 1 ELSE 0 END) AS volume_rows, "
            "SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) AS amount_rows, "
            "SUM(CASE WHEN turnover IS NOT NULL THEN 1 ELSE 0 END) AS turnover_rows, "
            "SUM(CASE WHEN outstanding_share IS NOT NULL THEN 1 ELSE 0 END) AS share_rows, "
            "SUM(CASE WHEN receipt_id IS NULL THEN 1 ELSE 0 END) AS legacy_rows, "
            "SUM(CASE WHEN open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL "
            "AND close IS NOT NULL AND (high < low OR high < open OR high < close "
            "OR low > open OR low > close OR open <= 0 OR high <= 0 OR low <= 0 "
            "OR close <= 0) THEN 1 ELSE 0 END) AS invalid_ohlc "
            "FROM quotes_daily" + where + " GROUP BY code"
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

    def _source_summaries(
        self, codes: Sequence[str], *, start: str | None, end: str | None
    ) -> list[dict[str, object]]:
        buckets: dict[str, dict[str, object]] = {}
        code_chunks: list[Sequence[str]]
        if codes:
            code_list = list(codes)
            code_chunks = [
                code_list[offset : offset + _SQL_IN_CHUNK]
                for offset in range(0, len(code_list), _SQL_IN_CHUNK)
            ]
        else:
            code_chunks = [()]

        for chunk in code_chunks:
            where, params = self._quote_where(chunk, start=start, end=end, alias="q")
            restriction = " AND (q.receipt_id IS NULL OR r.selected_source <> '')"
            source_rows = self.conn.execute(
                "SELECT CASE WHEN q.receipt_id IS NULL "
                "THEN COALESCE(NULLIF(q.source, ''), 'unknown') ELSE r.selected_source "
                "END AS source_id, "
                "COUNT(*) AS rows, COUNT(DISTINCT q.code) AS codes, "
                "MIN(q.trade_date) AS first_date, "
                "MAX(q.trade_date) AS last_date, MAX(q.fetched_at) AS last_fetched_at, "
                "SUM(CASE WHEN q.receipt_id IS NULL THEN 1 ELSE 0 END) AS legacy_rows "
                "FROM quotes_daily q LEFT JOIN source_route_receipts r "
                "ON r.receipt_id = q.receipt_id"
                + (
                    where + restriction
                    if where
                    else " WHERE " + restriction.removeprefix(" AND ")
                )
                + " GROUP BY source_id",
                params,
            ).fetchall()
            for row in source_rows:
                source_id = str(row["source_id"])
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
                bucket["codes"] = int(bucket["codes"]) + int(row["codes"] or 0)
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
