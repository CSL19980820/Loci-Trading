"""Independently audit the frozen quote ledger, without strategy replay or network.

Only the verification JSON is written. No execution/research module is imported,
no source is fetched, and SQLite is opened read-only and immutable. An exit code
of 1 means an accounting/evidence failure; 2 means an original-rule divergence.
Missing evidence remains unknown and never becomes a closed return.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import json
from math import fsum, isclose, isfinite
from pathlib import Path
import sqlite3
from statistics import fmean, median

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".local/research/2026-10-26-first-wave"
REPORT = ROOT / "docs/research/2026-10-27-first-wave"
GATES = ("no_mainline", "observed_theme", "price_resonance_proxy")
SUFFIX = "__sampled_quotes_1450__h10__staged__ma5_or_horizon"
SOURCES = (
    "scripts/first_wave_quote_research.py",
    "scripts/first_wave_quote_execution.py",
    "scripts/first_wave_execution.py",
)
# Independent transcription of the frozen research parameters, not broker fees.
STAMP = (
    ("1992-06-12", 0.003, 0.003),
    ("1997-05-12", 0.005, 0.005),
    ("1998-06-12", 0.004, 0.004),
    ("2001-11-16", 0.002, 0.002),
    ("2005-01-24", 0.001, 0.001),
    ("2007-05-30", 0.003, 0.003),
    ("2008-04-24", 0.001, 0.001),
    ("2008-09-19", 0.0, 0.001),
    ("2023-08-28", 0.0, 0.0005),
)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def positive(value: object) -> bool:
    return isinstance(value, (float, int)) and isfinite(value) and value > 0


def equal(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(equal(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, (list, tuple)):
        return (
            isinstance(actual, (list, tuple))
            and len(actual) == len(expected)
            and all(equal(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        return (
            isinstance(actual, (float, int))
            and not isinstance(actual, bool)
            and isfinite(actual)
            and isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7)
        )
    return actual == expected


class Audit:
    def __init__(self) -> None:
        self.checks: Counter = Counter()
        self.failures: list[dict] = []
        self.rule_violations: list[dict] = []
        self.counts: Counter = Counter()
        self.cache_hashes: dict[str, str] = {}
        self.cache_statuses: Counter = Counter()
        self.cache_kinds: Counter = Counter()
        self.negative_date_anomalies: list[dict] = []
        self.rows: list[dict] = []
        self.first_entries: list[dict] = []

    def check(self, name: str, condition: bool, context: object = None) -> None:
        self.checks[name] += 1
        if not condition:
            issue = {"check": name, "context": context}
            self.failures.append(issue)
            if len(self.failures) <= 8:
                print("FAIL", json.dumps(issue, ensure_ascii=False), flush=True)

    def same(self, name: str, actual: object, expected: object, context: object) -> None:
        self.check(name, equal(actual, expected), {
            "at": context, "actual": actual, "expected": expected,
        })


def costs(day: str, amount: float, side: str) -> dict:
    schedules = [s for s in STAMP if s[0] <= day]
    rate = schedules[-1][1 if side == "entry" else 2] if schedules else 0.0
    turnover = amount * (1.0005 if side == "entry" else 0.9995)
    parts = {"commission": max(5.0, turnover * 0.0003),
             "stamp_tax": turnover * rate, "stamp_rate": rate,
             "slippage": amount * 0.0005}
    parts["total"] = parts["commission"] + parts["stamp_tax"] + parts["slippage"]
    return parts


def in_session(timestamp: str) -> bool:
    clock = timestamp[11:16]
    return "09:30" <= clock <= "11:30" or "13:01" <= clock <= "15:00"


def minute_grid(day: str) -> list[str]:
    values = []
    for begin, end in (("09:30", "11:30"), ("13:01", "15:00")):
        current = datetime.fromisoformat(day + "T" + begin)
        stop = datetime.fromisoformat(day + "T" + end)
        while current <= stop:
            values.append(current.isoformat())
            current += timedelta(minutes=1)
    return values


class StockEvidence:
    """One code at a time: direct dictionary/SQLite/raw-cache lookups."""

    def __init__(self, con: sqlite3.Connection, audit: Audit, code: str,
                 cache: Path, calendar: list[str], max_day: str) -> None:
        self.audit, self.code, self.cache, self.calendar = audit, code, cache, calendar
        self.sessions: dict[str, tuple[dict, dict[str, dict]]] = {}
        self.daily = {
            r[0]: dict(zip(("open", "high", "low", "close", "volume"), r[1:], strict=True))
            for r in con.execute(
                "SELECT trade_date,open,high,low,close,volume FROM quotes_daily "
                "WHERE code=? AND trade_date<=? ORDER BY trade_date", (code, max_day)
            )
        }
        instrument = con.execute(
            "SELECT list_date,instrument_type FROM instruments WHERE code=?", (code,)
        ).fetchone()
        listing = (instrument[0] or "") if instrument else ""
        audit.check("non_index_opportunity", not instrument or instrument[1] != "INDEX", code)
        self.valid_days = []
        for day, bar in self.daily.items():
            values = tuple(bar.values())
            valid = all(isinstance(x, (float, int)) and isfinite(x) for x in values)
            if valid:
                op, hi, lo, cl, volume = values
                valid = (lo > 0 and volume > 0 and hi >= lo
                         and hi + 0.005 >= max(op, cl) and lo - 0.005 <= min(op, cl)
                         and day >= listing)
            if valid:
                self.valid_days.append(day)
        self.factor_dates, self.factors = [], []
        for day, factor in con.execute(
            "SELECT trade_date,hfq_factor FROM adjust_factors "
            "WHERE code=? AND trade_date<=? ORDER BY trade_date", (code, max_day)
        ):
            if positive(factor):
                self.factor_dates.append(day)
                self.factors.append(factor)

    def factor(self, day: str) -> float:
        i = bisect_right(self.factor_dates, day) - 1
        self.audit.check("effective_factor_available", i >= 0, (self.code, day))
        return self.factors[i] if i >= 0 else float("nan")

    def prior_days(self, day: str) -> list[str]:
        observed = set(self.valid_days[:bisect_left(self.valid_days, day)])
        for date, (receipt, points) in self.sessions.items():
            if date >= day:
                continue
            if receipt["status"] == "verified" and points:
                observed.add(date)
            elif receipt["status"] == "confirmed_no_trades":
                observed.discard(date)
        return sorted(observed)

    def ma5(self, day: str, price: float) -> float:
        previous = self.prior_days(day)[-4:]
        self.audit.check("ma5_four_prior_observations", len(previous) == 4, (self.code, day))
        valid = len(previous) == 4 and all(d in self.valid_days for d in previous)
        self.audit.check("ma5_history_not_silently_substituted", valid, (self.code, day, previous))
        if not valid:
            return float("nan")
        adjusted = fsum(self.daily[d]["close"] * self.factor(d) for d in previous)
        return (adjusted / self.factor(day) + price) / 5

    def reference(self, day: str) -> float:
        previous = self.prior_days(day)
        self.audit.check("reference_prior_observation", bool(previous), (self.code, day))
        if not previous:
            return float("nan")
        last = previous[-1]
        return self.daily[last]["close"] * self.factor(last) / self.factor(day)

    def limit(self, day: str, side: str) -> float | None:
        if day < "1996-12-16":
            self.audit.counts["fills_before_verified_limit_regime"] += 1
            return None
        code = self.code
        rate = Decimal("0.1")
        if code.startswith(("4", "8", "92")) or code.upper().endswith(".BJ"):
            rate = Decimal("0.3")
        elif code.startswith(("688", "689")) or (
            code.startswith(("300", "301")) and day >= "2020-08-24"
        ):
            rate = Decimal("0.2")
        last = self.prior_days(day)[-1]
        ref = Decimal(str(self.daily[last]["close"])) * Decimal(str(self.factor(last)))
        ref /= Decimal(str(self.factor(day)))
        return float((ref * (1 + (rate if side == "entry" else -rate))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ))

    def session(self, day: str) -> tuple[dict, dict[str, dict]]:
        if day in self.sessions:
            return self.sessions[day]
        path = self.cache / self.code / (day + ".json.gz")
        self.audit.check("referenced_cache_exists", path.is_file(), (self.code, day))
        if not path.is_file():
            result = ({"status": "absent"}, {})
            self.sessions[day] = result
            return result
        compressed = path.read_bytes()
        self.audit.cache_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(compressed).hexdigest()
        receipt = json.loads(gzip.decompress(compressed))
        self.audit.cache_statuses[receipt["status"]] += 1
        self.audit.cache_kinds[receipt.get("source_kind", "unknown")] += 1
        verified = receipt["status"] == "verified"
        identity = receipt.get("code") == self.code and receipt.get("requested_date") == day
        if verified:
            self.audit.check("verified_cache_identity", identity, (str(path), receipt.get("code"), receipt.get("requested_date")))
        elif not identity:
            self.audit.negative_date_anomalies.append({"code": self.code, "date": day, "kind": "cache_identity", "status": receipt["status"]})
        points, times = {}, []
        for raw in receipt.get("records", []):
            t = datetime.fromisoformat(str(raw["datetime"]))
            normalized = t.replace(tzinfo=None).isoformat()
            valid_date = t.date().isoformat() == day and not (t.second or t.microsecond or t.tzinfo)
            if verified:
                self.audit.check("verified_raw_timestamp_date", valid_date, (self.code, day, str(raw["datetime"])))
                self.audit.check("verified_raw_price_volume", positive(raw.get("close")) and isinstance(raw.get("volume"), (int, float)) and isfinite(raw["volume"]) and raw["volume"] >= 0, (self.code, day, normalized))
            elif not valid_date:
                self.audit.negative_date_anomalies.append({"code": self.code, "date": day, "kind": "raw_date", "raw_time": str(raw["datetime"]), "status": receipt["status"]})
            times.append(normalized)
            if in_session(normalized):
                points[normalized] = raw
        if verified:
            self.audit.check("verified_raw_sorted_unique", times == sorted(set(times)), (self.code, day))
            self.audit.check("verified_session_nonempty", bool(points), (self.code, day))
            self.audit.same("cache_quote_count", receipt.get("quote_count"), len(times), (self.code, day))
            bar = self.daily.get(day, {})
            self.audit.check("cache_daily_reference_present", all(positive(bar.get(k)) for k in ("open", "high", "low", "close")), (self.code, day))
            if times and all(positive(bar.get(k)) for k in ("open", "high", "low", "close")):
                prices = [raw["close"] for raw in receipt["records"]]
                self.audit.same("cache_daily_reference", receipt.get("daily_reference"), {k: bar[k] for k in ("open", "high", "low", "close")}, (self.code, day))
                difference = prices[-1] - bar["close"]
                inside = min(prices) >= bar["low"] - 0.011 and max(prices) <= bar["high"] + 0.011
                self.audit.same("cache_closing_difference", receipt.get("closing_difference"), difference, (self.code, day))
                self.audit.check("cache_daily_close_and_range", abs(difference) <= 0.011 and inside, (self.code, day))
                self.audit.same("cache_daily_range_flag", receipt.get("all_prices_inside_daily_range"), inside, (self.code, day))
        if receipt["status"] == "confirmed_no_trades":
            self.audit.same("confirmed_no_trades_raw_volume", self.daily.get(day, {}).get("volume"), 0, (self.code, day))
        self.sessions[day] = receipt, points
        return receipt, points

    def quote(self, timestamp: str, expected_price: float, context: object, *, fill: bool = False) -> dict:
        receipt, points = self.session(timestamp[:10])
        self.audit.same("used_cache_verified", receipt["status"], "verified", context)
        point = points.get(timestamp)
        self.audit.check("raw_quote_present", point is not None, context)
        if point is not None:
            self.audit.same("raw_quote_price", expected_price, point["close"], context)
            if fill:
                self.audit.check("fill_positive_volume", positive(point["volume"]), context)
        return point or {}

    def first_fill(self, decision: str, fill: str, side: str, entry_day: str,
                   context: object) -> None:
        self.audit.check("fill_strictly_after_decision", fill > decision, context)
        start = bisect_left(self.calendar, decision[:10])
        stop = bisect_right(self.calendar, fill[:10])
        first = None
        for day in self.calendar[start:stop]:
            if side == "exit" and day <= entry_day:
                continue
            receipt, points = self.session(day)
            if receipt["status"] == "confirmed_no_trades":
                continue
            self.audit.same("execution_path_verified", receipt["status"], "verified", (context, day))
            limit = self.limit(day, side)
            for t in minute_grid(day):
                if t[11:16] == "09:30" and t not in points:
                    continue
                if t <= decision or t > fill:
                    continue
                point = points.get(t)
                self.audit.check("execution_path_no_missing_sample", point is not None, (context, t))
                if point is None or not positive(point.get("volume")):
                    continue
                blocked = limit is not None and (
                    point["close"] >= limit - 1e-10 if side == "entry"
                    else point["close"] <= limit + 1e-10
                )
                if blocked:
                    # A blocked buy is cancelled; a blocked sell stays queued.
                    if side == "entry":
                        first = "blocked_at:" + t
                        break
                    continue
                first = t
                break
            if first is not None:
                break
        self.audit.same("first_eligible_positive_volume_fill", fill, first, context)


def verify_evidence(row: dict, evidence: StockEvidence, audit: Audit) -> None:
    key = (row["code"], row["signal_date"], row["mainline_gate"])
    events = row.get("evidence", [])
    for event in events:
        day, action, t = event["date"], event["action"], event.get("time")
        if t is not None:
            audit.same("event_date", t[:10], day, (key, action, t))
        if "price" in event:
            if event.get("observation") == "daily_open":
                audit.same("surge_known_daily_open", event["price"], evidence.daily[day]["open"], (key, t))
            else:
                evidence.quote(t, event["price"], (key, action, t), fill=action in {"buy", "sell", "buy_blocked"})
        if "ma5" in event:
            audit.same("dynamic_ma5", event["ma5"], evidence.ma5(day, event["price"]), (key, action, t))
        if "reference" in event:
            audit.same("factor_adjusted_reference", event["reference"], evidence.reference(day), (key, action, t))
        if action == "snapshot_1450":
            decision = day + "T14:50:00"
            audit.same("snapshot_decision_clock", event.get("decision_time"), decision, (key, t))
            _, points = evidence.session(day)
            available = [q for q, point in points.items() if q <= decision and positive(point["close"])]
            latest = max(available) if available else None
            audit.same("snapshot_latest_known_price", t, latest, key)
            audit.check("snapshot_age_at_most_one_minute", t is not None and timedelta(0) <= datetime.fromisoformat(decision) - datetime.fromisoformat(t) <= timedelta(minutes=1), (key, t))
        elif action == "pullback_wait":
            audit.check("surge_observed_at_least_five_percent", event["price"] / evidence.reference(day) - 1 >= 0.05 - 1e-10, (key, t))
            audit.same("surge_on_d3", evidence.calendar.index(day), evidence.calendar.index(row["signal_date"]) + 1, (key, t))
        elif action == "pullback_window":
            ma = evidence.ma5(day, event["price"])
            in_band = ma - 1e-10 <= event["price"] <= ma * 1.01 + 1e-10
            audit.same("sampled_window_held_semantics", event["held"], in_band, (key, t))
            if event["held"] != in_band:
                audit.rule_violations.append({
                    "rule": "baseline_window_endpoint_must_be_inside_ma5_one_percent_band",
                    "code": row["code"], "signal_date": row["signal_date"],
                    "gate": row["mainline_gate"], "time": t,
                    "price": event["price"], "recomputed_ma5": ma,
                    "baseline_lower_bound": ma,
                    "baseline_upper_bound": ma * 1.01,
                    "reported_held": event["held"], "expected_held": in_band,
                    "expected_rule": "endpoint_inside_ma5_one_percent_band",
                })
        elif action in {"entry_queued", "exit_queued", "add_queued"}:
            reason = event["reason"]
            if reason == "horizon":
                expected = evidence.calendar.index(row["legs"][0]["entry_date"]) + 10
                audit.same("horizon_calendar_index", evidence.calendar.index(day), expected, key)
                audit.same("horizon_decision_clock", t, day + "T00:00:00", key)
            elif reason in {"d2_dynamic_ma5_confirmation", "ma5_break", "d3_small_k"}:
                audit.same("decision_1450_clock", t, day + "T14:50:00", (key, reason))
                snapshots = [e for e in events if e["action"] == "snapshot_1450" and e["date"] == day]
                audit.same("decision_has_snapshot", len(snapshots), 1, (key, t, reason))
                if snapshots:
                    snap = snapshots[0]
                    ma = evidence.ma5(day, snap["price"])
                    audit.check("decision_ma5_direction", snap["price"] < ma - 1e-10 if reason == "ma5_break" else snap["price"] >= ma - 1e-10, (key, reason, t))
                    if reason == "d3_small_k":
                        ref = evidence.reference(day)
                        opening = evidence.daily[day]["open"]
                        audit.same("small_k_is_d3", evidence.calendar.index(day), evidence.calendar.index(row["signal_date"]) + 1, key)
                        audit.check("small_k_body_and_reference", abs(snap["price"] / opening - 1) <= 0.02 + 1e-10 and abs(snap["price"] / ref - 1) <= 0.03 + 1e-10, key)
                        _, points = evidence.session(day)
                        seen = [p["close"] for q, p in points.items() if q <= t]
                        audit.check("small_k_no_observed_five_percent_surge", max([opening, *seen]) / ref - 1 < 0.05 - 1e-10, key)
            elif reason == "ma5_pullback_two_windows":
                end = datetime.fromisoformat(t)
                window = [(end - timedelta(minutes=offset)).isoformat() for offset in range(9, -1, -1)]
                _, points = evidence.session(day)
                audit.check("pullback_ten_samples_same_session", all(q in points and in_session(q) for q in window), (key, t))
                if all(q in points for q in window):
                    first_price = points[window[0]]["close"]
                    first_ma = evidence.ma5(day, first_price)
                    audit.check("pullback_started_in_band", first_ma - 1e-10 <= first_price <= first_ma * 1.01 + 1e-10, (key, t))
                    surge = [e for e in events if e["action"] == "pullback_wait" and e["time"] < window[0]]
                    audit.check("pullback_after_observed_surge", bool(surge), (key, t))
                    for endpoint in (window[4], window[9]):
                        price = points[endpoint]["close"]
                        ma = evidence.ma5(day, price)
                        audit.check("pullback_both_endpoints_inside_band", ma - 1e-10 <= price <= ma * 1.01 + 1e-10, (key, endpoint))
                        audit.check("pullback_window_evidence", any(e["action"] == "pullback_window" and e["time"] == endpoint and e["held"] for e in events), (key, endpoint))
        elif action == "buy_blocked":
            upper = evidence.limit(day, "entry")
            point = evidence.sessions[day][1].get(t, {})
            audit.check("buy_blocked_at_upper_limit", upper is not None and point.get("close", 0) >= upper - 1e-10 and event["reason"] == "upper_limit", (key, t))
    for action, side in (("buy", "entry"), ("sell", "exit")):
        recorded = Counter((e["time"], e["reason"]) for e in events if e["action"] == action)
        expected = Counter((leg[side + "_time"], leg[side + "_reason"]) for leg in row["legs"] if leg.get(side + "_date"))
        audit.same("trade_event_leg_bijection", sorted(recorded.items()), sorted(expected.items()), (key, action))


def verify_accounting(row: dict, evidence: StockEvidence, audit: Audit) -> dict:
    key = (row["code"], row["signal_date"], row["mainline_gate"])
    legs = row["legs"]
    audit.check("at_most_two_tranches", len(legs) <= 2, key)
    audit.same("research_notional", row["notional"], 100000.0, key)
    recomputed_closed = []
    for index, leg in enumerate(legs):
        at = (*key, index)
        audit.counts["entry_legs_checked"] += 1
        audit.same("tranche_notional", leg["notional"], 50000.0, at)
        audit.same("tranche_weight", leg["weight"], 0.5, at)
        price = leg["entry_price"]
        audit.check("entry_price_positive", positive(price), at)
        quantity = 50000.0 / price
        audit.same("entry_quantity", leg["quantity"], quantity, at)
        entry_factor = evidence.factor(leg["entry_date"])
        audit.same("entry_factor", leg["entry_factor"], entry_factor, at)
        audit.same("factor_alias", leg["factor"], entry_factor, at)
        entry_cost = costs(leg["entry_date"], 50000, "entry")
        audit.same("entry_cost_components", leg["entry_costs"], entry_cost, at)
        for side in ("entry", "exit"):
            day = leg.get(side + "_date")
            if day is None:
                continue
            t, decision = leg[side + "_time"], leg[side + "_decision_time"]
            audit.same("leg_date_clock", t[:10], day, (at, side))
            evidence.quote(t, leg[side + "_price"], (at, side), fill=True)
            queues = [e for e in row.get("evidence", []) if e["action"] in ({"entry_queued", "add_queued"} if side == "entry" else {"exit_queued"}) and e["time"] == decision and e["reason"] == leg[side + "_reason"]]
            audit.same("leg_has_causal_order", len(queues), 1, (at, side))
            evidence.first_fill(decision, t, side, leg["entry_date"], (at, side))
        if index == 0:
            audit.counts["first_entries_checked"] += 1
            audit.first_entries.append({"code": row["code"], "signal_date": row["signal_date"], "gate": row["mainline_gate"], "entry_time": leg["entry_time"]})
            audit.same("first_entry_decision_on_d2", leg["entry_decision_time"], row["signal_date"] + "T14:50:00", at)
            audit.same("first_entry_reason", leg["entry_reason"], "d2_dynamic_ma5_confirmation", at)
            if leg["entry_date"] != row["signal_date"]:
                audit.rule_violations.append({"rule": "first_entry_must_execute_on_d2", "code": row["code"], "signal_date": row["signal_date"], "gate": row["mainline_gate"], "entry_time": leg["entry_time"], "calendar_session_offset": evidence.calendar.index(leg["entry_date"]) - evidence.calendar.index(row["signal_date"])})
        else:
            audit.check("second_entry_after_first", leg["entry_time"] > legs[0]["entry_time"], at)
        if leg.get("exit_date") is None:
            audit.counts["open_legs_checked"] += 1
            for field in ("exit_time", "exit_price", "exit_factor", "exit_reason", "exit_costs", "gross_pnl", "net_pnl"):
                audit.same("open_leg_has_no_realized_close", leg.get(field), None, (at, field))
            continue
        audit.counts["closed_legs_checked"] += 1
        audit.check("each_leg_t_plus_one", leg["exit_date"] > leg["entry_date"], at)
        exit_factor = evidence.factor(leg["exit_date"])
        audit.same("exit_factor", leg["exit_factor"], exit_factor, at)
        exit_quantity = quantity * (exit_factor / entry_factor)
        proceeds = exit_quantity * leg["exit_price"]
        exit_cost = costs(leg["exit_date"], proceeds, "exit")
        gross = proceeds - 50000
        net = gross - entry_cost["total"] - exit_cost["total"]
        audit.same("exit_quantity_factor_ratio", leg["exit_quantity"], exit_quantity, at)
        audit.same("exit_cost_components", leg["exit_costs"], exit_cost, at)
        audit.same("leg_gross_pnl", leg["gross_pnl"], gross, at)
        audit.same("leg_net_pnl", leg["net_pnl"], net, at)
        recomputed_closed.append((gross, net))
    invested = len(legs) * 50000
    gross = fsum(p[0] for p in recomputed_closed)
    net = fsum(p[1] for p in recomputed_closed)
    for field, value in (("invested_notional", invested), ("uninvested_cash", 100000 - invested), ("realized_gross_pnl", gross), ("realized_net_pnl", net)):
        audit.same("opportunity_cash_and_realized_pnl", row.get(field), value, (key, field))
    audit.same("opportunity_first_entry_date", row.get("entry_date"), legs[0]["entry_date"] if legs else None, key)
    status = row["status"]
    if status == "closed":
        audit.check("closed_means_every_leg_closed", bool(legs) and len(recomputed_closed) == len(legs), key)
        audit.same("closed_exit_date", row.get("exit_date"), max(leg["exit_date"] for leg in legs), key)
        expected = {"gross_pnl": gross, "net_pnl": net,
                    "gross_return_pct": gross / 1000, "net_return_pct": net / 1000,
                    "invested_gross_return_pct": gross / invested * 100,
                    "invested_net_return_pct": net / invested * 100}
    elif status == "skipped":
        audit.same("skipped_has_no_legs", legs, [], key)
        expected = {"gross_pnl": 0.0, "net_pnl": 0.0, "gross_return_pct": 0.0, "net_return_pct": 0.0, "invested_gross_return_pct": None, "invested_net_return_pct": None}
    else:
        audit.counts["unknown_rows_with_legs"] += bool(legs)
        expected = dict.fromkeys(("gross_pnl", "net_pnl", "gross_return_pct", "net_return_pct", "invested_gross_return_pct", "invested_net_return_pct"))
        audit.same("unknown_no_final_exit_date", row.get("exit_date"), None, key)
    for field, value in expected.items():
        audit.same("aggregate_returns_do_not_mix_unknown", row.get(field), value, (key, field))
    missing = row.get("missing_quote_date")
    if missing:
        receipt, _ = evidence.session(missing)
        audit.same("unknown_failure_receipt", row.get("quote_source_failure"), {k: v for k, v in receipt.items() if k != "records"}, key)
        audit.check("unknown_rejected_source_not_used_as_fill", receipt["status"] != "verified", key)
    result = {**row, **expected}
    result["invested_notional"] = invested
    return result


def aggregate(rows: list[dict]) -> dict:
    """Recompute every reported statistic from audited rows, never metrics()."""
    closed = [r for r in rows if r["status"] == "closed"]
    result = {"opportunities": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)), "realized_trades": len(closed)}
    if not closed:
        return result
    values = [r["net_return_pct"] for r in closed]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    result.update(mean_net_pct=fmean(values), median_net_pct=median(values),
                  win_rate_pct=len(wins) / len(values) * 100,
                  mean_win_pct=fmean(wins) if wins else None,
                  mean_loss_pct=fmean(losses) if losses else None,
                  profit_factor=fsum(wins) / -fsum(losses) if losses else None,
                  worst_trade_pct=min(values), best_trade_pct=max(values),
                  mean_invested_net_pct=fmean(r["invested_net_return_pct"] for r in closed),
                  mean_allocation_pct=fmean(r["invested_notional"] / 100000 for r in closed) * 100,
                  two_tranche_rate_pct=sum(len(r["legs"]) == 2 for r in closed) / len(closed) * 100)
    months: dict[str, list[float]] = {}
    for row in closed:
        months.setdefault(row["signal_date"][:7], []).append(row["net_return_pct"])
    if len(months) >= 5:
        # The documented seeded resampling algorithm requires the same RNG;
        # all inputs here are independently recomputed leg cash flows.
        sums = [fsum(v) for v in months.values()]
        sizes = [len(v) for v in months.values()]
        draws = np.random.default_rng(20261027).integers(0, len(months), size=(1000, len(months)))
        estimates = sorted(fsum(sums[i] for i in draw) / sum(sizes[i] for i in draw) for draw in draws)
        intervals = []
        for probability in (0.025, 0.975):
            position = (len(estimates) - 1) * probability
            lo = int(position)
            intervals.append(estimates[lo] + (estimates[lo + 1] - estimates[lo]) * (position - lo))
        result["mean_net_month_cluster_ci95"] = intervals
    return result


def verify_observed_sources(con: sqlite3.Connection, overlay: Path | None,
                            contexts: list[StockEvidence], summary: dict,
                            audit: Audit) -> None:
    expected_hashes = summary.get("coverage", {}).get("overlay_hashes", {})
    actual_hashes = {p.name: sha256(p) for p in sorted(overlay.glob("*.json"))} if overlay else {}
    audit.same("minute_overlay_hashes", actual_hashes, expected_hashes, str(overlay))
    snapshots = [(day, json.loads(payload), fetched) for day, payload, fetched in con.execute(
        "SELECT trade_date,payload_json,fetched_at FROM intel_snapshots WHERE tool=? ORDER BY fetched_at", ("minute_data",)
    )]
    if overlay:
        for name in actual_hashes:
            wrapper = json.loads((overlay / name).read_text(encoding="utf-8"))
            snapshots.append((wrapper["trade_date"], wrapper, wrapper["fetched_at"]))
    observed: dict[tuple[str, str], dict[str, tuple[float, float]]] = {}
    for day, wrapper, fetched in sorted(snapshots, key=lambda x: x[2]):
        body, metadata = wrapper.get("structured"), wrapper.get("metadata") or {}
        if wrapper.get("is_error") or wrapper.get("truncated") or not isinstance(body, dict):
            continue
        nodes = (wrapper, body, metadata)
        if any(n.get("dateStatus") == "mismatch" or any("date_mismatch" in str(w) for w in n.get("qualityWarnings", [])) for n in nodes):
            continue
        actual_day = body.get("actualTradeDate") or metadata.get("actualTradeDate") or body.get("tradeDate")
        if actual_day and str(actual_day)[:10].replace("-", "") != day.replace("-", ""):
            continue
        code = str((body.get("stock") or {}).get("code") or (wrapper.get("arguments") or {}).get("code") or "")
        points = body.get("points") or []
        if not code or not isinstance(points, list) or not points:
            continue
        bucket = {}
        for point in points:
            t = str(point.get("time", ""))
            if t[:10] != day or not all(k in point or "price" in point for k in ("open", "high", "low", "close")) or "volume" not in point:
                continue
            normalized = datetime.fromisoformat(t).isoformat()
            bucket[normalized] = (point.get("close", point.get("price")), point["volume"])
        if bucket:
            observed[(code, day)] = bucket
    coverage = summary.get("coverage", {})
    audit.same("observed_snapshot_count", coverage.get("snapshots"), len(snapshots), "coverage")
    audit.same("observed_code_day_count", coverage.get("code_days"), len(observed), "coverage")
    audit.same("observed_code_count", coverage.get("codes"), len({k[0] for k in observed}), "coverage")
    days = sorted({k[1] for k in observed})
    audit.same("observed_date_range", [coverage.get("first_date"), coverage.get("last_date")], [days[0], days[-1]] if days else [None, None], "coverage")
    for context in contexts:
        for day, (receipt, _) in context.sessions.items():
            if receipt.get("status") != "verified" or receipt.get("source_kind") != "observed_minute_bar_closes":
                continue
            audit.counts["observed_source_sessions_checked"] += 1
            actual = {datetime.fromisoformat(str(p["datetime"])).isoformat(): (p["close"], p["volume"]) for p in receipt["records"]}
            audit.same("cache_matches_frozen_or_overlay_raw_points", actual, observed.get((context.code, day)), (context.code, day))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--minute-overlay", type=Path)
    args = parser.parse_args()
    db, directory, cache = args.db.resolve(), args.report.resolve(), args.cache.resolve()
    overlay = args.minute_overlay.resolve() if args.minute_overlay else None
    audit = Audit()
    paths = [db, *(directory / name for name in ("quote-protocol.json", "quote-summary.json", "quote-opportunities.jsonl", "all-wave-setups.csv")), *(ROOT / name for name in SOURCES), Path(__file__).resolve()]
    if overlay:
        paths.extend(sorted(overlay.glob("*.json")))
    before = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    protocol = json.loads((directory / "quote-protocol.json").read_text(encoding="utf-8"))
    summary = json.loads((directory / "quote-summary.json").read_text(encoding="utf-8"))
    with (directory / "all-wave-setups.csv").open(encoding="utf-8-sig", newline="") as source:
        setups = [r for r in csv.DictReader(source) if r["status"] == "setup_ready" and r["d2_date"]]
    ready = {(r["code"], r["d2_date"]): r for r in setups}
    with (directory / "quote-opportunities.jsonl").open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    by_key = {(r["code"], r["signal_date"], r["mainline_gate"]): r for r in rows}
    audit.same("unique_setup_keys", len(ready), len(setups), "all-wave-setups.csv")
    audit.same("expected_opportunities", len(ready), 2991, "setups")
    audit.same("expected_ledger_rows", len(rows), 8973, "ledger")
    audit.same("unique_ledger_keys", len(by_key), len(rows), "ledger")
    audit.same("summary_universe_counts", [summary.get("opportunities"), summary.get("ledger_rows")], [len(ready), len(rows)], "summary")
    expected_keys = {(code, day, gate) for code, day in ready for gate in GATES}
    audit.check("all_opportunities_all_three_gates_no_topn_or_capital_deletion", by_key.keys() == expected_keys, {"missing": sorted(expected_keys - by_key.keys()), "extra": sorted(by_key.keys() - expected_keys)})
    audit.same("summary_protocol_source_hashes", summary["source_hashes"], protocol["source_hashes"], "hashes")
    actual_sources = {k: before[str(Path(k.replace("\\", "/")))] for k in protocol["source_hashes"]}
    audit.same("current_source_hashes", actual_sources, protocol["source_hashes"], "hashes")
    audit.same("frozen_database_hash", before[str(db.relative_to(ROOT))], protocol["baseline_database_sha256"], "hashes")
    audit.same("summary_database_hash", summary["baseline_database_sha256"], protocol["baseline_database_sha256"], "hashes")
    audit.same("setup_ledger_hash", before[str((directory / "all-wave-setups.csv").relative_to(ROOT))], protocol["setup_ledger_sha256"], "hashes")
    audit.same("declared_source_file_set", {k.replace("\\", "/") for k in protocol["source_hashes"]}, set(SOURCES), "hashes")
    audit.same("ledger_order", [(r["signal_date"], r["code"], r["mainline_gate"]) for r in rows], sorted((r["signal_date"], r["code"], r["mainline_gate"]) for r in rows), "deterministic summaries")
    con = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)
    con.execute("PRAGMA query_only=ON")
    calendar = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date")]
    calendar_index = {day: i for i, day in enumerate(calendar)}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["code"]].append(row)
    contexts = []
    audited_by_key = {}
    for number, (code, stock_rows) in enumerate(sorted(grouped.items()), 1):
        base_rows = [r for r in stock_rows if r["mainline_gate"] == "no_mainline"]
        needed_days = set()
        for row in base_rows:
            endpoints = [row["signal_date"], *(e["date"] for e in row.get("evidence", [])), *([row["missing_quote_date"]] if row.get("missing_quote_date") else [])]
            stop = max(endpoints)
            needed_days.update(calendar[calendar_index[row["signal_date"]]:calendar_index[stop] + 1])
        evidence = StockEvidence(con, audit, code, cache, calendar, max(needed_days))
        for day in sorted(needed_days):
            evidence.session(day)
        for row in stock_rows:
            key = (code, row["signal_date"], row["mainline_gate"])
            setup = ready.get((code, row["signal_date"]))
            if setup is None:
                continue
            audit.same("signal_is_setup_d2", row["signal_date"], setup["d2_date"], key)
            audit.same("d0_d1_lineage", [row["d0_date"], row["d1_date"]], [setup["d0_date"], setup["d1_date"]], key)
            audit.same("d0_d1_d2_market_sessions", [calendar_index[setup[k]] for k in ("d0_date", "d1_date", "d2_date")], list(range(calendar_index[setup["d0_date"]], calendar_index[setup["d0_date"]] + 3)), key)
            audit.same("setup_session_indices", [int(float(setup[k])) for k in ("d0_index", "d1_index", "d2_index")], [calendar_index[setup[k]] for k in ("d0_date", "d1_date", "d2_date")], key)
            audit.same("variant_configuration", [row["variant"], row["mode"], row["hold_days"], row["staged"], row["exit_rule"]], [row["mainline_gate"] + SUFFIX, "sampled_quotes_1450", 10, True, "ma5_or_horizon"], key)
            gate = row["mainline_gate"]
            passed = gate == "no_mainline" or (gate == "price_resonance_proxy" and setup["mainline_proxy_passed"].lower() == "true") or (gate == "observed_theme" and setup["theme_status"] == "verified")
            if passed:
                base = by_key[(code, row["signal_date"], "no_mainline")]
                audit.same("passing_gate_preserves_full_opportunity", {k: v for k, v in row.items() if k not in {"mainline_gate", "variant"}}, {k: v for k, v in base.items() if k not in {"mainline_gate", "variant"}}, key)
                verify_evidence(row, evidence, audit)
                audited = verify_accounting(row, evidence, audit)
                snapshots = [e for e in row.get("evidence", []) if e["action"] == "snapshot_1450" and e["date"] == row["signal_date"]]
                if row["status"] == "skipped" and row.get("reason") == "d2_below_dynamic_ma5":
                    audit.check("d2_skipped_below_ma5", len(snapshots) == 1 and snapshots[0]["price"] < evidence.ma5(row["signal_date"], snapshots[0]["price"]) - 1e-10, key)
            else:
                expected_status = "mainline_unverifiable" if gate == "observed_theme" and setup["theme_status"] == "unknown" else "mainline_rejected"
                audit.same("gate_rejection_status", row["status"], expected_status, key)
                audit.same("gate_rejection_has_no_legs", row["legs"], [], key)
                for field in ("net_return_pct", "gross_return_pct", "gross_pnl", "net_pnl", "exit_reason"):
                    audit.same("gate_unknown_no_closed_return", row.get(field), None, (key, field))
                audited = row
            audited_by_key[key] = audited
        # Retain only observed minute receipts needed for raw-source crosschecks.
        evidence.sessions = {day: value for day, value in evidence.sessions.items() if value[0].get("source_kind") == "observed_minute_bar_closes" and value[0].get("status") == "verified"}
        evidence.daily.clear()
        evidence.valid_days.clear()
        evidence.factor_dates.clear()
        evidence.factors.clear()
        contexts.append(evidence)
        if number % 100 == 0 or number == len(grouped):
            print(f"verified_codes {number}/{len(grouped)} rows {len(audited_by_key)} failures {len(audit.failures)}", flush=True)
    verify_observed_sources(con, overlay, contexts, summary, audit)
    con.close()
    audited_rows = [audited_by_key[(r["code"], r["signal_date"], r["mainline_gate"])] for r in rows if (r["code"], r["signal_date"], r["mainline_gate"]) in audited_by_key]
    audit.same("all_rows_independently_visited", len(audited_rows), len(rows), "ledger")
    recomputed_summary = {}
    audit.same("summary_variant_set", sorted(summary["variants"]), sorted(g + SUFFIX for g in GATES), "summary")
    for gate in GATES:
        variant = gate + SUFFIX
        subset = [r for r in audited_rows if r["variant"] == variant]
        recomputed = {"overall": aggregate(subset), "by_year": {str(y): aggregate([r for r in subset if r["signal_date"][:4] == str(y)]) for y in range(1990, 2027)}}
        recomputed_summary[variant] = recomputed
        audit.same("summary_overall", summary["variants"][variant]["overall"], recomputed["overall"], variant)
        audit.same("summary_complete_year_set", sorted(summary["variants"][variant]["by_year"]), sorted(recomputed["by_year"]), variant)
        for year, result in recomputed["by_year"].items():
            audit.same("summary_by_year", summary["variants"][variant]["by_year"].get(year), result, (variant, year))
    after = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    audit.same("protected_inputs_unchanged_during_verification", after, before, "hashes")
    cache_after = {name: sha256(ROOT / name) for name in audit.cache_hashes}
    audit.same("used_cache_bytes_unchanged_during_verification", cache_after, audit.cache_hashes, "hashes")
    cross_day = [r for r in audit.first_entries if r["entry_time"][:10] != r["signal_date"]]
    affected_window_trades = []
    for row in rows:
        windows = [v for v in audit.rule_violations if v["rule"].startswith("baseline_window") and (v["code"], v["signal_date"], v["gate"]) == (row["code"], row["signal_date"], row["mainline_gate"])]
        for leg in row["legs"]:
            if leg["entry_reason"] != "ma5_pullback_two_windows":
                continue
            end = datetime.fromisoformat(leg["entry_decision_time"])
            endpoints = {(end - timedelta(minutes=5)).isoformat(), end.isoformat()}
            outside = [v for v in windows if v["time"] in endpoints]
            if outside:
                affected_window_trades.append({"code": row["code"], "signal_date": row["signal_date"], "gate": row["mainline_gate"], "entry_time": leg["entry_time"], "status": row["status"], "endpoints_outside_baseline_band": [v["time"] for v in outside]})
    audit.counts.update(ledger_rows=len(rows), independent_opportunities=len(ready), codes=len(grouped), summary_overall_groups=len(GATES), summary_year_groups=len(GATES) * 37)
    rule_counts = dict(Counter(v["rule"] for v in audit.rule_violations))
    gaps = {"unknown_status_counts": dict(Counter(r["status"] for r in rows if r["status"] not in {"closed", "skipped", "mainline_rejected"})),
            "quote_failure_status_counts": dict(Counter(r.get("quote_source_failure", {}).get("status", "missing_receipt") for r in rows if r["status"] == "unverifiable")),
            "quote_failures": [{"code": r["code"], "signal_date": r["signal_date"], "gate": r["mainline_gate"], "date": r.get("missing_quote_date"), "source_status": r.get("quote_source_failure", {}).get("status"), "open_legs": sum(leg.get("exit_date") is None for leg in r["legs"])} for r in rows if r["status"] == "unverifiable"],
            "limits": ["Price samples cannot prove unseen intraminute extrema, full tick paths or executable size; fills retain the unlimited-capacity sampling assumption.", "Historical sampled quote dates are checked against local timestamps, requested_date and frozen daily range/close; the provider response has no independently authenticated historical session timestamp.", "Uniform commission/slippage, fractional shares, historical ST status, delisted universe and listing exemptions remain research assumptions, not verified broker/exchange fills.", "This verifies the supplied setup universe and gate evidence fields, not a fresh detection or historical-sector data reconstruction.", "Original-rule divergences are reported without changing decisions, returns, source files or unknown outcomes."]}
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed" if audit.failures else ("ledger_pass_original_rule_divergence" if audit.rule_violations else "passed_with_evidence_gaps"),
              "ledger_checks_passed": not audit.failures,
              "original_rules_passed": not audit.rule_violations,
              "method": "Direct read-only SQLite, cached raw dictionaries and independently recomputed leg cash flows; no simulate, metrics, strategy imports, network requests, TopN selection or portfolio deletion.",
              "numeric_tolerance": {"relative": 1e-10, "absolute": 1e-7},
              "counts": dict(audit.counts), "checks": dict(audit.checks),
              "failure_count": len(audit.failures), "failures": audit.failures,
              "first_entry_verification": {"checked_rows": len(audit.first_entries), "unique_opportunities": len({(r["code"], r["signal_date"]) for r in audit.first_entries}), "cross_day_count": len(cross_day), "cross_day_rows": cross_day, "fill_clock_counts": dict(Counter(r["entry_time"][11:16] for r in audit.first_entries))},
              "original_rule_violations": {"counts": rule_counts, "endpoint_details": audit.rule_violations, "affected_pullback_additions": affected_window_trades, "affected_additions_by_gate": dict(Counter(r["gate"] for r in affected_window_trades))},
              "input_sha256": before, "cache": {"sessions_checked": len(audit.cache_hashes), "status_counts": dict(audit.cache_statuses), "source_kind_counts": dict(audit.cache_kinds), "sha256_manifest": audit.cache_hashes, "rejected_date_anomalies": audit.negative_date_anomalies},
              "recomputed_summary": recomputed_summary, "evidence_gaps": gaps}
    output = directory / "quote-ledger-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "failures": len(audit.failures), "original_rule_violations": rule_counts, "output": str(output)}, ensure_ascii=False), flush=True)
    return 1 if audit.failures else (2 if audit.rule_violations else 0)


if __name__ == "__main__":
    raise SystemExit(main())
