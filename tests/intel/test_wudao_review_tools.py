"""配了悟道就要用起来：新增截面工具进配方 + brief 把它们投影出来。

三类回归：

1. **参数键名**：``limit_down`` 认 ``date``、``board_break_analysis`` /
   ``auction_theme_strength`` / ``margin_trading`` 认 ``tradeDate``、日历类一个日期键
   都不补（2026-08-31 逐个双向实调验证：写反 = 整条 INVALID_ARGUMENTS 作废）。
2. **配方**：这些工具真的挂在 open / close 档上，且不进盘中档（盘中一天 24 轮，
   一条截面工具就是 24 次配额）。
3. **投影**：brief 得真读得懂它们的返回形状——尤其两融必须把交易所三行加起来，
   服务端给的 ``latest`` 只是第一行（实测 BSE 83 亿，全市场 2.6 万亿）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.intel.application.brief import BRIEF_TOOLS, build_intel_brief
from src.intel.application.daily_recipe import build_static_calls
from src.intel.application.wudao_keys import (
    DATE_ARG_BY_TOOL,
    DATELESS_TOOLS,
    date_argument,
)
from src.intel.infrastructure.intel_cache import write_cached_snapshot
from src.market import MarketStore

DAY = "2026-08-28"


def _snapshot(structured: dict) -> dict:
    """与 ``call_mcp_tool`` 落库同形：``structured`` 是服务端 ``data`` 段（已解包）。"""
    return {"text": "", "structured": structured, "is_error": False, "server": "wudao"}


class WudaoKeyTests(unittest.TestCase):
    def test_verified_date_keys(self) -> None:
        self.assertEqual(date_argument("limit_down", DAY), {"date": DAY})
        self.assertEqual(date_argument("anomaly_detection", DAY), {"date": DAY})
        for tool in ("board_break_analysis", "auction_theme_strength", "margin_trading", "northbound_holdings"):
            self.assertEqual(date_argument(tool, DAY), {"tradeDate": DAY}, tool)
            self.assertEqual(DATE_ARG_BY_TOOL[tool], "tradeDate")

    def test_calendar_tools_take_no_trade_date(self) -> None:
        """日历是「向前看」的区间；补上今天等于把日历砍成一天（且 tradeDate 实测被拒）。"""
        for tool in ("macro_calendar", "market_catalyst_calendar", "unlock_events"):
            self.assertIn(tool, DATELESS_TOOLS)
            self.assertEqual(date_argument(tool, DAY), {}, tool)


class RecipeTests(unittest.TestCase):
    def _args(self, phase: str) -> dict[str, dict]:
        calls = build_static_calls(phase, screener_count=12, trade_date=DAY)  # type: ignore[arg-type]
        return {call["tool"]: call["arguments"] for call in calls}

    def test_open_phase_adds_auction_theme_and_catalysts(self) -> None:
        args = self._args("open")
        self.assertEqual(
            args["auction_theme_strength"],
            {"limit": 12, "detailLevel": "summary", "tradeDate": DAY},
        )
        # 载荷体积：standard 档实测 63KB，summary 5KB。每天一张快照，别拿大的。
        self.assertEqual(args["market_catalyst_calendar"], {"limit": 60})
        self.assertNotIn("country", args["market_catalyst_calendar"])

    def test_close_phase_adds_review_and_risk_tools(self) -> None:
        args = self._args("close")
        self.assertEqual(args["board_break_analysis"], {"focus": "all", "limit": 80, "tradeDate": DAY})
        self.assertEqual(args["limit_down"], {"date": DAY})
        # 两融是 T+1 数据：问当天必空（线上实测），所以给七天窗口 + 消费侧取最新一天
        self.assertEqual(args["margin_trading"], {"startDate": "2026-08-21", "endDate": DAY})
        self.assertNotIn("tradeDate", args["margin_trading"], "schema 明写与区间二选一")
        self.assertEqual(
            args["unlock_events"],
            {"limit": 60, "startDate": DAY, "endDate": "2026-09-27"},
        )

    def test_intraday_phase_stays_lean(self) -> None:
        """盘中一天 24 轮：一条截面工具 = 24 次配额，这几条都不该进盘中档。"""
        args = self._args("intraday")
        for tool in (
            "board_break_analysis",
            "limit_down",
            "margin_trading",
            "unlock_events",
            "auction_theme_strength",
            "market_catalyst_calendar",
        ):
            self.assertNotIn(tool, args, tool)


class BriefProjectionTests(unittest.TestCase):
    def test_new_tools_are_part_of_the_brief(self) -> None:
        for tool in (
            "board_break_analysis",
            "limit_down",
            "auction_theme_strength",
            "market_catalyst_calendar",
            "margin_trading",
            "unlock_events",
        ):
            self.assertIn(tool, BRIEF_TOOLS, tool)

    def test_projects_review_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="board_break_analysis",
                    arguments={"tradeDate": DAY},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "summary": {
                                "totalPrevLimitUps": 76,
                                "sealedAgainCount": 17,
                                "brokenCount": 59,
                                "breakRate": 0.776,
                                "avgBrokenPctChg": 0.74,
                                "sentimentSignal": "cooling",
                                "highBoardBroken": [
                                    {"code": "003040", "name": "楚天龙", "prevStreak": 5, "pctChg": -1.23}
                                ],
                            }
                        }
                    ),
                )
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="limit_down",
                    arguments={"date": DAY},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "total": 3,
                            "stats": {
                                "limitDownCount": {"today": {"num": 3, "rate": 0.125, "open_num": 7}}
                            },
                            "rows": [{"code": "002963", "name": "豪尔赛"}],
                        }
                    ),
                )
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="auction_theme_strength",
                    arguments={"tradeDate": DAY},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "themes": [
                                {
                                    "name": "AI硬件",
                                    "memberCount": 377,
                                    "hitCount": 171,
                                    "totalBidAmountText": "66.48亿",
                                    "avgChangeRate": -0.03,
                                    "consistency": 0.032,
                                    "limitUpOpenCount": 3,
                                    "leaders": [{"code": "301591", "name": "肯特股份", "changeRate": 13.99}],
                                }
                            ]
                        }
                    ),
                )
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="market_catalyst_calendar",
                    arguments={"limit": 60},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "rows": [
                                {
                                    "date": "2026-08-27",
                                    "title": "已经过去的会议",
                                    "country": "中国",
                                    "star": 5,
                                    "type": "事件",
                                },
                                {
                                    "date": "2026-08-31",
                                    "time": "2026-08-31 09:30:00",
                                    "title": "中国8月官方制造业PMI",
                                    "country": "中国",
                                    "star": 3,
                                    "type": "经济数据",
                                },
                                {
                                    "date": "2026-08-31",
                                    "title": "美国非农",
                                    "country": "美国",
                                    "star": 5,
                                    "type": "经济数据",
                                },
                            ]
                        }
                    ),
                )
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="margin_trading",
                    arguments={"startDate": "2026-08-21", "endDate": DAY},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "latest": {"exchangeId": "BSE", "marginBalance": 8332418348},
                            "rows": [
                                {
                                    # 窗口里的旧一天：**不许**被加进汇总（否则一周余额摞在一起）
                                    "tradeDate": "20260827",
                                    "exchangeId": "SSE",
                                    "marginBalance": 999999999999,
                                    "marginBuy": 1,
                                    "marginRepay": 2,
                                },
                                {
                                    "tradeDate": "20260828",
                                    "exchangeId": "BSE",
                                    "marginBalance": 8332418348,
                                    "marginBuy": 659105185,
                                    "marginRepay": 676378913,
                                },
                                {
                                    "tradeDate": "20260828",
                                    "exchangeId": "SSE",
                                    "marginBalance": 1342943855079,
                                    "marginBuy": 94338686041,
                                    "marginRepay": 100458576084,
                                },
                                {
                                    "tradeDate": "20260828",
                                    "exchangeId": "SZSE",
                                    "marginBalance": 1278973655069,
                                    "marginBuy": 90000000000,
                                    "marginRepay": 89992223192,
                                },
                            ],
                        }
                    ),
                )
                write_cached_snapshot(
                    store,
                    trade_date=DAY,
                    tool="unlock_events",
                    arguments={"limit": 60},
                    server="wudao",
                    payload=_snapshot(
                        {
                            "rows": [
                                {
                                    "tsCode": "000100.SZ",
                                    "floatDate": "20260910",
                                    "floatRatio": 1.45,
                                    "shareType": "定增股份",
                                    "holderName": "某投资集团",
                                },
                                {
                                    "tsCode": "920288.BJ",
                                    "floatDate": "20260905",
                                    "floatRatio": 27.72,
                                    "shareType": "首发原始股",
                                    "holderName": "某自然人",
                                },
                            ]
                        }
                    ),
                )
                brief = build_intel_brief(store, trade_date=DAY)

        board = brief["board_break"]
        self.assertAlmostEqual(board["break_rate"], 77.6, places=1)
        self.assertEqual(board["sentiment_signal"], "cooling")
        self.assertEqual(board["sentiment_zh"], "退潮")
        self.assertEqual(board["high_board_broken"][0]["name"], "楚天龙")

        down = brief["limit_down"]
        self.assertEqual(down["count"], 3)
        self.assertAlmostEqual(down["sealed_rate"], 12.5)
        self.assertEqual(down["reopened"], 7)
        self.assertEqual(down["rows"][0]["code"], "002963")
        # 跌停池是权威口径：情绪表没采时也该有跌停家数
        self.assertEqual(brief["emotion"]["limit_down_count"], 3)

        auction = brief["auction_themes"][0]
        self.assertEqual(auction["name"], "AI硬件")
        self.assertAlmostEqual(auction["consistency"], 3.2, places=1)
        self.assertEqual(auction["leaders"][0]["name"], "肯特股份")

        titles = [row["title"] for row in brief["catalysts"]]
        self.assertIn("中国8月官方制造业PMI", titles)
        self.assertNotIn("已经过去的会议", titles, "过去的催化不该再报")
        self.assertNotIn("美国非农", titles, "非中国事件不进 A 股催化行")

        margin = brief["margin"]
        # 服务端 latest 只有 BSE 的 83 亿；全市场必须是三行之和
           # 窗口里还有 20260827 那一行（余额 1 万亿量级），只汇总最新一天才不会摞在一起
        self.assertEqual(margin["trade_date"], "20260828")
        self.assertEqual(margin["exchange_count"], 3)
        self.assertAlmostEqual(margin["balance"], 2630249928496.0, places=0)
        self.assertLess(margin["net_buy"], 0)

        unlocks = brief["unlocks"]
        self.assertEqual(unlocks[0]["code"], "920288", "按解禁比例降序")
        self.assertAlmostEqual(unlocks[0]["float_ratio"], 27.72)

    def test_sections_stay_empty_without_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                brief = build_intel_brief(store, trade_date=DAY)
        self.assertIsNone(brief["board_break"])
        self.assertIsNone(brief["limit_down"])
        self.assertIsNone(brief["margin"])
        self.assertEqual(brief["auction_themes"], [])
        self.assertEqual(brief["catalysts"], [])
        self.assertEqual(brief["unlocks"], [])


if __name__ == "__main__":
    unittest.main()
