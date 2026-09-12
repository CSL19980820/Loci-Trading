"""Bounded raw quote reuse for one range task; adjustment remains per request."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import sqlite3
from typing import Any

import numpy as np
import pandas as pd

from .store_codes import normalize_code


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
    max_evidence_bytes: int = 192_000_000

    def current_version(self) -> tuple[int, int]:
        return self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0]

    def clear(self) -> None:
        self.panels.clear()
        self.present = None
        self.declined = False
        self.evidence = None
        self.evidence_declined = False

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

    def prepare(self, fields: Sequence[str]) -> bool:
        if not self.refresh():
            return False
        version = self.version
        if self.present is not None:
            return self.present.empty or all(name in self.panels for name in fields)
        if self.declined:
            return False
        self.declined = True
        width = len(fields) + 1
        max_rows = max(0, self.max_cells // width)
        if not max_rows:
            return False
        # LIMIT bounds both the guard scan and the subsequent flat allocation.
        count, dates, codes = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT trade_date), COUNT(DISTINCT code) "
            "FROM (SELECT trade_date, code FROM quotes_daily "
            "WHERE trade_date >= ? AND trade_date <= ? LIMIT ?)",
            (self.start, self.end, max_rows + 1),
        ).fetchone()
        if count > max_rows or dates * codes * width > self.max_cells:
            return False
        if not count:
            self.present = pd.DataFrame()
            return True
        axes = []
        for name in ("trade_date", "code"):
            values = self.conn.execute(
                f"SELECT DISTINCT {name} FROM quotes_daily "
                f"WHERE trade_date >= ? AND trade_date <= ? ORDER BY {name} LIMIT ?",
                (self.start, self.end, max_rows + 1),
            ).fetchall()
            axes.append(pd.Index([row[0] for row in values], name=name))
        index, columns = axes
        if len(index) * len(columns) * width > self.max_cells:
            return False
        # Fill dense arrays in bounded chunks; never retain millions of Python
        # SQL rows, a long DataFrame and a pivot copy at the same time.
        arrays = {name: np.full((len(index), len(columns)), np.nan) for name in fields}
        present = np.zeros((len(index), len(columns)), dtype=bool)
        cursor = self.conn.execute(
            f"SELECT trade_date, code, {', '.join(fields)} FROM quotes_daily "
            "WHERE trade_date >= ? AND trade_date <= ? LIMIT ?",
            (self.start, self.end, max_rows + 1),
        )
        loaded = 0
        try:
            while batch := cursor.fetchmany(16_384):
                loaded += len(batch)
                if loaded > max_rows:
                    return False
                frame = pd.DataFrame.from_records(batch, columns=["trade_date", "code", *fields])
                row_positions = index.get_indexer(frame["trade_date"])
                col_positions = columns.get_indexer(frame["code"])
                if (row_positions < 0).any() or (col_positions < 0).any():
                    return False
                present[row_positions, col_positions] = True
                for name, array in arrays.items():
                    array[row_positions, col_positions] = frame[name].to_numpy(dtype=float)
        finally:
            cursor.close()
        if version != self.current_version():
            return False
        self.panels = {name: pd.DataFrame(array, index=index, columns=columns, copy=False)
                       for name, array in arrays.items()}
        # Existence is independent of values: an all-NULL quote still creates axes.
        self.present = pd.DataFrame(present, index=index, columns=columns, copy=False)
        return True


_ACTIVE_WINDOW: ContextVar[_PanelWindow | None] = ContextVar("market_panel_window", default=None)


@contextmanager
def panel_read_window(
    store: Any, *, start: str, end: str, max_cells: int = 24_000_000,
    max_evidence_bytes: int = 192_000_000,
) -> Iterator[None]:
    """Reuse raw panels only inside this task, capped at max_cells numeric cells.

    Include warmup in start. Requests outside the bounds use the normal reader.
    No read transaction is held; concurrent database commits invalidate reuse.
    """
    state = _PanelWindow(store, store.conn, start, end, max_cells,
                         max_evidence_bytes=max_evidence_bytes)
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
            or start < state.start or end > state.end or not state.prepare(fields)):
        return None
    present = state.present.loc[start:end]
    if codes:
        requested = {normalize_code(code) for code in codes}
        present = present.loc[:, present.columns.isin(requested)]
    if present.empty or not present.to_numpy().any():
        return {name: pd.DataFrame() for name in fields}
    rows = present.index[present.any(axis=1)]
    columns = present.columns[present.any(axis=0)]
    # A caller may mutate raw or adjusted outputs; cache arrays must stay private.
    return {name: state.panels[name].loc[rows, columns].copy() for name in fields}
