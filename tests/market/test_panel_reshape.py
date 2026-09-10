"""Panel refactors preserve the calendar, missing values and adjustment basis."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.market.infrastructure.store_panel import MarketPanelMixin, _consolidate


class _PanelStore(MarketPanelMixin):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


@pytest.mark.parametrize("fields", [("close",), ("volume", "close", "open", "close")])
@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
@pytest.mark.parametrize("min_bars", [0, 2, 10])
def test_sparse_unsorted_panel_preserves_existing_contract(
    fields: tuple[str, ...], adjust: str, min_bars: int
) -> None:
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE quotes_daily (trade_date TEXT, code TEXT, open REAL, close REAL, volume REAL);
            CREATE TABLE adjust_factors (trade_date TEXT, code TEXT, hfq_factor REAL);
            INSERT INTO quotes_daily VALUES
                ('2026-01-05','600519',10,11,100),
                ('2026-01-02','000001',20,21,200),
                ('2026-01-02','600519',8,NULL,0),
                ('2026-01-06','000001',NULL,22,210);
            INSERT INTO adjust_factors VALUES
                ('2026-01-01','600519',1),('2026-01-05','600519',2),
                ('2026-01-01','000001',1);
        ''')
        store = _PanelStore(conn)
        flat = pd.read_sql_query("SELECT * FROM quotes_daily", conn)
        expected = {
            f: flat.pivot(index="trade_date", columns="code", values=f).sort_index()
            for f in dict.fromkeys(fields)
        }
        if min_bars:
            keep = expected["close"].notna().sum() >= min_bars
            expected = {f: panel.loc[:, keep] for f, panel in expected.items()}
        if adjust != "none":
            ratio = store._factor_panel(expected["close"], adjust)
            expected = {f: panel * ratio if f in {"open", "close"} else panel
                        for f, panel in expected.items()}
        actual = store.load_panel(fields=fields, start="2026-01-01", adjust=adjust, min_bars=min_bars)
        assert list(actual) == list(expected)
        for f, panel in actual.items():
            assert_frame_equal(panel, _consolidate(expected[f]))


def test_polars_column_conversion_preserves_null_numeric_and_text_values() -> None:
    pl = pytest.importorskip("polars")
    from src.market.infrastructure.polars_panel import _to_pandas

    frame = pl.DataFrame({"code": ["000001", None], "close": [10.0, np.nan], "volume": [1, None]})
    assert_frame_equal(_to_pandas(frame), pd.DataFrame(frame.to_dicts()))
