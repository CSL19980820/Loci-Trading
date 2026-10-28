"""消费证据：SQL 计数与有界明细，等效于完整来源证据的既有压缩结果。"""
from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
import sys
from typing import TYPE_CHECKING, Any

from src.shared.evidence_compact import (
    compact_source_evidence, RECEIPT_LIMIT, RECEIPT_SOURCE, SAMPLE_LIMIT,
)
from src.market.infrastructure.store_provenance_window import cached_quote_evidence
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW

if TYPE_CHECKING:
    from src.market.infrastructure.store import MarketStore

_IN_CHUNK = 900
_METADATA_FIELDS = ("receipt_id", "code", "state", "unresolved", "generated_at", "selected_source")


def _cache_size(value: Any) -> int:
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(_cache_size(key) + _cache_size(item) for key, item in value.items())
    if isinstance(value, (tuple, list)):
        return size + sum(_cache_size(item) for item in value)
    return size


def _cache_add(state: Any, kind: str, key: Any, value: Any) -> None:
    # A conservative allowance covers dict growth and entry bookkeeping in addition
    # to the retained keys and values; over-budget entries simply stay uncached.
    size = 256 + _cache_size(kind) + _cache_size(key) + _cache_size(value)
    if state.provenance_bytes + size <= state.max_provenance_bytes:
        state.provenance_cache.setdefault(kind, {})[key] = value
        state.provenance_bytes += size


def _provenance_state(
    store: MarketStore, *, start: str | None, end: str | None,
) -> Any:
    state = _ACTIVE_WINDOW.get()
    if (state is None or state.store is not store or state.conn is not store.conn
            or not start or not end or start > end or start < state.start or end > state.end
            or state.max_provenance_bytes <= 0 or not state.refresh_provenance()):
        return None
    return state


def _cached_ids(state: Any, kind: str, ids: Sequence[str], reader: Any) -> Any:
    if state is None:
        return reader(ids)
    version = state.provenance_version
    cache = state.provenance_cache.get(kind, {})
    unique_ids = list(dict.fromkeys(ids))
    missing = [receipt_id for receipt_id in unique_ids if receipt_id not in cache]
    if missing:
        loaded = reader(missing)
        if kind == "metadata":
            by_id = {receipt_id: [] for receipt_id in missing}
            for row in loaded:
                by_id[str(row["receipt_id"])].append(tuple(row[field] for field in _METADATA_FIELDS[1:]))
        else:
            by_id = loaded
        if not state.refresh_provenance() or state.provenance_version != version:
            return reader(ids)
        for receipt_id in missing:
            _cache_add(state, kind, receipt_id, by_id[receipt_id])
    else:
        by_id = {}
    values = {receipt_id: cache.get(receipt_id, by_id.get(receipt_id)) for receipt_id in unique_ids}
    if kind == "counts":
        return values
    rows = [dict(zip(_METADATA_FIELDS, (receipt_id, *values_tuple)))
            for receipt_id in unique_ids for values_tuple in values[receipt_id]]
    rows.sort(key=lambda row: (str(row["generated_at"] or ""), str(row["receipt_id"])))
    return rows


def _cached_call(state: Any, kind: str, key: Any, reader: Any) -> Any:
    if state is None:
        return reader()
    version = state.provenance_version
    cache = state.provenance_cache.get(kind, {})
    if key in cache:
        return deepcopy(cache[key])
    value = reader()
    if not state.refresh_provenance() or state.provenance_version != version:
        return reader()
    _cache_add(state, kind, key, deepcopy(value))
    return value


