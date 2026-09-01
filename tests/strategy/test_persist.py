"""选股结果入库与进度快照。"""
from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ledger import PalaceStore
from src.strategy.application.persist import (
    BACKFILL_SOURCE,
    factor_reason,
    persist_screen_candidates,
    score_from_factors,
)
from src.strategy.application.screen_run import (
    execute_screen_run,
    screen_run_snapshot,
    screen_run_try_begin,
    screen_run_update,
    start_screen_run_thread,
)


class PersistScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = f"{self.tmp.name}/palace.db"
        self.store = PalaceStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_factor_reason_truncates_and_formats(self) -> None:
        text = factor_reason("qianlong", {"a": 1.234, "b": True, "c": "x", "d": 2.0, "score": 88.5})
        self.assertIn("潜龙选中", text)
        self.assertIn("评分=88.50", text)
        self.assertIn("a=1.23", text)
        self.assertNotIn("True", text)

    def test_score_from_factors_maps_roc5_to_pct(self) -> None:
        self.assertEqual(score_from_factors({"ROC5": 1.085}), 8.5)
        self.assertEqual(score_from_factors({"ROC5": 0.95}), 0.0)
        self.assertEqual(score_from_factors({"ROC5": 2.5}), 100.0)
        self.assertEqual(score_from_factors({"score": 77.0}), 77.0)
        self.assertEqual(score_from_factors({"白线贴近度": 0.995, "ROC5": 1.15}), 99.5)

    def test_persist_writes_and_overwrites_same_day(self) -> None:
        result = SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="a" * 64,
            trade_date="2026-07-28",
            entry_timing="next_open",
            params={"N": 20},
            effective_params={"N": 30},
            picks=[
                {"code": "600519", "factors": {"score": 88.0}},
                {"code": "000001", "factors": {"score": 70.5}},
            ],
        )
        first = persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600519": "茅台", "000001": "平安"},
            source="test",
        )
        self.assertEqual(first["written"], 2)
        self.assertEqual(first["pool_id"], "demo@2026-07-28")

        result.picks = [{"code": "600519", "factors": {"score": 91.0}}]
        second = persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600519": "茅台"},
            source="test",
        )
        self.assertEqual(second["written"], 1)
        self.assertEqual(second["removed"], 2)

        rows = self.store.candidates_payload("2026-07-28")
        pool_rows = [row for row in rows if row.get("pool_id") == "demo@2026-07-28"]
        self.assertEqual(len(pool_rows), 1)
        persisted = pool_rows[0]
        self.assertEqual(persisted["code"], "600519")
        self.assertEqual(persisted["strategy_slug"], "demo")
        self.assertEqual(persisted["strategy_revision"], "a" * 64)
        self.assertEqual(persisted["effective_params"], {"N": 30})
        self.assertNotIn("_strategy_revision", persisted["evidence"])
        self.assertNotIn("_effective_params", persisted["evidence"])

    def test_watch_picks_are_persisted_as_observe_not_selected(self) -> None:
        result = SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="rev-watch",
            trade_date="2026-08-11",
            entry_timing="next_open",
            params={},
            effective_params={},
            picks=[{"code": "600001", "factors": {"score": 88.0}}],
            watch_picks=[{"code": "600002", "factors": {"score": 77.0}}],
        )

        outcome = persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600001": "正式票", "600002": "观察票"},
            source="job:screen",
        )

        self.assertEqual(outcome["written"], 2)
        self.assertEqual(outcome["formal_written"], 1)
        self.assertEqual(outcome["watch_written"], 1)
        rows = {
            row["code"]: row
            for row in self.store.candidates_payload("2026-08-11")
        }
        self.assertEqual(rows["600001"]["decision"], "精选")
        self.assertEqual(rows["600001"]["tier"], "core")
        self.assertEqual(rows["600002"]["decision"], "观察")
        self.assertEqual(rows["600002"]["tier"], "watch")
        self.assertIn("弱市低吸观察", rows["600002"]["reason"])

    def test_backfill_does_not_clobber_live_screen(self) -> None:
        """区间回填不得删除 job:screen / api:screen_run 真选。"""
        day = "2026-07-30"
        result = SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="rev1",
            trade_date=day,
            entry_timing="next_open",
            params={},
            effective_params={},
            picks=[{"code": "600519", "factors": {"score": 88.0}}],
        )
        persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600519": "茅台"},
            source="job:screen",
        )
        # 对齐写入日=选股日，模拟盘后当日落库
        self.store.conn.execute(
            "UPDATE candidate_reviews SET created_at = ? WHERE occurred_on = ?",
            (f"{day}T15:30:00+08:00", day),
        )
        self.store.conn.commit()

        result.picks = [{"code": "000001", "factors": {"score": 70.0}}]
        backfill = persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"000001": "平安"},
            source=BACKFILL_SOURCE,
        )
        self.assertEqual(backfill["removed"], 0)
        self.assertEqual(backfill["written"], 1)

        live = self.store.candidates_by_strategy("demo", live_only=True)
        self.assertEqual([row["code"] for row in live], ["600519"])
        self.assertEqual(live[0]["source"], "job:screen")

        all_rows = self.store.candidates_by_strategy("demo", live_only=False)
        codes = sorted(row["code"] for row in all_rows)
        self.assertEqual(codes, ["000001", "600519"])

    def test_live_only_excludes_next_day_writes(self) -> None:
        """即使源不是 backfill，隔日写入也不进首页真选。"""
        result = SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="rev1",
            trade_date="2026-07-29",
            entry_timing="next_open",
            params={},
            effective_params={},
            picks=[{"code": "600519", "factors": {"score": 88.0}}],
        )
        persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600519": "茅台"},
            source="api:screen_run",
        )
        self.store.conn.execute(
            "UPDATE candidate_reviews SET created_at = ? WHERE occurred_on = ?",
            ("2026-07-31T10:00:00+08:00", "2026-07-29"),
        )
        self.store.conn.commit()
        self.assertEqual(
            self.store.candidates_by_strategy("demo", live_only=True),
            [],
        )
        self.assertEqual(
            len(self.store.candidates_by_strategy("demo", live_only=False)),
            1,
        )

    def test_persist_zero_picks_clears_same_day_pool(self) -> None:
        result = SimpleNamespace(
            strategy_slug="demo",
            strategy_revision="rev1",
            trade_date="2026-07-28",
            entry_timing="next_open",
            params={},
            effective_params={},
            picks=[{"code": "600519", "factors": {"score": 88.0}}],
        )
        persist_screen_candidates(
            result,
            palace_db=self.db,
            names={"600519": "茅台"},
            source="test",
        )
        result.picks = []
        cleared = persist_screen_candidates(result, palace_db=self.db, source="test")
        self.assertEqual(cleared["written"], 0)
        self.assertEqual(cleared["removed"], 1)
        rows = [
            row
            for row in self.store.candidates_payload("2026-07-28")
            if row.get("pool_id") == "demo@2026-07-28"
        ]
        self.assertEqual(rows, [])


