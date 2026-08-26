"""证券目录快照应淘汰已不在交易所上市列表中的旧标的。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.sync import sync_instruments


class _CompleteSnapshotSource:
    name = "complete_snapshot"

    def fetch_instruments(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            [
                {"code": "600611", "name": "大众交通"},
                {"code": "000001", "name": "平安银行"},
                {"code": "920001", "name": "北交样本"},
            ]
        )
        frame.attrs["complete_markets"] = ("sh", "sz", "bj")
        return frame


class _PartiallyTruncatedSnapshotSource:
    name = "partial_snapshot"

    def fetch_instruments(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            [
                {"code": "600001", "name": "沪市样本"},
                {"code": "920001", "name": "北交样本"},
            ]
        )
        frame.attrs["complete_markets"] = ("sh", "bj")
        return frame


class InstrumentLifecycleTests(unittest.TestCase):
    def test_complete_exchange_snapshot_retires_missing_normal_stock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketStore(Path(tmp) / "market.db")
            try:
                store.upsert_instruments(
                    [
                        {"code": "600611", "name": "大众交通", "instrument_type": "STOCK"},
                        {"code": "000001", "name": "平安银行", "instrument_type": "STOCK"},
                        {"code": "920001", "name": "北交样本", "instrument_type": "STOCK"},
                        {"code": "920305", "name": "云创退", "instrument_type": "STOCK"},
                    ]
                )

                sync_instruments(store, sources=[_CompleteSnapshotSource()])

                rows = {
                    row["code"]: row
                    for row in store.list_instruments(instrument_type="STOCK", status="")
                }
                self.assertEqual(rows["920305"]["status"], "delisted")
                self.assertEqual(rows["600611"]["status"], "normal")
                self.assertEqual(store.instrument_snapshot_date(), date.today().isoformat())
            finally:
                store.close()

    def test_truncated_exchange_is_preserved_while_valid_exchange_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketStore(Path(tmp) / "market.db")
            try:
                store.upsert_instruments(
                    [
                        *[
                            {
                                "code": f"60{index:04d}",
                                "name": f"沪市{index}",
                                "instrument_type": "STOCK",
                            }
                            for index in range(20)
                        ],
                        {"code": "920001", "name": "北交样本", "instrument_type": "STOCK"},
                        {"code": "920305", "name": "云创退", "instrument_type": "STOCK"},
                    ]
                )

                sync_instruments(store, sources=[_PartiallyTruncatedSnapshotSource()])

                rows = {
                    row["code"]: row
                    for row in store.list_instruments(instrument_type="STOCK", status="")
                }
                self.assertEqual(rows["600002"]["status"], "normal")
                self.assertEqual(rows["920305"]["status"], "delisted")
                self.assertEqual(store.instrument_snapshot_date(), date.today().isoformat())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
