"""消费读取与完整证据后压缩等效，且热路径只解码有界凭证。"""
from __future__ import annotations

import json

import pytest

from src.market import MarketStore, panel_read_window
from src.market.application.provenance_archive import archive_selected_batch, default_archive_root
from src.market.infrastructure.store_codes import MarketError
from src.shared.evidence_compact import compact_job_result, compact_source_evidence

DAYS = ["2024-01-02", "2024-01-03"]


@pytest.fixture
def compact_store(tmp_path):
    codes = [str(600000 + position) for position in range(120)]
    with MarketStore(tmp_path / "market.db") as store:
        for position, code in enumerate(codes):
            receipt = f"receipt-{120 - position:03}"
            stamp = f"2024-01-03T15:{30 + position // 60:02}:{position % 60:02}"
            for day in DAYS:
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
                    "turnover,outstanding_share,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day, code, 10., 9. if position == 3 else 10.2, 9.8, 10., 1000.,
                     None if position % 3 == 0 else 10000., .01, 100000., "sina",
                     None if position == 0 and day == DAYS[0] else receipt, stamp),
                )
            if position % 17 == 0:
                continue  # SQL metadata 缺口保持真实，不能伪造 legacy 或 attempts。
            store.conn.execute(
                "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,unresolved,"
                "coverage_start,coverage_end,coverage_json,generated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (receipt, code, "hist_daily", "tdx" if position % 3 else "tencent",
                 "failed" if position >= 40 else "selected", int(position % 11 == 0),
                 DAYS[0], DAYS[-1], json.dumps({"rows": 2, "start": DAYS[0]}), stamp),
            )
            if position % 2 == 0:
                continue
            for number in range(70 if position == 1 else 3):
                store.conn.execute(
                    "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,"
                    "rows,fields_json,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
                    (receipt, number, "tdx", "failed" if number == 0 else "selected", stamp, 2,
                     '["open","close"]', f"digest-{position}-{number}"),
                )
        for position in range(4):
            store.conn.execute(
                "INSERT INTO source_route_receipts(receipt_id,code,lane,state,coverage_start,coverage_end,"
                "generated_at) VALUES(?,?,?,?,?,?,?)",
                (f"unlinked-{position}", codes[0], "hist_daily", "failed", DAYS[0], DAYS[-1],
                 f"2024-01-03T16:00:0{position}"),
            )
        store.conn.commit()
        yield store, codes


@pytest.mark.parametrize("include_details", [False, True])
@pytest.mark.parametrize("summary_only", [False, True])
def test_compact_read_equals_full_then_compact_with_all_counts_and_samples(
        compact_store, include_details, summary_only):
    store, codes = compact_store
    scope = dict(codes=[*codes, "600999", "unparsed"], start=DAYS[0], end=DAYS[-1],
                 include_details=include_details, summary_only=summary_only)
    expected = store.source_evidence(**scope)
    compact_source_evidence(expected)
    actual = store.source_evidence(**scope, mode="compact")
    assert actual == expected
    assert compact_source_evidence(actual) is False
    assert actual["observed_codes_total"] == 120
    assert len(actual["observed_codes"]) == 50
    assert actual["unparsed_codes"] == ["unparsed"]
    if not summary_only:
        assert actual["receipts_failed"] > 50
        assert len(actual["receipts"]) == len(actual["attempts"]) == 50
        assert actual["attempts_total"] > 50
        assert actual["attempts"][0]["receipt_id"] == "receipt-119"
        assert actual["attempts"][-1]["payload_sha256"] == "digest-1-49"
        assert len(actual["attempts_not_observed_receipt_ids"]) > 50


@pytest.mark.parametrize("include_details", [False, True])
def test_data_snapshot_compact_mode_preserves_watermarks_and_versions(compact_store, include_details):
    store, codes = compact_store
    scope = dict(codes=codes, start=DAYS[0], end=DAYS[-1], include_source_details=include_details)
    expected = store.data_snapshot(**scope)
    compact_job_result(expected)
    actual = store.data_snapshot(**scope, source_evidence_mode="compact")
    assert actual == expected
    assert compact_job_result(actual) == 0


