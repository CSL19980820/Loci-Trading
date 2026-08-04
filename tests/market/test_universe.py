"""股票池归类与默认/高级筛选单测。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.market.infrastructure.store import MarketStore
from src.market.domain.universe import (
    UniverseSpec,
    classify_board,
    expand_spec,
    is_st_name,
    list_presets,
    resolve_universe,
)


class ClassifyBoardTests(unittest.TestCase):
    def test_buckets(self) -> None:
        self.assertEqual(classify_board("600000"), "main")
        self.assertEqual(classify_board("000001"), "main")
        self.assertEqual(classify_board("300750"), "chi_next")
        self.assertEqual(classify_board("301000"), "chi_next")
        self.assertEqual(classify_board("688981"), "star")
        self.assertEqual(classify_board("689009"), "star")
        self.assertEqual(classify_board("430047"), "bse")
        self.assertEqual(classify_board("830799"), "bse")
        self.assertEqual(classify_board("920001"), "bse")

    def test_st_name(self) -> None:
        self.assertTrue(is_st_name("*ST宁科"))
        self.assertTrue(is_st_name("ST 假名"))
        self.assertFalse(is_st_name("宁德时代"))


class ExpandSpecTests(unittest.TestCase):
    def test_default_excludes_st_and_bse(self) -> None:
        final = expand_spec(UniverseSpec())
        self.assertEqual(final["boards"], ["main", "chi_next", "star"])
        self.assertTrue(final["exclude_st"])
        self.assertNotIn("bse", final["boards"])

    def test_bse_can_be_selected_explicitly(self) -> None:
        final = expand_spec(UniverseSpec(preset="custom", boards=("main", "bse")))
        self.assertEqual(final["boards"], ["main", "bse"])

    def test_all_a_share_preset_includes_bse(self) -> None:
        preset = next(item for item in list_presets() if item["id"] == "all_a_share")
        self.assertIn("bse", preset["boards"])


class ResolveUniverseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "m.db")
        self.store.upsert_instruments(
            [
                {
                    "code": "600000",
                    "name": "浦发银行",
                    "market": "sh",
                    "board": "上交所",
                    "industry": "银行",
                    "instrument_type": "STOCK",
                    "list_date": "1999-11-10",
                    "status": "normal",
                },
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "market": "sz",
                    "board": "创业板",
                    "industry": "电池",
                    "instrument_type": "STOCK",
                    "list_date": "2018-06-15",
                    "status": "normal",
                },
                {
                    "code": "688981",
                    "name": "中芯国际",
                    "market": "sh",
                    "board": "上交所",
                    "industry": "半导体",
                    "instrument_type": "STOCK",
                    "list_date": "2020-07-16",
                    "status": "normal",
                },
                {
                    "code": "600001",
                    "name": "*ST示例",
                    "market": "sh",
                    "board": "上交所",
                    "industry": "银行",
                    "instrument_type": "STOCK",
                    "list_date": "2000-01-01",
                    "status": "normal",
                },
                {
                    "code": "830799",
                    "name": "北交示例",
                    "market": "bj",
                    "board": "北交所",
                    "industry": "软件",
                    "instrument_type": "STOCK",
                    "list_date": "2021-01-01",
                    "status": "normal",
                },
            ]
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_default_drops_st_and_bse(self) -> None:
        resolved = resolve_universe(self.store)
        self.assertEqual(resolved.codes, ["300750", "600000", "688981"])
        self.assertTrue(resolved.spec["exclude_st"])
        self.assertEqual(resolved.funnel.after_board, 4)  # 三板+ST 主板，北交未进 after_board

    def test_include_st_keeps_st_still_no_bse(self) -> None:
        resolved = resolve_universe(self.store, {"preset": "include_st"})
        self.assertIn("600001", resolved.codes)
        self.assertNotIn("830799", resolved.codes)

    def test_explicit_bse_and_industry_filters(self) -> None:
        resolved = resolve_universe(
            self.store,
            {
                "preset": "all_a_share",
                "industries_include": ["软件", "半导体"],
                "industries_exclude": ["半导体"],
            },
        )
        self.assertEqual(resolved.codes, ["830799"])
        self.assertEqual(resolved.spec["industries_include"], ["软件", "半导体"])
        self.assertEqual(resolved.funnel.after_industry, 1)

    def test_main_only(self) -> None:
        resolved = resolve_universe(self.store, {"preset": "main_only"})
        self.assertEqual(resolved.codes, ["600000"])


if __name__ == "__main__":
    unittest.main()