class ScreenRunStateTests(unittest.TestCase):
    def test_try_begin_rejects_when_running(self) -> None:
        screen_run_update(status="idle", log=[])
        first = screen_run_try_begin(strategy="demo", trade_date="2026-07-28")
        self.assertIsNone(first)
        snap = screen_run_snapshot()
        self.assertEqual(snap["status"], "running")
        # 同一战法防重；换个战法则并行放行（见 test_screen_run_multi.py）。
        busy = screen_run_try_begin(strategy="demo", trade_date="")
        self.assertIsNotNone(busy)
        self.assertEqual(busy["strategy"], "demo")
        self.assertEqual(busy["busy_reason"], "same_strategy")
        self.assertIsNone(screen_run_try_begin(strategy="other", trade_date=""))
        screen_run_update(status="idle", result=None, error="", log=[], strategy="other")
        screen_run_update(status="idle", result=None, error="", log=[])

    def test_thread_start_failure_moves_run_to_error(self) -> None:
        """线程资源耗尽时不能把选股进度永久留在 running。"""
        def broken_spawn(*args: object, **kwargs: object) -> None:
            raise RuntimeError("no thread slots")

        screen_run_update(status="idle", result=None, error="", log=[])
        try:
            with patch(
                "src.strategy.application.screen_run.spawn_tenant_thread",
                broken_spawn,
            ):
                snap = start_screen_run_thread(
                    {"strategy": "demo", "date": "2026-07-28"},
                    market_factory=lambda: None,
                    palace_db=None,
                )
            self.assertEqual(snap["status"], "error")
            self.assertEqual(snap["phase"], "error")
            self.assertIn("no thread slots", snap["error"])
        finally:
            screen_run_update(status="idle", result=None, error="", log=[])

    def test_range_screen_reuses_one_market_snapshot(self) -> None:
        class FakeMarketStore:
            def __init__(self) -> None:
                self.snapshot_calls = 0

            def __enter__(self) -> "FakeMarketStore":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            def trading_days(self, *, start: str, end: str) -> list[str]:
                return [start, end]

            def list_instruments(self, *, status: str) -> list[dict[str, str]]:
                return []

            def coverage(self) -> dict[str, str]:
                return {}

            def data_snapshot(self) -> dict[str, str]:
                self.snapshot_calls += 1
                return {"market_revision": "fixed"}

        market = FakeMarketStore()
        snapshots: list[dict[str, str] | None] = []

        def fake_screen(*args: object, **kwargs: object) -> SimpleNamespace:
            snapshot = kwargs.get("data_snapshot")
            snapshots.append(snapshot if isinstance(snapshot, dict) else None)
            return SimpleNamespace(
                strategy_slug="demo",
                strategy_revision="rev1",
                trade_date=str(kwargs["trade_date"]),
                entry_timing="next_open",
                universe_size=0,
                elapsed_seconds=0.01,
                params={},
                effective_params={},
                picks=[],
                health=None,
                universe={},
                universe_funnel={},
                data_snapshot=dict(snapshot or {}),
            )

        screen_run_update(status="idle", log=[])
        with patch("src.strategy.screen", side_effect=fake_screen):
            execute_screen_run(
                {
                    "strategy": "demo",
                    "start": "2026-07-30",
                    "end": "2026-07-31",
                    "record_candidates": False,
                    "skip_health_check": True,
                },
                market_factory=lambda: market,
                palace_db=None,
            )

        self.assertEqual(screen_run_snapshot()["status"], "done")
        self.assertEqual(market.snapshot_calls, 1)
        self.assertEqual(snapshots, [{"market_revision": "fixed"}] * 2)
        screen_run_update(status="idle", result=None, error="", log=[])

    def test_screen_run_refreshes_spot_when_window_includes_today(self) -> None:
        """窗口含今天时先保证当日行情就绪，再跑选股（与 job:screen 对齐）。"""
        from datetime import date

        today = date.today().isoformat()
        ensure_calls: list[list[str]] = []

        class Market:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def trading_days(self, start=None, end=None):
                return [today]

            def data_snapshot(self):
                return {"market_revision": "spot-fixed"}

            def coverage(self):
                return {"last_date": today}

            def list_instruments(self, status=None):
                return [
                    {"code": "600519", "name": "茅台", "instrument_type": "STOCK"},
                    {"code": "000001", "name": "平安", "instrument_type": "STOCK"},
                ]

        def fake_ensure(store, codes, **_kw):
            ensure_calls.append(list(codes))
            return {
                "status": "refreshed",
                "written": len(codes),
                "requested": len(codes),
                "message": f"当日现价已刷新，写入 {len(codes)} 行",
                "coverage": {"ratio": 1.0},
            }

        def fake_screen(store, strategy, **kwargs):
            return SimpleNamespace(
                strategy_slug=str(strategy),
                strategy_revision="rev1",
                trade_date=str(kwargs["trade_date"]),
                entry_timing="close",
                universe_size=2,
                elapsed_seconds=0.01,
                params={},
                effective_params={},
                picks=[{"code": "600519", "factors": {"score": 1.0}}],
                health=None,
                universe={},
                universe_funnel={},
                data_snapshot=dict(kwargs.get("data_snapshot") or {}),
            )

        screen_run_update(status="idle", log=[])
        with (
            patch("src.strategy.screen", side_effect=fake_screen),
            patch(
                "src.market.application.screen_spot.ensure_today_quotes_for_screen",
                side_effect=fake_ensure,
            ),
        ):
            execute_screen_run(
                {
                    "strategy": "qianlong-close-v3",
                    "start": today,
                    "end": today,
                    "record_candidates": False,
                    "skip_health_check": True,
                },
                market_factory=Market,
                palace_db=None,
            )

        snap = screen_run_snapshot()
        self.assertEqual(snap["status"], "done")
        self.assertEqual(len(ensure_calls), 1)
        self.assertEqual(ensure_calls[0], ["600519", "000001"])
        self.assertTrue(any("当日" in line for line in snap["log"]))
        screen_run_update(status="idle", result=None, error="", log=[])

    def test_screen_run_can_skip_spot_refresh(self) -> None:
        from datetime import date

        today = date.today().isoformat()

        class Market:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def trading_days(self, start=None, end=None):
                return [today]

            def data_snapshot(self):
                return {}

            def coverage(self):
                return {"last_date": today}

            def list_instruments(self, status=None):
                return [{"code": "600519", "name": "茅台", "instrument_type": "STOCK"}]

        def boom(*_a, **_k):
            raise AssertionError("refresh_spot=false 不应准备当日行情")

        def fake_screen(store, strategy, **kwargs):
            return SimpleNamespace(
                strategy_slug=str(strategy),
                strategy_revision="",
                trade_date=str(kwargs["trade_date"]),
                entry_timing="close",
                universe_size=1,
                elapsed_seconds=0.01,
                params={},
                effective_params={},
                picks=[],
                health=None,
                universe={},
                universe_funnel={},
                data_snapshot={},
            )

        screen_run_update(status="idle", log=[])
        with (
            patch("src.strategy.screen", side_effect=fake_screen),
            patch(
                "src.market.application.screen_spot.ensure_today_quotes_for_screen",
                side_effect=boom,
            ),
        ):
            execute_screen_run(
                {
                    "strategy": "demo",
                    "start": today,
                    "end": today,
                    "record_candidates": False,
                    "skip_health_check": True,
                    "refresh_spot": False,
                },
                market_factory=Market,
                palace_db=None,
            )
        self.assertEqual(screen_run_snapshot()["status"], "done")
        screen_run_update(status="idle", result=None, error="", log=[])


class RemediationTests(unittest.TestCase):
    def test_coverage_has_sync_remediation(self) -> None:
        from src.market.infrastructure.sentinel import Finding, remediation_for

        self.assertEqual(remediation_for("coverage")["action"], "sync")
        payload = Finding("coverage", "block", "low").to_dict()
        self.assertEqual(payload["remediation"]["label"], "补齐当日覆盖")
        self.assertIsNone(remediation_for("unknown_check"))

    def test_turnover_remediation_is_backfill(self) -> None:
        from src.market.infrastructure.sentinel import remediation_for

        rem = remediation_for("turnover")
        self.assertEqual(rem["action"], "repair_turnover")
        self.assertIn("换手", rem["label"])


if __name__ == "__main__":
    unittest.main()
