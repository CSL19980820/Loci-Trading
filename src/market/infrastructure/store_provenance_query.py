"""MarketStore 来源证据查询（只读路径）。"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_provenance_window import cached_quote_evidence, INVALID_OHLC_SQL

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
        include_details: bool = True,
    ) -> dict[str, object]:
        requested_codes, unparsed_codes = self._requested_codes(codes)
        quote_rows = self._quote_evidence_rows(requested_codes, start=start, end=end)
        quote_summary = self._aggregate_quote_rows(quote_rows)
        observed_codes = quote_summary["observed_codes"]
        legacy_codes = quote_summary["legacy_codes"]
        receipt_rows = self._receipt_rows(
            requested_codes, start=start, end=end,
            linked_ids=list(dict.fromkeys(str(row["receipt_id"]) for row in quote_rows
                                          if row["receipt_id"])),
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
            receipt_map={str(row["receipt_id"]): row for row in receipt_rows},
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
        missing = [receipt_id for receipt_id, attempts in grouped.items() if not attempts]
        if missing:
            from src.market.application.provenance_archive import (
                default_archive_root,
                query_archived_attempts,
            )

            for row in query_archived_attempts(default_archive_root(self.db_path), missing):
                try:
                    fields = json.loads(str(row.get("fields_json") or "[]"))
                except json.JSONDecodeError:
                    fields = []
                grouped[str(row["receipt_id"])].append(
                    {
                        "source_id": str(row.get("source_id") or ""),
                        "state": str(row.get("state") or ""),
                        "checked_at": str(row.get("checked_at") or ""),
                        "rows": row.get("rows"),
                        "fields": fields if isinstance(fields, list) else [],
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
            "FROM quotes_daily" + where + " GROUP BY code, receipt_id, legacy_source"
            ") q LEFT JOIN source_route_receipts r ON r.receipt_id = q.receipt_id"
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