def _receipt_metadata(store: MarketStore, receipt_ids: Sequence[str]) -> list[Any]:
    rows = []
    for offset in range(0, len(receipt_ids), _IN_CHUNK):
        chunk = receipt_ids[offset:offset + _IN_CHUNK]
        rows.extend(store.conn.execute(
            "SELECT receipt_id, code, state, unresolved, generated_at, selected_source "
            "FROM source_route_receipts WHERE receipt_id IN (" + ",".join("?" for _ in chunk) + ")",
            chunk,
        ).fetchall())
    found = {str(row["receipt_id"]) for row in rows}
    missing = [item for item in receipt_ids if item not in found]
    if missing:
        from src.market.application.provenance_archive import (
            default_archive_root, query_archived_receipt_metadata,
        )

        rows.extend(query_archived_receipt_metadata(default_archive_root(store.db_path), missing))
    rows.sort(key=lambda row: (str(row["generated_at"] or ""), str(row["receipt_id"])))
    return rows


def _attempt_counts(store: MarketStore, receipt_ids: Sequence[str]) -> dict[str, int]:
    counts = dict.fromkeys(receipt_ids, 0)
    unique_ids = list(counts)
    for offset in range(0, len(unique_ids), _IN_CHUNK):
        chunk = unique_ids[offset:offset + _IN_CHUNK]
        for row in store.conn.execute(
            "SELECT receipt_id, COUNT(*) AS total FROM source_route_attempts WHERE receipt_id IN ("
            + ",".join("?" for _ in chunk) + ") GROUP BY receipt_id", chunk,
        ):
            counts[str(row["receipt_id"])] = int(row["total"])
    missing = [receipt_id for receipt_id, count in counts.items() if not count]
    if missing:
        from src.market.application.provenance_archive import (
            default_archive_root, query_archived_attempt_counts,
        )

        for row in query_archived_attempt_counts(default_archive_root(store.db_path), missing):
            counts[str(row["receipt_id"])] += int(row["total"])
    return counts


