"""来源 SQL 摘要的有界装载、真实仓等效计数与旧明细兼容。"""
from __future__ import annotations

from copy import copy

import pandas as pd
import pytest

from src.market import MarketStore
from src.backtest.application.runner import prepare_backtest_context
from src.strategy import get, screen
from src.shared.evidence_compact import compact_source_evidence

CODES = ["300001", "301001"]


@pytest.fixture
def evidence_store(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        dates = pd.bdate_range("2024-01-02", periods=6).strftime("%Y-%m-%d").tolist()
        store.upsert_instruments(
            {"code": code, "name": "测试", "market": "sz", "board": "chi_next",
             "list_date": "2015-01-05"} for code in [*CODES, "600001"]
        )
        for code in [*CODES, "600001"]:
            for position, day in enumerate(dates):
                receipt = f"{code}-{day}"
                selected_source = "tdx" if position % 2 == 0 else "tencent"
                legacy = code == CODES[0] and position == 2
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
                    "turnover,outstanding_share,source,receipt_id,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day, code, 10.0, 9.0 if position == 3 else 10.2, 9.8, 10.0,
                     1000.0, None if position == 1 else 10000.0, None if position == 4 else 0.01,
                     100000.0, "sina" if legacy else "unverified_quote_source",
                     None if legacy else receipt, day + "T15:30:00"),
                )
                if legacy:
                    continue
                store.conn.execute(
                    "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,"
                    "coverage_start,coverage_end,generated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (receipt, code, "hist_daily", selected_source, "ok", day, day, day + "T15:30:00"),
                )
                store.conn.execute(
                    "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,rows) "
                    "VALUES(?,?,?,?,?,?)", (receipt, 1, selected_source, "ok", day + "T15:30:00", 1),
                )
        store.conn.commit()
        store.rebuild_calendar()
        yield store, dates


def test_summary_matches_full_quote_facts_with_the_same_code_and_date_scope(evidence_store):
    store, dates = evidence_store
    scope = {"codes": CODES, "start": dates[1], "end": dates[4]}
    full = store.source_evidence(**scope)
    summary = store.source_evidence(**scope, summary_only=True)
    for key in ("requested_codes", "observed_codes", "unresolved_codes", "unparsed_codes",
                "sources", "field_coverage", "invalid_ohlc_rows"):
        assert summary[key] == full[key]
    assert summary["rows"] == 8
    assert summary["invalid_ohlc_rows"] == 2
    assert summary["field_coverage"]["amount"]["rows"] == 6
    assert summary["legacy_quote_rows"] == 1
    assert summary["legacy_quote_codes"] == [CODES[0]]
    assert summary["missing_receipt_metadata_rows"] == 0
    assert summary["source_summary_incomplete"] is False
    assert summary["evidence_scope"] == scope
    assert {item["source_id"] for item in summary["sources"]} == {"tdx", "tencent", "sina"}
    assert full["receipts"] and full["attempts"]
    assert summary["receipts"] == [] and summary["attempts"] == []
    assert summary["receipt_details_omitted"] and summary["attempt_details_omitted"]
    assert summary["attempts_not_observed"] is None
    assert summary["attempt_observation_status"] == "not_evaluated"


def test_summary_never_materializes_quote_receipt_or_attempt_details(evidence_store, monkeypatch):
    store, dates = evidence_store

    def forbidden(*_args, **_kwargs):
        raise AssertionError("来源摘要不得装载逐回执或attempt明细")

    for name in ("_quote_evidence_rows", "_receipt_rows", "_attempts_by_receipt",
                 "_receipt_detail", "_failure_scope_summary"):
        monkeypatch.setattr(store, name, forbidden)
    queries = []
    store.conn.set_trace_callback(queries.append)
    snapshot = store.data_snapshot(codes=CODES, start=dates[0], end=dates[-1],
                                   source_summary_only=True)
    store.conn.set_trace_callback(None)
    assert snapshot["source_evidence"]["rows"] == 12
    assert not any("source_route_attempts" in query.lower() for query in queries)
    # 内层 SQL 可以按回执预聚合，但 Python 只接收最终 code/source 汇总。
    assert any("group by q.code, source_id" in query.lower() for query in queries)
    assert all("select r.*" not in query.lower() for query in queries)


