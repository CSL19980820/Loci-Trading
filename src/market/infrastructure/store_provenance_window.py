"""Task-local, bounded categorical quote facts for overlapping evidence windows."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
import sys
from typing import Any

import numpy as np

from .store_panel_window import _ACTIVE_WINDOW, _PanelWindow


FIELD_COLUMNS = ("open", "high", "low", "close", "volume", "amount", "turnover", "outstanding_share")
COUNT_COLUMNS = ("open_rows", "high_rows", "low_rows", "close_rows", "volume_rows", "amount_rows", "turnover_rows", "share_rows")
INVALID_OHLC_SQL = (
    "open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL "
    "AND (high < low OR high < open OR high < close OR low > open OR low > close "
    "OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0)"
)
_DTYPE = np.dtype([("group", "u4"), ("date", "u4"), ("fetched", "u4"), ("flags", "u2")])


@dataclass
class _EvidenceWindow:
    rows: np.ndarray
    groups: list[tuple[str, str | None, str]]
    dates: list[str]
    fetched: list[str]
    sources: dict[str, str]

    def aggregate(self, codes: Sequence[str], start: str, end: str) -> list[dict[str, Any]]:
        first, last = bisect_left(self.dates, start), bisect_right(self.dates, end)
        mask = (self.rows["date"] >= first) & (self.rows["date"] < last)
        if codes:
            wanted = set(codes)
            allowed = np.array([key[0] in wanted for key in self.groups], dtype=bool)
            mask &= allowed[self.rows["group"]]
        rows = self.rows[mask]
        if not len(rows):
            return []
        ids = rows["group"]
        size = len(self.groups)
        counts = np.bincount(ids, minlength=size)
        fields = [np.bincount(ids[(rows["flags"] & (1 << bit)) != 0], minlength=size)
                  for bit in range(9)]
        first_dates = np.full(size, len(self.dates), dtype=np.uint32)
        last_dates = np.zeros(size, dtype=np.uint32)
        last_fetched = np.zeros(size, dtype=np.uint32)
        np.minimum.at(first_dates, ids, rows["date"])
        np.maximum.at(last_dates, ids, rows["date"])
        np.maximum.at(last_fetched, ids, rows["fetched"])
        result = []
        for group_id in np.flatnonzero(counts):
            code, receipt_id, legacy_source = self.groups[group_id]
            count = int(counts[group_id])
            result.append({
                "code": code, "receipt_id": receipt_id, "legacy_source": legacy_source,
                "source_id": legacy_source if receipt_id is None else self.sources.get(receipt_id),
                "rows": count, "first_date": self.dates[first_dates[group_id]],
                "last_date": self.dates[last_dates[group_id]],
                "last_fetched_at": self.fetched[last_fetched[group_id]],
                "legacy_rows": count if receipt_id is None else 0,
                "invalid_ohlc": int(fields[8][group_id]),
                **{name: int(values[group_id]) for name, values in zip(COUNT_COLUMNS, fields)},
            })
        return result


def _load(state: _PanelWindow) -> _EvidenceWindow | None:
    # Reserve 48 bytes/row for packed storage, slice/mask and aggregation scratch.
    # Metadata gets the remaining budget; it cannot grow with arbitrary string IDs.
    max_rows = max(0, state.max_evidence_bytes // 48)
    if not max_rows:
        return None
    count = state.conn.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM quotes_daily "
        "WHERE trade_date >= ? AND trade_date <= ? LIMIT ?)",
        (state.start, state.end, max_rows + 1),
    ).fetchone()[0]
    if count > max_rows:
        return None
    packed = np.empty(count, dtype=_DTYPE)
    groups: dict[tuple[str, str | None, str], int] = {}
    dates: dict[str, int] = {}
    fetched: dict[str, int] = {}
    budget = state.max_evidence_bytes - count * 48
    flags = " + ".join(f"({name} IS NOT NULL) * {1 << bit}" for bit, name in enumerate(FIELD_COLUMNS))
    flags += f" + (CASE WHEN {INVALID_OHLC_SQL} THEN 256 ELSE 0 END)"
    cursor = state.conn.execute(
        "SELECT code, trade_date, receipt_id, CASE WHEN receipt_id IS NULL "
        "THEN COALESCE(NULLIF(source, ''), 'unknown') ELSE '' END, fetched_at, " + flags
        + " FROM quotes_daily WHERE trade_date >= ? AND trade_date <= ? LIMIT ?",
        (state.start, state.end, max_rows + 1),
    )
    offset = 0
    try:
        while batch := cursor.fetchmany(8192):
            if offset + len(batch) > count:
                return None
            encoded = []
            for code, day, receipt_id, source, stamp, valid in batch:
                key = (code, receipt_id, source)
                if key not in groups:
                    # Include group metadata, nine count arrays and result dictionaries.
                    budget -= 2048 + sum(sys.getsizeof(part) for part in key)
                    groups[key] = len(groups)
                for value, mapping in ((day, dates), (stamp, fetched)):
                    if value not in mapping:
                        budget -= 192 + sys.getsizeof(value)
                        mapping[value] = len(mapping)
                if budget < 0:
                    return None
                encoded.append((groups[key], dates[day], fetched[stamp], valid))
            packed[offset:offset + len(batch)] = encoded
            offset += len(batch)
    finally:
        cursor.close()
    if offset != count:
        return None
    axes = []
    for field, mapping in (("date", dates), ("fetched", fetched)):
        ordered = sorted(mapping)
        remap = np.empty(len(ordered), dtype=np.uint32)
        for rank, value in enumerate(ordered):
            remap[mapping[value]] = rank
        packed[field] = remap[packed[field]]
        axes.append(ordered)
    receipt_ids = list({key[1] for key in groups if key[1] is not None})
    sources = {}
    for offset in range(0, len(receipt_ids), 900):
        chunk = receipt_ids[offset:offset + 900]
        for receipt_id, source in state.conn.execute(
            "SELECT receipt_id,selected_source FROM source_route_receipts WHERE receipt_id IN ("
            + ",".join("?" for _ in chunk) + ")", chunk,
        ):
            budget -= 192 + sys.getsizeof(source)
            if budget < 0:
                return None
            sources[receipt_id] = source
    return _EvidenceWindow(packed, list(groups), axes[0], axes[1], sources)


def cached_quote_evidence(
    store: Any, codes: Sequence[str], *, start: str | None, end: str | None,
) -> list[dict[str, Any]] | None:
    state = _ACTIVE_WINDOW.get()
    if (state is None or state.store is not store or state.conn is not store.conn
            or not start or not end or start < state.start or end > state.end
            or not state.refresh()):
        return None
    version = state.version
    if state.evidence is None:
        if state.evidence_declined:
            return None
        state.evidence_declined = True
        candidate = _load(state)
        if state.conn.in_transaction or version != state.current_version():
            state.clear()
            return None
        state.evidence = candidate
        if candidate is None:
            return None
    result = state.evidence.aggregate(codes, start, end)
    if state.conn.in_transaction or version != state.current_version():
        state.clear()
        return None
    return result
