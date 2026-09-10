from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.ledger import PalaceStore, normalize_decision


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

        self.store.record_review(
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


    def test_journal_pool_and_review_payloads(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
