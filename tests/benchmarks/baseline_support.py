"""Deterministic inputs and measurement helpers for the performance baseline.

The benchmark intentionally uses synthetic OHLCV values.  The fixture is
generated from a fixed seed and its input digest is recorded in the artifact,
so a result can be compared without copying user market data into CI.
"""
from __future__ import annotations

import ctypes
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from typing import Any

import numpy as np
import pandas as pd

from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops import OpsStore

FIXTURE_SEED = 20260808
OBSERVED_AT = "2026-08-08T00:00:00+00:00"
MARKET_DAY_COUNT = 240
MARKET_CODE_COUNT = 256
TIMED_RUNS = 5


@dataclass
class BaselineWorkspace:
    """Isolated stores and immutable dimensions shared by benchmark cases."""

    data_root: Path
    market: MarketStore
    palace: PalaceStore
    ops: OpsStore
    job: dict[str, Any]
    codes: tuple[str, ...]
    dates: tuple[str, ...]
    input_sha256: str

    def close(self) -> None:
        """Close every store before the autouse test fixture removes its root."""
        self.market.close()
        self.palace.close()
        self.ops.close()


def build_workspace(data_root: Path) -> BaselineWorkspace:
    """Create a synthetic market, ledger, and ops workspace under ``data_root``."""
    data_root.mkdir(parents=True, exist_ok=True)
    dates = tuple(
        pd.bdate_range("2025-08-04", periods=MARKET_DAY_COUNT)
        .strftime("%Y-%m-%d")
        .tolist()
    )
    codes = tuple(f"{index:06d}" for index in range(1, MARKET_CODE_COUNT + 1))
    bars, input_sha256 = synthetic_bars(codes, dates)

    market = MarketStore(data_root / "market.db")
    market.upsert_instruments(
        {
            "code": code,
            "name": f"脱敏标的{code}",
            "market": "SZ",
            "board": "main",
            "industry": "synthetic",
            "instrument_type": "STOCK",
            "list_date": "2020-01-01",
            "status": "normal",
        }
        for code in codes
    )
    market.upsert_quote_bars(bars, source="synthetic-performance-baseline")

    palace = PalaceStore(data_root / "palace.db")
    ops = OpsStore(data_root / "ops.db")
    job_id = ops.create_job(name="baseline-lock", kind="sync", config={})
    job = ops.get_job(job_id)
    if job is None:
        market.close()
        palace.close()
        ops.close()
        raise RuntimeError("无法创建 benchmark job")

    return BaselineWorkspace(
        data_root=data_root,
        market=market,
        palace=palace,
        ops=ops,
        job=job,
        codes=codes,
        dates=dates,
        input_sha256=input_sha256,
    )


def synthetic_bars(
    codes: Iterable[str], dates: Iterable[str]
) -> tuple[list[dict[str, Any]], str]:
    """Return deterministic, non-user OHLCV rows and a digest of their inputs."""
    code_values = tuple(str(code) for code in codes)
    date_values = tuple(str(day) for day in dates)
    day_grid = np.arange(len(date_values), dtype=float)[None, :]
    code_grid = np.arange(len(code_values), dtype=float)[:, None]

    base = 8.0 + code_grid * 0.017
    trend = day_grid * 0.018 + 0.35 * np.sin((day_grid + code_grid * 0.13) / 11.0)
    close = base + trend + 0.08 * np.sin((day_grid + code_grid) / 5.0)
    opening = close * (1.0 + 0.001 * np.cos((day_grid + code_grid) / 7.0))
    spread = 0.012 + 0.003 * np.mod(day_grid + code_grid, 4.0)
    high = np.maximum(opening, close) * (1.0 + spread)
    low = np.minimum(opening, close) * (1.0 - spread)
    volume = 100_000.0 + np.mod(day_grid * 1_700.0 + code_grid * 91.0, 40_000.0)
    amount = close * volume
    turnover = 0.02 + np.mod(day_grid + code_grid, 17.0) / 1_000.0

    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {"seed": FIXTURE_SEED, "codes": code_values, "dates": date_values},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for name, values in (
        ("open", opening),
        ("high", high),
        ("low", low),
        ("close", close),
        ("volume", volume),
        ("amount", amount),
        ("turnover", turnover),
    ):
        digest.update(name.encode("ascii"))
        digest.update(np.ascontiguousarray(values, dtype="<f8").tobytes())

    rows: list[dict[str, Any]] = []
    for code_index, code in enumerate(code_values):
        for day_index, trade_date in enumerate(date_values):
            rows.append(
                {
                    "code": code,
                    "date": trade_date,
                    "open": float(opening[code_index, day_index]),
                    "high": float(high[code_index, day_index]),
                    "low": float(low[code_index, day_index]),
                    "close": float(close[code_index, day_index]),
                    "volume": float(volume[code_index, day_index]),
                    "amount": float(amount[code_index, day_index]),
                    "turnover": float(turnover[code_index, day_index]),
                }
            )
    return rows, digest.hexdigest()


