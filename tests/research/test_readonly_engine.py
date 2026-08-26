from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.research.application.readonly_engine import readonly_frame


def test_research_readonly_engine_defaults_to_same_pandas_frame() -> None:
    frame = pd.DataFrame({"close": [10.0, 11.0]}, index=["2026-08-05", "2026-08-06"])
    assert readonly_frame(frame) is frame


def test_research_polars_engine_is_optional_and_equivalent() -> None:
    pytest.importorskip("polars")
    frame = pd.DataFrame(
        {"close": [10.0, 11.0], "volume": [100.0, 120.0]},
        index=pd.Index(["2026-08-05", "2026-08-06"], name="trade_date"),
    )
    result = readonly_frame(frame, engine="polars")
    assert_frame_equal(result, frame, check_dtype=False)
