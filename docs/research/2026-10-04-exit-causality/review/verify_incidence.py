"""Independent incidence verification: CSV identities + direct read-only SQL.

No experiment/classifier imports, network access, alternative exits or returns.
Replay without --output prints fresh evidence; --output writes a new JSON here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
REVIEW = Path(__file__).resolve().parent
INCIDENCE = REVIEW.parent / "incidence"
PLAN_SHA = "6474a050923021626789047cef7a67a058a3fe2adf013bac5a509740f6a5c1b6"
DATABASES = {
    "chinext": ROOT / ".local/chinext-payoff-20261004/market.db",
    "main": ROOT / ".local/multi-strategy-scoring-20261004/market.db",
}
# Select only original identity/status/entry fields. Do not load return or exit-price columns.
SOURCE_FIELDS = {
    "decision_date", "signal_date", "code", "label_status", "label_reason",
    "execution_reason", "status", "entry_date", "entry_price", "entry_factor",
    "exit_date", "exit_reason",
}
HALTS = {
    "chinext": {("300506", "2025-05-19"), ("300959", "2025-06-20")},
    "main": {
        *(('605389', day) for day in ("2025-07-04", "2025-07-07", "2025-07-08", "2025-07-09", "2025-07-10")),
        *(('002036', day) for day in ("2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29")),
    },
}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(2**20), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def csv_rows(path: Path, source: bool = False) -> list[dict]:
    options = {"usecols": lambda name: name in SOURCE_FIELDS} if source else {}
    return pd.read_csv(path, dtype=str, keep_default_na=False, **options).to_dict("records")


def number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def positive(value) -> bool:
    value = number(value)
    return value is not None and value > 0


def equal_number(actual, expected):
    actual, expected = number(actual), number(expected)
    if expected is None:
        assert actual is None, (actual, expected)
    else:
        assert actual is not None and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8), (actual, expected)


def boolean(value) -> bool:
    assert value in ("True", "False", True, False), value
    return value in ("True", True)


def event_key(row: dict) -> tuple:
    return row["group_id"], row["signal_date"], row["code"]


def local_path(name: str) -> Path:
    return ROOT / name.replace("\\", "/")


def source_orders(plan: dict) -> dict:
    result = {}
    for spec in plan["specs"]:
        group = "/".join(spec[key] for key in ("family", "segment", "policy"))
        path = local_path(spec["path"])
        source = csv_rows(path, source=True)
        events, trades = {}, {}
        if spec["kind"] == "labels":
            events = {(r["signal_date"], r["code"]): r for r in csv_rows(Path(str(path).replace("-labels.csv", "-events.csv")), source=True)}
            trades = {(r["signal_date"], r["code"]): r for r in csv_rows(Path(str(path).replace("-labels.csv", "-trades.csv")), source=True)}
        for row in source:
            day = row.get("signal_date") or row["decision_date"]
            code, status = row["code"], row["label_status"]
            extra = events.get((day, code), row)
            normalized = dict(group_id=group, family=spec["family"], segment=spec["segment"],
                policy=spec["policy"], db=spec["db"], signal_date=day, code=code,
                source_label_status=status, source_reason=row.get("label_reason") or row.get("execution_reason") or "",
                entry_date=row.get("entry_date") or extra.get("entry_date") or "",
                entry_price=extra.get("entry_price", ""), entry_factor=extra.get("entry_factor", ""),
                source_exit_date=row.get("exit_date") or extra.get("exit_date") or "",
                source_exit_reason=extra.get("exit_reason") or "")
            if spec["kind"] == "labels" and status == "closed":
                trade = trades[(day, code)]
                for name in ("entry_price", "entry_factor"):
                    equal_number(normalized[name], trade[name])
                assert normalized["entry_date"] == trade["entry_date"]
                assert normalized["source_exit_date"] == trade["exit_date"]
                assert normalized["source_exit_reason"] == trade["exit_reason"]
            key = event_key(normalized)
            assert key not in result, key
            result[key] = normalized
    return result


class SqlEvidence:
    def __init__(self, path: Path, label: str):
        self.label = label
        self.connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("BEGIN")
        self.days = [r[0] for r in self.connection.execute("SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date")]
        self.day_index = {day: index for index, day in enumerate(self.days)}
        self.factor_cache, self.quote_cache, self.previous_cache = {}, {}, {}

    def close(self):
        self.connection.close()

    def factor(self, code: str, day: str):
        key = code, day
        if key not in self.factor_cache:
            row = self.connection.execute("SELECT trade_date,hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1", key).fetchone()
            self.factor_cache[key] = (row[0], number(row[1])) if row else (None, None)
        return self.factor_cache[key]

    def quote(self, code: str, day: str):
        key = code, day
        if key not in self.quote_cache:
            row = self.connection.execute("SELECT open,high,low,close,volume,source FROM quotes_daily WHERE code=? AND trade_date=?", key).fetchone()
            self.quote_cache[key] = dict(row) if row else {}
        return self.quote_cache[key]

    def previous(self, code: str, day: str):
        key = code, day
        if key not in self.previous_cache:
            row = self.connection.execute("SELECT trade_date,close,volume FROM quotes_daily WHERE code=? AND trade_date<? AND close>0 AND volume>0 ORDER BY trade_date DESC LIMIT 1", key).fetchone()
            self.previous_cache[key] = (row[0], number(row[1])) if row else (None, None)
        return self.previous_cache[key]

    def facts(self, code: str, day: str, stop: float, offset: int) -> dict:
        quote = self.quote(code, day)
        date_factor, factor = self.factor(code, day)
        prior_date, prior_close = self.previous(code, day)
        prior_factor = self.factor(code, prior_date)[1] if prior_date else None
        raw_volume = number(quote.get("volume"))
        official = (code, day) in HALTS[self.label]
        if official:
            assert raw_volume is None or raw_volume == 0, (code, day, raw_volume)
        volume = 0. if official else raw_volume
        o, h, low, c = [number(quote.get(name)) for name in ("open", "high", "low", "close")]
        reference = prior_close * prior_factor / factor if all(positive(x) for x in (prior_close, prior_factor, factor)) else None
        ratio = .20 if code.startswith(("300", "301")) else .10
        floor = math.floor(reference * (1-ratio) * 100 + .5 + 1e-9) / 100 if positive(reference) else None
        if volume == 0:
            touched, touch_evidence = False, "known_no_trade"
        elif volume is not None and volume > 0 and positive(low) and positive(factor):
            touched, touch_evidence = low*factor <= stop, "known_positive_volume_low"
        else:
            touched, touch_evidence = None, "unknown_possible_trade_path"
        complete = all(positive(x) for x in (o, h, low, c)) and h >= max(o, c) and low <= min(o, c)
        close_masked = floor is not None and c is not None and c <= floor+.005
        nonflat = h is not None and low is not None and h > low
        opening_stop = positive(o) and positive(factor) and o*factor <= stop
        above_floor = floor is not None and positive(o) and o > floor+.005
        return dict(trade_date=day, offset_after_entry=offset, open=o, high=h, low=low, close=c,
            volume=volume, raw_volume_before_overlay=raw_volume, factor=factor,
            factor_observation_date=date_factor, previous_valid_date=prior_date,
            previous_valid_close=prior_close, previous_valid_factor=prior_factor,
            reference_raw=reference, lower_limit_raw=floor, reference_known=floor is not None,
            model_strict_down=bool(close_masked or floor is None), official_halt=official,
            source=quote.get("source"), quote_row_present=bool(quote), stop_economic=stop,
            stop_raw_on_day=stop/factor if positive(factor) else None,
            stop_touched=touched, touch_evidence=touch_evidence, ohlc_complete=complete,
            close_masked=bool(close_masked), nonflat=bool(nonflat), opening_stop=bool(opening_stop),
            open_above_floor=bool(above_floor))


def basis_key(row: dict) -> tuple:
    return row["db"], row["code"], row["entry_date"], number(row["entry_price"]), number(row["entry_factor"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="New JSON filename within this review directory")
    args = parser.parse_args()
    plan_path = INCIDENCE / "PLAN.json"
    assert digest(plan_path) == PLAN_SHA
    plan = read_json(plan_path)
    assert len(plan["specs"]) == 11
    complete = read_json(INCIDENCE / "completion-receipt.json")
    assert complete["plan_sha256"] == PLAN_SHA
    for name, expected in complete["artifacts_sha256"].items():
        assert digest(INCIDENCE / name) == expected
    for name, expected in plan["files_sha256"].items():
        assert digest(local_path(name)) == expected
    database_hashes = {key: digest(path) for key, path in DATABASES.items()}
    assert database_hashes == plan["databases_sha256"]
    original = source_orders(plan)
    reported_rows = csv_rows(INCIDENCE / "all-orders-incidence.csv")
    reported = {event_key(row): row for row in reported_rows}
    assert len(reported) == len(reported_rows) == len(original) and reported.keys() == original.keys()
    window = {(event_key(r), r["trade_date"]): r for r in csv_rows(INCIDENCE / "stop-window-ledger.csv")}
    reported_cases = {event_key(r) for r in csv_rows(INCIDENCE / "close-masked-nonflat-cases.csv")}
    reported_triggers = {event_key(r) for r in csv_rows(INCIDENCE / "all-first-stop-triggers.csv")}
    reported_unknown = {event_key(r) for r in csv_rows(INCIDENCE / "unknown-orders-preserved.csv")}
    stores = {key: SqlEvidence(path, key) for key, path in DATABASES.items()}
    statuses, groups, first_keys, cases, narrow = Counter(), {}, set(), [], []
    path_rows, unresolved_rows, filled_basis, no_trade_days = 0, [], set(), 0
    try:
        for key, order in sorted(original.items()):
            row = reported[key]
            group = groups.setdefault(order["group_id"], {"orders": 0, "source_statuses": Counter(), "incidence_statuses": Counter(), "close_masked_nonflat": 0, "narrow_opening_gap": 0})
            group["orders"] += 1
            group["source_statuses"][order["source_label_status"]] += 1
            for name in ("db", "source_label_status", "source_reason", "entry_date", "source_exit_date", "source_exit_reason"):
                assert row[name] == order[name], (key, name, row[name], order[name])
            for name in ("entry_price", "entry_factor"):
                equal_number(row[name], order[name])
            assert boolean(row["source_unknown_preserved"]) == (order["source_label_status"] == "unresolved")
            if order["source_label_status"] == "cancelled":
                assert not positive(order["entry_price"])
                state, facts, first = "known_cancelled_no_entry", [], None
            else:
                store = stores[order["db"]]
                assert positive(order["entry_price"]) and order["entry_date"] in store.day_index
                _, entry_factor = store.factor(order["code"], order["entry_date"])
                equal_number(order["entry_factor"], entry_factor)
                basis = float(order["entry_price"])*entry_factor
                stop = basis*.94
                equal_number(row["entry_factor_direct"], entry_factor)
                equal_number(row["entry_basis_economic"], basis)
                equal_number(row["stop_economic"], stop)
                index = store.day_index[order["entry_date"]]
                assert row["planned_expiry_date"] == store.days[index+3]
                facts = [store.facts(order["code"], store.days[index+offset], stop, offset) for offset in (1, 2, 3)]
                filled_basis.add(basis_key(order))
                first, preceding_unknown = None, False
                for fact in facts:
                    if fact["stop_touched"] is None:
                        preceding_unknown = True
                    elif fact["stop_touched"] and not preceding_unknown:
                        first = fact
                        break
                state = "first_stop_trigger_known" if first else "trigger_unknown_incomplete_path" if any(f["stop_touched"] is None for f in facts) else "no_stop_trigger_in_planned_window"
                for fact in facts:
                    observed = window[(key, fact["trade_date"])]
                    path_rows += 1
                    for name in ("open", "high", "low", "close", "volume", "raw_volume_before_overlay", "factor", "previous_valid_close", "previous_valid_factor", "reference_raw", "lower_limit_raw", "stop_economic", "stop_raw_on_day"):
                        equal_number(observed[name], fact[name])
                    for name in ("factor_observation_date", "previous_valid_date"):
                        assert observed[name] == (fact[name] or "")
                    for name in ("reference_known", "model_strict_down", "official_halt", "quote_row_present"):
                        assert boolean(observed[name]) == fact[name], (key, fact["trade_date"], name)
                    assert observed["stop_touched"] == ("" if fact["stop_touched"] is None else str(fact["stop_touched"]))
                    no_trade_days += fact["volume"] == 0
            assert row["incidence_status"] == state, (key, row["incidence_status"], state)
            statuses[state] += 1
            group["incidence_statuses"][state] += 1
            if order["source_label_status"] == "unresolved":
                unresolved_rows.append({**order, "verified_incidence_status": state, "window": facts})
            if first is None:
                assert row["trigger_trade_date"] == ""
                continue
            first_keys.add(key)
            assert row["trigger_trade_date"] == first["trade_date"]
            for name in ("open", "high", "low", "close", "volume", "factor", "previous_valid_close", "previous_valid_factor", "reference_raw", "lower_limit_raw", "stop_economic", "stop_raw_on_day"):
                equal_number(row[f"trigger_{name}"], first[name])
            for name in ("factor_observation_date", "previous_valid_date"):
                assert row[f"trigger_{name}"] == first[name]
            assert boolean(row["trigger_nonflat_high_above_low"]) == first["nonflat"]
            assert boolean(row["trigger_open_at_or_below_stop"]) == first["opening_stop"]
            assert boolean(row["trigger_model_strict_down"]) == first["model_strict_down"]
            if first["close_masked"] and first["nonflat"]:
                assert first["ohlc_complete"], (key, "flagged event has invalid OHLC")
                is_narrow = first["opening_stop"] and first["open_above_floor"]
                item = {**order, "first_stop_date": first["trade_date"], "narrow_opening_gap": is_narrow,
                    "original_exit_later": order["source_exit_date"] > first["trade_date"], "first_stop_facts": first,
                    "preceding_stop_window_facts": [f for f in facts if f["trade_date"] < first["trade_date"]]}
                assert item["original_exit_later"]
                cases.append(item)
                group["close_masked_nonflat"] += 1
                if is_narrow:
                    assert row["trigger_open_relative_lower"] == "above_lower"
                    assert row["trigger_stop_trigger_price_path"] == "open_at_or_below_stop_above_lower"
                    narrow.append(item)
                    group["narrow_opening_gap"] += 1
    finally:
        for store in stores.values():
            store.close()
    assert path_rows == len(window)
    assert first_keys == reported_triggers
    assert {event_key(r) for r in cases} == reported_cases
    assert {event_key(r) for r in unresolved_rows} == reported_unknown
    summary = read_json(INCIDENCE / "summary.json")
    for group, value in groups.items():
        expected = summary["groups"][group]
        assert value["orders"] == expected["orders"]
        assert dict(value["source_statuses"]) == expected["source_statuses"]
        assert dict(value["incidence_statuses"]) == expected["incidence_statuses"]
        assert value["close_masked_nonflat"] == expected["close_masked_nonflat"]
        assert value["narrow_opening_gap"] == expected["nonflat_masked_open_at_or_below_stop_above_lower"]
    assert len(filled_basis) == summary["unique_filled_basis_rows"]
    assert len({basis_key(r) for r in cases}) == summary["unique_nonflat_masked_basis_rows"]
    result = dict(completed_at=datetime.now(timezone.utc).isoformat(), passed=True,
        plan_sha256=PLAN_SHA, verifier_sha256=digest(Path(__file__)), database_sha256=database_hashes,
        no_experiment_imports=True, no_network=True, no_return_or_exit_price_columns_loaded=True,
        no_counterfactual_exits_or_returns_computed=True, source_groups=len(groups), source_orders=len(original),
        original_source_statuses=dict(Counter(r["source_label_status"] for r in original.values())),
        incidence_statuses=dict(statuses), direct_sql_stop_window_rows=path_rows, known_no_trade_window_rows=no_trade_days,
        unique_filled_basis_rows=len(filled_basis), close_masked_nonflat_policy_orders=len(cases),
        close_masked_nonflat_unique_basis_rows=len({basis_key(r) for r in cases}),
        narrow_opening_gap_policy_orders=len(narrow), narrow_opening_gap_unique_basis_rows=len({basis_key(r) for r in narrow}),
        narrow_opening_gap_unique_code_dates=len({(r["db"], r["code"], r["first_stop_date"]) for r in narrow}),
        groups=groups, all_close_masked_nonflat_cases=cases, narrow_opening_gap_cases=narrow,
        original_unknown_orders_preserved=unresolved_rows,
        interpretation="Incidence and source identities only. Positive-volume price prints are not proof of own-order execution; no sensitivity outcome is read or computed.")
    if args.output:
        output = (REVIEW / args.output).resolve()
        assert output.parent == REVIEW, "Output must be a new file directly in the review directory"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    compact = {key: value for key, value in result.items() if key not in ("groups", "all_close_masked_nonflat_cases", "narrow_opening_gap_cases", "original_unknown_orders_preserved")}
    compact["narrow_opening_groups"] = {key: value["narrow_opening_gap"] for key, value in groups.items() if value["narrow_opening_gap"]}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
