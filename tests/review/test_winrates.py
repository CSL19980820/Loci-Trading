"""胜率页的三个视角：分周期、样本明细、最佳样本 / 最佳持有期。

这些数字是页头「综合胜率 55.2%」唯一的解释来源，口径错了页面就在骗人：

- 分周期必须与主表**同源**（精选候选 T+N）。旧版读手工 ``reviews``，而线上那张表
  0 行，于是「分周期明细」永远一句「无周期明细」——本文件第一条用例是那个 bug 的
  回归网。
- 周编号必须与 SQLite 回退路径算得一样，否则两种来源画进同一张表会串周。
- 样本明细的条数必须等于胜率的分母，否则「怎么算的」看了也白看。
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import PalaceStore
from src.market.infrastructure.store import MarketStore
from src.review import (
    build_winrate_summary,
    evaluate_candidates,
    winrate_periods,
    winrate_samples,
)
from src.review.api import router as router_module
from src.review.api.router import build_review_router

#: 跨 3/4 月的连续工作日，用来验证分月聚合真的分出了两行。
DAYS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2026-03-16", periods=40)]
TAG = "demo-screen"


def _quotes(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": DAYS[:n],
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "amount": close * 1_000_000.0,
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class WinRateEvidenceTests(unittest.TestCase):
    """一涨一跌两只票，四条走完窗口的精选 + 一条还在观察。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace = PalaceStore(base / "palace.db")
        self.market = MarketStore(base / "market.db")
        self.market.upsert_quotes("600001", _quotes([10.0 + i * 0.25 for i in range(40)]))
        self.market.upsert_quotes("600002", _quotes([20.0 - i * 0.25 for i in range(40)]))
        self.market.upsert_quotes("000300", _quotes([50.0] * 40))
        # 3 月两条赢、4 月两条输：分月聚合应当一行 100% 一行 0%
        self._pick("600001", DAYS[0])
        self._pick("600001", DAYS[1])
        self._pick("600002", DAYS[20])
        self._pick("600002", DAYS[21])
        # 日历末日选出：T+5 走不完，只能算 observing，不许进胜率分母
        self._pick("600001", DAYS[-1])
        self.outcomes = evaluate_candidates(self.palace, self.market)

    def tearDown(self) -> None:
        self.palace.close()
        self.market.close()
        self.temp.cleanup()

    def _pick(self, code: str, day: str) -> None:
        self.palace.record_candidate(
            code=code,
            name=code,
            decision="精选",
            reason="回踩不破",
            occurred_on=day,
            pool_id="POOL-" + day,
            strategy_slug=TAG,
            rule_version=TAG,
        )

    def test_periods_come_from_candidates_not_manual_reviews(self) -> None:
        """分月胜率来自候选 T+5；``reviews`` 一行都没有也必须出数。"""
        empty = self.palace.winrate_trend(strategy_tags=[TAG], granularity="month")
        self.assertEqual(empty, [], "手工复盘表本来就是空的，这条前提一变用例就失去意义")

        rows = winrate_periods(self.outcomes, granularity="month", strategy_tags=[TAG])
        by_period = {row["period"]: row for row in rows}
        self.assertEqual(sorted(by_period), ["2026-03", "2026-04"])
        self.assertEqual(by_period["2026-03"]["total"], 2)
        self.assertEqual(by_period["2026-03"]["win_rate"], 100.0)
        self.assertEqual(by_period["2026-04"]["total"], 2)
        self.assertEqual(by_period["2026-04"]["win_rate"], 0.0)
        self.assertEqual(by_period["2026-03"]["source"], "candidates")
        self.assertGreater(by_period["2026-03"]["avg_return"], 0)
        self.assertLess(by_period["2026-04"]["avg_return"], 0)

    def test_week_period_matches_sqlite_fallback_key(self) -> None:
        """周编号与 ``date(d,'weekday 0','-6 days')`` 一致：同一张表不能有两套周。"""
        rows = winrate_periods(self.outcomes, granularity="week", strategy_tags=[TAG])
        self.assertTrue(rows)
        conn = sqlite3.connect(":memory:")
        try:
            for day in (DAYS[0], DAYS[20], DAYS[21]):
                expected = conn.execute(
                    "SELECT date(?, 'weekday 0', '-6 days')", (day,)
                ).fetchone()[0]
                matched = [row for row in rows if row["period"] == expected]
                self.assertTrue(matched, f"{day} 应落进周期 {expected}，实际 {[r['period'] for r in rows]}")
        finally:
            conn.close()

    def test_observing_sample_stays_out_of_the_denominator(self) -> None:
        """窗口没走完的那条只能计 observing；混进分母就是虚高胜率。"""
        detail = winrate_samples(self.outcomes, strategy_tag=TAG)
        self.assertEqual(detail["settled"], 4)
        self.assertEqual(detail["observing"], 1)
        self.assertEqual(detail["wins"], 2)
        self.assertEqual(detail["win_rate"], 50.0)
        self.assertEqual(len(detail["samples"]), 5)
        wins = [s for s in detail["samples"] if s["win"] is True]
        losses = [s for s in detail["samples"] if s["win"] is False]
        pending = [s for s in detail["samples"] if s["win"] is None]
        self.assertEqual(len(wins), 2)
        self.assertEqual(len(losses), 2)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(wins) + len(losses), detail["settled"])
        self.assertEqual([s["code"] for s in wins], ["600001", "600001"])
        self.assertEqual(detail["samples"][0]["base_date"], DAYS[-1], "样本按选出日倒序")

    def test_samples_are_scoped_to_one_strategy(self) -> None:
        """换个 tag 就该是空的：明细串了战法比没有明细更糟。"""
        detail = winrate_samples(self.outcomes, strategy_tag="other-slug")
        self.assertEqual(detail["samples"], [])
        self.assertEqual(detail["settled"], 0)
        self.assertIsNone(detail["win_rate"])

    def test_summary_names_the_best_and_worst_sample(self) -> None:
        """「最佳样本」得说出是哪只票哪天：光给个 +12% 没法复盘。"""
        rows = build_winrate_summary(self.outcomes, self.palace.strategy_winrates())
        row = {r["strategy_tag"]: r for r in rows}[TAG]
        self.assertEqual(row["best_sample"]["code"], "600001")
        self.assertEqual(row["worst_sample"]["code"], "600002")
        self.assertGreater(row["best_sample"]["return_pct"], 0)
        self.assertLess(row["worst_sample"]["return_pct"], 0)
        self.assertEqual(row["best_sample"]["horizon"], 5)
        self.assertIn(row["best_sample"]["base_date"], (DAYS[0], DAYS[1]))

    def test_summary_exposes_every_horizon_and_picks_the_best(self) -> None:
        """T+10/20/60 本来就算了；丢掉它们等于没法回答「这战法该拿几天」。"""
        rows = build_winrate_summary(self.outcomes, self.palace.strategy_winrates())
        row = {r["strategy_tag"]: r for r in rows}[TAG]
        self.assertEqual(sorted(row["horizons"]), ["t1", "t10", "t20", "t3", "t5"])
        best = row["best_horizon"]
        self.assertIsNotNone(best)
        self.assertGreaterEqual(best["n"], 3)
        self.assertEqual(
            best["win_rate"],
            max(body["win_rate"] for body in row["horizons"].values() if body["n"] >= 3),
        )

    def test_best_horizon_needs_enough_samples(self) -> None:
        """两个样本的 100% 不是结论：样本不足时不许评「最佳持有期」。"""
        thin = [o for o in self.outcomes if o.base_date in (DAYS[0], DAYS[1])]
        rows = build_winrate_summary(thin, [])
        row = {r["strategy_tag"]: r for r in rows}[TAG]
        self.assertEqual(row["total"], 2)
        self.assertIsNone(row["best_horizon"])


