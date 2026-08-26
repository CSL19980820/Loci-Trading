from __future__ import annotations

from pathlib import Path
import pytest
from pandas.testing import assert_frame_equal

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.polars_panel import (
    polars_available,
    read_quotes_flat_polars,
)


def _bars() -> list[dict[str, object]]:
    return [
        {
            "code": code,
            "date": day,
            "open": float(index + 10),
            "high": float(index + 11),
            "low": float(index + 9),
            "close": float(index + 10.5),
            "volume": float(index * 100),
            "amount": float(index * 1000),
            "turnover": 0.01,
        }
        for index, (code, day) in enumerate(
            [
                ("600519", "2026-08-05"),
                ("000001", "2026-08-05"),
                ("600519", "2026-08-06"),
                ("000001", "2026-08-06"),
            ]
        )
    ]


@pytest.mark.skipif(not polars_available(), reason="可选依赖 polars 未安装")
def test_polars_panel_matches_pandas_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "market.db"
    palace_path = tmp_path / "palace.db"
    store = MarketStore(db_path)
    try:
        store.upsert_quote_bars(_bars(), source="test")
        columns = "trade_date, code, open, high, low, close, volume, amount, turnover"
        flat = read_quotes_flat_polars(
            store.conn,
            columns_sql=columns,
            where_sql=" AND code IN (?, ?)",
            params=["600519", "000001"],
        )
        assert flat is not None
        assert not flat.empty

        monkeypatch.setenv("LOCI_MARKET_POLARS", "1")
        monkeypatch.delenv("LOCI_MARKET_DUCKDB", raising=False)
        polars_panels = store.load_panel(
            fields=("open", "close", "volume"),
            codes=("600519", "000001"),
            adjust="none",
        )
        monkeypatch.delenv("LOCI_MARKET_POLARS", raising=False)
        pandas_panels = store.load_panel(
            fields=("open", "close", "volume"),
            codes=("600519", "000001"),
            adjust="none",
        )
        assert polars_panels.keys() == pandas_panels.keys()
        for field in polars_panels:
            assert_frame_equal(polars_panels[field], pandas_panels[field], check_dtype=False)
    finally:
        store.close()

    assert db_path.is_file()
    assert not palace_path.exists()
