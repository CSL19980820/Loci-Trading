from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.ops.application.jobs import JobContext, execute_sync, run_job
from src.ops.application.notify import (
    NotifyError,
    format_alerts,
    format_pct,
    format_screen_picks_text,
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
        self.assertNotIn("###", text)
        screen = format_screen_result(
            {
                "strategy": "demo",
                "trade_date": "2026-07-28",
                "picks": [{"code": "300358", "name": "楚天科技", "score": 80}],
            }
        )
        self.assertIn("【demo】-量化", screen)
        self.assertIn("📌 楚天科技 300358", screen)
        self.assertNotIn("###", screen)

    def test_format_screen_picks_text_with_pct_and_skill_tag(self) -> None:
        text = format_screen_picks_text(
            {
                "skill_name": "尾盘狙击",
                "picks": [
                    {"code": "300105", "name": "龙星科技", "pct_chg": 1.5},
                    {"code": "600018", "name": "上港集团", "pct_chg": 5},
                ],
            },
            kind_tag="skills",
            title="尾盘狙击",
        )
        self.assertEqual(
            text,
            "【尾盘狙击】-技能\n📌 龙星科技 300105 +1.5%\n📌 上港集团 600018 +5%",
        )
        self.assertEqual(format_pct(1.5), "+1.5%")
        self.assertEqual(format_pct(5), "+5%")
        self.assertEqual(format_pct(-2.3), "-2.3%")

    def test_legacy_english_skill_tag_is_normalized_to_chinese(self) -> None:
        from src.ops.application.notify_screen_template import normalize_screen_template

        template = normalize_screen_template({"skills_tag": "skills"})
        self.assertEqual(template["skills_tag"], "技能")

    def test_failed_screen_status_does_not_expose_internal_slug(self) -> None:
        from src.ops.application.notify import format_job_status

        text = format_job_status(
            job_name="screen:qianlong-close-v3",
            kind="screen",
            status="failed",
            error="行情刷新失败",
        )
        self.assertIn("【任务✗ 潜龙出海（V3）】", text)
        self.assertIn("类型 选股 · 状态 失败", text)
        self.assertNotIn("screen", text)
        self.assertNotIn("failed", text)

    def test_screen_template_presets_and_custom(self) -> None:
        from src.ops.application.notify_screen_template import (
            normalize_screen_template,
            preview_screen_template,
        )

        compact = normalize_screen_template({"preset": "compact"})
        compact_text = format_screen_picks_text(
            {
                "strategy": "demo",
                "picks": [{"code": "300105", "name": "龙星科技", "pct_chg": 1.5}],
            },
            template=compact,
        )
        self.assertIn("【demo】-量化", compact_text)
        self.assertNotIn("选股如下", compact_text)

        dated = normalize_screen_template({"preset": "with_date"})
        dated_text = format_screen_picks_text(
            {
                "strategy": "demo",
                "trade_date": "2026-07-30",
                "picks": [{"code": "300105", "name": "龙星科技", "pct_chg": 1.5}],
            },
            template=dated,
        )
        self.assertIn("📅 2026-07-30", dated_text)

        custom = normalize_screen_template(
            {
                "preset": "custom",
                "header": "#{title}/{kind}",
                "intro": "",
                "pick": "{code}|{name}|{pct}",
                "quant_tag": "战法",
            }
        )
        custom_text = format_screen_picks_text(
            {
                "strategy": "潜龙",
                "picks": [{"code": "300105", "name": "龙星科技", "pct_chg": 1.5}],
            },
            kind_tag=custom["quant_tag"],
            template=custom,
        )
        self.assertEqual(custom_text, "#潜龙/战法\n300105|龙星科技|+1.5%")
        preview = preview_screen_template(custom, kind="quant")
        self.assertIn("战法", preview)

    def test_builtin_slug_is_rendered_with_chinese_title(self) -> None:
        text = format_screen_picks_text(
            {"strategy": "rsi30-dip", "picks": [{"code": "000001", "name": "平安银行"}]}
        )
        self.assertTrue(text.startswith("【RSI22 次日低吸】-量化\n"))


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
            patch(
                "src.market.infrastructure.sync.refresh_adjust_factors",
                lambda *_a, **_k: 0,
            ),
        ):
            result = execute_sync({"mode": "today_refresh"}, ctx)

        self.assertEqual(result["mode"], "today_refresh")
        self.assertEqual(result["spot_rows"], 3)
        self.assertEqual(called["sync_quotes"], 0)
        self.assertEqual(called["spot"], 1)


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

            def list_instruments(self):
                return [
                    {"code": "600519", "instrument_type": "STOCK"},
                    {"code": "000001", "instrument_type": "STOCK"},
                ]

        report = SimpleNamespace(
            total=2,
            succeeded=0,
            skipped=0,
            failed=0,
            rows_written=0,
            failures=[],
            elapsed_seconds=0.0,
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
        ):
            execute_sync({}, ctx, progress=callback)


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
        with patch("src.ops.application.notify.send_wecom_text") as send:
            outcome = run_job(self.store, notify_id, context=JobContext(ops_store=self.store))
            send.assert_not_called()
        self.assertEqual(outcome["status"], "skipped")
        self.assertTrue(outcome["result"]["skipped"])

    def test_screen_push_wecom_uses_text_template(self) -> None:
        job_id = self.store.create_job(
            name="screen:demo",
            kind="screen",
            config={"strategy": "demo", "push_wecom": True},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        def fake_executor(_config, _ctx):
            return {
                "strategy": "demo",
                "picks": [
                    {"code": "300105", "name": "龙星科技", "pct_chg": 1.5},
                    {"code": "600018", "name": "上港集团", "pct_chg": 5.0},
                ],
            }

        with (
            patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": fake_executor}),
            patch("src.ops.application.notify.send_wecom_text") as send,
        ):
            send.return_value = {"errcode": 0}
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            send.assert_called_once()
            content = send.call_args.args[1]
        self.assertEqual(outcome["status"], "success")
        self.assertTrue(outcome["result"].get("pushed"))
        self.assertIn("【demo】-量化", content)
        self.assertIn("📌 龙星科技 300105 +1.5%", content)
        self.assertIn("📌 上港集团 600018 +5%", content)
        self.assertNotIn("msgtype", content)

    def test_screen_push_wecom_skips_second_send_same_day(self) -> None:
        job_id = self.store.create_job(
            name="screen:demo-once",
            kind="screen",
            config={"strategy": "demo", "push_wecom": True},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        def fake_executor(_config, _ctx):
            return {
                "strategy": "demo",
                "trade_date": "2026-08-03",
                "picks": [{"code": "300105", "name": "龙星科技", "pct_chg": 1.5}],
            }

        with (
            patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": fake_executor}),
            patch("src.ops.application.notify.send_wecom_text") as send,
        ):
            send.return_value = {"errcode": 0}
            first = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            second = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertTrue(first["result"].get("pushed"))
        self.assertEqual(send.call_count, 1)
        self.assertTrue(second["result"].get("push_skipped"))
        self.assertEqual(second["result"].get("reason"), "already_pushed")
        self.assertEqual(second["result"].get("push_day"), "2026-08-03")

    def test_skill_push_wecom_uses_skills_template(self) -> None:
        job_id = self.store.create_job(
            name="skill:demo",
            kind="skill",
            config={"skill": "demo", "provider": "x", "push_wecom": True},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        def fake_executor(_config, _ctx):
            return {
                "skill": "demo",
                "skill_name": "演示技能",
                "picks": [{"code": "300105", "name": "龙星科技", "pct_chg": 2.0}],
            }

        with (
            patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"skill": fake_executor}),
            patch("src.ops.application.notify.send_wecom_text") as send,
        ):
            send.return_value = {"errcode": 0}
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            send.assert_called_once()
            content = send.call_args.args[1]
        self.assertEqual(outcome["status"], "success")
        self.assertTrue(outcome["result"].get("pushed"))
        self.assertIn("演示技能", content)
        self.assertIn("龙星科技", content)

    def test_push_wecom_off_skips_send(self) -> None:
        job_id = self.store.create_job(
            name="screen:demo",
            kind="screen",
            config={"strategy": "demo", "push_wecom": False},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        def fake_executor(_config, _ctx):
            return {"strategy": "demo", "picks": [{"code": "300105", "name": "龙星"}]}

        with (
            patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": fake_executor}),
            patch("src.ops.application.notify.send_wecom_text") as send,
        ):
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            send.assert_not_called()
        self.assertEqual(outcome["status"], "success")
        self.assertIsNone(outcome["result"].get("pushed"))


if __name__ == "__main__":
    unittest.main()
