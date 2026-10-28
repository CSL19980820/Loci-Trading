"""Synthetic, isolated proofs for the original first-buy evidence audit."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pytest

from scripts import first_wave_original_audit as audit

DAY = "2026-10-23"
CODE = "000001.SZ"


def daily(*, low: float = 9, high: float = 11) -> pd.DataFrame:
    dates = pd.bdate_range(end=DAY, periods=7).strftime("%Y-%m-%d")
    frame = pd.DataFrame({
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0,
        "volume": 100.0, "factor": 1.0,
    }, index=dates)
    frame.loc[DAY, ["low", "high"]] = low, high
    return frame


def minutes(points: list[tuple[str, float, float, float]], *, day: str = DAY) -> pd.DataFrame:
    """Points contain time, close, open, volume; quotes may have zero volume."""
    return pd.DataFrame([
        {"open": opening, "high": max(price, opening), "low": min(price, opening),
         "close": price, "volume": volume}
        for _, price, opening, volume in points
    ], index=pd.to_datetime([f"{day} {time}" for time, *_ in points]))


def test_price_samples_prove_condition_without_inventing_minute_open_or_extrema():
    frame = pd.DataFrame({"close": [10.1, 10.2], "volume": [0, 100]},
                         index=pd.to_datetime([f"{DAY} 14:50", f"{DAY} 14:51"]))
    frame = frame.reindex(columns=["open", "high", "low", "close", "volume"])
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_condition"] == "true"
    assert result["minute_1450_price"] == 10.1
    assert result["minute_1450_volume"] == 0
    assert result["next_observed_open"] is None


def test_binary_rounding_at_daily_high_is_not_a_real_price_inconsistency():
    bars = daily(low=5, high=6.06)
    bars.loc[bars.index[:-1], "close"] = 6
    frame = minutes([("14:50", 6.0600000000000005, 6.06, 100)])
    result = audit.audit_buy_condition(bars, DAY, code=CODE, minute_frame=frame)
    assert result["minute_status"] == "observed"
    assert result["minute_condition"] == "true"
    assert result["data_inconsistent"] is False
    frame.loc[frame.index[0], "close"] = 6.07
    assert audit.audit_buy_condition(bars, DAY, code=CODE, minute_frame=frame)["minute_status"] == "data_inconsistent"


@pytest.mark.parametrize(("low", "high", "expected"), [
    (10, 12, "always_true"), (11, 12, "always_true"),
    (8, 9.99, "always_false"), (9, 11, "ambiguous"),
    (9, 10, "ambiguous"), (10, 10, "always_true"),
])
def test_interval_proofs_and_equalities(low, high, expected):
    result = audit.audit_buy_condition(daily(low=low, high=high), DAY, code=CODE)
    assert result["threshold_raw"] == 10
    assert result["interval_status"] == expected
    assert result["minute_condition"] == "unknown"
    assert result["next_observed_open"] is None


@pytest.mark.parametrize("factor", [0.5, 1.0, 2.0, 8.0])
def test_algebra_matches_dynamic_ma5_with_corporate_actions(factor):
    bars = daily(low=1, high=100)
    bars.loc[bars.index[-5:-1], "close"] = [8, 12, 10, 6]
    bars.loc[bars.index[-5:-1], "factor"] = [1, 1, 2, 2]
    bars.loc[DAY, "factor"] = factor
    total = 8 + 12 + 20 + 12
    threshold = total / (4 * factor)
    for price in [threshold * 0.9, threshold, threshold * 1.1]:
        result = audit.audit_buy_condition(bars, DAY, code=CODE, minute_frame=minutes([("14:50", price, price, 0)]))
        dynamic_ma5 = (total / factor + price) / 5
        assert (price >= dynamic_ma5) == (price >= result["threshold_raw"])
        assert result["minute_condition"] == ("true" if price >= dynamic_ma5 else "false")
        assert result["prior_adjusted_close_sum"] == total
        assert [row["close_adjusted"] for row in result["reference_closes"]] == [8, 12, 20, 12]


@pytest.mark.parametrize("bad_factor", [0, -1, np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("on_d2", [False, True])
def test_bad_required_factor_is_unknown_and_never_replaced(bad_factor, on_d2):
    bars = daily()
    bad_day = DAY if on_d2 else bars.index[-3]
    bars.loc[bad_day, "factor"] = bad_factor
    result = audit.audit_buy_condition(bars, DAY, code=CODE, minute_frame=minutes([("14:50", 10, 10, 100)]))
    assert result["interval_status"] == "unverifiable"
    assert result["threshold_raw"] is None
    assert result["minute_condition"] == "unknown"
    assert [row["date"] for row in result["reference_closes"]] == list(bars.index[-5:-1])


@pytest.mark.parametrize("bad_close", [0, -1, np.nan, np.inf])
def test_invalid_observed_close_does_not_substitute_older_day(bad_close):
    bars = daily()
    bars.loc[bars.index[-3], "close"] = bad_close
    result = audit.audit_buy_condition(bars, DAY, code=CODE)
    assert result["interval_status"] == "unverifiable"
    assert result["threshold_raw"] is None
    assert result["reference_closes"][2]["date"] == bars.index[-3]


def test_insufficient_history_missing_d2_and_suspended_calendar_rows():
    bars = daily()
    result = audit.audit_buy_condition(bars.iloc[-4:], DAY, code=CODE)
    assert result["interval_reason"] == "insufficient_observed_history"
    assert result["threshold_raw"] is None
    missing = audit.audit_buy_condition(bars.iloc[:-1], DAY, code=CODE)
    assert missing["interval_reason"] == "signal_date_missing"
    suspended_day = bars.index[-3]
    bars.loc[suspended_day, ["open", "high", "low", "close", "volume"]] = np.nan
    bars.loc[suspended_day, "factor"] = 0
    result = audit.audit_buy_condition(bars, DAY, code=CODE)
    assert result["threshold_raw"] == 10
    assert suspended_day not in [row["date"] for row in result["reference_closes"]]


def test_future_daily_values_and_d2_eventual_close_cannot_change_threshold():
    bars = daily()
    before = audit.audit_buy_condition(bars, DAY, code=CODE)
    bars.loc[DAY, "close"] = 9999
    bars.loc["2026-10-26"] = [np.inf, -1, np.nan, 999999, 0, np.nan]
    after = audit.audit_buy_condition(bars, DAY, code=CODE)
    assert after["threshold_raw"] == before["threshold_raw"] == 10
    assert after["reference_closes"] == before["reference_closes"]
    assert after["interval_status"] == before["interval_status"]


def test_zero_volume_quote_and_next_open_are_distinct_observations():
    frame = minutes([("14:49", 10, 10, 0), ("14:51", 10.8, 10.6, 0)])
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_status"] == "observed"
    assert result["minute_condition"] == "true"
    assert result["minute_1450_lag_seconds"] == 60
    assert result["minute_1450_volume"] == 0
    assert result["next_observed_open"] == 10.6
    assert result["next_observed_open_time"] == f"{DAY}T14:51:00"
    assert not any("fill" in key or "return" in key for key in result)


def test_later_minutes_do_not_supply_a_decision_quote():
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=minutes([("14:51", 11, 10.5, 100)]))
    assert result["minute_condition"] == "unknown"
    assert result["minute_1450_price"] is None
    assert result["next_observed_open"] == 10.5


def test_later_invalid_prices_do_not_change_1450_condition():
    frame = minutes([("14:50", 9.5, 9.5, 100), ("14:51", 10, 10, 100)])
    before = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    changed = frame.astype(object)
    changed.loc[pd.Timestamp(f"{DAY} 14:51"), ["open", "close", "high", "low"]] = "invalid"
    after = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=changed)
    for field in ("threshold_raw", "minute_1450_time", "minute_1450_price", "minute_status", "minute_condition"):
        assert after[field] == before[field]
    assert after["next_open_status"] == "unverifiable"


def test_latest_snapshot_wins_and_older_than_one_minute_is_unknown():
    frame = minutes([("14:48", 11, 11, 100), ("14:51", 10, 10, 100)])
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_status"] == "stale"
    assert result["minute_condition"] == "unknown"
    assert result["minute_1450_lag_seconds"] == 120
    frame = minutes([("14:49", 11, 11, 100), ("14:50", 9.5, 9.5, 0), ("14:51", 11, 11, 100)])
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_1450_price"] == 9.5
    assert result["minute_condition"] == "false"


@pytest.mark.parametrize(("low", "high", "price", "comparison"), [
    (10, 11, 9, "contradiction"), (8, 9, 10, "contradiction"),
    (10, 11, 12, "consistent"), (9, 11, 12, "not_comparable"),
])
def test_minute_daily_inconsistency_and_proof_contradictions(low, high, price, comparison):
    result = audit.audit_buy_condition(daily(low=low, high=high), DAY, code=CODE, minute_frame=minutes([("14:50", price, price, 0)]))
    assert result["data_inconsistent"] is True
    assert result["minute_status"] == "data_inconsistent"
    assert result["minute_condition"] == "unknown"
    assert result["interval_minute_comparison"] == comparison
    assert result["minute_range_inconsistent_times"] == [f"{DAY}T14:50:00"]


def test_later_range_inconsistency_only_affects_retrospective_evidence():
    result = audit.audit_buy_condition(daily(low=10, high=11), DAY, code=CODE, minute_frame=minutes([
        ("14:50", 10, 10, 100), ("14:53", 999, 999, 0),
    ]))
    assert result["minute_condition"] == "true"
    assert result["minute_status"] == "observed"
    assert result["interval_minute_comparison"] == "consistent"
    assert result["data_inconsistent"] is True
    assert result["next_open_status"] == "data_inconsistent"
    assert result["next_observed_open_time"] == f"{DAY}T14:53:00"


def test_timezone_and_invalid_minute_indices():
    frame = minutes([("14:50", 10, 10, 100)])
    frame.index = frame.index.tz_localize("Asia/Shanghai").tz_convert("UTC")
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_condition"] == "true"
    frame.index = pd.to_datetime(["2026-10-22 14:50"])
    result = audit.audit_buy_condition(daily(), DAY, code=CODE, minute_frame=frame)
    assert result["minute_status"] == "unverifiable"
    assert result["minute_condition"] == "unknown"


def synthetic_database(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE instruments(code TEXT, name TEXT, instrument_type TEXT, list_date TEXT);
            CREATE TABLE quotes_daily(trade_date TEXT, code TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);
            CREATE TABLE adjust_factors(code TEXT, trade_date TEXT, hfq_factor REAL);
            CREATE TABLE intel_snapshots(tool TEXT, trade_date TEXT, payload_json TEXT, fetched_at TEXT);
        """)
        con.execute("INSERT INTO instruments VALUES (?, 'synthetic', 'STOCK', '')", (CODE,))
        con.executemany("INSERT INTO quotes_daily VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (day, CODE, *row[["open", "high", "low", "close", "volume"]]) for day, row in daily().iterrows()
        ])
        con.execute("INSERT INTO adjust_factors VALUES (?, '1990-01-01', 1)", (CODE,))


