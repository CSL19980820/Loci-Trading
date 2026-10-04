"""Bounded task-local result reuse, preserving actual input and audit boundaries."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from hashlib import blake2b
import json
import os
import time
from typing import Any, Iterator

import numpy as np
import pandas as pd

from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult


def execution_profile(engine: Any, params: dict | None = None) -> ExecutionProfile:
    method = getattr(engine, "execution_profile", None)
    if not callable(method):
        return ExecutionProfile()
    profile = method(params)
    return profile if isinstance(profile, ExecutionProfile) else ExecutionProfile()


def truncate_panels(panels: dict, cutoff: str) -> dict:
    """Date metadata follows the same cutoff as numerical inputs."""
    return {
        name: (value.loc[:cutoff] if isinstance(value, pd.DataFrame)
               else value[value <= cutoff] if name == "__signal_calendar__"
               and isinstance(value, pd.Index) else value)
        for name, value in panels.items()
    }


def project_result(result: SignalResult, dates: list, columns: Any = None) -> SignalResult:
    axes: list[pd.Index | None] = [None, None]

    def project(frame: pd.DataFrame) -> pd.DataFrame:
        rows = [day for day in dates if day in frame.index]
        out = frame.loc[rows]
        if columns is not None:
            out = out.loc[:, [col for col in columns if col in out.columns]]
        out = out.copy()
        # Equal immutable axes can be shared by every channel without sharing
        # mutable values or hiding a factor's incompatible axis contract.
        for axis, current in enumerate((out.index, out.columns)):
            shared = axes[axis]
            if shared is None:
                axes[axis] = current
            elif (shared.dtype == current.dtype and shared.names == current.names
                  and shared.equals(current)):
                if axis == 0:
                    out.index = shared
                else:
                    out.columns = shared
        return out
    return SignalResult(project(result.signals),
                        {name: project(frame) for name, frame in result.factors.items()},
                        project(result.watch_signals) if result.watch_signals is not None else None)


def _metadata_digest_input(value: Any) -> bytes:
    if isinstance(value, pd.Index):
        return repr((str(value.dtype), value.tolist())).encode()
    return json.dumps(value, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode()


def _digest_value(value: Any, digest: Any, *, contents: bytes | None = None,
                  columns: bytes | None = None) -> None:
    if isinstance(value, pd.DataFrame):
        digest.update(repr((list(value.index), value.index.names, str(value.index.dtype))).encode())
        digest.update(columns if columns is not None else _column_digest_input(value))
        if contents is None:
            array = value.to_numpy(copy=False)
            if array.dtype.kind not in "biufc":
                raise TypeError("non-numeric panel")
            data = memoryview(np.ascontiguousarray(array)).cast("B") if array.size else b""
            contents = blake2b(data, digest_size=24).digest()
        digest.update(contents)
    else:
        digest.update(_metadata_digest_input(value))


def _column_digest_input(frame: pd.DataFrame) -> bytes:
    return repr((list(frame.columns), frame.columns.names, str(frame.columns.dtype),
                 tuple(map(str, frame.dtypes)))).encode()


def _causal_input_keys(engine: Any, panels: dict, params: dict | None,
                       profile: ExecutionProfile, days: list[str]) -> dict[str, bytes | None]:
    """Hash each real input row once for all requested prefixes in this call.

    No fingerprint survives the call: in-place edits and changed axes/metadata
    must still be observed. Content digests compose with the same exact-input
    format used by real truncation audits.
    """
    if len(days) < 2:
        return {day: _input_key(engine, panels, params, profile, day, causal=True) for day in days}
    try:
        header = blake2b(digest_size=24)
        header.update(str(id(engine)).encode())
        _digest_value(params or {}, header)
        header.update(str(getattr(engine, "strategy_revision", "")).encode())
        digests = {day: header.copy() for day in days}
        required = engine.required_fields()
        for name in (*required, *profile.metadata_fields):
            if name not in panels and name not in required:
                for digest in digests.values():
                    digest.update((name + "\0ABSENT").encode())
                continue
            value = panels[name]
            for digest in digests.values():
                digest.update(name.encode())
            if isinstance(value, pd.DataFrame):
                if not value.index.is_monotonic_increasing or not value.index.is_unique:
                    raise TypeError("prefix hashing requires an ordered unique date axis")
                array = value.to_numpy(copy=False)
                if array.dtype.kind not in "biufc":
                    raise TypeError("non-numeric panel")
                cuts = []
                for day in days:
                    selection = value.index.slice_indexer(end=day)
                    if not isinstance(selection, slice) or selection.start not in (None, 0):
                        raise TypeError("non-prefix selection")
                    cuts.append((selection.stop if selection.stop is not None else len(value), day))
                columns = _column_digest_input(value)
                contents = blake2b(digest_size=24)
                previous = 0
                for stop, day in sorted(cuts):
                    if stop > previous:
                        block = np.ascontiguousarray(array[previous:stop])
                        contents.update(memoryview(block).cast("B"))
                        previous = stop
                    _digest_value(value.iloc[:stop], digests[day],
                                  contents=contents.digest(), columns=columns)
            elif name == "__signal_calendar__" and isinstance(value, pd.Index):
                for day, digest in digests.items():
                    _digest_value(value[value <= day], digest)
            else:
                # Identical metadata belongs to every date, but its bytes are
                # rebuilt each call so in-place edits still invalidate results.
                encoded = _metadata_digest_input(value)
                for digest in digests.values():
                    digest.update(encoded)
        for day, digest in digests.items():
            digest.update(str(day).encode())
        return {day: digest.digest() for day, digest in digests.items()}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {day: _input_key(engine, panels, params, profile, day, causal=True) for day in days}


def _input_digest(engine: Any, panels: dict, params: dict | None,
                  profile: ExecutionProfile, day: str, *, causal: bool) -> Any:
    digest = blake2b(digest_size=24)
    try:
        digest.update(str(id(engine)).encode())
        _digest_value(params or {}, digest)
        digest.update(str(getattr(engine, "strategy_revision", "")).encode())
        required = engine.required_fields()
        for name in (*required, *profile.metadata_fields):
            if name not in panels and name not in required:
                digest.update((name + "\0ABSENT").encode())
                continue
            value = panels[name]
            if causal and isinstance(value, pd.DataFrame):
                value = value.loc[:day]
                # Keep the original prefix even for finite mathematical windows:
                # rolling compensated sums can differ at a threshold after an
                # origin change. The causal key promises identical signal bits.
            elif causal and name == "__signal_calendar__" and isinstance(value, pd.Index):
                value = value[value <= day]
            digest.update(name.encode())
            _digest_value(value, digest)
        return digest
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _input_key(engine: Any, panels: dict, params: dict | None,
               profile: ExecutionProfile, day: str, *, causal: bool) -> bytes | None:
    digest = _input_digest(engine, panels, params, profile, day, causal=causal)
    if digest is None:
        return None
    digest.update(str(day).encode())
    return digest.digest()


@dataclass
class _ComputeScope:
    store: Any
    days: tuple[str, ...] = ()
    max_bytes: int = 64_000_000
    results: OrderedDict = field(default_factory=OrderedDict)
    result_refs: dict[int, tuple[int, int]] = field(default_factory=dict)
    bytes_used: int = 0
    version: Any = None
    primed: bool = False
    primed_layouts: set[Any] = field(default_factory=set)
    engines: dict[int, Any] = field(default_factory=dict)
    unknown_deadline: float = field(default_factory=lambda: time.monotonic() + 120.0)
    formula_deadline: float = field(default_factory=lambda: time.monotonic() + 180.0)
    prepared: dict[Any, Any] = field(default_factory=dict)
    source_audits: OrderedDict = field(default_factory=OrderedDict)
    source_audit_bytes: int = 0
    independent_budget: int | None = None

    def refresh(self) -> bool:
        conn = getattr(self.store, "conn", None)
        if conn is None:
            return True
        version = (conn.total_changes, conn.execute("PRAGMA data_version").fetchone()[0])
        if conn.in_transaction or self.version != version:
            self.results.clear()
            self.result_refs.clear()
            self.engines.clear()
            self.prepared.clear()
            self.bytes_used = 0
            self.primed = False
            self.primed_layouts.clear()
            self.version = version
        return not conn.in_transaction

    def put(self, key: Any, result: SignalResult) -> None:
        frames = [result.signals, *result.factors.values()]
        if result.watch_signals is not None:
            frames.append(result.watch_signals)
        # Numerical result rows are dense arrays. pandas.memory_usage still
        # iterates every column for each factor, even for one-row projections.
        axes: set[int] = set()

        def frame_bytes(frame):
            values = frame.to_numpy(copy=False)
            numeric = values.dtype.kind in "biufc"
            data = values.nbytes if numeric else frame.memory_usage(index=False, deep=True).sum()
            size = int(data)
            for axis in (frame.index, frame.columns):
                if id(axis) not in axes:
                    axes.add(id(axis))
                    size += int(axis.memory_usage(deep=True))
            return size
        size = 512 + sum(frame_bytes(frame) for frame in frames)
        if size > self.max_bytes:
            return
        if key in self.results:
            self._drop(key)
        identity = id(result)
        additional = 0 if identity in self.result_refs else size
        while self.results and self.bytes_used + additional > self.max_bytes:
            self._drop(next(iter(self.results)))
        count, tracked = self.result_refs.get(identity, (0, size))
        self.result_refs[identity] = (count + 1, tracked)
        if count == 0:
            self.bytes_used += tracked
        self.results[key] = (result, size)

    def _drop(self, key: Any) -> None:
        result, _size = self.results.pop(key)
        identity = id(result)
        count, size = self.result_refs[identity]
        if count == 1:
            del self.result_refs[identity]
            self.bytes_used -= size
        else:
            self.result_refs[identity] = (count - 1, size)


_SCOPE: ContextVar[_ComputeScope | None] = ContextVar("screen_compute_scope", default=None)


@contextmanager
def computation_scope(store: Any, days: list[str] | None = None,
                      *, max_bytes: int = 64_000_000) -> Iterator[None]:
    current = _SCOPE.get()
    if current is not None and current.store is store:
        yield
        return
    try:
        budget = float(os.environ.get("LOCI_SCREEN_UNKNOWN_RUNTIME_SECONDS", "120"))
        if not np.isfinite(budget) or budget <= 0:
            budget = 120.0
    except ValueError:
        budget = 120.0
    try:
        formula_budget = float(os.environ.get("LOCI_SCREEN_FORMULA_RUNTIME_SECONDS", "180"))
        if not np.isfinite(formula_budget) or formula_budget <= 0:
            formula_budget = 180.0
    except ValueError:
        formula_budget = 180.0
    token = _SCOPE.set(_ComputeScope(store, tuple(days or ()), max_bytes,
                                   unknown_deadline=time.monotonic() + budget,
                                   formula_deadline=time.monotonic() + formula_budget))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def remaining_unknown_seconds() -> float | None:
    scope = _SCOPE.get()
    return max(0.0, scope.unknown_deadline - time.monotonic()) if scope is not None else None


def remaining_formula_seconds() -> float | None:
    scope = _SCOPE.get()
    return max(0.0, scope.formula_deadline - time.monotonic()) if scope is not None else None


def range_compute_end(engine: Any = None, panels: dict | None = None,
                      params: dict | None = None) -> str | None:
    scope = _SCOPE.get()
    if scope is None or not scope.refresh() or len(scope.days) < 2:
        return None
    # The current input cannot certify later rolling origins or qfq anchors.
    # Engines may decline speculative priming without changing result reuse.
    if engine is not None and getattr(engine, "range_prime_enabled", True) is False:
        return None
    if engine is None or panels is None:
        if scope.primed:
            return None
        scope.primed = True
    else:
        reference = next((frame for frame in panels.values()
                          if isinstance(frame, pd.DataFrame) and not frame.empty), None)
        if reference is None:
            return None
        profile = execution_profile(engine, params)
        layout = (id(engine), repr(params), tuple(reference.columns),
                  str(reference.index[0]) if profile.origin == "sensitive" else None)
        if layout in scope.primed_layouts or len(scope.primed_layouts) >= 64:
            return None
        scope.primed_layouts.add(layout)
    return scope.days[-1]


def compute_result(engine: Any, panels: dict, params: dict | None = None,
                   *, dates: list[str] | None = None, audit: bool = False,
                   reuse: bool = True) -> SignalResult:
    """Hash inputs only when a caller can actually reuse this computation.

    One-shot daily execution can bypass caching; real audits and shared range
    calculations keep exact-input certification and caller-private results.
    """
    scope = _SCOPE.get() if reuse else None
    profile = execution_profile(engine, params)
    reference = next((value for value in panels.values()
                      if isinstance(value, pd.DataFrame) and not value.empty), None)
    requested = list(dict.fromkeys(dates or (list(reference.index[-3:])
                                            if reference is not None else [])))
    reusable = scope is not None and scope.refresh() and profile.pure
    if reusable:
        # Hold cached instances alive: Python may recycle id() after a short-lived
        # formula engine is released. Bound even this small task-local registry.
        reusable = id(engine) in scope.engines or len(scope.engines) < 64
        if reusable:
            scope.engines[id(engine)] = engine
    certified_version = scope.version if reusable else None
    exact_digest = None
    exact_ready = False

    def exact_key(day: str) -> bytes | None:
        nonlocal exact_digest, exact_ready
        # Every output row from one real invocation shares the same complete
        # input. Hash that input once, retaining the date-specific final key.
        if not exact_ready:
            exact_digest = _input_digest(engine, panels, params, profile, "", causal=False)
            exact_ready = True
        if exact_digest is None:
            return None
        digest = exact_digest.copy()
        digest.update(str(day).encode())
        return digest.digest()

    keys: list[Any] = []
    if reusable:
        causal_days = [day for day in requested if not audit and profile.causal
                       and (profile.causal_from is None or str(day) >= profile.causal_from)]
        causal_keys = _causal_input_keys(engine, panels, params, profile, causal_days)
        for day in requested:
            causal = (not audit and profile.causal
                      and (profile.causal_from is None or str(day) >= profile.causal_from))
            key = (causal_keys[day]
                   if causal else exact_key(day))
            keys.append((causal, key) if key is not None else None)
        if keys and all(key is not None and key in scope.results for key in keys):
            rows = [scope.results[key][0] for key in keys]
            combined = SignalResult(pd.concat([row.signals for row in rows]),
                                    {name: pd.concat([row.factors[name] for row in rows])
                                     for name in rows[0].factors},
                                    pd.concat([row.watch_signals for row in rows])
                                    if rows[0].watch_signals is not None else None)
            return project_result(combined, requested)
    projector = getattr(engine, "compute_projection", None) if profile.pure else None
    result = (projector(panels, params, requested) if callable(projector)
              else engine.compute(panels, params))
    if reusable and scope.refresh() and scope.version == certified_version:
        for day, key in zip(requested, keys):
            if key is not None and day in result.signals.index:
                row = project_result(result, [day])
                scope.put(key, row)
                # A real computation also establishes exact-input evidence.
                exact = exact_key(day)
                if exact is not None and key != (False, exact):
                    scope.put((False, exact), row)
        return project_result(result, requested)
    return project_result(result, requested)