def test_compact_hot_read_only_loads_failed_receipt_samples_and_limited_attempts(compact_store, monkeypatch):
    store, codes = compact_store
    detail_ids, attempt_reads = [], []
    original_receipts, original_attempts = store._receipt_rows, store._attempts_by_receipt

    def receipt_rows(*args, **kwargs):
        detail_ids.extend(kwargs["linked_ids"])
        return original_receipts(*args, **kwargs)

    def attempts(receipt_ids, **kwargs):
        attempt_reads.append((list(receipt_ids), kwargs.get("max_rows")))
        return original_attempts(receipt_ids, **kwargs)

    monkeypatch.setattr(store, "_receipt_rows", receipt_rows)
    monkeypatch.setattr(store, "_attempts_by_receipt", attempts)
    actual = store.source_evidence(codes=codes, start=DAYS[0], end=DAYS[-1],
                                   include_details=False, mode="compact")
    assert len(detail_ids) == 50
    assert all(len(ids) <= 50 for ids, _limit in attempt_reads)
    assert any(ids == ["receipt-119"] and limit == 50 for ids, limit in attempt_reads)
    assert len(actual["attempts"]) == 50


@pytest.mark.parametrize("include_details", [False, True])
def test_compact_cold_reads_restore_sources_counts_and_sample_order(compact_store, include_details):
    store, codes = compact_store
    root = default_archive_root(store.db_path)
    archived = archive_selected_batch(store.conn, root, cutoff="2025-01-01", batch_size=1000)
    assert archived["receipts"] > 0 and archived["attempts"] > 50
    scope = dict(codes=codes, start=DAYS[0], end=DAYS[-1], include_details=include_details)
    expected = store.source_evidence(**scope)
    compact_source_evidence(expected)
    actual = store.source_evidence(**scope, mode="compact")
    assert actual == expected
    assert actual["attempts"][0]["receipt_id"] == "receipt-119"
    assert actual["attempts"][-1]["payload_sha256"] == "digest-1-49"


@pytest.mark.parametrize("scope", [
    dict(codes=["600999"], start=DAYS[0], end=DAYS[-1]),
    dict(codes=["600001"], start="2025-01-01", end="2025-01-02"),
    dict(codes=None, start=DAYS[0], end=DAYS[-1]),
    dict(codes=[str(601000 + position) for position in range(905)] + ["600001"]),
])
def test_compact_empty_unscoped_and_chunked_ranges_keep_existing_contract(compact_store, scope):
    store, _codes = compact_store
    expected = store.source_evidence(**scope, include_details=False)
    compact_source_evidence(expected)
    assert store.source_evidence(**scope, include_details=False, mode="compact") == expected


def test_unknown_evidence_mode_is_rejected(compact_store):
    store, codes = compact_store
    with pytest.raises(MarketError, match="mode"):
        store.data_snapshot(codes=codes, source_evidence_mode="unknown")


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("budget", [1, 192_000_000])
def test_range_compact_reuses_quote_facts_and_preserves_full_evidence(
        compact_store, monkeypatch, archived, budget):
    store, codes = compact_store
    if archived:
        archive_selected_batch(store.conn, default_archive_root(store.db_path),
                               cutoff="2025-01-01", batch_size=1000)
    scopes = [
        dict(codes=codes, start=DAYS[0], end=DAYS[0], include_details=False),
        dict(codes=codes, start=DAYS[0], end=DAYS[-1], include_details=True),
        dict(codes=codes[1:20], start=DAYS[-1], end=DAYS[-1], include_details=False),
    ]
    expected = [store.source_evidence(**scope) for scope in scopes]
    for result in expected:
        compact_source_evidence(result)
    if budget > 1:
        def forbidden(*args, **kwargs):
            raise AssertionError("Cached quote facts already contain the linked receipt IDs")
        monkeypatch.setattr(store, "_linked_receipt_ids", forbidden)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_evidence_bytes=budget):
        for scope, oracle in zip(scopes, expected):
            assert store.source_evidence(**scope, mode="compact") == oracle


@pytest.mark.parametrize("external_writer", [False, True])
def test_range_compact_reloads_direct_quote_and_receipt_changes(compact_store, external_writer):
    store, codes = compact_store
    scope = dict(codes=codes, start=DAYS[0], end=DAYS[-1], include_details=False)
    with MarketStore(store.db_path) as other:
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
            before = store.source_evidence(**scope, mode="compact")
            writer = other if external_writer else store
            # Intentionally bypass application revision counters; connection versions
            # must invalidate the cached field counts and receipt source attribution.
            writer.conn.execute("UPDATE quotes_daily SET close=NULL WHERE code=?", (codes[1],))
            writer.conn.execute("UPDATE source_route_receipts SET selected_source='revised' "
                                "WHERE receipt_id='receipt-119'")
            writer.conn.commit()
            expected = other.source_evidence(**scope)
            compact_source_evidence(expected)
            actual = store.source_evidence(**scope, mode="compact")
            assert actual == expected
            assert actual["field_coverage"] != before["field_coverage"]
            assert actual["sources"] != before["sources"]
