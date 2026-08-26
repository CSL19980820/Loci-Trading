from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.intel.application.brief import build_intel_brief
from src.intel.infrastructure.intel_cache import list_latest_snapshots, write_cached_snapshot
from src.market import MarketStore


class IntelBriefTests(unittest.TestCase):
    def test_list_latest_prefers_newest_args_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-06",
                    tool="short_term_emotion",
                    arguments={},
                    server="wudao",
                    payload={
                        "structured": {"limitUpCount": 40, "promotionRate": 0.5},
                        "text": "",
                    },
                )
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-06",
                    tool="short_term_emotion",
                    arguments={"tradeDate": "2026-08-06"},
                    server="wudao",
                    payload={
                        "structured": {"limitUpCount": 55, "promotionRate": 0.62},
                        "text": "",
                    },
                )
                latest = list_latest_snapshots(
                    store,
                    trade_date="2026-08-06",
                    tools=["short_term_emotion"],
                )
                self.assertEqual(
                    latest["short_term_emotion"]["payload"]["structured"]["limitUpCount"],
                    55,
                )

    def test_brief_projects_emotion_themes_ladder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-06",
                    tool="short_term_emotion",
                    arguments={},
                    server="wudao",
                    payload={
                        "structured": {
                            "limitUpCount": 48,
                            "limitDownCount": 3,
                            "promotionRate": 0.55,
                            "brokenRate": 0.28,
                            "temperature": 66,
                        }
                    },
                )
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-06",
                    tool="theme_intraday_capital",
                    arguments={"limit": 60},
                    server="wudao",
                    payload={
                        "structured": {
                            "rows": [
                                {
                                    "themeCode": "801843k",
                                    "themeName": "机器人",
                                    "strength": 88.5,
                                },
                                {"themeCode": "801001k", "themeName": "半导体", "score": 70},
                            ]
                        }
                    },
                )
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-06",
                    tool="limit_up_ladder",
                    arguments={},
                    server="wudao",
                    payload={
                        "structured": {
                            "rows": [
                                {"code": "000001", "level": 3},
                                {"code": "000002", "board": 5},
                            ]
                        }
                    },
                )
                brief = build_intel_brief(store, trade_date="2026-08-06")
            self.assertTrue(brief["available"])
            self.assertEqual(brief["emotion"]["limit_up_count"], 48.0)
            # 0.55 比例 → 55 百分数；口径收在 brief，前端不再猜
            self.assertAlmostEqual(brief["emotion"]["promotion_rate"], 55.0)
            self.assertAlmostEqual(brief["emotion"]["broken_rate"], 28.0)
            self.assertEqual(brief["themes"][0]["name"], "机器人")
            self.assertEqual(brief["ladder"]["count"], 2)
            self.assertEqual(brief["ladder"]["height"], 5.0)

    def test_brief_reads_wudao_sealed_aliases_and_theme_money(self) -> None:
        """悟道 short_term_emotion 用 sealed*/broken*；题材要能读涨跌幅与主力净额。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-07",
                    tool="short_term_emotion",
                    arguments={},
                    server="wudao",
                    payload={
                        "structured": {
                            "summary": {
                                "sealedLimitUp": 64,
                                "sealedLimitDown": 5,
                                "brokenBoardRate": 31.91,
                                "promotionRates": {"firstToSecond": 12.07},
                            }
                        }
                    },
                )
                write_cached_snapshot(
                    store,
                    trade_date="2026-08-07",
                    tool="theme_intraday_capital",
                    arguments={},
                    server="wudao",
                    payload={
                        "structured": {
                            "rows": [
                                {
                                    "themeCode": "801027k",
                                    "themeName": "通信",
                                    "strength": 15990,
                                    "pctChg": 2.4,
                                    "mainNetAmountText": "+12.3亿",
                                }
                            ]
                        }
                    },
                )
                brief = build_intel_brief(store, trade_date="2026-08-07")
            self.assertEqual(brief["emotion"]["limit_up_count"], 64.0)
            self.assertEqual(brief["emotion"]["limit_down_count"], 5.0)
            self.assertEqual(brief["emotion"]["broken_rate"], 31.91)
            self.assertEqual(brief["emotion"]["promotion_rate"], 12.07)
            self.assertEqual(brief["themes"][0]["pct_chg"], 2.4)
            self.assertEqual(brief["themes"][0]["main_net_amount_text"], "+12.3亿")

    def test_brief_empty_when_no_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                brief = build_intel_brief(store, trade_date="2026-08-06")
            self.assertFalse(brief["available"])
            self.assertTrue(brief.get("optional"))
            self.assertIsNone(brief["emotion"])
            self.assertEqual(brief["themes"], [])

    def test_brief_survives_list_failure(self) -> None:
        from unittest.mock import MagicMock, patch

        store = MagicMock()
        with patch(
            "src.intel.application.brief.list_latest_snapshots",
            side_effect=RuntimeError("db down"),
        ):
            brief = build_intel_brief(store, trade_date="2026-08-06")
        self.assertFalse(brief["available"])
        self.assertTrue(brief.get("optional"))


if __name__ == "__main__":
    unittest.main()