def test_summary_preserves_all_snapshot_version_and_watermark_metadata(evidence_store):
    store, dates = evidence_store
    scope = {"codes": CODES, "start": dates[0], "end": dates[-1]}
    full = store.data_snapshot(**scope)
    summary = store.data_snapshot(**scope, source_summary_only=True)
    assert {key: value for key, value in summary.items() if key != "source_evidence"} == {
        key: value for key, value in full.items() if key != "source_evidence"
    }
    assert summary["market_revision"] == store.market_revision()
    assert full["source_evidence"]["receipts"]
    assert "receipt_details_omitted" not in full["source_evidence"]


def test_default_and_existing_include_details_false_keep_their_full_linked_evidence(evidence_store):
    store, dates = evidence_store
    scope = {"codes": CODES, "start": dates[0], "end": dates[-1]}
    default = store.source_evidence(**scope)
    explicit = store.source_evidence(**scope, summary_only=False)
    reduced_failures = store.source_evidence(**scope, include_details=False)
    assert default == explicit
    assert len(default["receipts"]) == 11
    assert len(default["attempts"]) == 11
    assert reduced_failures["receipts"] == default["receipts"]
    assert reduced_failures["attempts"] == default["attempts"]
    assert reduced_failures["receipt_detail_basis"] == "all_quote_linked_receipts"
    assert "attempt_details_omitted" not in reduced_failures


def test_reduced_details_uses_compact_quote_facts_with_all_linked_evidence(evidence_store, monkeypatch):
    store, dates = evidence_store
    scope = {"codes": CODES, "start": dates[0], "end": dates[-1]}
    expected = store.source_evidence(**scope, include_details=False)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("正常热回执不应装载逐回执报价分组")

    monkeypatch.setattr(store, "_quote_evidence_rows", forbidden)
    assert store.source_evidence(**scope, include_details=False) == expected


def test_shared_receipts_keep_quote_row_counts_and_missing_metadata_scope(evidence_store):
    store, dates = evidence_store
    store.conn.execute("UPDATE quotes_daily SET receipt_id=? WHERE code=? AND trade_date<=?",
                       (f"{CODES[1]}-{dates[0]}", CODES[1], dates[2]))
    store.conn.execute("UPDATE quotes_daily SET receipt_id='missing-shared-receipt' "
                       "WHERE code=? AND trade_date>?", (CODES[1], dates[2]))
    store.conn.commit()
    scope = {"codes": CODES, "start": dates[0], "end": dates[-1]}
    summary = store.source_evidence(**scope, summary_only=True)
    full = store.source_evidence(**scope)
    assert summary["rows"] == 12
    assert summary["missing_receipt_metadata_rows"] == 3
    assert summary["unresolved_source_rows"] == 3
    assert summary["legacy_quote_rows"] == 1
    for field in ("field_coverage", "invalid_ohlc_rows", "sources"):
        assert summary[field] == full[field]
    assert sum(item["rows"] for item in summary["sources"]) == 9


