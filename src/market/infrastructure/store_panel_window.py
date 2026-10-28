"""Bounded raw quote reuse for one range task; adjustment remains per request."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _row_value(row: Any) -> Any:
    if hasattr(row, "values"):
        return next(iter(row.values()))
    return row[0]


def _row_tuple(row: Any, fields: Sequence[str]) -> tuple[Any, ...]:
    """Return selected values from sqlite3 rows or psycopg mapping rows."""
    if isinstance(row, dict) or hasattr(row, "keys"):
        return tuple(row[field] for field in fields)
    return tuple(row)


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
        columns = pd.Index([_row_value(row) for row in conn.execute(sql, values)], name="code")
        if max_rows is not None and len(columns) > max_rows:
            return None
    sql = "SELECT DISTINCT trade_date FROM quotes_daily WHERE " + where + " ORDER BY trade_date"
    values = list(params)
    max_dates = None if max_rows is None else max_rows // max(1, len(columns))
    if max_dates is not None:
        sql += " LIMIT ?"
        values.append(max_dates + 1)
    index = pd.Index([_row_value(row) for row in conn.execute(sql, values)], name="trade_date")
    if max_dates is not None and len(index) > max_dates:
        return None
    arrays = {name: np.full((len(index), len(columns)), np.nan) for name in fields}
    present = np.zeros((len(index), len(columns)), dtype=bool)
    sql = f"SELECT trade_date, code, {', '.join(fields)} FROM quotes_daily WHERE " + where
    values = list(params)
    if max_rows is not None:
        sql += " LIMIT ?"
        values.append(max_rows + 1)
    tuple_cursor = getattr(conn, "tuple_cursor", None)
    if tuple_cursor is not None:
        cursor = tuple_cursor(sql, values)
        tuple_rows = True
    else:
        cursor = conn.execute(sql, values)
        # Bulk positional rows do not need sqlite3.Row's per-row mapping wrapper.
        # Keep the connection's row_factory intact for every other public reader.
        cursor.row_factory = None
        tuple_rows = False
    loaded = 0
    try:
        while batch := cursor.fetchmany(16_384):
            loaded += len(batch)
            if max_rows is not None and loaded > max_rows:
                return None
            if tuple_rows:
                records = np.asarray(batch, dtype=object)
            else:
                records = np.asarray(
                    [_row_tuple(row, ("trade_date", "code", *fields)) for row in batch],
                    dtype=object,
                )
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
    version: tuple[Any, ...] | None = None
    panels: dict[str, pd.DataFrame] = field(default_factory=dict)
    present: pd.DataFrame | None = None
    panel_results: dict[
        tuple[Any, ...], tuple[dict[str, np.ndarray], pd.Index, pd.Index]
    ] = field(default_factory=dict)
    panel_result_cells: int = 0
    declined: bool = False
    evidence: Any = None
    evidence_declined: bool = False
    evidence_declined_request: Any = None
    max_evidence_bytes: int = 384_000_000
    source_summary: Any = None
    source_summary_declined: bool = False
    source_summary_scopes: tuple[tuple[str, str], ...] = ()
    source_summary_codes: tuple[str, ...] = ()
    source_summary_batch: Any = None
    loaded_codes: frozenset[str] | None = None
    declined_request: Any = None
    factor_rows: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
    factor_bytes: int = 0
    factor_declined: bool = False
    max_factor_bytes: int = 16_000_000
    factor_panels: dict[
        tuple[str, ...], tuple[pd.Index, pd.Index, np.ndarray]
    ] = field(default_factory=dict)
    factor_panel_cells: int = 0
    provenance_version: Any = None
    provenance_cache: dict[str, dict[Any, Any]] = field(default_factory=dict)
    provenance_bytes: int = 0
    max_provenance_bytes: int = 160_000_000

    def current_version(self) -> tuple[Any, ...]:
        if getattr(self.store, "_use_postgres", False):
            return ("postgres", str(self.store.market_revision()))
        return (
            "sqlite",
            self.conn.total_changes,
            self.conn.execute("PRAGMA data_version").fetchone()[0],
        )

    def stale(self, version: tuple[Any, ...]) -> bool:
        """PostgreSQL remains INTRANS after a SELECT and is still cacheable by revision."""
        if not getattr(self.store, "_use_postgres", False) and self.conn.in_transaction:
            return True
        return version != self.current_version()

    def clear(self) -> None:
        self.panels.clear()
        self.present = None
        self.panel_results.clear()
        self.panel_result_cells = 0
        self.declined = False
        self.evidence = None
        self.evidence_declined = False
        self.evidence_declined_request = None
        self.source_summary = None
        self.source_summary_declined = False
        self.source_summary_batch = None
        self.loaded_codes = None
        self.declined_request = None
        self.factor_rows.clear()
        self.factor_bytes = 0
        self.factor_declined = False
        self.factor_panels.clear()
        self.factor_panel_cells = 0
        self.clear_provenance()

    def clear_provenance(self) -> None:
        self.provenance_cache.clear()
        self.provenance_bytes = 0
        self.provenance_version = None

    def archive_version(self) -> str | None:
        """Fingerprint the exact Parquet inputs read by the archive queries."""
        import hashlib
        from src.market.application.provenance_archive import default_archive_root

        root = default_archive_root(Path(self.store.db_path))
        digest = hashlib.sha256()
        try:
            for table in ("receipts", "attempts"):
                directory = root / table
                if directory.is_dir():
                    for path in sorted(directory.glob("**/*.parquet")):
                        stat = path.stat()
                        fingerprint = (str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns,
                                       stat.st_ctime_ns, stat.st_ino)
                        digest.update(repr(fingerprint).encode("utf-8"))
        except OSError:
            return None
        return digest.hexdigest()

    def refresh_provenance(self) -> bool:
        if not self.refresh():
            return False
        snapshot = None
        if getattr(self.store, "_use_postgres", False):
            row = self.conn.execute(
                "SELECT pg_current_xact_id_if_assigned() AS own_xid, "
                "pg_current_snapshot()::text AS snapshot"
            ).fetchone()
            # A transaction with local writes may change the same receipt again
            # without changing its xid; its contents must never be cached.
            if row["own_xid"] is not None:
                self.clear_provenance()
                return False
            snapshot = str(row["snapshot"])
        archive = self.archive_version()
        if archive is None:
            self.clear_provenance()
            return False
        version = (self.version, snapshot, archive)
        if version != self.provenance_version:
            self.clear_provenance()
            self.provenance_version = version
        return True

    def refresh(self) -> bool:
        # Never reuse a transaction snapshot, including writes later rolled back.
        # PostgreSQL connections stay INTRANS after every read; their market revision
        # provides the same coherency boundary without disabling task-local reuse.
        if not getattr(self.store, "_use_postgres", False) and self.conn.in_transaction:
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
        if self.stale(version):
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
    max_evidence_bytes: int = 384_000_000,
    max_factor_bytes: int = 16_000_000,
    max_provenance_bytes: int = 160_000_000,
    source_summary_scopes: Sequence[tuple[str, str]] = (),
    source_summary_codes: Sequence[str] = (),
) -> Iterator[None]:
    """Reuse raw panels only inside this task, capped at max_cells numeric cells.

    Include warmup in start. Requests outside the bounds use the normal reader.
    No read transaction is held; concurrent database commits invalidate reuse.
    """
    state = _PanelWindow(store, store.conn, start, end, max_cells,
                         max_evidence_bytes=max_evidence_bytes, max_factor_bytes=max_factor_bytes,
                         max_provenance_bytes=max_provenance_bytes)
    state.source_summary_scopes = tuple(source_summary_scopes)
    state.source_summary_codes = tuple(source_summary_codes)
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
    if state.version is None or state.stale(state.version):
        state.clear()
        return None
    return result


def cached_adjusted_panels(
    store: Any, fields: Sequence[str], *, codes: Sequence[str] | None,
    start: str | None, end: str | None, adjust: str,
    min_bars: int, raw_price_fields: Sequence[str],
) -> dict[str, pd.DataFrame] | None:
    """Reuse a completed adjusted panel inside the same bounded read task."""
    state = _ACTIVE_WINDOW.get()
    if (adjust == "none" or state is None or state.store is not store
            or state.conn is not store.conn or not fields or not start or not end
            or start < state.start or end > state.end or start > end
            or not state.refresh()):
        return None
    axis = (
        tuple(fields),
        tuple(sorted(set(codes))) if codes else None,
        adjust,
        min_bars,
        tuple(raw_price_fields),
    )
    key = (
        tuple(fields),
        tuple(sorted(set(codes))) if codes else None,
        start,
        end,
        adjust,
        min_bars,
        tuple(raw_price_fields),
    )
    cached = state.panel_results.get(key)
    exact = cached is not None
    if cached is None and adjust == "hfq":
        # HFQ factors for an older row do not depend on later rows. A task that
        # primed a wider range can therefore serve each daily prefix without a
        # second PostgreSQL read. QFQ remains exact-range-only because its
        # anchor can move with the requested end date.
        for (cached_fields, cached_codes, cached_start, cached_end,
             cached_adjust, cached_min_bars, cached_raw_fields), candidate in reversed(
                 state.panel_results.items()
             ):
            if (
                (cached_fields, cached_codes, cached_adjust, cached_min_bars, cached_raw_fields)
                != axis or cached_start > start or cached_end < end
            ):
                continue
            cached = candidate
            break
    if cached is None:
        return None
    version = state.version
    arrays, index, columns = cached
    if not exact:
        row_positions = index.slice_indexer(start=start, end=end)
        if not isinstance(row_positions, slice):
            return None
        index = index[row_positions]
        arrays = {name: array[row_positions] for name, array in arrays.items()}
        if min_bars > 0 and arrays:
            reference = arrays["close"] if "close" in arrays else next(iter(arrays.values()))
            keep = np.isfinite(reference).sum(axis=0) >= min_bars
            columns = columns[keep]
            arrays = {name: array[:, keep] for name, array in arrays.items()}
    result = {
        name: pd.DataFrame(array.copy(), index=index, columns=columns, copy=False)
        for name, array in arrays.items()
    }
    if version is None or state.stale(version):
        state.clear()
        return None
    return result


def cache_adjusted_panels(
    store: Any, fields: Sequence[str], *, codes: Sequence[str] | None,
    start: str | None, end: str | None, adjust: str,
    min_bars: int, raw_price_fields: Sequence[str],
    panels: dict[str, pd.DataFrame],
) -> None:
    """Keep private arrays for repeated adjusted reads; callers retain their outputs."""
    state = _ACTIVE_WINDOW.get()
    if (adjust == "none" or state is None or state.store is not store
            or state.conn is not store.conn or not fields or not start or not end
            or start < state.start or end > state.end or start > end
            or not state.refresh()):
        return
    key = (
        tuple(fields),
        tuple(sorted(set(codes))) if codes else None,
        start,
        end,
        adjust,
        min_bars,
        tuple(raw_price_fields),
    )
    if key in state.panel_results:
        return
    cells = sum(frame.size for frame in panels.values())
    if cells <= 0 or state.panel_result_cells + cells > min(state.max_cells, 8_000_000):
        return
    version = state.version
    arrays = {name: frame.to_numpy(dtype=float, copy=True) for name, frame in panels.items()}
    if version is None or state.stale(version):
        state.clear()
        return
    first = next(iter(panels.values()))
    state.panel_results[key] = (arrays, first.index, first.columns)
    state.panel_result_cells += cells


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
            for row in cursor:
                code, day, factor = _row_tuple(
                    row, ("code", "trade_date", "hfq_factor"),
                )
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
    if state.stale(version):
        state.clear()
        return None
    result = [(code, day, factor) for code in requested
              for day, factor in state.factor_rows[code]]
    if state.stale(version):
        state.clear()
        return None
    return result


def cached_adjustment_factor_panel(
    store: Any,
    reference: pd.DataFrame,
    adjust: str,
) -> pd.DataFrame | None:
    """Derive an exact qfq/hfq ratio prefix from one aligned factor matrix."""
    state = _ACTIVE_WINDOW.get()
    if (
        state is None or state.store is not store or state.conn is not store.conn
        or reference.empty or adjust not in {"qfq", "hfq"} or not state.refresh()
    ):
        return None
    columns = tuple(str(code) for code in reference.columns)
    cached = state.factor_panels.get(columns)
    if cached is None:
        return None
    index, cached_columns, aligned = cached
    if not cached_columns.equals(reference.columns):
        return None
    start = str(reference.index[0])
    end = str(reference.index[-1])
    if start < str(index[0]) or end > str(index[-1]):
        return None
    slice_ = index.slice_indexer(start=start, end=end)
    if not isinstance(slice_, slice):
        return None
    ratio = np.array(aligned[slice_], copy=True)
    if adjust == "qfq" and ratio.size:
        latest = ratio[-1].copy()
        latest[latest == 0.0] = 1.0
        ratio /= latest
    version = state.version
    if version is None or state.stale(version):
        state.clear()
        return None
    return pd.DataFrame(
        ratio, index=reference.index, columns=reference.columns, copy=False,
    )


def cache_adjustment_factor_panel(
    store: Any,
    reference: pd.DataFrame,
    aligned: pd.DataFrame,
) -> None:
    """Cache the aligned HFQ ratio task-locally; qfq remains derived per anchor."""
    state = _ACTIVE_WINDOW.get()
    if (
        state is None or state.store is not store or state.conn is not store.conn
        or reference.empty or aligned.empty or not state.refresh()
    ):
        return
    columns = tuple(str(code) for code in reference.columns)
    existing = state.factor_panels.get(columns)
    if (
        existing is not None
        and str(existing[0][0]) <= str(reference.index[0])
        and str(existing[0][-1]) >= str(reference.index[-1])
    ):
        return
    cells = int(aligned.size)
    if cells <= 0 or cells > min(state.max_cells, 4_000_000):
        return
    array = aligned.to_numpy(dtype=float, copy=True)
    version = state.version
    if version is None or state.stale(version):
        state.clear()
        return
    if existing is not None:
        state.factor_panel_cells -= int(existing[2].size)
    state.factor_panels[columns] = (
        aligned.index.copy(), aligned.columns.copy(), array,
    )
    state.factor_panel_cells += cells
