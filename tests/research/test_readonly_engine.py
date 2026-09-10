from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.research.application.readonly_engine import readonly_frame


def test_research_readonly_engine_defaults_to_same_pandas_frame() -> None:
    frame = pd.DataFrame({"close": [10.0, 11.0]}, index=["2026-08-05", "2026-08-06"])
    assert readonly_frame(frame) is frame


def test_legacy_engine_does_not_copy_or_coerce_nullable_input(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.research.application.readonly_engine import polars_research_enabled

    monkeypatch.setenv("LOCI_RESEARCH_POLARS", "1")
    frame = pd.DataFrame(
        {"close": pd.array([10.0, None], dtype="Float64"), "volume": pd.array([100, None], dtype="Int64")},
        index=pd.Index(["2026-08-05", "2026-08-06"], name="trade_date"),
    )
    result = readonly_frame(frame, engine="polars")
    assert result is frame
    assert not polars_research_enabled()
    assert_frame_equal(result, frame)
