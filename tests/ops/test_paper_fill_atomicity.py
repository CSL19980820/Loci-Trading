"""纸面成交流水与仓位快照必须同事务落库。

两者互为对方的校验：出现「有成交、仓位没动」的半条记录后，无法判断哪份才是
当前真仓，后续加减仓都会在错的基数上算。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile
import unittest

from src.ops.application.paper_exec import PaperOrder, execute_orders
from src.ops.infrastructure.store import OpsStore


class _PositionWriteFails(OpsStore):
    """仓位快照写入必然失败，用来观察成交流水会不会留下孤儿行。"""

    def _write_paper_position(self, cursor: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")


class PaperFillAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "ops.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fill_and_position_land_together(self) -> None:
        with OpsStore(self.db) as store:
            store.ensure_paper_cabin("demo", max_layers=4.0)
            result = execute_orders(
                store,
                slug="demo",
                orders=[PaperOrder(code="600519", action="open", layers=1.0, reason="开仓")],
                quotes={"600519": {"price": 100.0, "name": "茅台"}},
                source="test",
            )
            self.assertEqual(len(result.fills), 1)
            cabin_id = str(store.get_paper_cabin("demo")["id"])
            self.assertEqual(len(store.list_paper_fills(cabin_id)), 1)
            self.assertEqual(store.list_paper_positions(cabin_id)[0]["layers"], 1.0)

    def test_failed_position_write_rolls_the_fill_back(self) -> None:
        with OpsStore(self.db) as store:
            store.ensure_paper_cabin("demo", max_layers=4.0)
            cabin_id = str(store.get_paper_cabin("demo")["id"])

        with _PositionWriteFails(self.db) as broken:
            with self.assertRaises(RuntimeError):
                execute_orders(
                    broken,
                    slug="demo",
                    orders=[
                        PaperOrder(code="600519", action="open", layers=1.0, reason="开仓")
                    ],
                    quotes={"600519": {"price": 100.0, "name": "茅台"}},
                    source="test",
                )

        with OpsStore(self.db) as store:
            self.assertEqual(store.list_paper_fills(cabin_id), [])
            self.assertEqual(store.list_paper_positions(cabin_id), [])


if __name__ == "__main__":
    unittest.main()
