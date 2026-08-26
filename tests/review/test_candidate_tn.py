"""候选 T+N 短线窗口与战法聚合。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.ledger import PalaceStore
from src.market.infrastructure.store import MarketStore
from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.outcome import execute_outcome
from src.ops.infrastructure.store import OpsStore
from src.review import (
    PRIMARY_HORIZONS,
    CandidateOutcome,
    evaluate_candidates,
    filter_recent_outcomes,
    strategy_winrate_summary,
    summarize_by_strategy,
    track_candidate_outcomes,
)

DAYS = [f"2026-03-{day:02d}" for day in range(2, 27)]


def _quotes(closes: list[float], *, spread: float = 0.02) -> pd.DataFrame:
    n = len(closes)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": DAYS[:n],
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "amount": close * 1_000_000.0,
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class CandidateTnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace = PalaceStore(base / "palace.db")
        self.market = MarketStore(base / "market.db")
        rising = [10.0, 10.5, 11.0, 12.0, 13.0, 12.5, 11.5, 11.0, 10.8, 11.2] + [12.0] * 15
        flat = [50.0] * 25
        self.market.upsert_quotes("600001", _quotes(rising))
        self.market.upsert_quotes("000300", _quotes(flat))

    def tearDown(self) -> None:
        self.palace.close()
        self.market.close()
        self.temp.cleanup()

    def test_horizons_include_t1_t3_t5(self) -> None:
        self.assertEqual(PRIMARY_HORIZONS, (1, 3, 5))
        self.palace.record_candidate(
            code="600001",
            name="甲",
            decision="精选",
            reason="r",
            occurred_on=DAYS[0],
            strategy_slug="demo-screen",
            rule_version="demo-screen",
        )
        outcome = evaluate_candidates(self.palace, self.market)[0]
        self.assertIsNotNone(outcome.returns[1])
        self.assertIsNotNone(outcome.returns[3])
        self.assertIsNotNone(outcome.returns[5])
        self.assertEqual(outcome.window_progress()["status"], "complete")
        self.assertEqual(outcome.strategy_tag(), "demo-screen")

    def test_summarize_by_strategy_uses_selected_t5(self) -> None:
        self.palace.record_candidate(
            code="600001",
            name="甲",
            decision="精选",
            reason="r",
            occurred_on=DAYS[0],
            strategy_slug="demo-screen",
        )
        rows = summarize_by_strategy(evaluate_candidates(self.palace, self.market))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_tag"], "demo-screen")
        self.assertEqual(rows[0]["source"], "candidates")
        self.assertGreater(rows[0]["total"], 0)
        self.assertIn("t1", rows[0]["horizons"])
        self.assertIn("t5", rows[0]["horizons"])

    def test_small_sample_winrate_is_marked_low_confidence(self) -> None:
        """一只候选也能报「胜率 100%」；不标样本档等于放任把它当结论。"""
        self.palace.record_candidate(
            code="600001",
            name="甲",
            decision="精选",
            reason="r",
            occurred_on=DAYS[0],
            strategy_slug="demo-screen",
        )
        rows = summarize_by_strategy(evaluate_candidates(self.palace, self.market))
        row = rows[0]
        self.assertEqual(row["total"], 1)
        self.assertEqual(row["sample_confidence"], "low")
        self.assertIn("不宜据此外推", row["caution"])
        self.assertEqual(row["horizons"]["t5"]["sample_confidence"], "low")
        self.assertIn("caution", row["horizons"]["t5"])
        # 胜率口径本身不变，只是多了样本披露
        self.assertEqual(row["win_rate"], row["horizons"]["t5"]["win_rate"])

    def test_reuses_market_series_for_same_code_candidates(self) -> None:
        """同一标的的多池候选不应各自重复读一次日线。"""
        for index, day in enumerate(DAYS[:2]):
            self.palace.record_candidate(
                code="600001",
                name="甲",
                decision="精选",
                reason="r",
                occurred_on=day,
                pool_id=f"pool-{index}",
                strategy_slug="demo-screen",
            )

        with patch.object(
            self.market, "history", wraps=self.market.history
        ) as history, patch.object(
            self.market, "load_panel", wraps=self.market.load_panel
        ) as panel:
            outcomes = evaluate_candidates(self.palace, self.market)

        self.assertEqual(len(outcomes), 2)
        # 候选日线走一次 load_panel 批量取；``history`` 只剩基准指数那一次。
        # 逐票 history 在 2000 条候选上是 2000 次查询，批量后恒为 1 次面板。
        self.assertEqual(panel.call_count, 1)
        self.assertEqual(history.call_count, 1)

    def test_winrate_summary_prefers_candidates(self) -> None:
        self.palace.record_candidate(
            code="600001",
            name="甲",
            decision="精选",
            reason="r",
            occurred_on=DAYS[0],
            strategy_slug="alpha-slug",
        )
        rows = strategy_winrate_summary(self.palace, self.market)
        by_tag = {r["strategy_tag"]: r for r in rows}
        self.assertIn("alpha-slug", by_tag)
        self.assertEqual(by_tag["alpha-slug"]["source"], "candidates")

    def test_track_and_outcome_job(self) -> None:
        self.palace.record_candidate(
            code="600001",
            name="甲",
            decision="精选",
            reason="r",
            occurred_on=DAYS[0],
            strategy_slug="job-screen",
        )
        tracked = track_candidate_outcomes(self.palace, self.market, max_age_trading_days=5)
        self.assertEqual(tracked["horizons"], [1, 3, 5])
        self.assertGreaterEqual(tracked["total_outcomes"], 1)
        self.assertTrue(tracked["by_strategy"])
        # 窗口已走完且早于近 5 日 → recent_selected 可为 0，但 by_strategy 仍有全量样本
        self.assertGreaterEqual(tracked["by_strategy"][0]["total"], 1)

        ops = OpsStore(Path(self.temp.name) / "ops.db")
        try:
            job_id = ops.ensure_managed_outcome_job()
            job = ops.get_job(job_id)
            assert job is not None
            self.assertEqual(job["kind"], "outcome")
            self.assertEqual(job["name"], "候选T+N跟踪")
            result = execute_outcome(
                {},
                JobContext(
                    market_db=str(self.market.db_path),
                    palace_db=str(self.palace.db_path),
                    ops_store=ops,
                ),
            )
            self.assertIn("by_strategy", result)
            self.assertEqual(result["horizons"], [1, 3, 5])
        finally:
            ops.close()

    def test_filter_recent_outcomes_five_trading_days(self) -> None:
        calendar = DAYS[:10]
        as_of = calendar[7]  # index 7 → window [3..7] when window=5
        rows = [
            CandidateOutcome(
                candidate_id=f"c{i}",
                code="600001",
                name="甲",
                base_date=calendar[i],
                decision="精选" if i != 4 else "落选",
                selected=i != 4,
                score=1.0,
                base_close=10.0,
            )
            for i in range(8)
        ]
        kept = filter_recent_outcomes(
            rows, calendar, as_of=as_of, window_days=5, selected_only=True
        )
        self.assertEqual([r.base_date for r in kept], [calendar[3], calendar[5], calendar[6], calendar[7]])


if __name__ == "__main__":
    unittest.main()
