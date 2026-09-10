"""/api/review/* 结果缓存：命中、失效与「不缓存名单」。

这层缓存把 candidates / plans / winrate_summary 从几百毫秒压到个位数毫秒
（手工基准：candidates 214→9ms、plans 499→8ms、winrate/summary 602→7ms）。
它只有一条硬要求：**账本一写就得失效**，任何情况下不许发陈数据。

每条用例钉住这条要求的一个面，尤其：

- 失效断言一律「重算发生了 + 内容真的变了 + 键换了」三件套一起断，
  只断内容变了区分不出「命中旧键」和「压根没缓存」。
- 等长改判（精选→落选，行数不变）必须失效：这是 review_read_fingerprint 里
  candidate_reviews 逐行摘要存在的唯一理由，有人把它简化成 COUNT(*) 时要红。
- 已删的实盘端点必须 404：挡住哪天有人把持仓/成交端点又加回来。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.review as review_pkg
from src.ledger import PalaceStore
from src.market.infrastructure.store import MarketStore
from src.review.api import router as router_module
from src.review.api.router import build_review_router

DAYS = ["2026-03-%02d" % day for day in range(2, 27)]


def _quotes(closes: list[float]) -> pd.DataFrame:
    count = len(closes)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        dict(
            date=DAYS[:count],
            open=close,
            high=close * 1.02,
            low=close * 0.98,
            close=close,
            volume=np.full(count, 1_000_000.0),
            amount=close * 1_000_000.0,
            outstanding_share=np.full(count, 1e9),
            turnover=np.full(count, 0.001),
        )
    )


class ReviewCacheFixture(unittest.TestCase):
    """一个候选池 + 一份行情 + 挂着 review router 的 TestClient。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace_db = base / "palace.db"
        self.market_db = base / "market.db"
        with MarketStore(self.market_db) as market:
            market.upsert_quotes("600001", _quotes([10.0 + i * 0.1 for i in range(25)]))
            market.upsert_quotes("600002", _quotes([20.0 - i * 0.1 for i in range(25)]))
            market.upsert_quotes("000300", _quotes([50.0] * 25))
        with PalaceStore(self.palace_db) as palace:
            self._record_candidate(palace, "600001", DAYS[0], "精选")
        # _CACHE 是模块级的，不清会跨用例串，条目数断言全部失真
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

    @staticmethod
    def _record_candidate(palace, code: str, day: str, decision: str) -> None:
        palace.record_candidate(
            code=code,
            name=code,
            decision=decision,
            reason="回踩不破",
            occurred_on=day,
            pool_id="POOL-" + day,
            strategy_slug="demo-screen",
            rule_version="demo-screen",
        )

    def _cache_size(self) -> int:
        return len(router_module._CACHE)

    def _spy_on_candidates(self):
        """盯住真正的重算入口：命中缓存时它一次都不该被调到。

        router 是在请求里 ``from src.review import evaluate_candidates`` 的，
        所以打在包属性上就能拦到。
        """
        return patch.object(
            review_pkg, "evaluate_candidates", wraps=review_pkg.evaluate_candidates
        )


class CacheHitTests(ReviewCacheFixture):
    def test_scopes_cached_and_second_pass_all_hits(self) -> None:
        """每个 scope 各占一条；第二轮全命中，条目数不涨。

        四条 = candidates / plans / winrate_summary 三个端点 + 它们共用的
        ``candidate_outcomes``（winrate 三兄弟从它派生，见 router 模块头）。
        """
        paths = ["/api/review/candidates", "/api/review/plans", "/api/winrate/summary"]
        first = []
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            first.append(response.json())
        self.assertEqual(self._cache_size(), 4)

        for path, expected in zip(paths, first):
            self.assertEqual(self.client.get(path).json(), expected, path)
        self.assertEqual(self._cache_size(), 4)

    def test_repeat_request_does_not_recompute(self) -> None:
        """命中就是命中：底层 evaluate_candidates 只该跑一次。"""
        with self._spy_on_candidates() as spy:
            first = self.client.get("/api/review/candidates").json()
            second = self.client.get("/api/review/candidates").json()
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(self._cache_size(), 1)

    def test_distinct_params_do_not_share_one_entry(self) -> None:
        """参数进键：selected_only 不同不能互相串。"""
        self.client.get("/api/review/candidates")
        self.client.get("/api/review/candidates", params=dict(selected_only=True))
        self.assertEqual(self._cache_size(), 2)

    def test_winrate_trio_shares_one_outcomes_computation(self) -> None:
        """summary / trend / samples 同源：三条请求只重算一次候选 T+N。

        trend 旧版读手工 ``reviews`` 表（线上 0 行），页面「分周期明细」因此永远
        空着。改成与主表同源后它也进了缓存；这条钉住「同源」不退化回「各算各的」
        ——那会把 700ms 乘三。
        """
        with self._spy_on_candidates() as spy:
            self.assertEqual(self.client.get("/api/winrate/summary").status_code, 200)
            self.assertEqual(self.client.get("/api/winrate/trend").status_code, 200)
            samples = self.client.get("/api/winrate/samples", params=dict(tag="demo-screen"))
        self.assertEqual(samples.status_code, 200)
        self.assertEqual(spy.call_count, 1)


