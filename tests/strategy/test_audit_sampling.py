"""动态前视探测的面板列抽样。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.application.audit_sampling import (
    DEFAULT_AUDIT_PANEL_SAMPLE_SIZE,
    FULL_UNIVERSE_THRESHOLD,
    MAX_AUDIT_PANEL_SAMPLE_SIZE,
    iter_guard_panel_shards,
    prepare_guard_panels,
    resolve_audit_panel_sample_size,
    sample_panel_columns,
)


def test_small_universe_uses_all_columns() -> None:
    cols = [f"c{i:03d}" for i in range(FULL_UNIVERSE_THRESHOLD)]
    assert sample_panel_columns(cols) == cols


def test_large_universe_includes_boundary_anchors() -> None:
    cols = [f"c{i:04d}" for i in range(800)]
    picked = sample_panel_columns(cols, sample_size=50)
    assert cols[0] in picked
    assert cols[-1] in picked
    assert cols[len(cols) // 2] in picked
    assert cols[len(cols) // 4] in picked
    assert cols[(3 * len(cols)) // 4] in picked


def test_large_universe_respects_sample_size() -> None:
    cols = [f"c{i:05d}" for i in range(3000)]
    picked = sample_panel_columns(cols, sample_size=120)
    assert len(picked) == 120


def test_default_sample_size_is_200() -> None:
    cols = [f"c{i:05d}" for i in range(5000)]
    picked = sample_panel_columns(cols)
    assert len(picked) == DEFAULT_AUDIT_PANEL_SAMPLE_SIZE


def test_tail_column_always_included_even_if_hash_prefix_would_skip() -> None:
    cols = [f"c{i:04d}" for i in range(500)]
    old_prefix = sorted(
        cols,
        key=lambda c: __import__("hashlib").md5(str(c).encode("utf-8")).hexdigest(),
    )[:40]
    assert cols[-1] not in old_prefix

    picked = sample_panel_columns(cols, sample_size=40)
    assert cols[-1] in picked


def test_resolve_audit_panel_sample_size_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCI_AUDIT_PANEL_SAMPLE_SIZE", "350")
    assert resolve_audit_panel_sample_size() == 350


def test_resolve_audit_panel_sample_size_caps_at_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCI_AUDIT_PANEL_SAMPLE_SIZE", "9999")
    assert resolve_audit_panel_sample_size() == MAX_AUDIT_PANEL_SAMPLE_SIZE


def test_resolve_audit_panel_sample_size_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCI_AUDIT_PANEL_SAMPLE_SIZE", "not-a-number")
    assert resolve_audit_panel_sample_size() == DEFAULT_AUDIT_PANEL_SAMPLE_SIZE


def test_prepare_guard_panels_subsets_dataframes() -> None:
    cols = [f"c{i:04d}" for i in range(250)]
    index = pd.date_range("2024-01-01", periods=5, freq="B")
    panels = {
        "close": pd.DataFrame({col: range(5) for col in cols}, index=index),
        "open": pd.DataFrame({col: range(5) for col in cols}, index=index),
        "__instrument_names__": {"c0000": "演示"},
    }
    guard = prepare_guard_panels(panels, sample_size=30)
    assert guard["close"].shape[1] == 30
    assert guard["open"].shape[1] == 30
    assert guard["__instrument_names__"] == {"c0000": "演示"}


def test_prepare_guard_panels_keeps_small_universe() -> None:
    cols = [f"c{i:03d}" for i in range(50)]
    index = pd.date_range("2024-01-01", periods=3, freq="B")
    panels = {"close": pd.DataFrame({col: range(3) for col in cols}, index=index)}
    guard = prepare_guard_panels(panels)
    assert guard["close"].shape[1] == 50


def test_iter_guard_panel_shards_covers_all_columns() -> None:
    cols = [f"c{i:04d}" for i in range(450)]
    index = pd.date_range("2024-01-01", periods=3, freq="B")
    panels = {"close": pd.DataFrame({col: range(3) for col in cols}, index=index)}
    seen: set[str] = set()
    shard_count = 0
    for shard in iter_guard_panel_shards(panels, shard_size=200):
        shard_count += 1
        seen.update(shard["close"].columns)
    assert seen == set(cols)
    assert shard_count == 3


def test_iter_guard_panel_shards_single_shard_for_small_universe() -> None:
    cols = [f"c{i:03d}" for i in range(FULL_UNIVERSE_THRESHOLD)]
    panels = {"close": pd.DataFrame({col: 1 for col in cols}, index=[0])}
    shards = list(iter_guard_panel_shards(panels, shard_size=50))
    assert len(shards) == 1
    assert list(shards[0]["close"].columns) == cols
