"""Synthetic evidence only: chronology, truthful coverage, and read-only loading."""
from copy import deepcopy
import json
import sqlite3

import pytest

from scripts.first_wave_theme_evidence import load_theme_evidence


D0 = "2026-10-21"
D2 = "2026-10-23"
THEME = "空中成像"


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE intel_snapshots (
            trade_date TEXT NOT NULL, tool TEXT NOT NULL, args_hash TEXT NOT NULL,
            server TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL, PRIMARY KEY (trade_date, tool, args_hash)
        )
    """)
    yield connection
    connection.close()


def sector(*, theme=THEME, fact_date=D0, strength_period=5, **metrics):
    row = {
        "name": theme, "periodChange": 23.78, "recentChange": 17.64,
        "recentUpDays": 4, "volumeRatio": 2.67,
    }
    row.update(metrics)
    result = {
        "stats": {}, "meta": {"period": 60, "strengthPeriod": strength_period, "sectorCount": 251},
        "topLists": {"continuingStrong": [row], "emerging": []},
    }
    if fact_date is not None:
        result["meta"]["tradeDate"] = fact_date
    return result


def membership(*, codes=("600001",), theme=THEME, fact_date=D0, **extra):
    result = {
        "theme": {"name": theme, "themeCode": "801631k"},
        "resolution": {"tradeDate": fact_date.replace("-", "")},
        "rows": [{"code": code, "tags": [{"name": "别的标签"}]} for code in codes],
        "total": len(codes), "returned": len(codes),
    }
    result.update(extra)
    return result


def put(db, tool, body, *, day=D0, fetched="2026-10-21T16:00:00+08:00", mode="structured", **flags):
    wrapper = {"tool": tool, "arguments": {}, "server": "synthetic", "is_error": False, "truncated": False}
    if mode == "text":
        wrapper.update(structured=None, text=json.dumps({"tool": tool, "success": True, "data": body}))
    elif mode == "envelope":
        wrapper["structured"] = {"tool": tool, "success": True, "data": body}
    elif mode == "json_structured":
        wrapper["structured"] = json.dumps(body)
    else:
        wrapper["structured"] = body
    wrapper.update(flags)
    key = str(db.execute("SELECT COUNT(*) FROM intel_snapshots").fetchone()[0])
    db.execute(
        "INSERT INTO intel_snapshots (trade_date,tool,args_hash,payload_json,fetched_at) VALUES (?,?,?,?,?)",
        (day, tool, key, json.dumps(wrapper), fetched),
    )


def evaluate(db, code="600001", **dates):
    return load_theme_evidence(db).evaluate(code, dates.get("asof", D0), dates.get("decision", D2))


@pytest.mark.parametrize("mode", ["structured", "text", "envelope", "json_structured"])
def test_real_wrapper_shapes_and_positive_membership(db, mode):
    put(db, "sector_analysis", sector(fact_date=None), fetched="2026-10-21T07:40:07+00:00")
    put(db, "theme_stocks", membership(), mode=mode)
    result = evaluate(db)
    assert result["passed"] is True
    assert result["status"] == "verified"
    assert result["themes"] == [THEME]
    assert result["coverage_complete"] is True
    assert "sector_analysis:fact_date_from_same_day_capture" in result["warnings"]
    assert {r["tool"] for r in result["source"]} == {"sector_analysis", "theme_stocks"}
    assert all(r["trade_date"] == D0 and r["fetched_at"] for r in result["source"])


@pytest.mark.parametrize("tool", ["sector_analysis", "theme_stocks"])
@pytest.mark.parametrize("fetched,passed", [
    ("2026-10-22T09:00:00+08:00", True),  # D0 fact fetched after its close.
    ("2026-10-23T06:49:59+00:00", True),
    ("2026-10-23T06:50:00+00:00", False),  # Exactly 14:50 is excluded.
    ("2026-10-23T14:50:01+08:00", False),
    ("2026-10-26T09:00:00+08:00", False),
])
def test_actual_fetch_time_and_strict_local_cutoff(db, tool, fetched, passed):
    for current, body in (("sector_analysis", sector()), ("theme_stocks", membership())):
        kwargs = {"fetched": fetched} if current == tool else {}
        put(db, current, body, **kwargs)
    result = evaluate(db)
    assert result["passed"] is passed
    if not passed:
        assert result["status"] == "unknown"
        assert not any(r["fetched_at"] == fetched for r in result["source"])


@pytest.mark.parametrize("fact_date", ["2026-10-20", "2026-10-22"])
def test_sector_facts_must_belong_to_d0_even_if_cache_key_claims_d0(db, fact_date):
    put(db, "sector_analysis", sector(fact_date=fact_date))
    put(db, "theme_stocks", membership())
    result = evaluate(db)
    assert result["status"] == "unknown"
    assert "sector_analysis:sector_fact_date_not_asof" in result["warnings"]


def test_previous_day_strength_is_not_carried_forward(db):
    put(db, "sector_analysis", sector(fact_date="2026-10-20"), day="2026-10-20")
    put(db, "theme_stocks", membership())
    assert evaluate(db)["status"] == "unknown"


def test_undated_cross_day_sector_is_not_backfilled_from_requested_arguments(db):
    put(db, "sector_analysis", sector(fact_date=None), fetched="2026-10-22T09:00:00+08:00",
        arguments={"tradeDate": D0})
    put(db, "theme_stocks", membership())
    result = evaluate(db)
    assert result["status"] == "unknown"
    assert "sector_analysis:undated_sector_captured_on_other_day" in result["warnings"]


@pytest.mark.parametrize("patch", [
    {"actualTradeDate": "20261022"},
    {"dateStatus": "mismatch"},
    {"qualityWarnings": ["date_mismatch"]},
])
def test_sector_date_mismatch_cannot_pass(db, patch):
    body = sector()
    body["meta"].update(patch)
    put(db, "sector_analysis", body)
    put(db, "theme_stocks", membership())
    assert evaluate(db)["status"] == "unknown"


def test_future_membership_actual_date_is_rejected_with_diagnostics(db):
    put(db, "sector_analysis", sector())
    body = membership()
    body["resolution"].update(actualTradeDate="20261022", dateStatus="mismatch")
    put(db, "theme_stocks", body, fetched="2026-10-22T16:00:00+08:00")
    result = evaluate(db)
    assert result["status"] == "unknown"
    assert any("membership_fact_date_after_asof" in w for w in result["warnings"])
    assert any("date_mismatch" in w for w in result["warnings"])


def test_explicit_d0_membership_can_be_captured_and_cached_on_d1(db):
    put(db, "sector_analysis", sector(), fetched="2026-10-22T09:00:00+08:00")
    put(db, "theme_stocks", membership(), day="2026-10-22", fetched="2026-10-22T09:01:00+08:00")
    result = evaluate(db)
    assert result["passed"] is True
    assert result["source"][-1]["trade_date"] == "2026-10-22"
    assert result["source"][-1]["fact_dates"] == [D0]


def test_disagreeing_member_dates_warn_even_when_server_omits_mismatch_flag(db):
    put(db, "sector_analysis", sector())
    body = membership()
    body["resolution"]["actualTradeDate"] = "20261020"
    put(db, "theme_stocks", body)
    evidence = load_theme_evidence(db)
    positive = evidence.evaluate("600001", D0, D2)
    assert positive["passed"] is True
    assert positive["coverage_complete"] is False
    assert any("date_mismatch" in w for w in positive["warnings"])
    assert evidence.evaluate("600002", D0, D2)["status"] == "unknown"


def test_older_actual_membership_cannot_override_complete_d0_facts(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership(codes=("600002",)))
    older = membership()
    older["resolution"].update(actualTradeDate="20261020", dateStatus="mismatch")
    put(db, "theme_stocks", older, fetched="2026-10-22T10:00:00+08:00")
    assert evaluate(db)["status"] == "not_in_observed_mainline"


@pytest.mark.parametrize("patch", [
    {"recentChange": 4.99}, {"recentUpDays": 2}, {"volumeRatio": 1.09},
])
def test_mainline_requires_all_recent_thresholds_not_long_period_gain_or_theme_name(db, patch):
    put(db, "sector_analysis", sector(**patch))
    put(db, "theme_stocks", membership())
    result = evaluate(db)
    assert result["status"] == "not_in_observed_mainline"
    assert result["themes"] == []
    assert result["passed"] is False


def test_emerging_at_exact_thresholds_counts_as_mainline(db):
    body = sector(recentChange=5, recentUpDays=3, volumeRatio=1.1)
    body["topLists"]["emerging"] = body["topLists"].pop("continuingStrong")
    body["topLists"]["continuingStrong"] = []
    put(db, "sector_analysis", body)
    put(db, "theme_stocks", membership())
    assert evaluate(db)["passed"] is True


@pytest.mark.parametrize("period", [None, 20])
def test_five_day_strength_window_must_be_verified(db, period):
    put(db, "sector_analysis", sector(strength_period=period))
    put(db, "theme_stocks", membership())
    assert evaluate(db)["status"] == "unknown"


@pytest.mark.parametrize("field", ["recentChange", "recentUpDays", "volumeRatio"])
def test_missing_metrics_do_not_prove_absence(db, field):
    body = sector()
    del body["topLists"]["continuingStrong"][0][field]
    put(db, "sector_analysis", body)
    assert evaluate(db)["status"] == "unknown"


@pytest.mark.parametrize("patch", [
    {"recentChange": float("nan")}, {"recentUpDays": 3.5},
    {"recentTotalDays": 3}, {"volumeRatio": float("inf")},
])
def test_unverifiable_strength_metrics_are_unknown(db, patch):
    put(db, "sector_analysis", sector(**patch))
    put(db, "theme_stocks", membership())
    assert evaluate(db)["status"] == "unknown"


@pytest.mark.parametrize("kind", ["truncated", "partial_errors", "returned_limit", "missing_counts", "date_mismatch"])
def test_partial_positive_is_evidence_but_partial_absence_is_unknown(db, kind):
    put(db, "sector_analysis", sector())
    body, flags = membership(), {}
    if kind == "truncated":
        flags["truncated"] = True
    elif kind == "partial_errors":
        body["partialErrors"] = [{"reason": "upstream_timeout"}]
    elif kind == "returned_limit":
        body["total"] = 165
    elif kind == "missing_counts":
        del body["total"]
    else:
        body["resolution"].update(dateStatus="mismatch", actualTradeDate="20261020")
    put(db, "theme_stocks", body, **flags)
    evidence = load_theme_evidence(db)
    positive = evidence.evaluate("600001", D0, D2)
    missing = evidence.evaluate("600002", D0, D2)
    assert positive["passed"] is True
    assert positive["status"] == "verified"
    assert positive["warnings"]
    assert positive["coverage_complete"] is False
    assert missing["status"] == "unknown"
    assert missing["passed"] is False


def test_mismatch_without_actual_date_does_not_validate_requested_date(db):
    put(db, "sector_analysis", sector())
    body = membership()
    body["resolution"]["dateStatus"] = "mismatch"
    put(db, "theme_stocks", body)
    assert evaluate(db)["status"] == "unknown"


def test_missing_member_snapshot_is_not_negative_evidence(db):
    put(db, "sector_analysis", sector())
    assert evaluate(db)["status"] == "unknown"


def test_complete_historical_nonmember_is_known_only_within_observed_mainlines(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership(codes=("600002",), fact_date="2026-10-20"), day="2026-10-20")
    result = evaluate(db)
    assert result["status"] == "not_in_observed_mainline"
    assert result["coverage_complete"] is True
    assert result["passed"] is False
    assert result["source"][-1]["fact_dates"] == ["2026-10-20"]


def test_empty_complete_list_and_missing_rows_are_different(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership(codes=()))
    assert evaluate(db)["status"] == "not_in_observed_mainline"
    incomplete = membership(codes=())
    del incomplete["rows"]
    put(db, "theme_stocks", incomplete, fetched="2026-10-21T17:00:00+08:00")
    # Latest complete remains usable; a failed response cannot fabricate absence.
    assert evaluate(db)["status"] == "not_in_observed_mainline"
    db.execute("DELETE FROM intel_snapshots WHERE fetched_at=?", ("2026-10-21T16:00:00+08:00",))
    put(db, "sector_analysis", sector())
    assert evaluate(db)["status"] == "unknown"


def test_membership_requires_fact_date_not_argument_or_tag(db):
    put(db, "sector_analysis", sector())
    body = membership(theme="其他题材")
    body.pop("resolution")
    body["rows"][0]["tags"] = [{"name": THEME}]
    put(db, "theme_stocks", body, arguments={"tradeDate": D0, "themeName": THEME})
    assert evaluate(db)["status"] == "unknown"


def test_matching_theme_with_missing_fact_date_cannot_use_cache_key(db):
    put(db, "sector_analysis", sector())
    body = membership()
    body.pop("resolution")
    put(db, "theme_stocks", body, arguments={"tradeDate": D0})
    result = evaluate(db)
    assert result["status"] == "unknown"
    assert any("missing_membership_fact_date" in w for w in result["warnings"])


@pytest.mark.parametrize("code,status", [("600001", "verified"), ("600002", "unknown")])
def test_truncated_sector_retains_observed_positive_but_cannot_prove_absence(db, code, status):
    put(db, "sector_analysis", sector(), truncated=True)
    put(db, "theme_stocks", membership())
    result = evaluate(db, code)
    assert result["status"] == status
    assert result["coverage_complete"] is False
    assert "sector_analysis:truncated" in result["warnings"]


def test_latest_complete_membership_overrides_old_positive_and_future_is_ignored(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership(), truncated=True)
    put(db, "theme_stocks", membership(codes=("600002",)), fetched="2026-10-22T10:00:00+08:00")
    put(db, "theme_stocks", membership(), fetched="2026-10-23T14:51:00+08:00")
    assert evaluate(db)["status"] == "not_in_observed_mainline"


def test_newer_partial_absence_preserves_latest_complete_and_new_positive_is_independent(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership())
    put(db, "theme_stocks", membership(codes=("600002",), total=120), fetched="2026-10-22T10:00:00+08:00")
    evidence = load_theme_evidence(db)
    assert evidence.evaluate("600001", D0, D2)["passed"] is True
    assert evidence.evaluate("600002", D0, D2)["passed"] is True
    assert evidence.evaluate("600003", D0, D2)["status"] == "not_in_observed_mainline"


def test_latest_complete_sector_is_used_instead_of_newer_unverifiable_response(db):
    put(db, "sector_analysis", sector())
    put(db, "sector_analysis", sector(theme="其他题材"), truncated=True, fetched="2026-10-22T11:00:00+08:00")
    put(db, "theme_stocks", membership())
    result = evaluate(db)
    assert result["passed"] is True
    assert result["themes"] == [THEME]
    assert "sector_analysis:truncated" in result["warnings"]


def test_any_positive_can_pass_when_other_observed_themes_are_unknown(db):
    body = sector()
    other = deepcopy(body["topLists"]["continuingStrong"][0])
    other["name"] = "未覆盖题材"
    body["topLists"]["emerging"].append(other)
    put(db, "sector_analysis", body)
    put(db, "theme_stocks", membership())
    result = evaluate(db)
    assert result["passed"] is True
    assert result["coverage_complete"] is False
    assert evaluate(db, "600002")["status"] == "unknown"


@pytest.mark.parametrize("payload", ["not json", '{"structured": null}', '{"is_error": true}'])
def test_bad_payloads_fail_closed(db, payload):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership())
    db.execute("UPDATE intel_snapshots SET payload_json=? WHERE tool=?", (payload, "theme_stocks"))
    assert evaluate(db)["status"] == "unknown"


@pytest.mark.parametrize("fetched", ["2026-10-21", "garbled", ""])
def test_date_only_or_invalid_fetch_timestamp_cannot_be_invented(db, fetched):
    put(db, "sector_analysis", sector(), fetched=fetched)
    put(db, "theme_stocks", membership())
    assert evaluate(db)["status"] == "unknown"


def test_load_and_evaluate_are_read_only_and_do_not_rescan_sql(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership())
    db.commit()
    db.execute("PRAGMA query_only=ON")
    statements = []
    db.set_trace_callback(statements.append)
    evidence = load_theme_evidence(db)
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert len([s for s in statements if "SELECT tool," in s]) == 1
    statements.clear()
    for _ in range(3):
        for code in ("600001", "600002"):
            assert evidence.evaluate(code, D0, D2)["status"] != "unknown"
    assert statements == []


@pytest.mark.parametrize("tool", ["sector_analysis", "theme_stocks"])
def test_transport_errors_cannot_supply_positive_evidence(db, tool):
    put(db, "sector_analysis", sector(), is_error=tool == "sector_analysis")
    put(db, "theme_stocks", membership(), is_error=tool == "theme_stocks")
    assert evaluate(db)["status"] == "unknown"


def test_evaluations_do_not_share_mutable_output(db):
    put(db, "sector_analysis", sector())
    put(db, "theme_stocks", membership())
    evidence = load_theme_evidence(db)
    first = evidence.evaluate("600001", D0, D2)
    first["source"][0]["themes"].clear()
    first["themes"].clear()
    first["warnings"].append("caller_mutation")
    second = evidence.evaluate("sh600001", "20261021", "20261023")
    assert second["themes"] == [THEME]
    assert second["source"][0]["themes"] == [THEME]
    assert "caller_mutation" not in second["warnings"]


def test_missing_table_and_old_history_return_unknown_without_creating_data():
    connection = sqlite3.connect(":memory:")
    evidence = load_theme_evidence(connection)
    connection.close()
    result = evidence.evaluate("600001", "2010-01-04", "2010-01-06")
    assert result["status"] == "unknown"
    assert result["warnings"] == ["missing_intel_snapshots"]


@pytest.mark.parametrize("code,asof,decision", [
    ("bad", D0, D2), ("600001", "bad", D2), ("600001", D0, "2026-10-20"),
])
def test_invalid_inputs_cannot_pass(db, code, asof, decision):
    assert evaluate(db, code, asof=asof, decision=decision)["status"] == "unknown"
