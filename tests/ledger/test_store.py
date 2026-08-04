from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from src.ledger import PalaceError, PalaceStore, normalize_decision


class PalaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "palace.db"
        self.store = PalaceStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_normalize_decision_is_a_package_root_contract(self) -> None:
        self.assertEqual(normalize_decision("买入"), "精选")
        self.assertEqual(normalize_decision("剔除"), "落选")
        self.assertEqual(normalize_decision("持仓"), "观察")

    def test_positions_payload_batches_event_queries_and_keeps_lifecycle_semantics(
        self,
    ) -> None:
        today = date.today()
        code_a = "600001"
        code_b = "600002"
        self.store.record_trade(
            action="OPENING",
            code=code_a,
            name="甲",
            shares=100,
            price=10,
            occurred_on=today.isoformat(),
        )
        self.store.record_trade(
            action="OPENING",
            code=code_b,
            name="乙",
            shares=100,
            price=10,
            occurred_on=(today - timedelta(days=10)).isoformat(),
        )
        self.store.record_trade(
            action="SELL",
            code=code_b,
            shares=100,
            price=11,
            occurred_on=(today - timedelta(days=5)).isoformat(),
        )
        self.store.record_trade(
            action="OPENING",
            code=code_b,
            name="乙",
            shares=50,
            price=12,
            occurred_on=(today - timedelta(days=2)).isoformat(),
        )

        statements: list[str] = []
        self.store.conn.set_trace_callback(statements.append)
        try:
            payload = self.store.positions_payload()
        finally:
            self.store.conn.set_trace_callback(None)

        by_code = {row["code"]: row for row in payload}
        self.assertEqual(by_code[code_a]["today_buy_shares"], 100)
        self.assertEqual(by_code[code_a]["available_shares"], 0)
        self.assertEqual(by_code[code_a]["holding_days"], 0)
        self.assertEqual(by_code[code_b]["today_buy_shares"], 0)
        self.assertEqual(
            by_code[code_b]["opened_on"], (today - timedelta(days=2)).isoformat()
        )
        event_selects = [
            statement
            for statement in statements
            if "FROM position_events" in statement and statement.lstrip().startswith("SELECT")
        ]
        self.assertEqual(len(event_selects), 3)

    def test_positions_payload_keeps_same_day_reopen_as_current_round_start(self) -> None:
        code = "600003"
        self.store.record_trade(
            action="BUY",
            code=code,
            name="丙",
            shares=100,
            price=10,
            occurred_on="2026-07-01",
        )
        self.store.record_trade(
            action="SELL",
            code=code,
            shares=100,
            price=11,
            occurred_on="2026-07-02",
        )
        self.store.record_trade(
            action="BUY",
            code=code,
            shares=50,
            price=12,
            occurred_on="2026-07-02",
        )
        self.store.record_trade(
            action="BUY",
            code=code,
            shares=50,
            price=13,
            occurred_on="2026-07-03",
        )

        payload = self.store.positions_payload()

        self.assertEqual(payload[0]["opened_on"], "2026-07-02")

    def test_candidates_by_strategy_filters_by_rule_version(self) -> None:
        """按战法查历史选股，只返回匹配 rule_version 的记录。"""
        self.store.record_candidate(
            code="000001", name="平安银行", decision="入选", reason="test",
            occurred_on="2026-06-01", pool_id="strat-a@2026-06-01", rule_version="strat-a",
        )
        self.store.record_candidate(
            code="000002", name="万科A", decision="入选", reason="test",
            occurred_on="2026-06-01", pool_id="strat-b@2026-06-01", rule_version="strat-b",
        )
        self.store.record_candidate(
            code="000003", name="国药控股", decision="入选", reason="test",
            occurred_on="2026-06-02", pool_id="strat-a@2026-06-02", rule_version="strat-a",
        )
        results = self.store.candidates_by_strategy("strat-a", live_only=False)
        codes = [r["code"] for r in results]
        self.assertIn("000001", codes)
        self.assertIn("000003", codes)
        self.assertNotIn("000002", codes)

    def test_candidate_preserves_formula_revision_and_params(self) -> None:
        self.store.record_candidate(
            code="000001",
            name="平安银行",
            decision="精选",
            reason="公式命中",
            occurred_on="2026-07-29",
            pool_id="my-breakout@2026-07-29",
            rule_version="我的突破战法",
            strategy_slug="my-breakout",
            strategy_revision="a" * 64,
            effective_params={"N": 20, "VOL_MULT": 1.5},
        )

        rows = self.store.candidates_by_strategy("my-breakout", live_only=False)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_slug"], "my-breakout")
        self.assertEqual(rows[0]["strategy_revision"], "a" * 64)
        self.assertEqual(rows[0]["effective_params"], {"N": 20, "VOL_MULT": 1.5})

    def test_legacy_candidate_table_migrates_formula_revision_columns(self) -> None:
        legacy_db = Path(self.temp.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_db)) as conn:
            conn.execute(
                """
                CREATE TABLE candidate_reviews (
                    id TEXT PRIMARY KEY,
                    occurred_on TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score REAL,
                    decision TEXT NOT NULL,
                    timing TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL,
                    rule_version TEXT NOT NULL DEFAULT '潜龙',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    tier TEXT NOT NULL DEFAULT 'core',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                )
                """
            )

        legacy = PalaceStore(legacy_db)
        try:
            columns = {
                str(row["name"])
                for row in legacy.conn.execute("PRAGMA table_info(candidate_reviews)")
            }
        finally:
            legacy.close()

        self.assertTrue(
            {"strategy_slug", "strategy_revision", "effective_params_json"} <= columns
        )

    def test_candidates_by_strategy_respects_date_range(self) -> None:
        for day in ("2026-05-01", "2026-06-01", "2026-07-01"):
            self.store.record_candidate(
                code="000001", name="平安银行", decision="入选", reason="test",
                occurred_on=day, pool_id=f"s@{day}", rule_version="strat-x",
            )
        results = self.store.candidates_by_strategy(
            "strat-x", start="2026-06-01", end="2026-06-30", live_only=False
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["date"], "2026-06-01")

    def test_candidates_by_strategy_deduplicates_same_day(self) -> None:
        """同一天同一标的重跑两次，只返回最新一条。"""
        self.store.record_candidate(
            code="000001", name="平安银行", decision="入选", reason="first run",
            occurred_on="2026-06-01", pool_id="s@2026-06-01", rule_version="strat-x",
        )
        self.store.record_candidate(
            code="000001", name="平安银行", decision="入选", reason="second run",
            occurred_on="2026-06-01", pool_id="s@2026-06-01", rule_version="strat-x",
        )
        results = self.store.candidates_by_strategy("strat-x", live_only=False)
        self.assertEqual(len(results), 1)

    def test_current_schema_open_does_not_rewrite_candidate_facts(self) -> None:
        """打开当前版本账本不能把历史候选原文改成新的裁决口径。"""
        candidate_id = self.store.record_candidate(
            code="600519",
            name="茅台",
            decision="精选",
            reason="原始理由",
            occurred_on="2026-07-29",
            pool_id="audit@2026-07-29",
            rule_version="潜龙",
            source="manual",
        )
        self.store.conn.execute(
            """
            UPDATE candidate_reviews
            SET decision = ?, timing = ?, reason = ?, rule_version = ?
            WHERE id = ?
            """,
            ("入选", "t+1", "历史原文", "qianlong", candidate_id),
        )
        self.store.conn.commit()
        before = dict(
            self.store.conn.execute(
                """
                SELECT decision, timing, reason, rule_version, source
                FROM candidate_reviews WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
        )
        self.store.close()

        from src.ledger.infrastructure.store_types import _SCHEMA_READY

        _SCHEMA_READY.discard(str(self.db.resolve()))
        reopened = PalaceStore(self.db)
        try:
            after = dict(
                reopened.conn.execute(
                    """
                    SELECT decision, timing, reason, rule_version, source
                    FROM candidate_reviews WHERE id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
            )
            self.assertEqual(after, before)
        finally:
            reopened.close()
            self.store = PalaceStore(self.db)

    def test_retag_stale_api_screen_to_backfill(self) -> None:
        """过期 API 选股按回填展示，但打开账本不改写 source 事实。"""
        from src.ledger.infrastructure.store_types import _SCHEMA_READY

        self.store.record_candidate(
            code="600519",
            name="茅台",
            decision="精选",
            reason="polluted",
            occurred_on="2026-07-29",
            pool_id="demo@2026-07-29",
            rule_version="demo",
            strategy_slug="demo",
            source="api:screen_run",
        )
        self.store.conn.execute(
            "UPDATE candidate_reviews SET created_at = ? WHERE occurred_on = ?",
            ("2026-07-31T10:00:00+08:00", "2026-07-29"),
        )
        self.store.conn.commit()
        self.store.close()
        _SCHEMA_READY.discard(str(self.db.resolve()))

        reopened = PalaceStore(self.db)
        try:
            source = reopened.conn.execute(
                "SELECT source FROM candidate_reviews WHERE code = '600519'"
            ).fetchone()["source"]
            self.assertEqual(source, "api:screen_run")
            self.assertEqual(
                reopened.candidates_list_payload(strategy="demo"),
                [],
            )
            self.assertEqual(
                len(reopened.candidates_list_payload(strategy="demo", include_backfill=True)),
                1,
            )
        finally:
            reopened.close()
            self.store = PalaceStore(self.db)

    def test_pool_dates_excludes_backfill_only_pools(self) -> None:
        self.store.record_candidate(
            code="600000",
            name="可见",
            decision="观察",
            reason="本轮选股",
            occurred_on="2026-07-31",
            pool_id="live",
        )
        self.store.record_candidate(
            code="600001",
            name="回填",
            decision="观察",
            reason="历史回填",
            occurred_on="2026-07-31",
            pool_id="history",
            source="strategy:backfill",
        )

        pools = self.store.pool_dates_payload()

        self.assertEqual([(row["pool_id"], row["total"]) for row in pools], [("live", 1)])

    def test_winrate_trend_groups_by_month(self) -> None:
        """胜率趋势按月聚合。"""
        self.store.record_trade(action="BUY", code="000001", name="A", shares=100, price=10, occurred_on="2026-05-01")
        self.store.record_trade(action="SELL", code="000001", shares=100, price=12, occurred_on="2026-05-02")

        review_id = self.store.record_review(
            entity_type="trade",
            entity_id="dummy",
            outcome="盈利",
            reviewed_on="2026-05-10",
            strategy_tag="strat-z",
            return_pct=5.0,
        )
        self.store.record_review(
            entity_type="trade",
            entity_id="dummy2",
            outcome="亏损",
            reviewed_on="2026-05-15",
            strategy_tag="strat-z",
            return_pct=-3.0,
        )
        trend = self.store.winrate_trend(strategy_tags=["strat-z"], granularity="month")
        self.assertEqual(len(trend), 1)
        row = trend[0]
        self.assertEqual(row["strategy_tag"], "strat-z")
        self.assertEqual(row["total"], 2)
        self.assertEqual(row["wins"], 1)
        self.assertAlmostEqual(row["win_rate"], 50.0)

    def test_strategy_winrates_returns_all_tags(self) -> None:
        """综合胜率汇总包含所有战法。"""
        for tag, ret in [("aa", 5.0), ("aa", -2.0), ("bb", 8.0)]:
            self.store.record_review(
                entity_type="trade", entity_id="x",
                outcome="ok", reviewed_on="2026-06-01",
                strategy_tag=tag, return_pct=ret,
            )
        summary = self.store.strategy_winrates()
        tags = {row["strategy_tag"] for row in summary}
        self.assertIn("aa", tags)
        self.assertIn("bb", tags)
        aa = next(r for r in summary if r["strategy_tag"] == "aa")
        self.assertEqual(aa["total"], 2)
        self.assertEqual(aa["wins"], 1)
        self.assertAlmostEqual(aa["win_rate"], 50.0)
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=10, occurred_on="2026-07-01")
        self.store.record_trade(action="BUY", code="300358", shares=100, price=12, occurred_on="2026-07-02")
        result = self.store.record_trade(action="SELL", code="300358", shares=50, price=10, occurred_on="2026-07-03")

        position = self.store.list_positions()[0]
        self.assertEqual(position.shares, 150)
        self.assertAlmostEqual(position.cost, 11.333333, places=5)
        self.assertEqual(result["realized_pnl"], -50.0)
        self.assertEqual(self.store.realized_pnl(), -50.0)
        self.assertIn("SELL 50股", self.store.timeline_markdown("300358"))

    def test_rejects_sell_larger_than_position(self) -> None:
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=10)
        with self.assertRaises(PalaceError):
            self.store.record_trade(action="SELL", code="300358", shares=101, price=10)

    def test_concurrent_buys_cannot_both_pass_cash_check(self) -> None:
        self.store.record_snapshot(total_assets=100, cash=100, occurred_on="2026-07-31")
        barrier = threading.Barrier(2)
        original_cash = PalaceStore.broker_cash

        def gated_cash(store: PalaceStore) -> float | None:
            available = original_cash(store)
            # 旧实现的余额读取在事务外；让两个请求都拿到同一余额，稳定重现透支。
            if not store.conn.in_transaction:
                barrier.wait(timeout=5)
            return available

        def buy() -> bool:
            try:
                with PalaceStore(self.db) as store:
                    store.record_trade(
                        action="BUY",
                        code="300358",
                        shares=10,
                        price=10,
                        occurred_on="2026-07-31",
                    )
                return True
            except PalaceError:
                return False

        with mock.patch.object(PalaceStore, "broker_cash", gated_cash):
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(lambda _: buy(), range(2)))

        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.store.broker_cash(), 0.0)
        self.assertEqual(self.store.list_positions()[0].shares, 10)

    def test_dashboard_connects_candidate_plan_and_review(self) -> None:
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=8.3)
        self.store.record_snapshot(total_assets=206400, occurred_on="2026-07-24")
        candidate_id = self.store.record_candidate(
            code="300358", name="楚天科技", score=81, decision="重点", timing="D-low",
            reason="记录回踩确认条件", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        plan_id = self.store.record_plan(
            code="300358", title="首仓预案", scenario="回踩企稳", entry_zone="8.10-8.30",
            stop_price=7.76, target_price=9.1, layers=1, invalidation="跌破结构位", occurred_on="2026-07-24",
        )
        self.store.record_review(
            entity_type="candidate", entity_id=candidate_id, outcome="T+5 回看", return_pct=3.2,
            lesson="等待回踩确认", next_rule="保留 D-low", reviewed_on="2026-07-29",
        )
        dashboard = self.store.dashboard_markdown("2026-07-24")
        self.assertIn("POOL-2026-07-24", dashboard)
        self.assertIn(plan_id, dashboard)
        self.assertIn("3.20%", dashboard)

    def test_imports_skill_state_once_as_opening_snapshot(self) -> None:
        state_path = Path(self.temp.name) / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "updatedAt": "2026-07-24",
                    "totalAssets": 206400,
                    "realizedPnlCumulative": -11104,
                    "holdings": [{"name": "楚天科技", "code": "300358", "cost": 8.3, "shares": 3200, "layers": 1.29}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = self.store.import_qianlong_state(state_path)
        self.assertEqual(len(result["position_events"]), 1)
        self.assertEqual(self.store.list_positions()[0].shares, 3200)
        self.assertEqual(self.store.realized_pnl(), -11104.0)
        dashboard = self.store.dashboard_payload("2026-07-24")
        self.assertIsNone(dashboard["account"]["today_realized_pnl"])
        self.assertIn("累计盈亏基线", dashboard["account"]["today_realized_note"])
        with self.assertRaises(PalaceError):
            self.store.import_qianlong_state(state_path)

    def test_preview_qianlong_state_without_writes(self) -> None:
        payload = {
            "updatedAt": "2026-07-24",
            "totalAssets": 206400,
            "realizedPnlCumulative": -11104,
            "holdings": [{"name": "楚天科技", "code": "300358", "cost": 8.3, "shares": 3200, "note": "首仓"}],
        }
        preview = self.store.preview_qianlong_state(payload)
        self.assertTrue(preview["can_import"])
        self.assertEqual(preview["block_reason"], "")
        self.assertEqual(preview["holdings_count"], 1)
        self.assertEqual(preview["holdings"][0]["code"], "300358")
        self.assertEqual(self.store.list_positions(), [])

        self.store.import_qianlong_payload(payload, source_label="state.json")
        blocked = self.store.preview_qianlong_state(payload)
        self.assertFalse(blocked["can_import"])
        self.assertIn("账本已有仓位事件", blocked["block_reason"])

    def test_batch_trades_and_qianlong_import_rollback_all_facts_on_failure(self) -> None:
        with self.assertRaises(PalaceError):
            self.store.record_trades([
                {"action": "BUY", "code": "600001", "shares": 100, "price": 10},
                {"action": "SELL", "code": "600002", "shares": 100, "price": 10},
            ])
        self.assertEqual(self.store.trades_payload(), [])
        self.assertEqual(self.store.positions_payload(), [])

        payload = {
            "updatedAt": "2026-07-24",
            "totalAssets": 100000,
            "holdings": [
                {"code": "600001", "shares": 100, "cost": 10},
                {"code": "600001", "shares": 100, "cost": 11},
            ],
        }
        with self.assertRaises(PalaceError):
            self.store.import_qianlong_payload(payload)
        self.assertEqual(self.store.trades_payload(), [])
        self.assertEqual(self.store.positions_payload(), [])
        meta = self.store.conn.execute(
            "SELECT value FROM meta WHERE key = 'qianlong_state_import'"
        ).fetchone()
        self.assertIsNone(meta)

    def test_journal_pool_review_and_analytics_payloads(self) -> None:
        self.store.record_trade(
            action="BUY", code="300358", name="楚天科技", shares=100, price=8.3, occurred_on="2026-07-20"
        )
        self.store.record_trade(
            action="SELL", code="300358", shares=40, price=8.8, occurred_on="2026-07-22", reason="减仓"
        )
        self.store.record_candidate(
            code="300358", name="楚天科技", score=81, decision="重点", timing="D-low",
            reason="结构回踩", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        self.store.record_candidate(
            code="000722", name="湖南发展", score=55, decision="落选", timing="观望",
            reason="量能不足", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        candidate_id = self.store.record_candidate(
            code="002230", name="科大讯飞", score=72, decision="观察", timing="D0",
            reason="等待确认", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        self.store.record_review(
            entity_type="candidate",
            entity_id=candidate_id,
            outcome="T+3 回看",
            return_pct=1.5,
            lesson="观察池也要记失效条件",
            next_rule="观察票单独样本",
            reviewed_on="2026-07-27",
        )

        trades = self.store.trades_payload()
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["action"], "SELL")
        self.assertEqual(trades[0]["realized_pnl"], 20.0)

        pools = self.store.pool_dates_payload()
        self.assertEqual(pools[0]["total"], 3)
        self.assertEqual(pools[0]["selected"], 1)
        self.assertEqual(pools[0]["filtered"], 2)

        day = self.store.pool_day_payload("2026-07-24")
        self.assertEqual(day["selected_count"], 1)
        self.assertEqual(day["filtered_count"], 2)
        self.assertEqual(day["selected"][0]["code"], "300358")

        reviews = self.store.reviews_payload()
        self.assertEqual(reviews[0]["lesson"], "观察池也要记失效条件")

        analytics = self.store.analytics_payload()
        self.assertGreaterEqual(len(analytics["equity_curve"]), 1)
        self.assertEqual(analytics["equity_curve"][-1]["cumulative_pnl"], 20.0)
        self.assertTrue(any(item["decision"] == "精选" for item in analytics["decisions"]))


if __name__ == "__main__":
    unittest.main()
