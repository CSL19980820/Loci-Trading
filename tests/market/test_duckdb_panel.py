"""DuckDB load_panel 旁路：开关开时与 pandas 路径结果一致；关时不影响现网。"""
from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.market.infrastructure.duckdb_panel import (
    duckdb_panel_enabled,
    read_quotes_flat_duckdb,
)
from src.market.infrastructure.store import MarketStore

try:
    import duckdb  # noqa: F401

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False


def _quotes(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.linspace(base, base + n * 0.1, n),
            "high": np.linspace(base + 0.5, base + 0.5 + n * 0.1, n),
            "low": np.linspace(base - 0.5, base - 0.5 + n * 0.1, n),
            "close": np.linspace(base + 0.2, base + 0.2 + n * 0.1, n),
            "volume": np.full(n, 1_000_000.0),
            "amount": np.full(n, 10_000_000.0),
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class DuckdbPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
        self.store.upsert_instruments(
            [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "market": "SH",
                    "board": "main",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
                {
                    "code": "000001",
                    "name": "平安银行",
                    "market": "SZ",
                    "board": "main",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
            ]
        )
        self.store.upsert_quotes("600519", _quotes(self.dates, base=100.0))
        self.store.upsert_quotes("000001", _quotes(self.dates, base=10.0))
        self._prev = os.environ.get("LOCI_MARKET_DUCKDB")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()
        if self._prev is None:
            os.environ.pop("LOCI_MARKET_DUCKDB", None)
        else:
            os.environ["LOCI_MARKET_DUCKDB"] = self._prev

    def test_flag_off_by_default(self) -> None:
        os.environ.pop("LOCI_MARKET_DUCKDB", None)
        self.assertFalse(duckdb_panel_enabled())

    def test_duckdb_disabled_still_loads(self) -> None:
        os.environ["LOCI_MARKET_DUCKDB"] = "0"
        panels = self.store.load_panel(fields=("close",), start=self.dates[0], adjust="none")
        self.assertIn("600519", panels["close"].columns)
        self.assertIn("000001", panels["close"].columns)

    @unittest.skipUnless(_HAS_DUCKDB, "duckdb 未安装，跳过旁路对照")
    def test_duckdb_panel_matches_pandas_path(self) -> None:
        """同一夹具：经典 load_panel vs LOCI_MARKET_DUCKDB=1，行数/关键价一致。"""
        os.environ.pop("LOCI_MARKET_DUCKDB", None)
        baseline = self.store.load_panel(
            fields=("open", "high", "low", "close", "volume"), start=self.dates[0],
            adjust="none",
        )

        # 确认旁路可读（否则对照无意义，等于 pandas 自比）
        probe = read_quotes_flat_duckdb(
            self.store.conn,
            columns_sql="trade_date, code, open, high, low, close, volume",
            where_sql="",
            params=[],
        )
        self.assertIsNotNone(probe, "DuckDB 已装但旁路读失败，无法对照")
        assert probe is not None
        self.assertEqual(len(probe), len(self.dates) * 2)

        os.environ["LOCI_MARKET_DUCKDB"] = "1"
        self.assertTrue(duckdb_panel_enabled())
        via_duck = self.store.load_panel(
            fields=("open", "high", "low", "close", "volume"), start=self.dates[0],
            adjust="none",
        )

        self.assertEqual(list(baseline.keys()), list(via_duck.keys()))
        for field in baseline:
            left = baseline[field].sort_index(axis=1)
            right = via_duck[field].sort_index(axis=1)
            self.assertEqual(left.shape, right.shape, msg=field)
            self.assertEqual(list(left.index), list(right.index), msg=field)
            self.assertEqual(list(left.columns), list(right.columns), msg=field)
            # 关键价/量：允许浮点容差
            np.testing.assert_allclose(
                left.to_numpy(dtype=float),
                right.to_numpy(dtype=float),
                rtol=1e-9,
                atol=1e-9,
                err_msg=field,
            )
            if field in {"open", "high", "low", "close"}:
                self.assertAlmostEqual(
                    float(left.sum().sum()),
                    float(right.sum().sum()),
                    places=6,
                    msg=f"{field} 合计",
                )


    @unittest.skipUnless(_HAS_DUCKDB, "duckdb 未安装，跳过旁路对照")
    def test_duckdb_panel_matches_pandas_on_sparse_nulls(self) -> None:
        """缺行（停牌）与 NULL 换手才是旁路最容易错位的地方。

        稠密夹具对不出问题：行数差 / NaN 落错格子会让选股静默少票或把
        缺失当成 0，必须逐格比对。
        """
        sparse = _quotes([self.dates[0], self.dates[2]], base=7.0).assign(turnover=None)
        self.store.upsert_quotes("000002", sparse)

        os.environ.pop("LOCI_MARKET_DUCKDB", None)
        baseline = self.store.load_panel(
            fields=("close", "turnover"), start=self.dates[0], adjust="none"
        )
        os.environ["LOCI_MARKET_DUCKDB"] = "1"
        via_duck = self.store.load_panel(
            fields=("close", "turnover"), start=self.dates[0], adjust="none"
        )

        for field in ("close", "turnover"):
            left = baseline[field].sort_index(axis=1)
            right = via_duck[field].sort_index(axis=1)
            self.assertEqual(left.shape, right.shape, msg=field)
            self.assertEqual(list(left.columns), list(right.columns), msg=field)
            # NaN 必须落在同一格：np.allclose 的 equal_nan 只比值不比位置
            np.testing.assert_array_equal(
                left.isna().to_numpy(), right.isna().to_numpy(), err_msg=f"{field} NaN 位置"
            )
            np.testing.assert_allclose(
                left.to_numpy(dtype=float),
                right.to_numpy(dtype=float),
                rtol=1e-9,
                atol=1e-9,
                equal_nan=True,
                err_msg=field,
            )


if __name__ == "__main__":
    unittest.main()