def seed_candidate_pool(store: PalaceStore, *, size: int, occurred_on: str) -> None:
    """Insert one fixed-size candidate pool into the isolated ledger."""
    candidates = [
        {
            "code": f"{index:06d}",
            "name": f"脱敏候选{index:06d}",
            "decision": ("精选", "观察", "落选")[index % 3],
            "reason": "benchmark synthetic candidate",
            "occurred_on": occurred_on,
            "pool_id": f"baseline-{size}",
            "score": float(100 - index % 100),
            "timing": "next_open",
            "rule_version": "baseline",
            "strategy_slug": "baseline",
            "strategy_revision": "baseline-v1",
            "effective_params": {"seed": FIXTURE_SEED},
            "evidence": {"synthetic": True},
            "tier": "core",
            "source": "benchmark",
        }
        for index in range(1, size + 1)
    ]
    store.record_candidates(candidates)


def benchmark_panels(
    workspace: BaselineWorkspace, *, codes: Iterable[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Load a normal market panel through the production read path."""
    selected = tuple(codes or workspace.codes)
    return workspace.market.load_panel(
        fields=("open", "high", "low", "close", "volume", "turnover"),
        codes=selected,
        start=workspace.dates[0],
        end=workspace.dates[-1],
        adjust="qfq",
    )


def synthetic_signals(index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """Build stable, sufficiently dense signals without consulting future data."""
    rows, cols = np.indices((len(index), len(columns)))
    values = ((rows * 7 + cols * 11 + FIXTURE_SEED) % 29) == 0
    values[-8:, :] = False
    return pd.DataFrame(values, index=index, columns=columns)


def measure_case(
    name: str,
    operation: Callable[[], dict[str, Any]],
    *,
    repeats: int = TIMED_RUNS,
) -> dict[str, Any]:
    """Measure a warmed operation and return a JSON-safe case projection."""
    warmup_error: dict[str, str] | None = None
    try:
        operation()
    except Exception as exc:  # pragma: no cover - recorded in the artifact
        warmup_error = _error_payload(exc)

    durations: list[float] = []
    rss_deltas: list[int] = []
    errors: list[dict[str, str]] = []
    last_result: dict[str, Any] | None = None
    for _ in range(max(1, int(repeats))):
        before_rss = peak_rss_bytes()
        started = time.perf_counter()
        try:
            last_result = operation()
        except Exception as exc:  # pragma: no cover - recorded in the artifact
            errors.append(_error_payload(exc))
        finally:
            durations.append((time.perf_counter() - started) * 1000.0)
            after_rss = peak_rss_bytes()
            rss_deltas.append(max(0, after_rss - before_rss))

    successful = len(durations) - len(errors)
    return {
        "name": name,
        "runs": len(durations),
        "warmup_runs": 1,
        "warmup_error": warmup_error,
        "durations_ms": [round(value, 3) for value in durations],
        "p50_ms": round(_quantile(durations, 0.50), 3) if durations else None,
        "p95_ms": round(_quantile(durations, 0.95), 3) if durations else None,
        "peak_rss_bytes": peak_rss_bytes(),
        "rss_delta_max_bytes": max(rss_deltas, default=0),
        "successful_runs": successful,
        "error_count": len(errors),
        "error_rate": round(len(errors) / len(durations), 4) if durations else 1.0,
        "errors": errors,
        "result": _json_safe(last_result),
        "result_sha256": _json_digest(last_result) if last_result is not None else None,
    }


def artifact_payload(
    workspace: BaselineWorkspace, measurements: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build the stable top-level schema written by the benchmark test."""
    return {
        "schema_version": "loci-performance-baseline-v1",
        "fixture": {
            "seed": FIXTURE_SEED,
            "input_sha256": workspace.input_sha256,
            "market_days": len(workspace.dates),
            "market_codes": len(workspace.codes),
            "market_rows": len(workspace.dates) * len(workspace.codes),
            "candidate_pool_sizes": [1000, 5000],
            "synthetic": True,
            "observed_at": OBSERVED_AT,
        },
        "environment": environment_payload(),
        "measurements": measurements,
        "summary": {
            "case_count": len(measurements),
            "errors": sum(int(item["error_count"]) for item in measurements.values()),
            "process_peak_rss_bytes": peak_rss_bytes(),
            "lock_wait_cases": [
                name
                for name in measurements
                if "lock_wait" in name
            ],
        },
    }


def environment_payload() -> dict[str, str]:
    """Return comparison metadata without local paths or user data."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def peak_rss_bytes() -> int:
    """Read the process high-water RSS on Windows, Linux, and macOS."""
    if os.name == "nt":
        class MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(MemoryCounters)
        try:
            process = ctypes.windll.kernel32.GetCurrentProcess()
            getter = ctypes.windll.psapi.GetProcessMemoryInfo
            getter.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(MemoryCounters),
                wintypes.DWORD,
            ]
            getter.restype = wintypes.BOOL
            if getter(process, ctypes.byref(counters), counters.cb):
                return int(counters.peak_working_set_size)
        except (AttributeError, OSError):
            pass

    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="ascii", errors="ignore").splitlines():
            if line.startswith("VmHWM:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if platform.system() == "Darwin" else value * 1024
    except (AttributeError, ImportError, OSError):
        return 0


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _error_payload(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:500]}


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


__all__ = [
    "BaselineWorkspace",
    "FIXTURE_SEED",
    "MARKET_CODE_COUNT",
    "OBSERVED_AT",
    "TIMED_RUNS",
    "artifact_payload",
    "benchmark_panels",
    "build_workspace",
    "measure_case",
    "peak_rss_bytes",
    "seed_candidate_pool",
    "synthetic_bars",
    "synthetic_signals",
]