def read_compact_source_evidence(
    store: MarketStore, codes: Sequence[str], unparsed: Sequence[str], *,
    start: str | None, end: str | None, include_details: bool,
) -> dict[str, object]:
    # 区间任务已有带版本校验与内存上限的报价事实缓存。由同一份事实生成
    # 汇总和关联回执，避免每天汇总后再扫描日 K 获取 receipt_id。
    rows = cached_quote_evidence(store, codes, start=start, end=end)
    detailed_quotes = rows is not None
    if rows is None:
        rows = store._cached_source_summary_rows(codes, start=start, end=end)
        if rows is None:
            rows = list(store._iter_source_summary_rows(codes, start=start, end=end))
        detailed_quotes = any(int(row["missing_receipt_metadata_rows"] or 0) for row in rows)
        if detailed_quotes:
            # 归档 metadata 仍可能补齐 selected_source，不能把热库缺失当成来源缺失。
            rows = store._quote_evidence_rows(codes, start=start, end=end)
    if detailed_quotes:
        linked_ids = list(dict.fromkeys(str(row["receipt_id"]) for row in rows if row["receipt_id"]))
    else:
        linked_ids = store._linked_receipt_ids(codes, start=start, end=end)
    unlinked_ids = store._unlinked_receipt_ids(codes, start=start, end=end) if include_details else []
    state = _provenance_state(store, start=start, end=end)
    metadata = _cached_ids(state, "metadata", list(dict.fromkeys([*linked_ids, *unlinked_ids])),
                           lambda ids: _receipt_metadata(store, ids))
    ids = [str(row["receipt_id"]) for row in metadata]
    counts = _cached_ids(state, "counts", ids, lambda requested: _attempt_counts(store, requested))
    failed = [row for row in metadata if row["unresolved"] or str(row["state"] or "") == "failed"]
    failed_ids = [str(row["receipt_id"]) for row in failed[:RECEIPT_LIMIT]]
    failed_rows = _cached_call(
        state, "failed_receipts", tuple(failed_ids),
        lambda: [dict(row) for row in store._receipt_rows(
            codes, start=start, end=end, linked_ids=failed_ids, include_unlinked=False,
        )],
    ) if failed_ids else []
    failed_rows = [row for row in failed_rows
                   if row["unresolved"] or str(row["state"] or "") == "failed"][:RECEIPT_LIMIT]
    failed_attempts = _cached_call(
        state, "failed_attempts", tuple(failed_ids), lambda: store._attempts_by_receipt(failed_ids),
    ) if failed_ids else {}
    receipts = [store._receipt_detail(row, failed_attempts[str(row["receipt_id"])]) for row in failed_rows]
    # Complete receipts within the sample budget can share one bounded lookup;
    # the first overflowing receipt still uses the original per-receipt LIMIT.
    prefix_ids: list[str] = []
    prefix_count = 0
    for row in metadata:
        receipt_id = str(row["receipt_id"])
        count = counts[receipt_id]
        if prefix_count + count > SAMPLE_LIMIT:
            break
        if count:
            prefix_ids.append(receipt_id)
            prefix_count += count
        if prefix_count == SAMPLE_LIMIT:
            break
    prefix = _cached_call(
        state, "attempt_prefix", tuple(prefix_ids), lambda: store._attempts_by_receipt(prefix_ids),
    ) if prefix_ids else {}
    prefix_remaining = len(prefix_ids)
    attempts = []
    for row in metadata:
        if len(attempts) >= SAMPLE_LIMIT:
            break
        receipt_id = str(row["receipt_id"])
        if counts[receipt_id]:
            limit = SAMPLE_LIMIT - len(attempts)
            if prefix_remaining:
                sample = prefix
                prefix_remaining -= 1
            else:
                sample = _cached_call(
                    state, "attempt_sample", (receipt_id, limit),
                    lambda: store._attempts_by_receipt([receipt_id], max_rows=limit),
                )
            attempts.extend({"receipt_id": receipt_id, "code": str(row["code"]), **attempt}
                            for attempt in sample[receipt_id][:limit])
    facts = store._aggregate_quote_rows(rows)
    sources = store._source_summaries(
        rows, receipt_map={str(row["receipt_id"]): row for row in metadata} if detailed_quotes else None,
    )
    if not sources and codes and not metadata:
        sources.append({"source_id": "market.db", "state": "failed", "rows": 0, "codes": 0,
                        "error": "查询范围没有落盘行情"})
    missing = [row for row in metadata if not counts[str(row["receipt_id"])]]
    missing_codes = {*facts["legacy_codes"], *(str(row["code"]) for row in missing)}
    result = {
        "lane": "hist_daily", "requested_codes": list(codes),
        "observed_codes": sorted(facts["observed_codes"]),
        "unresolved_codes": sorted(set(codes) - facts["observed_codes"]) if codes else [],
        "unparsed_codes": list(unparsed),
        "unresolved_receipt_codes": sorted({str(row["code"]) for row in metadata if row["unresolved"]}),
        "sources": sources, "receipts": receipts, "attempts": attempts,
        "field_coverage": facts["field_coverage"], "invalid_ohlc_rows": facts["invalid_ohlc_rows"],
        "attempts_not_observed": bool(missing_codes), "attempts_not_observed_codes": sorted(missing_codes),
        "attempts_not_observed_receipt_ids": sorted(str(row["receipt_id"]) for row in missing),
    }
    if not include_details:
        result.update({
            "receipt_details_omitted": True, "receipt_detail_basis": "all_quote_linked_receipts",
            "historical_failure_scope": store._failure_scope_summary(codes, start=start, end=end),
            "evidence_scope": {"codes": list(codes), "start": start, "end": end},
            "detail_note": "保留所有实际报价关联回执及attempt；额外历史失败回执仅汇总，不能作为完整严格PIT证据。",
        })
    # 复用公共裁剪规则处理代码数组，然后覆盖由计数查询得到的原始总数。
    compact_source_evidence(result)
    if metadata:
        result.update(receipts_total=len(metadata), receipts_failed=len(failed), receipts_source=RECEIPT_SOURCE)
    attempt_total = sum(counts[str(row["receipt_id"])] for row in metadata)
    if attempt_total > SAMPLE_LIMIT:
        result["attempts_total"] = attempt_total
    return result
