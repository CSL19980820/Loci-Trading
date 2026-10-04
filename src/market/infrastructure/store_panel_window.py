"""Bounded raw quote reuse for one range task; adjustment remains per request."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import sqlite3
import sys
from typing import Any

import numpy as np
import pandas as pd


def read_raw_panel_arrays(
    conn: sqlite3.Connection, fields: Sequence[str], *, where: str,
    params: Sequence[Any], codes: Sequence[str] | None = None,
    max_cells: int | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame] | None:
    """Stream quotes into dense numeric arrays, shared by ordinary and cached reads.

    Only the optional cache budget can limit a query; exceeding it returns None,
    never a partial panel. Quote existence, including all-NULL rows, defines axes.
    The caller certifies one connection version across the axis/data statements.
    """
    max_rows = None if max_cells is None else max(0, max_cells // (len(fields) + 1))
    if max_rows == 0:
        return None
    if codes:
        columns = pd.Index(sorted(set(codes)), name="code")
        if max_rows is not None and len(columns) > max_rows:
            return None
    else:
        sql = "SELECT DISTINCT code FROM quotes_daily WHERE " + where + " ORDER BY code"
        values = list(params)
        if max_rows is not None:
            sql += " LIMIT ?"
            values.append(max_rows + 1)
        columns = pd.Index([row[0] for row in conn.execute(sql, values)], name="code")
        if max_rows is not None and len(columns) > max_rows:
            return None
    sql = "SELECT DISTINCT trade_date FROM quotes_daily WHERE " + where + " ORDER BY trade_date"
    values = list(params)
    max_dates = None if max_rows is None else max_rows // max(1, len(columns))
    if max_dates is not None:
        sql += " LIMIT ?"
        values.append(max_dates + 1)
    index = pd.Index([row[0] for row in conn.execute(sql, values)], name="trade_date")
    if max_dates is not None and len(index) > max_dates:
        return None
    arrays = {name: np.full((len(index), len(columns)), np.nan) for name in fields}
    present = np.zeros((len(index), len(columns)), dtype=bool)
    sql = f"SELECT trade_date, code, {', '.join(fields)} FROM quotes_daily WHERE " + where
    values = list(params)
    if max_rows is not None:
        sql += " LIMIT ?"
        values.append(max_rows + 1)
    cursor = conn.execute(sql, values)
    # Bulk positional rows do not need sqlite3.Row's per-row mapping wrapper.
    # Keep the connection's row_factory intact for every other public reader.
    cursor.row_factory = None
    loaded = 0
    try:
        while batch := cursor.fetchmany(16_384):
            loaded += len(batch)
            if max_rows is not None and loaded > max_rows:
                return None
            records = np.asarray(batch, dtype=object)
            row_positions = index.get_indexer(records[:, 0])
            col_positions = columns.get_indexer(records[:, 1])
            if (row_positions < 0).any() or (col_positions < 0).any():
                return None
            present[row_positions, col_positions] = True
            numeric = records[:, 2:].astype(float)
            for position, array in enumerate(arrays.values()):
                array[row_positions, col_positions] = numeric[:, position]
    finally:
        cursor.close()
    return (
        {name: pd.DataFrame(array, index=index, columns=columns, copy=False)
         for name, array in arrays.items()},
        pd.DataFrame(present, index=index, columns=columns, copy=False),
    )


@dataclass
class _PanelWindow:
    store: Any
    conn: sqlite3.Connection
    start: str
    end: str
    max_cells: int
    version: tuple[int, int] | None = None
    panels: dict[str, pd.DataFrame] = field(default_factory=dict)
    present: pd.DataFrame | None = None
    declined: bool = False
    evidence: Any = None
    evidence_declined: bool = False
    evidence_declined_request: Any = None
    max_evidence_bytes: int = 192_000_000
    source_summary: Any = None
    source_summary_declined: bool = False
    loaded_codes: frozenset[str] | None = None
    declined_request: Any = None
    factor_rows: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
    factor_bytes: int = 0
    factor_declined: bool = False
    max_factor_bytes: int = 16_000_000

    def current_version(self) -> tuple[int, int]:
        return self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0]

    def clear(self) -> None:
        self.panels.clear()
        self.present = None
        self.declined = False
        self.evidence = None
        self.evidence_declined = False
        self.evidence_declined_request = None
        self.source_summary = None
        self.source_summary_declined = False
        self.loaded_codes = None
        self.declined_request = None
        self.factor_rows.clear()
        self.factor_bytes = 0
        self.factor_declined = False

    def refresh(self) -> bool:
        # Never reuse a transaction snapshot, including writes later rolled back.
        if self.conn.in_transaction:
            self.clear()
            self.version = None
            return False
        version = self.current_version()
        if version != self.version:
            self.clear()
            self.version = version
        return True

    def prepare(self, fields: Sequence[str], codes: Sequence[str] | None = None) -> bool:
        if not self.refresh():
            return False
        version = self.version
        # load_panel is the shared validation/normalization boundary.
        requested = frozenset(codes) if codes else None
        if (self.present is not None and all(name in self.panels for name in fields)
                and (self.loaded_codes is None or requested is not None
                     and requested.issubset(self.loaded_codes))):
            return True
        # Keep actual code/field scope. A new code or field may extend the cache;
        # failure to extend cannot invalidate a previously complete narrower read.
        scope = requested
        if self.present is not None:
            scope = (None if requested is None or self.loaded_codes is None
                     else requested | self.loaded_codes)
        needed = tuple(dict.fromkeys([*self.panels, *fields]))
        request_key = (needed, scope)
        if self.declined and self.declined_request == request_key:
            return False
        self.declined = True
        self.declined_request = request_key
        incremental = (self.present is not None and self.loaded_codes is not None
                       and scope is not None and len(needed) == len(self.panels))
        read_scope = scope - self.loaded_codes if incremental else scope
        if (incremental and len(self.present.index) * len(scope) * (len(needed) + 1)
                > self.max_cells):
            return False
        where = "trade_date >= ? AND trade_date <= ?"
        params: list[Any] = [self.start, self.end]
        if read_scope is not None:
            columns = sorted(read_scope)
            where += " AND code IN (" + ",".join("?" for _ in columns) + ")"
            params.extend(columns)
        loaded = read_raw_panel_arrays(
            self.conn, needed, where=where, params=params,
            codes=sorted(read_scope) if read_scope is not None else None, max_cells=self.max_cells,
        )
        if incremental and loaded is not None:
            added, present = loaded
            index = self.present.index.union(present.index)
            columns = self.present.columns.union(present.columns)
            shape = (len(index), len(columns))
            if shape[0] * shape[1] * (len(needed) + 1) > self.max_cells:
                loaded = None
            else:
                old_positions = np.ix_(index.get_indexer(self.present.index),
                                       columns.get_indexer(self.present.columns))
                new_positions = np.ix_(index.get_indexer(present.index),
                                       columns.get_indexer(present.columns))
                # Construct complete private arrays before certifying/publishing
                # the extension. An all-NULL quote still contributes an axis.
                combined = {}
                for name in needed:
                    values = np.full(shape, np.nan)
                    values[old_positions] = self.panels[name].to_numpy(copy=False)
                    values[new_positions] = added[name].to_numpy(copy=False)
                    combined[name] = pd.DataFrame(values, index=index, columns=columns, copy=False)
                exists = np.zeros(shape, dtype=bool)
                exists[old_positions] = self.present.to_numpy(copy=False)
                exists[new_positions] = present.to_numpy(copy=False)
                loaded = (combined, pd.DataFrame(exists, index=index, columns=columns, copy=False))
        if self.conn.in_transaction or version != self.current_version():
            self.clear()
            return False
        if loaded is None:
            return False
        self.panels, self.present = loaded
        self.loaded_codes = scope
        self.declined = False
        self.declined_request = None
        return True


_ACTIVE_WINDOW: ContextVar[_PanelWindow | None] = ContextVar("market_panel_window", default=None)


@contextmanager
def panel_read_window(
    store: Any, *, start: str, end: str, max_cells: int = 24_000_000,
    max_evidence_bytes: int = 192_000_000,
    max_factor_bytes: int = 16_000_000,
) -> Iterator[None]:
    """Reuse raw panels only inside this task, capped at max_cells numeric cells.

    Include warmup in start. Requests outside the bounds use the normal reader.
    No read transaction is held; concurrent database commits invalidate reuse.
    """
    state = _PanelWindow(store, store.conn, start, end, max_cells,
                         max_evidence_bytes=max_evidence_bytes, max_factor_bytes=max_factor_bytes)
    token = _ACTIVE_WINDOW.set(state)
    try:
        yield
    finally:
        _ACTIVE_WINDOW.reset(token)
        state.clear()


def cached_raw_panels(
    store: Any, fields: Sequence[str], *, codes: Sequence[str] | None,
    start: str | None, end: str | None,
) -> dict[str, pd.DataFrame] | None:
    state = _ACTIVE_WINDOW.get()
    if (state is None or state.store is not store or state.conn is not store.conn
            or not fields or not start or not end
            or start < state.start or end > state.end or start > end
            or not state.prepare(fields, codes)):
        return None
    present = state.present.loc[start:end]
    if codes:
        requested = set(codes)
        present = present.loc[:, present.columns.isin(requested)]
    if present.empty or not present.to_numpy().any():
        result = {name: pd.DataFrame() for name in fields}
    else:
        rows = present.index[present.any(axis=1)]
        columns = present.columns[present.any(axis=0)]
        # A caller may mutate raw or adjusted outputs; cache arrays must stay private.
        row_positions = state.present.index.get_indexer(rows)
        col_positions = state.present.columns.get_indexer(columns)
        positions = np.ix_(row_positions, col_positions)
        result = {
            name: pd.DataFrame(state.panels[name].to_numpy(copy=False)[positions],
                               index=rows, columns=columns, copy=False)
            for name in fields
        }
    if state.conn.in_transaction or state.version != state.current_version():
        state.clear()
        return None
    return result


def cached_factor_rows(store: Any, codes: Sequence[str]) -> list[tuple[str, str, Any]] | None:
    """Reuse sparse facts, while callers still choose their own time boundary/anchor."""
    state = _ACTIVE_WINDOW.get()
    if (state is None or state.store is not store or state.conn is not store.conn
            or not codes or not state.refresh() or state.factor_declined):
        return None
    version = state.version
    requested = list(dict.fromkeys(str(code) for code in codes))
    missing = [code for code in requested if code not in state.factor_rows]
    for offset in range(0, len(missing), 900):
        chunk = missing[offset:offset + 900]
        for code in chunk:
            state.factor_rows[code] = []
            state.factor_bytes += sys.getsizeof(code) + sys.getsizeof(state.factor_rows[code])
        if sys.getsizeof(state.factor_rows) + state.factor_bytes > state.max_factor_bytes:
            state.factor_rows.clear()
            state.factor_bytes = 0
            state.factor_declined = True
            return None
        cursor = state.conn.execute(
            "SELECT code, trade_date, hfq_factor FROM adjust_factors WHERE code IN ("
            + ",".join("?" for _ in chunk) + ") ORDER BY code, trade_date", chunk,
        )
        try:
            for code, day, factor in cursor:
                item = (day, factor)
                values = state.factor_rows[code]
                before = sys.getsizeof(values)
                values.append(item)
                state.factor_bytes += (sys.getsizeof(values) - before + sys.getsizeof(item)
                                       + sys.getsizeof(day) + sys.getsizeof(factor))
                used = sys.getsizeof(state.factor_rows) + state.factor_bytes
                if used > state.max_factor_bytes:
                    state.factor_rows.clear()
                    state.factor_bytes = 0
                    state.factor_declined = True
                    return None
        finally:
            cursor.close()
    if state.conn.in_transaction or version != state.current_version():
        state.clear()
        return None
    result = [(code, day, factor) for code in requested
              for day, factor in state.factor_rows[code]]
    if state.conn.in_transaction or version != state.current_version():
        state.clear()
        return None
    return result
