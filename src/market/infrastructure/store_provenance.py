"""MarketStore 的来源回执写入。"""
from __future__ import annotations

from src.shared.clock import utc_now

import json
import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from src.market.infrastructure.store_codes import MarketError, normalize_code

from src.market.infrastructure.store_provenance_query import MarketProvenanceQueryMixin


class MarketProvenanceMixin(MarketProvenanceQueryMixin):
    """来源回执原子写入；查询见 MarketProvenanceQueryMixin。"""

    conn: sqlite3.Connection

    _PARSER_REVISION = "market-quote-normalizer-v1"

    def persist_quote_receipt(
        self, receipt: dict[str, Any], frame: Any, *, source: str
    ) -> int:
        """原子写入单票日 K 与其最终来源回执。"""
        code = normalize_code(str(receipt["code"]))
        payload = self._quote_payload_from_frame(code, frame, source=source, receipt_id=None)
        self._attach_quote_payload_provenance(receipt, payload)
        with self._transaction() as cursor:
            receipt_id = self._insert_source_receipt(
                cursor, receipt, trade_dates=[str(row[0]) for row in payload]
            )
            written = self._write_quote_payload(
                [(*row[:-1], receipt_id) for row in payload], cursor=cursor
            )
            self._record_rows_written(cursor, receipt_id, receipt, written)
            self._bump_revisions(cursor, "source_receipts")
        return written

    def persist_source_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        trade_dates: Sequence[str] = (),
    ) -> str:
        """只落来源回执（失败、watermark skip 等没有日 K 的终态）。"""
        with self._transaction() as cursor:
            receipt_id = self._insert_source_receipt(cursor, dict(receipt), trade_dates=trade_dates)
            self._bump_revisions(cursor, "source_receipts")
        return receipt_id

    def persist_quote_frame_receipts(
        self, items: Sequence[tuple[dict[str, Any], Any, str]]
    ) -> dict[str, int]:
        """一个事务写入多票历史日 K 与各自回执。

        历史同步过去是每票一次 ``BEGIN IMMEDIATE``：全市场 5500 只就是 5500 次
        写事务 + 5500 次 commit，几个 worker 还要互抢同一把 SQLite 写锁。
        按批合并后事务数降到 ``票数 / 批大小``。

        与 ``persist_quote_bar_receipts`` 的区别：这里每票各带自己的 frame 与
        命中源（历史线路逐票选路），不是一张共享的 spot 宽表。
        """
        prepared: list[tuple[str, dict[str, Any], list[Any]]] = []
        for receipt, frame, source in items:
            code = normalize_code(str(receipt["code"]))
            payload = self._quote_payload_from_frame(
                code, frame, source=source, receipt_id=None
            )
            self._attach_quote_payload_provenance(receipt, payload)
            prepared.append((code, receipt, payload))
        if not prepared:
            return {}
        written_by_code: dict[str, int] = {}
        with self._transaction() as cursor:
            for code, receipt, payload in prepared:
                receipt_id = self._insert_source_receipt(
                    cursor, receipt, trade_dates=[str(row[0]) for row in payload]
                )
                written = self._write_quote_payload(
                    [(*row[:-1], receipt_id) for row in payload], cursor=cursor
                )
                self._record_rows_written(cursor, receipt_id, receipt, written)
                written_by_code[code] = written
            self._bump_revisions(cursor, "source_receipts")
        return written_by_code

    def persist_source_receipts(
        self, receipts: Sequence[Mapping[str, Any]]
    ) -> list[str]:
        """一个事务写入多条无日 K 的终态回执（失败 / watermark skip）。

        跳过与失败在全量同步里同样是几千条，逐条开事务和成功路径一样贵。
        """
        if not receipts:
            return []
        out: list[str] = []
        with self._transaction() as cursor:
            for receipt in receipts:
                out.append(
                    self._insert_source_receipt(cursor, dict(receipt), trade_dates=())
                )
            self._bump_revisions(cursor, "source_receipts")
        return out
    def persist_quote_bar_receipts(
        self, receipts: Sequence[dict[str, Any]], bars: Sequence[dict[str, Any]], *, source: str
    ) -> int:
        """原子写入批量日 K 与逐代码来源回执（spot 使用）。"""
        payload = self._quote_payload_from_bars(bars, source=source)
        receipts_by_code = {
            normalize_code(str(receipt["code"])): receipt for receipt in receipts
        }
        # 线路可能返回批量中未请求的代码；没有本次请求的逐代码 receipt 就不能
        # 写入，否则会伪装成 attempts 未观测的 legacy 行情。
        payload = [row for row in payload if str(row[1]) in receipts_by_code]
        dates_by_code: dict[str, list[str]] = {}
        for trade_date, code, *_rest in payload:
            dates_by_code.setdefault(str(code), []).append(str(trade_date))
        for code, receipt in receipts_by_code.items():
            self._attach_quote_payload_provenance(
                receipt, [row for row in payload if str(row[1]) == code]
            )
        with self._transaction() as cursor:
            receipt_ids = {
                code: self._insert_source_receipt(
                    cursor, receipt, trade_dates=dates_by_code.get(code, ())
                )
                for code, receipt in receipts_by_code.items()
            }
            written = self._write_quote_payload(
                [(*row[:-1], receipt_ids.get(str(row[1]))) for row in payload], cursor=cursor
            )
            written_by_code = {
                code: sum(1 for row in payload if str(row[1]) == code)
                for code in receipts_by_code
            }
            for code, receipt_id in receipt_ids.items():
                self._record_rows_written(
                    cursor, receipt_id, receipts_by_code[code], written_by_code[code]
                )
            self._bump_revisions(cursor, "source_receipts")
        return written

    @staticmethod
    def _record_rows_written(
        cursor: sqlite3.Cursor,
        receipt_id: str,
        receipt: dict[str, Any],
        rows_written: int,
    ) -> None:
        coverage = dict(receipt.get("coverage") or {})
        coverage["rows_written"] = rows_written
        receipt["coverage"] = coverage
        cursor.execute(
            "UPDATE source_route_receipts SET coverage_json = ? WHERE receipt_id = ?",
            (json.dumps(coverage, sort_keys=True), receipt_id),
        )

    def _attach_quote_payload_provenance(
        self, receipt: dict[str, Any], payload: Sequence[Sequence[Any]]
    ) -> None:
        """把实际归一后、将要落库的 quote 载荷绑定到最终 receipt。"""
        if not payload:
            return
        receipt["payload_sha256"] = self._payload_sha256(payload)
        receipt.setdefault("fetched_at", utc_now())
        receipt.setdefault("as_of", max(str(row[0])[:10] for row in payload))
        receipt.setdefault("parser_revision", self._PARSER_REVISION)
        self._normalize_visibility(receipt)

    @staticmethod
    def _payload_sha256(payload: Sequence[Sequence[Any]]) -> str:
        """哈希真实写入字段；不把随机 receipt id 纳入同一行情载荷的内容指纹。"""
        body = [list(row[:-1]) for row in payload]
        encoded = json.dumps(
            body, ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _normalize_visibility(receipt: dict[str, Any]) -> None:
        for value_key, status_key in (
            ("published_at", "publication_status"),
            ("available_at", "availability_status"),
        ):
            value = str(receipt.get(value_key) or "")
            status = str(receipt.get(status_key) or "not_observed")
            if status != "observed" or not value:
                receipt[value_key] = ""
                receipt[status_key] = "not_observed"
            else:
                receipt[value_key] = value
                receipt[status_key] = "observed"

    def _insert_source_receipt(
        self, cursor: sqlite3.Cursor, receipt: dict[str, Any], *, trade_dates: Sequence[str] = ()
    ) -> str:
        self._normalize_visibility(receipt)
        attempts = receipt.get("attempts") or []
        unresolved = bool(receipt.get("unresolved"))
        requested_state = str(receipt.get("state") or "")
        if requested_state in {"selected", "failed", "skipped"}:
            state = requested_state
        else:
            state = "failed" if unresolved else "skipped" if any(
                isinstance(item, dict) and item.get("state") == "skipped" for item in attempts
            ) else "selected"
        receipt_id = str(receipt.get("receipt_id") or uuid4().hex)
        dates = sorted({str(value)[:10] for value in trade_dates if value})
        coverage_start = str(receipt.get("coverage_start") or (dates[0] if dates else ""))[:10]
        coverage_end = str(receipt.get("coverage_end") or (dates[-1] if dates else ""))[:10]
        raw_code = str(receipt["code"] or "").strip()
        try:
            stored_code = normalize_code(raw_code)
        except MarketError:
            if not raw_code:
                raise
            stored_code = raw_code
        cursor.execute(
            "INSERT INTO source_route_receipts("
            "receipt_id, code, lane, requested_sources_json, selected_source, fallback_used, "
            "unresolved, state, coverage_json, source_url, published_at, publication_status, "
            "fetched_at, as_of, payload_sha256, parser_revision, available_at, availability_status, "
            "coverage_start, coverage_end, request_start, request_end, error, generated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt_id, stored_code, str(receipt.get("lane") or "hist_daily"),
                json.dumps([str(item) for item in receipt.get("requested_sources") or []]),
                str(receipt.get("selected_source") or ""), int(bool(receipt.get("fallback_used"))),
                int(unresolved), state, json.dumps(receipt.get("coverage") or {}, sort_keys=True),
                str(receipt.get("source_url") or ""), str(receipt.get("published_at") or ""),
                str(receipt.get("publication_status") or "not_observed"),
                str(receipt.get("fetched_at") or ""), str(receipt.get("as_of") or "")[:10],
                str(receipt.get("payload_sha256") or ""),
                str(receipt.get("parser_revision") or ""),
                str(receipt.get("available_at") or ""),
                str(receipt.get("availability_status") or "not_observed"),
                coverage_start, coverage_end, str(receipt.get("request_start") or "")[:10],
                str(receipt.get("request_end") or "")[:10], str(receipt.get("error") or "")[:500],
                str(receipt.get("generated_at") or utc_now()),
            ),
        )
        cursor.executemany(
            "INSERT INTO source_route_attempts("
            "receipt_id, attempt_no, source_id, state, checked_at, rows, fields_json, source_url, "
            "published_at, publication_status, fetched_at, as_of, payload_sha256, parser_revision, "
            "available_at, availability_status, error) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                self._attempt_row(receipt_id, position, item, receipt)
                for position, item in enumerate(attempts, start=1) if isinstance(item, dict)
            ],
        )
        return receipt_id

    @staticmethod
    def _attempt_row(
        receipt_id: str, position: int, item: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        source_id = str(item.get("source_id") or "unknown")
        selected = source_id == str(receipt.get("selected_source") or "")

        def value(key: str) -> str:
            raw = item.get(key)
            if raw is None and selected:
                raw = receipt.get(key)
            return str(raw or "")

        publication_status = value("publication_status") or "not_observed"
        availability_status = value("availability_status") or "not_observed"
        published_at = value("published_at") if publication_status == "observed" else ""
        available_at = value("available_at") if availability_status == "observed" else ""
        if not published_at:
            publication_status = "not_observed"
        if not available_at:
            availability_status = "not_observed"
        return (
            receipt_id,
            position,
            source_id,
            str(item.get("state") or "attempted"),
            str(item.get("checked_at") or ""),
            item.get("rows"),
            json.dumps([str(field) for field in item.get("fields") or []]),
            value("source_url"),
            published_at,
            publication_status,
            value("fetched_at") or str(item.get("checked_at") or ""),
            value("as_of")[:10],
            value("payload_sha256"),
            value("parser_revision"),
            available_at,
            availability_status,
            str(item.get("error") or "")[:500],
        )