def test_run_uses_shared_readonly_boundary_all_opportunities_and_zero_years(tmp_path, monkeypatch):
    db = tmp_path / "synthetic.db"
    synthetic_database(db)
    original_bytes = db.read_bytes()
    setups = [
        {"code": CODE, "status": "setup_ready", "d2_date": DAY, "start_date": f"episode-{i}",
         "mainline_proxy_passed": "False" if i % 2 else "True", "theme_status": "unknown"}
        for i in range(25)
    ]
    setups += [
        {"code": CODE, "status": "setup_ready", "d2_date": ""},
        {"code": CODE, "status": "wave_gain", "d2_date": DAY},
        {"code": "000002.SZ", "status": "setup_ready", "d2_date": DAY},
    ]
    pd.DataFrame(setups).to_csv(tmp_path / "all-wave-setups.csv", index=False)
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    snapshot = {
        "trade_date": DAY, "fetched_at": f"{DAY}T15:10:00", "arguments": {"code": CODE},
        "structured": {"actualTradeDate": DAY, "points": [
            {"time": f"{DAY} 14:50", "price": 10, "volume": 0},
            {"time": f"{DAY} 14:51", "price": 10.5, "volume": 0},
        ]},
    }
    (overlay / "minute.json").write_text(json.dumps(snapshot), encoding="utf-8")
    actual_loader = audit.load_panels
    calls = []

    def check_readonly(con):
        calls.append("panels")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("DELETE FROM quotes_daily")
        return actual_loader(con)

    monkeypatch.setattr(audit, "load_panels", check_readonly)
    summary = audit.run(db, tmp_path, overlay)
    assert calls == ["panels"]
    assert db.read_bytes() == original_bytes
    assert summary["source_setup_rows"] == 28
    assert summary["setup_ready_rows"] == 27
    assert summary["setup_ready_without_d2"] == 1
    assert summary["eligible_opportunities"] == summary["opportunities"] == 26
    assert list(summary["by_year"]) == [str(year) for year in range(1990, 2027)]
    assert summary["by_year"]["1990"]["opportunities"] == 0
    assert summary["by_year"]["2026"]["opportunities"] == 26
    assert summary["by_year"]["1990"]["interval_status_counts"]["always_true"] == 0
    assert summary["minute_coverage"]["frames_available"] == 25
    assert summary["minute_coverage"]["zero_volume_1450_quotes"] == 25
    assert summary["minute_coverage"]["next_observed_opens"] == 25
    document = json.loads((tmp_path / "original-buy-audit.json").read_text(encoding="utf-8"))
    assert len(document["audits"]) == 26
    assert document["audits"][1]["mainline_proxy_passed"] == "False"
    assert document["audits"][1]["theme_status"] == "unknown"
    assert all(row["true_mainline_status"] == "unknown" for row in document["audits"])
    assert document["audits"][-1]["interval_reason"] == "code_missing_from_panels"
    output = pd.read_csv(tmp_path / "original-buy-audit.csv", dtype=str, keep_default_na=False)
    assert len(output) == 26
    assert output.iloc[0]["code"] == CODE
    assert len(json.loads(output.iloc[0]["reference_closes"])) == 4


def test_empty_opportunity_universe_writes_headers_and_all_years(tmp_path):
    db = tmp_path / "synthetic.db"
    synthetic_database(db)
    (tmp_path / "all-wave-setups.csv").write_text("status,code,d2_date\n", encoding="utf-8")
    summary = audit.run(db, tmp_path)
    assert summary["opportunities"] == 0
    assert all(year["opportunities"] == 0 for year in summary["by_year"].values())
    assert "threshold_raw" in pd.read_csv(tmp_path / "original-buy-audit.csv").columns