class WinRateTrendFallbackTests(unittest.TestCase):
    """没有候选样本、只有手工复盘时，trend 必须回退而不是交白卷。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace_db = base / "palace.db"
        self.market_db = base / "market.db"
        with MarketStore(self.market_db) as market:
            market.upsert_quotes("000300", _quotes([50.0] * 40))
        with PalaceStore(self.palace_db) as palace:
            palace.record_review(
                entity_type="candidate",
                entity_id="C-1",
                outcome="win",
                reviewed_on=DAYS[0],
                strategy_tag="legacy-manual",
                return_pct=4.2,
            )
        router_module.clear_review_cache()
        app = FastAPI()
        app.include_router(
            build_review_router(market_db=str(self.market_db), palace_db=str(self.palace_db))
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        router_module.clear_review_cache()
        self.temp.cleanup()

    def test_trend_falls_back_to_manual_reviews(self) -> None:
        response = self.client.get("/api/winrate/trend")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_tag"], "legacy-manual")
        self.assertEqual(rows[0]["period"], DAYS[0][:7])
        self.assertEqual(rows[0]["source"], "reviews")
        self.assertIsNone(rows[0]["avg_return"])

    def test_samples_endpoint_rejects_unknown_horizon(self) -> None:
        """horizon 只认 evaluate_candidates 真的算过的那几档。"""
        ok = self.client.get("/api/winrate/samples", params=dict(tag="x", horizon=20))
        self.assertEqual(ok.status_code, 200)
        bad = self.client.get("/api/winrate/samples", params=dict(tag="x", horizon=7))
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
