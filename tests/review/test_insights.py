"""洞察层测试：衰减监测、重叠度、组合风控、容量校验。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ledger import PalaceStore
from src.review.application.decay import StrategyDecayReport, check_all_decay, check_decay
from src.review.application.overlap import OverlapReport, compute_overlap
from src.review.application.portfolio_guard import (
    GuardResult,
    PortfolioLimits,
    check_portfolio_limits,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_palace() -> tuple[PalaceStore, tempfile.TemporaryDirectory]:  # type: ignore[type-arg]
    tmp = tempfile.TemporaryDirectory()
    db = Path(tmp.name) / "palace.db"
    store = PalaceStore(db)
    return store, tmp


def _insert_review(store: PalaceStore, strategy_tag: str, return_pct: float, day: str) -> None:
    """直接往 reviews 表插一条记录（绕过 record_review 的外键约束）。"""
    store.conn.execute(
        """
        INSERT INTO reviews(id, reviewed_on, entity_type, entity_id,
                            strategy_tag, outcome, return_pct, created_at)
        VALUES (hex(randomblob(8)), ?, 'trade', 'dummy',
                ?, 'closed', ?, datetime('now'))
        """,
        (day, strategy_tag, return_pct),
    )
    store.conn.commit()


# ---------------------------------------------------------------------------
# DecayTests
# ---------------------------------------------------------------------------

class DecayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self.tmp = _make_palace()

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_no_data_returns_empty(self) -> None:
        report = check_decay(self.store, "ghost-strategy")
        self.assertEqual(report.strategy_tag, "ghost-strategy")
        self.assertEqual(report.total_records, 0)
        self.assertIsNone(report.baseline_win_rate)
        self.assertIsNone(report.recent_win_rate)
        self.assertEqual(report.decay_signal, "ok")

    def test_decay_detected_when_recent_worse(self) -> None:
        tag = "strat-decay"
        # baseline: 80 wins out of 100 → 80%
        for i in range(80):
            _insert_review(self.store, tag, 5.0, f"2025-01-{i % 28 + 1:02d}")
        for i in range(20):
            _insert_review(self.store, tag, -1.0, f"2025-02-{i % 28 + 1:02d}")
        # recent window (last 20): all losses → 0%
        for i in range(20):
            _insert_review(self.store, tag, -2.0, f"2026-06-{i + 1:02d}")

        report = check_decay(self.store, tag, window=20, baseline_window=100)
        self.assertIsNotNone(report.baseline_win_rate)
        self.assertIsNotNone(report.recent_win_rate)
        assert report.recent_win_rate is not None
        self.assertEqual(report.recent_win_rate, 0.0)
        # 0% < 30% → critical
        self.assertEqual(report.decay_signal, "critical")

    def test_check_all_decay_returns_all_tags(self) -> None:
        _insert_review(self.store, "alpha", 1.0, "2026-01-01")
        _insert_review(self.store, "beta", -1.0, "2026-01-01")
        reports = check_all_decay(self.store)
        tags = {r.strategy_tag for r in reports}
        self.assertIn("alpha", tags)
        self.assertIn("beta", tags)

    def test_warning_signal_on_moderate_drop(self) -> None:
        tag = "moderate-drop"
        # baseline: 60% win rate (60 wins / 100)
        for _ in range(60):
            _insert_review(self.store, tag, 1.0, "2025-03-01")
        for _ in range(40):
            _insert_review(self.store, tag, -1.0, "2025-03-02")
        # recent 20: 40% win rate (8 wins / 20) → drop = 20pp exactly → critical
        for _ in range(8):
            _insert_review(self.store, tag, 1.0, "2026-06-01")
        for _ in range(12):
            _insert_review(self.store, tag, -1.0, "2026-06-02")

        report = check_decay(self.store, tag, window=20, baseline_window=100)
        # 60 - 40 = 20pp drop → critical (>= 20 threshold)
        self.assertEqual(report.decay_signal, "critical")

    def test_warning_signal_on_small_drop(self) -> None:
        tag = "small-drop"
        # baseline: 60% win rate
        for _ in range(60):
            _insert_review(self.store, tag, 1.0, "2025-03-01")
        for _ in range(40):
            _insert_review(self.store, tag, -1.0, "2025-03-02")
        # recent 20: 45% win rate (9 wins) → drop = 15pp → warning
        for _ in range(9):
            _insert_review(self.store, tag, 1.0, "2026-06-01")
        for _ in range(11):
            _insert_review(self.store, tag, -1.0, "2026-06-02")

        report = check_decay(self.store, tag, window=20, baseline_window=100)
        self.assertEqual(report.decay_signal, "warning")


# ---------------------------------------------------------------------------
# OverlapTests
# ---------------------------------------------------------------------------

class OverlapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self.tmp = _make_palace()

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def _add_candidate(self, code: str, rule_version: str, day: str) -> None:
        self.store.record_candidate(
            code=code,
            name=f"股票{code}",
            decision="入选",
            reason="test",
            occurred_on=day,
            pool_id=f"{rule_version}@{day}",
            rule_version=rule_version,
            tier="core",
        )

    def test_identical_picks_full_overlap(self) -> None:
        day = "2026-06-01"
        for code in ("000001", "000002", "000003"):
            self._add_candidate(code, "strat-a", day)
            self._add_candidate(code, "strat-b", day)

        reports = compute_overlap(self.store, days=90)
        self.assertTrue(len(reports) > 0)
        top = reports[0]
        self.assertAlmostEqual(top.avg_jaccard, 1.0, places=3)
        self.assertEqual(top.overlap_level, "high")

    def test_disjoint_picks_zero_overlap(self) -> None:
        day = "2026-06-01"
        for code in ("000001", "000002"):
            self._add_candidate(code, "strat-x", day)
        for code in ("000003", "000004"):
            self._add_candidate(code, "strat-y", day)

        reports = compute_overlap(self.store, days=90)
        self.assertTrue(len(reports) > 0)
        top = reports[0]
        self.assertAlmostEqual(top.avg_jaccard, 0.0, places=3)
        self.assertEqual(top.overlap_level, "low")

    def test_no_strategies_returns_empty(self) -> None:
        reports = compute_overlap(self.store, days=90)
        self.assertEqual(reports, [])

    def test_single_strategy_returns_empty(self) -> None:
        self._add_candidate("000001", "only-one", "2026-06-01")
        reports = compute_overlap(self.store, days=90)
        self.assertEqual(reports, [])


# ---------------------------------------------------------------------------
# PortfolioGuardTests
# ---------------------------------------------------------------------------

class PortfolioGuardTests(unittest.TestCase):
    def test_within_limits_all_allowed(self) -> None:
        limits = PortfolioLimits(max_total_positions=10, max_positions_per_strategy=5)
        picks = [
            {"code": "000001", "rule_version": "strat-a"},
            {"code": "000002", "rule_version": "strat-a"},
        ]
        result = check_portfolio_limits(picks, existing_core=[], limits=limits)
        self.assertEqual(result.allowed_codes, ["000001", "000002"])

    def test_excess_positions_warned_not_dropped(self) -> None:
        limits = PortfolioLimits(max_total_positions=2, max_positions_per_strategy=5)
        existing = [
            {"code": "000099", "rule_version": "strat-z"},
            {"code": "000098", "rule_version": "strat-z"},
        ]
        picks = [
            {"code": "000001", "rule_version": "strat-a"},
            {"code": "000002", "rule_version": "strat-a"},
        ]
        result = check_portfolio_limits(picks, existing_core=existing, limits=limits)
        self.assertEqual(result.allowed_codes, ["000001", "000002"])
        self.assertTrue(len(result.violations) >= 2)
        self.assertTrue(all("未丢弃" in v for v in result.violations))

    def test_per_strategy_limit_warned_not_dropped(self) -> None:
        limits = PortfolioLimits(max_total_positions=20, max_positions_per_strategy=2)
        picks = [
            {"code": "000001", "rule_version": "strat-a"},
            {"code": "000002", "rule_version": "strat-a"},
            {"code": "000003", "rule_version": "strat-a"},
        ]
        result = check_portfolio_limits(picks, existing_core=[], limits=limits)
        self.assertEqual(result.allowed_codes, ["000001", "000002", "000003"])
        self.assertTrue(any("000003" in v and "未丢弃" in v for v in result.violations))

    def test_industry_warning_does_not_drop(self) -> None:
        limits = PortfolioLimits(max_total_positions=20, max_positions_per_strategy=10, max_per_industry=0.30)
        picks = [
            {"code": "000001", "rule_version": "strat-a", "industry": "银行"},
            {"code": "000002", "rule_version": "strat-a", "industry": "银行"},
            {"code": "000003", "rule_version": "strat-a", "industry": "银行"},
            {"code": "000004", "rule_version": "strat-a", "industry": "科技"},
        ]
        result = check_portfolio_limits(picks, existing_core=[], limits=limits)
        # 所有票都应该通过（行业超限只警告）
        self.assertEqual(len(result.allowed_codes), 4)
        # 但应该有行业警告
        industry_violations = [v for v in result.violations if "银行" in v]
        self.assertTrue(len(industry_violations) > 0)

    def test_no_picks_returns_empty(self) -> None:
        result = check_portfolio_limits([], existing_core=[], limits=None)
        self.assertEqual(result.allowed_codes, [])
        self.assertEqual(result.violations, [])

    def test_partial_existing_warns_on_overflow(self) -> None:
        limits = PortfolioLimits(max_total_positions=3, max_positions_per_strategy=5)
        existing = [{"code": "000099", "rule_version": "strat-z"}]
        picks = [
            {"code": "000001", "rule_version": "strat-a"},
            {"code": "000002", "rule_version": "strat-a"},
            {"code": "000003", "rule_version": "strat-a"},
        ]
        result = check_portfolio_limits(picks, existing_core=existing, limits=limits)
        self.assertEqual(len(result.allowed_codes), 3)
        self.assertTrue(any("000003" in v and "未丢弃" in v for v in result.violations))


if __name__ == "__main__":
    unittest.main()
