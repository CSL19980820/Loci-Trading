"""行情同步侧：设置存储、当日刷新与进度上报。

从 `test_notify_and_sync.py` 拆出（原 613 行，通知与同步两条线混在一起）。
通知用例见 `test_notify_and_sync.py`。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.ops.application.jobs import JobContext, execute_sync
from src.ops.infrastructure.store import MANAGED_SYNC_INTRADAY, OpsStore


class MarketSyncSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_settings_kv_and_ensure_job(self) -> None:
        self.store.set_setting("wecom_webhook", {"url": "x"})
        self.assertEqual(self.store.get_setting("wecom_webhook")["url"], "x")
        job_id = self.store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron="*/5 9-14 * * 1-5",
            config={"mode": "full"},
            enabled=True,
        )
        again = self.store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron="*/15 9-14 * * 1-5",
            config={"mode": "full", "workers": 6},
            enabled=False,
        )
        self.assertEqual(job_id, again)
        job = self.store.get_job(job_id)
        self.assertEqual(job["cron"], "*/15 9-14 * * 1-5")
        self.assertFalse(job["enabled"])
        self.assertEqual(job["config"]["workers"], 6)


class TodayRefreshSyncTests(unittest.TestCase):
    def test_today_refresh_skips_sync_quotes(self) -> None:
        called = {"sync_quotes": 0, "spot": 0}

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            @property
            def conn(self):
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

            def trading_days(self, *_args, **_kwargs):
                return []

        def fake_sync_quotes(*_args, **_kwargs):
            called["sync_quotes"] += 1
            raise AssertionError("today_refresh should not call sync_quotes")

        def fake_spot(_store, _codes, **_kwargs):
            called["spot"] += 1
            return 3

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.sync_quotes", fake_sync_quotes),
            patch("src.market.apply_today_spot", fake_spot),
            patch(
                "src.market.infrastructure.sync.refresh_adjust_factors",
                lambda *_a, **_k: 0,
            ),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertEqual(result["mode"], "today_refresh")
        self.assertEqual(result["spot_rows"], 3)
        self.assertEqual(called["sync_quotes"], 0)
        self.assertEqual(called["spot"], 1)
        self.assertEqual(result["factors_error"], "")

    def test_factor_refresh_failure_is_reported_in_result(self) -> None:
        """复权因子刷不动只写日志＝静默失败：除权后 qfq 会长期失真。"""

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

        def boom(*_args, **_kwargs):
            raise RuntimeError("复权源 SSL EOF")

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 1),
            patch("src.market.refresh_adjust_factors", boom),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync(
                {"mode": "today_refresh", "with_factors": True}, ctx
            )

        self.assertEqual(result["factors_refreshed"], 0)
        self.assertIn("复权源 SSL EOF", result["factors_error"])
        # 现价照常补，任务本身不因尽力而为的因子刷新变红
        self.assertEqual(result["spot_rows"], 1)
        self.assertEqual(result["failed"], 0)

    def test_turnover_backfill_failure_is_reported_in_result(self) -> None:
        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

        def boom(*_args, **_kwargs):
            raise RuntimeError("换手率回填炸了")

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 1),
            patch("src.market.refresh_adjust_factors", lambda *_a, **_k: 0),
            patch("src.market.backfill_missing_turnover", boom),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertIn("换手率回填炸了", result["turnover_repair"]["error"])


class SyncProgressTests(unittest.TestCase):
    def test_reports_total_before_first_quote_finishes(self) -> None:
        events: list[tuple[int, int, str]] = []

        def callback(done: int, total: int, code: str) -> None:
            events.append((done, total, code))

        class FakeStore:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def close(self) -> None:
                return None

            @property
            def conn(self):
                return None

            def list_instruments(self):
                return [
                    {"code": "600519", "instrument_type": "STOCK"},
                    {"code": "000001", "instrument_type": "STOCK"},
                ]

            def trading_days(self, *_args, **_kwargs):
                return []

        report = SimpleNamespace(
            total=2,
            succeeded=0,
            skipped=0,
            failed=0,
            rows_written=0,
            failures=[],
            elapsed_seconds=0.0,
            source_receipts=[],
            selected_sources={},
            unresolved_codes=[],
        )

        def fake_sync_quotes(*_args, **kwargs):
            self.assertEqual(events, [(0, 2, "")])
            self.assertIs(kwargs["progress"], callback)
            return report

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.sync_quotes", fake_sync_quotes),
            patch("src.market.apply_today_spot", lambda *_a, **_k: 0),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            execute_sync({}, ctx, progress=callback)
