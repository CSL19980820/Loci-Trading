"""Retrospective evidence audit of the original D2 first-buy MA5 condition.

For raw price P and D2 factor f, P >= (S / f + P) / 5 iff P >= S / (4f),
where S contains only the preceding four observed adjusted closes. Daily L/H
prove bounds after the fact; they are never intraday signals or buy prices.
The JSON contains ``summary`` and ``audits``; run() returns the summary.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import date
import hashlib
import gzip
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.first_wave_research import load_minutes, load_panels  # noqa: E402 - direct CLI path bootstrap

_OHLC = ["open", "high", "low", "close"]
_INTERVAL_STATUSES = ("always_true", "always_false", "ambiguous", "unverifiable")
_MINUTE_STATUSES = ("observed", "missing", "stale", "unverifiable", "data_inconsistent")
_COMPARISONS = ("consistent", "contradiction", "not_comparable")
_PRICE_EPS = 1e-10  # Binary float noise, far below the minimum quoted price tick.
_SETUP_FIELDS = (
    "start_date", "d0_date", "d1_date", "d2_date",
    "mainline_proxy_passed", "theme_status",
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _empty_audit(code: str, signal_date: str) -> dict:
    return {
        "code": code,
        "signal_date": signal_date,
        "threshold_raw": None,
        "low": None,
        "high": None,
        "d2_factor": None,
        "reference_closes": [],
        "prior_adjusted_close_sum": None,
        "interval_status": "unverifiable",
        "interval_reason": "signal_date_missing",
        "minute_frame_available": False,
        "minute_status": "missing",
        "minute_reason": "minute_data_missing",
        "minute_1450_time": None,
        "minute_1450_price": None,
        "minute_1450_volume": None,
        "minute_1450_lag_seconds": None,
        "minute_condition_raw": "unknown",
        "minute_condition": "unknown",
        "next_observed_open_time": None,
        "next_observed_open": None,
        "next_observed_open_volume": None,
        "next_open_status": "missing",
        "data_inconsistent": False,
        "minute_range_inconsistent_times": [],
        "interval_minute_comparison": "not_comparable",
        "true_mainline_status": "unknown",
    }


def audit_buy_condition(
    bars: pd.DataFrame,
    signal_date: str,
    *,
    code: str,
    minute_frame: pd.DataFrame | None = None,
) -> dict:
    """Audit one D2, without a fill, capacity, mainline or profit assumption.

    Index/schema follow first_wave_execution. A zero-volume minute still
    supplies a quote. ``minute_condition_raw`` retains the arithmetic result
    for contradiction checks; inconsistent quotes leave the accepted
    ``minute_condition`` unknown. Later observations cannot change that result.
    """
    result = _empty_audit(code, signal_date)
    try:
        if date.fromisoformat(signal_date).isoformat() != signal_date:
            raise ValueError("signal_date_must_be_iso")
        if (
            not bars.index.is_unique
            or not bars.index.is_monotonic_increasing
            or any(not isinstance(day, str) for day in bars.index)
        ):
            raise ValueError("daily_index_must_be_unique_sorted_iso_dates")
        if signal_date not in bars.index:
            return result
        # Nothing after D2, including D2's eventual close, enters the threshold.
        prefix = bars.loc[:signal_date, [*_OHLC, "volume", "factor"]]
        prior = prefix.iloc[:-1]
        observed = prior[_OHLC].notna().any(axis=1)
        history = prior.loc[observed].tail(4)
        if any(date.fromisoformat(day).isoformat() != day for day in history.index):
            raise ValueError("daily_index_must_be_unique_sorted_iso_dates")
    except (KeyError, TypeError, ValueError) as exc:
        result["interval_reason"] = f"invalid_daily_data: {exc}"
        return result

    day = prefix.iloc[-1]
    low, high, factor = (_number(day[field]) for field in ("low", "high", "factor"))
    result.update(low=low, high=high, d2_factor=factor)
    for reference_date, reference in history.iterrows():
        close, reference_factor = (_number(reference[field]) for field in ("close", "factor"))
        adjusted = (
            _number(close * reference_factor)
            if close is not None and close > 0 and reference_factor is not None and reference_factor > 0
            else None
        )
        result["reference_closes"].append({
            "date": reference_date, "close_raw": close,
            "factor": reference_factor, "close_adjusted": adjusted,
        })
    references = result["reference_closes"]
    if len(references) != 4:
        result["interval_reason"] = "insufficient_observed_history"
    elif any(item["close_adjusted"] is None or item["close_adjusted"] <= 0 for item in references):
        result["interval_reason"] = "invalid_reference_close_or_factor"
    elif factor is None or factor <= 0:
        result["interval_reason"] = "invalid_d2_factor"
    else:
        total = _number(sum(item["close_adjusted"] for item in references))
        threshold = _number(total / 4 / factor) if total is not None else None
        result.update(prior_adjusted_close_sum=total, threshold_raw=threshold)
        if threshold is None or threshold <= 0:
            result["interval_reason"] = "invalid_adjusted_threshold"
            result["threshold_raw"] = None
        elif low is None or high is None or not 0 < low <= high:
            result["interval_reason"] = "invalid_daily_interval"
        elif low >= threshold - _PRICE_EPS:
            result.update(interval_status="always_true", interval_reason="daily_low_ge_threshold")
        elif high < threshold - _PRICE_EPS:
            result.update(interval_status="always_false", interval_reason="daily_high_lt_threshold")
        else:
            result.update(interval_status="ambiguous", interval_reason="daily_interval_straddles_threshold")

    if minute_frame is None or minute_frame.empty:
        return result
    result["minute_frame_available"] = True
    # Validate timestamps here, and numeric prices only where consumed. A bad
    # future open must not invalidate an already observed 14:50 quote.
    try:
        index = minute_frame.index
        if not isinstance(index, pd.DatetimeIndex) or index.hasnans:
            raise ValueError("minute_index_must_be_datetime")
        if index.tz is not None:
            index = index.tz_convert("Asia/Shanghai").tz_localize(None)
        if not index.is_unique or not index.is_monotonic_increasing:
            raise ValueError("minute_index_must_be_unique_and_sorted")
        if any(t.date().isoformat() != signal_date or t.second or t.microsecond or t.nanosecond for t in index):
            raise ValueError("minute_index_must_match_session")
        frame = minute_frame.loc[:, [*_OHLC, "volume"]].set_axis(index)
        clock = index.strftime("%H:%M")
        frame = frame.loc[
            ((clock >= "09:30") & (clock <= "11:30"))
            | ((clock >= "13:00") & (clock <= "15:00"))
        ]
    except (KeyError, TypeError, ValueError) as exc:
        result.update(minute_status="unverifiable", minute_reason=f"invalid_minute_data: {exc}")
        return result

    interval_valid = low is not None and high is not None and 0 < low <= high
    decision = pd.Timestamp(f"{signal_date} 14:50")
    available = frame.loc[:decision]
    if not available.empty:
        timestamp, snapshot = available.index[-1], available.iloc[-1]
        price = _number(snapshot["close"])
        lag = (decision - timestamp).total_seconds()
        result.update(
            minute_1450_time=timestamp.isoformat(), minute_1450_price=price,
            minute_1450_volume=_number(snapshot["volume"]), minute_1450_lag_seconds=lag,
        )
        if lag > 60:
            result.update(minute_status="stale", minute_reason="minute_1450_older_than_one_minute")
        elif price is None or price <= 0:
            result.update(minute_status="unverifiable", minute_reason="invalid_minute_1450_price")
        else:
            result.update(minute_status="observed", minute_reason="observed_quote_not_a_fill")
            threshold = result["threshold_raw"]
            if threshold is not None:
                condition = "true" if price >= threshold - _PRICE_EPS else "false"
                result.update(minute_condition_raw=condition, minute_condition=condition)
                proof = result["interval_status"]
                if proof in {"always_true", "always_false"}:
                    expected = "true" if proof == "always_true" else "false"
                    result["interval_minute_comparison"] = "consistent" if condition == expected else "contradiction"
            if interval_valid and not low - _PRICE_EPS <= price <= high + _PRICE_EPS:
                result.update(
                    minute_status="data_inconsistent", minute_reason="minute_1450_outside_daily_interval",
                    minute_condition="unknown",
                )

    # First observed open at or after 14:51; gaps stay visible in its timestamp.
    # This is separate retrospective evidence, irrespective of the condition.
    subsequent = frame.loc[decision + pd.Timedelta(minutes=1):]
    if not subsequent.empty:
        timestamp, candle = subsequent.index[0], subsequent.iloc[0]
        opening = _number(candle["open"])
        result.update(
            next_observed_open_time=timestamp.isoformat(), next_observed_open=opening,
            next_observed_open_volume=_number(candle["volume"]),
            next_open_status="observed" if opening is not None and opening > 0 else "unverifiable",
        )
        if opening is not None and interval_valid and not low - _PRICE_EPS <= opening <= high + _PRICE_EPS:
            result["next_open_status"] = "data_inconsistent"

    if interval_valid and not frame.empty:
        prices = frame[_OHLC].apply(pd.to_numeric, errors="coerce")
        finite = prices.abs().lt(float("inf"))
        outside = ((prices.lt(low - _PRICE_EPS) | prices.gt(high + _PRICE_EPS)) & finite).any(axis=1)
        result["minute_range_inconsistent_times"] = [t.isoformat() for t in prices.index[outside]]
        result["data_inconsistent"] = bool(outside.any())
    return result


def _counts(rows: list[dict]) -> dict:
    def categories(field: str, values: tuple[str, ...]) -> dict[str, int]:
        counts = Counter(row[field] for row in rows)
        return {value: counts[value] for value in values}

    return {
        "opportunities": len(rows),
        "interval_status_counts": categories("interval_status", _INTERVAL_STATUSES),
        "minute_status_counts": categories("minute_status", _MINUTE_STATUSES),
        "minute_condition_counts": categories("minute_condition", ("true", "false", "unknown")),
        "interval_minute_comparison_counts": categories("interval_minute_comparison", _COMPARISONS),
        "data_inconsistent": sum(row["data_inconsistent"] for row in rows),
        "minute_coverage": {
            "frames_available": sum(row["minute_frame_available"] for row in rows),
            "fresh_1450_quotes": sum(row["minute_status"] in {"observed", "data_inconsistent"} for row in rows),
            "conditions_verified": sum(row["minute_condition"] != "unknown" for row in rows),
            "zero_volume_1450_quotes": sum(
                row["minute_status"] in {"observed", "data_inconsistent"} and row["minute_1450_volume"] == 0
                for row in rows
            ),
            "next_observed_opens": sum(row["next_open_status"] == "observed" for row in rows),
        },
        "mainline_proxy_labels": dict(Counter(row.get("mainline_proxy_passed", "") for row in rows)),
        "theme_status_labels": dict(Counter(row.get("theme_status", "") for row in rows)),
    }


def run(db: Path, directory: Path, minute_overlay: Path | None = None, quote_cache: Path | None = None) -> dict:
    """Audit every ready CSV row with a D2; use the shared, read-only loaders.

    No setup detection, Top-N, proxy/theme gate, or execution simulation runs.
    Missing panel evidence remains an unverifiable opportunity in the ledger.
    """
    ledger = (directory / "all-wave-setups.csv").read_bytes()
    try:
        setups = pd.read_csv(BytesIO(ledger), dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        setups = pd.DataFrame(columns=["status", "code", "d2_date"])
    required = {"status", "code", "d2_date"}
    if not required.issubset(setups.columns):
        raise ValueError(f"setup CSV missing columns: {sorted(required - set(setups.columns))}")
    ready = setups.loc[setups["status"].eq("setup_ready")]
    eligible = ready.loc[ready["d2_date"].ne("")]
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        dates, codes, panels, quality = load_panels(con)
        minutes, minute_quality = load_minutes(con, minute_overlay)
    positions = {code: position for position, code in enumerate(codes)}
    rows = []
    quote_hashes = {}
    for code, group in eligible.groupby("code", sort=False):
        if code in positions:
            position = positions[code]
            bars = pd.DataFrame({field: values[:, position] for field, values in panels.items()}, index=dates, copy=False)
        else:
            bars = pd.DataFrame(columns=[*_OHLC, "volume", "factor"])
        for row_number, setup in group.iterrows():
            signal_date = setup["d2_date"]
            minute_frame = minutes.get(code, {}).get(signal_date)
            source_kind = "observed_minute_ohlc" if minute_frame is not None else "missing"
            if minute_frame is None and quote_cache is not None:
                cached = quote_cache / code / f"{signal_date}.json.gz"
                if cached.exists():
                    with gzip.open(cached, "rt", encoding="utf-8") as source:
                        receipt = json.load(source)
                    if receipt["status"] == "verified":
                        frame = pd.DataFrame(receipt["records"])
                        frame.index = pd.to_datetime(frame.pop("datetime"))
                        # Absent OHLC remain NaN. Only observed last prices can
                        # prove the condition; no minute opening fill is invented.
                        minute_frame = frame.reindex(columns=[*_OHLC, "volume"])
                        source_kind = "verified_last_price_samples_without_minute_ohlc"
                        quote_hashes[f"{code}/{cached.name}"] = hashlib.sha256(cached.read_bytes()).hexdigest()
            audit = audit_buy_condition(bars, signal_date, code=code, minute_frame=minute_frame)
            audit["minute_source_kind"] = source_kind
            if code not in positions:
                audit["interval_reason"] = "code_missing_from_panels"
            audit.update(setup_csv_row=int(row_number) + 2, setup_status=setup["status"])
            audit.update({field: setup.get(field, "") for field in _SETUP_FIELDS})
            rows.append(audit)
    rows.sort(key=lambda row: row["setup_csv_row"])
    summary = {
        **_counts(rows),
        "database": str(db.resolve()),
        "setup_ledger_sha256": hashlib.sha256(ledger).hexdigest(),
        "source_setup_rows": len(setups),
        "setup_ready_rows": len(ready),
        "setup_ready_without_d2": len(ready) - len(eligible),
        "eligible_opportunities": len(eligible),
        "by_year": {str(year): _counts([row for row in rows if row["signal_date"][:4] == str(year)]) for year in range(1990, 2027)},
        "daily_quality": quality,
        "minute_source_coverage": minute_quality,
        "supplemental_quote_files": len(quote_hashes),
        "supplemental_quote_sha256": quote_hashes,
        "assumptions": [
            "All setup_ready rows with a D2 are audited independently, without Top-N or proxy/theme filtering.",
            "K = sum(previous four observed raw closes * their factors) / (4 * D2 factor); bad reference factors cannot be skipped.",
            "Daily L >= K and H < K are retrospective interval proofs, never 14:50 signals or actual buy prices.",
            "14:50 uses only the latest quote at or before 14:50, at most one minute old; zero volume still supplies a quote.",
            "next_observed_open is the first observed open at or after 14:51, with its timestamp; it is not an assumed fill.",
            "Condition true does not establish a known buy price, executable capacity, actual fill, or strategy profitability.",
            "Price-resonance and theme labels are retained verbatim; the original real mainline condition remains unknown.",
            "Minute records reconstruct observed historical prices; they do not prove the application received them at that time.",
            "Inconsistent minute prices are flagged; raw quote arithmetic is retained only for interval/minute contradiction checks.",
        ],
    }
    flat = [{key: json.dumps(value, ensure_ascii=False, allow_nan=False) if isinstance(value, (list, dict)) else value
             for key, value in row.items()} for row in rows]
    columns = [*_empty_audit("", ""), "minute_source_kind", "setup_csv_row", "setup_status", *_SETUP_FIELDS]
    pd.DataFrame(flat, columns=columns).to_csv(directory / "original-buy-audit.csv", index=False, encoding="utf-8-sig")
    (directory / "original-buy-audit.json").write_text(
        json.dumps({"summary": summary, "audits": rows}, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("--directory", "--output", dest="directory", type=Path, required=True)
    parser.add_argument("--minute-overlay", type=Path)
    parser.add_argument("--quote-cache", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.directory, args.minute_overlay, args.quote_cache), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