def test_reduced_details_recovers_archived_receipt_source_without_changing_facts(evidence_store, monkeypatch):
    from src.market.application import provenance_archive

    store, dates = evidence_store
    receipt_id = f"{CODES[1]}-{dates[0]}"
    store.conn.execute("UPDATE quotes_daily SET receipt_id=? WHERE code=?", (receipt_id, CODES[1]))
    store.conn.commit()
    scope = {"codes": CODES, "start": dates[0], "end": dates[-1]}
    expected = store.source_evidence(**scope, include_details=False)
    archived = dict(store.conn.execute("SELECT * FROM source_route_receipts WHERE receipt_id=?",
                                      (receipt_id,)).fetchone())
    store.conn.execute("DELETE FROM source_route_receipts WHERE receipt_id=?", (receipt_id,))
    store.conn.commit()
    requested = []

    def archived_receipts(_root, receipt_ids):
        requested.extend(receipt_ids)
        return [archived]

    monkeypatch.setattr(provenance_archive, "query_archived_receipts", archived_receipts)
    assert store.source_evidence(**scope, include_details=False) == expected
    assert requested == [receipt_id]


def test_attempt_field_reuse_returns_independent_lists_and_nested_values(evidence_store):
    store, dates = evidence_store
    receipt_ids = [f"{CODES[1]}-{day}" for day in dates]
    for position, payload in enumerate(['["open","close"]'] * 2 + ['[["nested"]]'] * 2
                                       + ['{invalid', '{"field":"open"}']):
        store.conn.execute("UPDATE source_route_attempts SET fields_json=? WHERE receipt_id=?",
                           (payload, receipt_ids[position]))
    store.conn.commit()
    attempts = store._attempts_by_receipt(receipt_ids)
    fields = [attempts[receipt_id][0]["fields"] for receipt_id in receipt_ids]
    fields[0].append("volume")
    fields[2][0].append("changed")
    assert fields[1] == ["open", "close"]
    assert fields[3] == [["nested"]]
    assert fields[4:] == [[], []]


def test_sql_summary_groups_by_code_and_source_instead_of_per_day_receipts(evidence_store):
    store, dates = evidence_store
    where, params = store._quote_where(CODES, start=dates[0], end=dates[-1], alias="q")
    summary_rows = store.conn.execute(store._quote_source_summary_sql(where), params).fetchall()
    original_rows = store._quote_evidence_rows(CODES, start=dates[0], end=dates[-1])
    assert len(original_rows) == 12
    assert len(summary_rows) == 5
    assert sum(row["rows"] for row in summary_rows) == 12
    assert all("receipt_id" not in row.keys() for row in summary_rows)


def test_missing_sqlite_receipt_metadata_is_reported_without_guessing_archive_or_attempt_status(evidence_store):
    store, dates = evidence_store
    store.conn.execute("DELETE FROM source_route_receipts WHERE receipt_id = ?",
                       (f"{CODES[1]}-{dates[2]}",))
    store.conn.commit()
    summary = store.source_evidence(codes=CODES, start=dates[0], end=dates[-1], summary_only=True)
    assert summary["rows"] == 12
    assert summary["missing_receipt_metadata_rows"] == 1
    assert summary["unresolved_source_rows"] == 1
    assert summary["source_summary_incomplete"] is True
    assert summary["attempts_not_observed"] is None
    assert "归档" in summary["detail_note"]
    assert sum(item["rows"] for item in summary["sources"]) == 11


def test_summary_handles_missing_codes_empty_ranges_and_chunked_code_parameters(evidence_store):
    store, dates = evidence_store
    requested = [*CODES, *[f"{600100 + position}" for position in range(905)]]
    summary = store.source_evidence(codes=requested, start=dates[0], end=dates[-1], summary_only=True)
    assert summary["rows"] == 12
    assert summary["observed_codes"] == CODES
    assert len(summary["unresolved_codes"]) == 905
    empty = store.source_evidence(codes=CODES, start="2025-01-01", summary_only=True)
    assert empty["rows"] == 0
    assert empty["sources"] == []
    assert empty["unresolved_codes"] == CODES
    assert empty["field_coverage"]["close"] == {"rows": 0, "ratio": 0.0}
    assert empty["attempts_not_observed"] is None


