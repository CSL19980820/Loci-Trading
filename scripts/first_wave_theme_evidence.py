"""Read-only, point-in-time theme evidence for the first-wave study.

No quote/industry proxy or live tool calls are used. Sector observations must
belong to D0; membership facts may be older than D0. Knowledge is cut strictly
before 14:50 Asia/Shanghai on the decision day (D2). A positive row in a partial
membership response is evidence; an absent row is not evidence of absence.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
import re
import sqlite3
from typing import Any


_LOCAL = timezone(timedelta(hours=8))
_QUADRANTS = ("continuingStrong", "emerging")


def _day(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isascii() and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:SH|SZ|BJ)?([0-9]{6})(?:\.(?:SH|SZ|BJ))?", value.strip().upper())
    return match[1] if match else None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _metadata(value: Any):
    """Inspect returned facts, never the caller's requested arguments."""
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key not in ("arguments", "text", "structured"):
                yield from _metadata(child)
    elif isinstance(value, list):
        for child in value:
            yield from _metadata(child)


@dataclass(frozen=True)
class _Snapshot:
    tool: str
    trade_date: str
    fetched_at: str
    known_at: datetime
    fact_dates: tuple[str, ...]
    actual_dates: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    mismatch: bool
    complete: bool
    themes: tuple[str, ...] = ()
    members: frozenset[str] = frozenset()

    @property
    def fact_day(self) -> str:
        return max(self.actual_dates or self.fact_dates, default=self.trade_date)

    @property
    def index_day(self) -> str:
        # A delayed fetch can be cached under a later day while stating older
        # facts. Also retain mislabeled older rows for rejection diagnostics.
        return min(self.trade_date, self.fact_day)

    def source(self, *, used: bool = True) -> dict[str, Any]:
        return {
            "tool": self.tool, "trade_date": self.trade_date,
            "fetched_at": self.fetched_at, "fact_dates": list(self.fact_dates),
            "actual_trade_dates": list(self.actual_dates),
            "themes": list(self.themes), "coverage_complete": self.complete,
            "used_as_evidence": used,
        }


def _parse(tool: str, trade_date: str, fetched_at: str, raw: str) -> _Snapshot | None:
    snapshot_day = _day(trade_date)
    if not snapshot_day or not isinstance(fetched_at, str) or not re.search(
        r"[T ]\d{2}:\d{2}", fetched_at,
    ):
        return None
    warnings: list[str] = []
    try:
        known_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return None  # A missing/invalid knowledge timestamp can never pass the gate.
    if known_at.tzinfo is None:
        known_at = known_at.replace(tzinfo=_LOCAL)
        warnings.append("naive_fetched_at_assumed_asia_shanghai")
    known_at = known_at.astimezone(_LOCAL)
    wrapper = _object(raw)
    root = (_object(wrapper.get("structured")) or _object(wrapper.get("text"))) if (
        "structured" in wrapper or "text" in wrapper
    ) else wrapper
    body = _object(root.get("data")) if "data" in root else root
    errors: list[str] = []
    if not body:
        errors.append("invalid_payload")
    for node in (wrapper, root, body):
        if node.get("is_error") or node.get("success") is False:
            errors.append("tool_error")
        if node.get("tool") and node["tool"] != tool:
            errors.append("tool_mismatch")
    fact_dates: set[str] = set()
    actual_dates: set[str] = set()
    mismatch = False
    # The wrapper contributes transport quality flags; dates come from results.
    nodes = [{k: v for k, v in wrapper.items() if k in (
        "truncated", "partialErrors", "qualityWarnings", "dateStatus", "clamped",
    )}, *_metadata(root)]
    for node in nodes:
        for field in ("tradeDate", "actualTradeDate"):
            if field not in node:
                continue
            fact_day = _day(node[field])
            if fact_day is None:
                errors.append("invalid_fact_date")
            else:
                fact_dates.add(fact_day)
                if field == "actualTradeDate":
                    actual_dates.add(fact_day)
        if node.get("truncated") or node.get("clamped"):
            warnings.append("truncated")
        if node.get("partialErrors"):
            warnings.append("partial_errors")
        quality = node.get("qualityWarnings")
        if quality:
            warnings.append("quality_warnings")
        if "mismatch" in str(node.get("dateStatus", "")).lower() or (
            quality and "date_mismatch" in str(quality).lower()
        ):
            mismatch = True
            warnings.append("date_mismatch")
    if actual_dates and len(fact_dates) > 1:
        mismatch = True
        warnings.append("date_mismatch")

    themes: list[str] = []
    members: set[str] = set()
    complete = not any(w != "naive_fetched_at_assumed_asia_shanghai" for w in warnings)
    if tool == "sector_analysis":
        meta = _object(body.get("meta"))
        if _number(meta.get("strengthPeriod")) != 5:
            errors.append("strength_period_not_verified_as_5")
        lists = _object(body.get("topLists"))
        for quadrant in _QUADRANTS:
            rows = lists.get(quadrant)
            if not isinstance(rows, list):
                warnings.append("missing_mainline_list")
                complete = False
                continue
            for row in rows:
                row = _object(row)
                name = row.get("name")
                metrics = [_number(row.get(key)) for key in (
                    "recentChange", "recentUpDays", "volumeRatio",
                )]
                if not isinstance(name, str) or not name.strip() or None in metrics:
                    warnings.append("unverifiable_mainline_row")
                    complete = False
                    continue
                change, up_days, volume = metrics
                if up_days != int(up_days) or not 0 <= up_days <= 5 or volume < 0 or (
                    _number(row.get("recentTotalDays", 5)) != 5
                ):
                    warnings.append("unverifiable_mainline_row")
                    complete = False
                    continue
                if change >= 5 and up_days >= 3 and volume >= 1.1:
                    themes.append(name.strip())
    else:
        theme = _object(body.get("theme"))
        resolution = _object(body.get("resolution"))
        name = theme.get("name") or resolution.get("resolvedName")
        if isinstance(name, str) and name.strip():
            themes.append(name.strip())
        else:
            errors.append("missing_resolved_theme")
        rows = body.get("rows")
        if not isinstance(rows, list):
            rows = []
            errors.append("missing_member_rows")
        for row in rows:
            code = _code(row.get("code")) if isinstance(row, dict) else None
            if code:
                members.add(code)
            else:
                warnings.append("unverifiable_member_row")
                complete = False
        total, returned = _number(body.get("total")), _number(body.get("returned"))
        if total is None or returned is None or not (
            total == returned == len(rows) == len(members)
        ):
            warnings.append("incomplete_member_coverage")
            complete = False
        if not fact_dates:
            errors.append("missing_membership_fact_date")
    if errors:
        complete = False
    return _Snapshot(
        tool, snapshot_day, fetched_at, known_at, tuple(sorted(fact_dates)),
        tuple(sorted(actual_dates)), tuple(dict.fromkeys(warnings)),
        tuple(dict.fromkeys(errors)), mismatch, complete,
        tuple(dict.fromkeys(themes)), frozenset(members),
    )