class CacheInvalidationTests(ReviewCacheFixture):
    """账本一写就得失效。每条都断「重算了 + 内容变了 + 换了新键」。"""

    def test_new_candidate_invalidates_cache(self) -> None:
        before = self.client.get("/api/review/candidates").json()
        self.assertEqual(self._cache_size(), 1)

        with PalaceStore(self.palace_db) as palace:
            self._record_candidate(palace, "600002", DAYS[1], "精选")

        with self._spy_on_candidates() as spy:
            after = self.client.get("/api/review/candidates").json()
        # 重算发生了：不是把旧值原样发回来
        self.assertEqual(spy.call_count, 1)
        # 换的是新键（旧键还留着，说明失效靠版本号而不是靠覆盖/清空）
        self.assertEqual(self._cache_size(), 2)
        # 内容真的变了
        codes_before = set(row["code"] for row in before["outcomes"])
        codes_after = set(row["code"] for row in after["outcomes"])
        self.assertEqual(codes_before, set(["600001"]))
        self.assertEqual(codes_after - codes_before, set(["600002"]))

    def test_equal_length_reversal_invalidates_cache(self) -> None:
        """等长改判：行数不变、created_at 不变、rowid 不变，缓存照样必须失效。

        「精选」→「落选」是 record_candidate 的原地 UPDATE 分支，两个裁决等长。
        指纹若退化成 COUNT(*)/MAX(rowid)/MAX(created_at)，这里就会把改判前的结果
        继续发出去——本用例是那条退化路径唯一的网。
        """
        params = dict(selected_only=True)
        first = self.client.get("/api/review/candidates", params=params).json()
        self.assertEqual([row["code"] for row in first["outcomes"]], ["600001"])

        with PalaceStore(self.palace_db) as palace:
            self._record_candidate(palace, "600001", DAYS[0], "落选")
            rows = palace.conn.execute("SELECT COUNT(*) FROM candidate_reviews").fetchone()[0]
        self.assertEqual(rows, 1, "改判必须是原地 UPDATE，否则这条用例就没在测等长改判")

        with self._spy_on_candidates() as spy:
            second = self.client.get("/api/review/candidates", params=params).json()
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self._cache_size(), 2)
        self.assertEqual(second["outcomes"], [])

    def test_market_write_invalidates_cache(self) -> None:
        """行情一同步也要换键：同一批候选、新的收盘价 = 新的 T+N 结论。"""
        self.client.get("/api/review/candidates")
        self.assertEqual(self._cache_size(), 1)

        with MarketStore(self.market_db) as market:
            market.upsert_quotes("600003", _quotes([30.0] * 25))

        with self._spy_on_candidates() as spy:
            self.client.get("/api/review/candidates")
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self._cache_size(), 2)

    def test_plan_write_invalidates_plans_scope(self) -> None:
        """预案也在指纹里：写一条预案后 plans 必须重算。"""
        before = self.client.get("/api/review/plans").json()
        self.assertEqual(before, [])
        with PalaceStore(self.palace_db) as palace:
            palace.record_plan(
                code="600001",
                title="回踩买",
                scenario="回踩 10 日线不破",
                occurred_on=DAYS[0],
                stop_price=9.0,
                target_price=12.0,
            )
        after = self.client.get("/api/review/plans").json()
        self.assertEqual(len(after), 1)
        self.assertEqual(self._cache_size(), 2)


class RemovedLiveTradeEndpointTests(ReviewCacheFixture):
    def test_live_trade_endpoints_are_gone(self) -> None:
        """实盘项已下线（2026-08）：这四条不能悄悄回来。"""
        for path in [
            "/api/review/equity",
            "/api/review/trips",
            "/api/review/positions",
            "/api/review/drift",
        ]:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self._cache_size(), 0)


if __name__ == "__main__":
    unittest.main()