def test_only_explicit_engine_opt_in_uses_summary_in_screen_and_backtest(tmp_path, monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=180).strftime("%Y-%m-%d").tolist()
    path = tmp_path / "strategy-market.db"
    flags = []
    original_snapshot = MarketStore.data_snapshot

    def observed_snapshot(self, **kwargs):
        flags.append(kwargs.get("source_summary_only", False))
        return original_snapshot(self, **kwargs)

    monkeypatch.setattr(MarketStore, "data_snapshot", observed_snapshot)
    with MarketStore(path) as store:
        store.upsert_instruments(
            {"code": code, "name": "样本", "market": "sz", "board": "chi_next",
             "list_date": "2015-01-05"} for code in CODES
        )
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
            "outstanding_share,turnover,source,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [(day, code, 10.0, 10.02, 9.98, 10.0, 1_000_000.0, 10_000_000.0,
              100_000_000.0, 0.01, "tdx", day + "T15:30:00")
             for day in dates for code in CODES],
        )
        store.conn.commit()
        store.rebuild_calendar()
        baseline = get("yangshi-tail-v1")
        summary_engine = copy(baseline)
        summary_engine.source_evidence_summary = True
        for engine, summary_only in [(summary_engine, True), (baseline, False)]:
            result = screen(store, engine, trade_date=dates[-1], codes=CODES,
                            health_check=False, live_overlay=False)
            assert result.data_snapshot["source_evidence"].get("attempt_details_omitted", False) is summary_only
            context = prepare_backtest_context(store, engine, start=dates[-10], end=dates[-1], codes=CODES)
            assert context["data_snapshot"]["source_evidence"].get("attempt_details_omitted", False) is summary_only
    assert flags == [True, True, False, False]