@dataclass(frozen=True)
class _MemberView:
    # Newer partial positives followed by the newest complete historical record.
    records: tuple[_Snapshot, ...]
    warnings: tuple[str, ...]
    rejected: tuple[_Snapshot, ...]

    @property
    def complete(self) -> bool:
        return bool(self.records and self.records[-1].complete)


class ThemeEvidence:
    """An in-memory index; evaluate performs no SQL or JSON parsing.

    ``verified`` requires one dated strong-theme membership witness. The negative
    status only describes the observed top lists and their latest complete member
    responses; it does not assert absence from every market theme. Missing or
    incomplete evidence returns ``unknown``. Every response is a fresh dictionary.
    """

    def __init__(self, snapshots: list[_Snapshot], warnings: tuple[str, ...] = ()):
        self._warnings = warnings
        self._sectors: dict[str, list[_Snapshot]] = {}
        self._members: dict[str, list[_Snapshot]] = {}
        for snapshot in snapshots:
            if snapshot.tool == "sector_analysis":
                self._sectors.setdefault(snapshot.trade_date, []).append(snapshot)
            else:
                for theme in snapshot.themes:
                    self._members.setdefault(theme, []).append(snapshot)
        for records in self._sectors.values():
            records.sort(key=lambda s: s.known_at, reverse=True)
        self._member_days: dict[str, tuple[str, ...]] = {}
        for theme, records in self._members.items():
            records.sort(key=lambda s: (s.index_day, s.known_at))
            self._member_days[theme] = tuple(s.index_day for s in records)

    @lru_cache(maxsize=128)
    def _context(self, asof: str, decision: str):
        cutoff = datetime.combine(date.fromisoformat(decision), time(14, 50), _LOCAL)
        warnings = list(self._warnings)
        sector = None
        rejected = []
        for record in self._sectors.get(asof, ()):
            if record.known_at >= cutoff:
                continue
            problems = list(record.errors)
            if record.fact_dates and any(d != asof for d in record.fact_dates):
                problems.append("sector_fact_date_not_asof")
            if record.mismatch:
                problems.append("sector_date_mismatch")
            if record.fact_day > record.known_at.date().isoformat():
                problems.append("fact_date_after_capture")
            if not record.fact_dates:
                if record.known_at.date().isoformat() != asof:
                    problems.append("undated_sector_captured_on_other_day")
                else:
                    warnings.append("sector_analysis:fact_date_from_same_day_capture")
            warnings.extend(f"sector_analysis:{w}" for w in (*record.warnings, *problems))
            if problems:
                rejected.append(record)
                continue
            if sector is None:
                sector = record
            if record.complete:
                sector = record
                break
        views = {}
        if sector:
            for theme in sector.themes:
                records = self._members.get(theme, ())
                end = bisect_right(self._member_days.get(theme, ()), asof)
                selected, member_warnings, invalid = [], [], []
                candidates = sorted(records[:end], key=lambda s: (s.fact_day, s.known_at), reverse=True)
                for record in candidates:
                    if record.known_at >= cutoff:
                        continue
                    problems = list(record.errors)
                    if any(d > asof for d in record.fact_dates):
                        problems.append("membership_fact_date_after_asof")
                    if record.trade_date > record.known_at.date().isoformat():
                        problems.append("snapshot_date_after_capture")
                    if record.fact_day > record.known_at.date().isoformat():
                        problems.append("fact_date_after_capture")
                    if record.mismatch and not record.actual_dates:
                        problems.append("mismatch_without_actual_trade_date")
                    member_warnings.extend(f"theme_stocks:{theme}:{w}" for w in (
                        *record.warnings, *problems,
                    ))
                    if problems:
                        invalid.append(record)
                        continue
                    selected.append(record)
                    if record.complete:
                        break
                if not selected:
                    member_warnings.append(f"theme_stocks:{theme}:missing_eligible_membership")
                views[theme] = _MemberView(
                    tuple(selected), tuple(dict.fromkeys(member_warnings)), tuple(invalid[:1]),
                )
        return sector, views, tuple(dict.fromkeys(warnings)), tuple(rejected[:1])

    def evaluate(self, code: str, asof_date: str, decision_date: str) -> dict[str, Any]:
        asof, decision, code = _day(asof_date), _day(decision_date), _code(code)
        result: dict[str, Any] = {
            "passed": False, "status": "unknown", "reason": "invalid_code_or_dates",
            "themes": [], "warnings": [], "source": [], "coverage_complete": False,
        }
        if not asof or not decision or not code or decision < asof:
            return result
        sector, views, warnings, rejected = self._context(asof, decision)
        result["warnings"] = list(warnings)
        if sector is None:
            result["reason"] = "no_verifiable_asof_sector_snapshot_before_decision_cutoff"
            result["source"] = [record.source(used=False) for record in rejected]
            return result
        result["source"].append(sector.source())
        complete = sector.complete
        for theme, view in views.items():
            result["warnings"].extend(view.warnings)
            witness = next((r for r in view.records if code in r.members), None)
            if witness:
                result["themes"].append(theme)
            # The last record is complete, if one exists. Only it can prove absence.
            source = witness or (view.records[-1] if view.records else None)
            if source:
                member_source = source.source()
                member_source["membership"] = "present" if witness else (
                    "absent_in_complete_snapshot" if source.complete else "unobserved_in_partial_snapshot"
                )
                member_source["code"] = code
                result["source"].append(member_source)
            else:
                result["source"].extend(r.source(used=False) for r in view.rejected)
            complete = complete and view.complete and bool(source and source.complete)
        result["warnings"] = list(dict.fromkeys(result["warnings"]))
        result["coverage_complete"] = complete
        if result["themes"]:
            result.update(passed=True, status="verified", reason="historical_mainline_membership_verified")
        elif complete:
            result.update(
                status="not_in_observed_mainline",
                reason=("absent_from_latest_complete_membership_of_observed_mainlines" if sector.themes
                        else "no_observed_theme_meets_mainline_strength_rule"),
            )
        else:
            result["reason"] = "observed_mainline_membership_coverage_incomplete"
        return result


def load_theme_evidence(connection: sqlite3.Connection) -> ThemeEvidence:
    """Read snapshots once without changing connection settings or database data."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", ("intel_snapshots",),
    ).fetchone()
    if not exists:
        return ThemeEvidence([], ("missing_intel_snapshots",))
    snapshots = []
    rows = connection.execute(
        "SELECT tool, trade_date, fetched_at, payload_json FROM intel_snapshots WHERE tool IN (?, ?)",
        ("sector_analysis", "theme_stocks"),
    )
    for tool, trade_date, fetched_at, raw in rows:
        snapshot = _parse(tool, trade_date, fetched_at, raw)
        if snapshot:
            snapshots.append(snapshot)
    return ThemeEvidence(snapshots)
