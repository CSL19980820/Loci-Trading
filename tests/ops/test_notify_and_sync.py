from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.ops.application.jobs import JobContext, execute_sync, run_job
from src.ops.application.notify import (
    NotifyError,
    format_alerts,
    format_screen_result,
    mask_wecom_webhook,
    validate_wecom_webhook,
)
from src.ops.infrastructure.store import MANAGED_SYNC_INTRADAY, OpsStore


class NotifyFormatTests(unittest.TestCase):
    def test_validate_and_mask_webhook(self) -> None:
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef1234567890"
        self.assertEqual(validate_wecom_webhook(url), url)
        masked = mask_wecom_webhook(url)
        self.assertIn("****7890", masked)
        self.assertNotIn("abcdef", masked)
        with self.assertRaises(NotifyError):
            validate_wecom_webhook("https://example.com/hook")

    def test_format_alerts_and_screen(self) -> None:
        text = format_alerts(
            [
                {"status": "ok", "name": "忽略", "code": "000001"},
                {
                    "status": "stop_hit",
                    "name": "楚天科技",
                    "code": "300358",
                    "last_close": 7.5,
                    "note": "破位",
                },
            ]
        )
        self.assertIn("楚天科技", text)
        self.assertIn("触及止损", text)
        screen = format_screen_result(
            {
                "strategy": "demo",
                "trade_date": "2026-07-28",
                "picks": [{"code": "300358", "name": "楚天科技", "score": 80}],
            }
        )
        self.assertIn("demo", screen)
        self.assertIn("300358", screen)


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

            def list_instruments(self):
                return [{"code": "300358", "instrument_type": "STOCK"}]

        def fake_sync_quotes(*_args, **_kwargs):
            called["sync_quotes"] += 1
            raise AssertionError("today_refresh should not call sync_quotes")

        def fake_spot(_store, _codes, instrument_types=None):
            called["spot"] += 1
            return 3

        ctx = JobContext(market_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.sync_instruments", lambda *_a, **_k: None),
            patch("src.market.sync_quotes", fake_sync_quotes),
            patch("src.market.apply_today_spot", fake_spot),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertEqual(result["mode"], "today_refresh")
        self.assertEqual(result["spot_rows"], 3)
        self.assertEqual(called["sync_quotes"], 0)
        self.assertEqual(called["spot"], 1)


class NotifyJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_notify_job_requires_webhook(self) -> None:
        job_id = self.store.create_job(
            name="触价推送", kind="notify", config={"template": "alerts"}
        )
        outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("Webhook", outcome["error"])

    def test_sync_fail_template_skips_when_clean(self) -> None:
        sync_id = self.store.create_job(name="同步", kind="sync")
        run_id = self.store.start_run(self.store.get_job(sync_id), trigger="manual")
        self.store.finish_run(
            run_id, status="success", result={"failed": 0, "succeeded": 10}, duration_ms=1
        )
        notify_id = self.store.create_job(
            name="同步告警",
            kind="notify",
            config={
                "template": "sync_fail",
                "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop",
            },
        )
        with patch("src.ops.application.notify.send_wecom_markdown") as send:
            outcome = run_job(self.store, notify_id, context=JobContext(ops_store=self.store))
            send.assert_not_called()
        self.assertEqual(outcome["status"], "skipped")
        self.assertTrue(outcome["result"]["skipped"])


if __name__ == "__main__":
    unittest.main()