@pytest.mark.parametrize("end_offset,failed_counts,unlinked_names", [
    (-1, {"failed": 4, "skipped": 1, "ok": 1},
     {"failure-at-start", "failure-overlap-start", "skip-at-end", "request-only", "unresolved-ok"}),
    (-4, {"failed": 3, "ok": 1},
     {"failure-at-start", "failure-overlap-start", "failure-before", "unresolved-ok"}),
])
def test_ordinary_screen_reads_compact_evidence_and_preserves_full_reader(
        tmp_path, monkeypatch, end_offset, failed_counts, unlinked_names):
    engine = get("qianlong-close-v3")
    assert not getattr(engine, "source_evidence_summary", False)
    dates = pd.bdate_range("2024-01-02", periods=72).strftime("%Y-%m-%d").tolist()
    latest_start, latest_end = dates[-engine.min_bars()], dates[-1]
    day = dates[end_offset]
    start = dates[dates.index(day) - engine.min_bars() + 1]
    code = CODES[0]
    linked_ids = {f"linked-{date}" for date in dates if start <= date <= day}
    linked_failure = f"linked-{dates[-2]}"
    with MarketStore(tmp_path / "screen-evidence.db") as store:
        store.upsert_instruments(
            {"code": item, "name": "样本", "market": "sz", "board": "chi_next",
             "list_date": "2015-01-05"} for item in CODES
        )
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
            "outstanding_share,turnover,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(date, code, 10., 10.2, 9.8, 10., 1_000_000., 10_000_000., 100_000_000.,
              .04, "tdx", f"linked-{date}", date + "T15:30:00") for date in dates],
        )
        receipts = [(f"linked-{date}", code, "hist_daily", "failed" if date == dates[-2] else "ok",
                     int(date == dates[-2]), date, date, "", "") for date in dates]
        receipts.extend([
            ("failure-at-start", code, "hist_daily", "failed", 0, latest_start, latest_start, "", ""),
            ("failure-overlap-start", code, "spot_batch", "failed", 0,
             dates[-engine.min_bars() - 1], latest_start, "", ""),
            ("skip-at-end", code, "hist_daily", "skipped", 0, latest_end, latest_end, "", ""),
            ("request-only", code, "hist_daily", "failed", 0, "", "", latest_end, latest_end),
            ("unresolved-ok", code, "hist_daily", "ok", 1, latest_start, latest_start, "", ""),
            ("failure-before", code, "hist_daily", "failed", 0,
             dates[-engine.min_bars() - 4], dates[-engine.min_bars() - 1], "", ""),
            ("failure-after", code, "hist_daily", "failed", 0, "2025-01-01", "2025-01-02", "", ""),
            ("failure-other-code", CODES[1], "hist_daily", "failed", 0, latest_start, latest_end, "", ""),
            ("failure-other-lane", code, "research", "failed", 0, latest_start, latest_end, "", ""),
            ("normal-unlinked", code, "hist_daily", "ok", 0, latest_start, latest_end, "", ""),
            ("unknown-scope", code, "hist_daily", "failed", 1, "", "", "", ""),
        ])
        store.conn.executemany(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,state,unresolved,coverage_start,"
            "coverage_end,request_start,request_end,selected_source,generated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(*row, "tencent", latest_end + "T15:30:00") for row in receipts],
        )
        store.conn.executemany(
            "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,rows) "
            "VALUES(?,?,?,?,?,?)",
            [(row[0], number, source, state, latest_end + "T15:30:00", int(number == 2))
             for row in receipts for number, source, state in [(1, "tdx", "failed"), (2, "tencent", "ok")]],
        )
        store.conn.commit()
        store.rebuild_calendar()
        attempt_requests = []
        original_attempts = store._attempts_by_receipt

        def observed_attempts(receipt_ids, **kwargs):
            attempt_requests.append((set(receipt_ids), kwargs))
            return original_attempts(receipt_ids, **kwargs)

        monkeypatch.setattr(store, "_attempts_by_receipt", observed_attempts)
        result = screen(store, engine, trade_date=day, codes=[code], extra_bars=0,
                        health_check=False, live_overlay=False)
        assert all(ids <= linked_ids for ids, _ in attempt_requests)
        assert any(options.get("max_rows") for _, options in attempt_requests)
        evidence = result.data_snapshot["source_evidence"]
        scope = {"codes": [code], "start": start, "end": day}
        assert result.data_snapshot["start"] == start and result.data_snapshot["end"] == day
        assert evidence["evidence_scope"] == scope
        assert {item["receipt_id"] for item in evidence["receipts"]} == (
            {linked_failure} if linked_failure in linked_ids else set()
        )
        assert evidence["receipts_total"] == len(linked_ids)
        assert evidence["attempts_total"] == 2 * len(linked_ids)
        assert len(evidence["attempts"]) == 50
        assert all(len(item["attempts"]) == 2 for item in evidence["receipts"])
        assert evidence["receipt_details_omitted"] is True
        assert evidence["receipt_detail_basis"] == "all_quote_linked_receipts"
        assert "attempt_details_omitted" not in evidence
        assert "完整严格PIT" in evidence["detail_note"]
        # Compact screening reads only the bounded transport projection. A linked
        # failed receipt remains detailed and the aggregate preserves its scope.
        assert evidence["historical_failure_scope"] == {
            "receipt_count": sum(failed_counts.values()), "by_state": failed_counts,
            "may_overlap_quote_linked_receipts": True, "detail_rows_materialized": False,
        }
        assert (linked_failure in linked_ids) is (end_offset == -1)
        full = store.source_evidence(**scope)
        assert attempt_requests[-1] == (linked_ids | unlinked_names, {})
        assert {item["receipt_id"] for item in full["receipts"]} == linked_ids | unlinked_names
        assert len(full["attempts"]) == 2 * (len(linked_ids) + len(unlinked_names))
        reduced = store.source_evidence(**scope, include_details=False)
        compact_source_evidence(reduced)
        assert evidence == reduced
        assert "receipt_details_omitted" not in full and "historical_failure_scope" not in full
        assert full["field_coverage"] == evidence["field_coverage"]
        assert full["invalid_ohlc_rows"] == evidence["invalid_ohlc_rows"]
