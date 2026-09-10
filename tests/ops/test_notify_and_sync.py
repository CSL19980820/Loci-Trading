"""通知侧：企微文案格式化、脱敏校验与通知 Job。

同步用例已拆到 `test_sync_jobs.py`。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.ops.application.jobs import JobContext, run_job
from src.ops.application.notify import (
    NotifyError,
    format_alerts,
    format_pct,
    format_screen_picks_text,
    format_screen_result,
    mask_wecom_webhook,
    validate_wecom_webhook,
)
from src.ops.infrastructure.store import OpsStore


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

    def test_weak_market_watch_picks_are_hidden_from_notification(self) -> None:
        text = format_screen_picks_text(
            {
                "strategy": "sanyuan-tail-v1",
                "trade_date": "2026-08-11",
                "picks": [],
                "watch_picks": [
                    {"code": "002963", "name": "豪尔赛", "pct_chg": 1.75},
                    {"code": "301529", "name": "福赛科技", "pct_chg": 1.73},
                ],
            }
        )

        self.assertNotIn("👀 低吸观察", text)
        self.assertNotIn("002963", text)
        self.assertNotIn("301529", text)
        self.assertIn("📭 暂无符合条件的标的", text)

    def test_show_watch_picks_flag_restores_watch_section(self) -> None:
        from src.ops.application.notify_screen_template import normalize_screen_template

        normalized = normalize_screen_template({"show_watch_picks": "true"})
        self.assertTrue(normalized["show_watch_picks"])
        self.assertFalse(
            normalize_screen_template({"show_watch_picks": "false"})["show_watch_picks"]
        )

        text = format_screen_picks_text(
            {
                "strategy": "sanyuan-tail-v1",
                "trade_date": "2026-08-11",
                "picks": [],
                "watch_picks": [{"code": "002963", "name": "豪尔赛", "pct_chg": 1.75}],
            },
            template=normalized,
        )

        self.assertIn("👀 低吸观察（不计正式胜率）", text)
        self.assertIn("▫️ 豪尔赛 002963 +1.75%", text)
        self.assertIn("📭 正式精选 0 只", text)

    def test_request_schema_accepts_every_template_key(self) -> None:
        """前端整份模板原样 PUT 回来；schema 少一个键就是 422「Extra inputs are not permitted」。

        2026-09-04 线上就是这样炸的：formal_empty / watch_header / watch_pick /
        watch_pick_no_pct 早在 DEFAULT_TEMPLATE 里，却一直没进 WecomScreenTemplateModel。
        """
        from src.ops.api.schemas import WecomScreenTemplateModel
        from src.ops.application.notify_screen_template import DEFAULT_TEMPLATE

        self.assertEqual(set(WecomScreenTemplateModel.model_fields), set(DEFAULT_TEMPLATE))
        model = WecomScreenTemplateModel(**{**DEFAULT_TEMPLATE, "watch_header": "👀 观察"})
        self.assertEqual(model.watch_header, "👀 观察")

    def test_watch_picks_stay_out_of_notification_when_formal_picks_exist(self) -> None:
        text = format_screen_picks_text(
            {
                "strategy": "sanyuan-tail-v1",
                "trade_date": "2026-08-11",
                "picks": [{"code": "600018", "name": "上港集团", "pct_chg": 5}],
                "watch_picks": [{"code": "002963", "name": "豪尔赛", "pct_chg": 1.75}],
            }
        )

        self.assertIn("📌 上港集团 600018 +5%", text)
        self.assertNotIn("👀 低吸观察", text)
        self.assertNotIn("002963", text)

    def test_skill_picks_include_clipped_note(self) -> None:
        from src.ops.application.notify_screen_template import clip_skill_note

        long_note = "N" * 55
        clipped = clip_skill_note(long_note)
        self.assertEqual(len(clipped), 40)
        self.assertTrue(clipped.endswith("…"))
        text = format_screen_picks_text(
            {
                "skill_name": "尾盘右侧",
                "picks": [
                    {
                        "code": "600487",
                        "name": "亨通光电",
                        "pct_chg": 3.2,
                        "note": long_note,
                    }
                ],
            },
            kind_tag="技能",
        )
        self.assertIn("【尾盘右侧】-技能", text)
        self.assertIn("📌 亨通光电 600487 +3.2%，" + clipped, text)
        self.assertNotIn(long_note, text)

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

    def test_skill_watch_status_uses_chinese_kind_and_name(self) -> None:
        from src.ops.application.notify import format_job_status

        text = format_job_status(
            job_name="监测·dragon-return",
            kind="skill_watch",
            status="skipped",
        )
        self.assertIn("监测·龙回头", text)
        self.assertIn("类型 监测 · 状态 已跳过", text)
        self.assertNotIn("dragon-return", text)
        self.assertNotIn("skill_watch", text)

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
        self.assertTrue(text.startswith("【RSI22 次日低吸（已下线）】-量化\n"))


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
        with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
            outcome = run_job(self.store, notify_id, context=JobContext(ops_store=self.store))
            send.assert_not_called()
        self.assertEqual(outcome["status"], "skipped")
        self.assertTrue(outcome["result"]["skipped"])

    def test_screen_push_wecom_uses_text_template(self) -> None:
        job_id = self.store.create_job(
            name="screen:sanyuan-tail-v1",
            kind="screen",
            config={"strategy": "sanyuan-tail-v1", "push_wecom": True},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        def fake_executor(_config, _ctx):
            return {
                "strategy": "sanyuan-tail-v1",
                "strategy_name": "三源尾盘共振",
                "picks": [
                    {"code": "300105", "name": "龙星科技", "pct_chg": 1.5},
                    {"code": "600018", "name": "上港集团", "pct_chg": 5.0},
                ],
            }

        with (
            patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": fake_executor}),
            patch("src.ops.application.notify_dispatch.send_wecom_text") as send,
        ):
            send.return_value = {"errcode": 0}
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            send.assert_called_once()
            content = send.call_args.args[1]
        self.assertEqual(outcome["status"], "success")
        self.assertTrue(outcome["result"].get("pushed"))
        self.assertTrue(content.startswith("【三源尾盘共振】-量化\n"))
        self.assertNotIn("screen:", content)
        self.assertNotIn("sanyuan-tail-v1", content)
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
            patch("src.ops.application.notify_dispatch.send_wecom_text") as send,
        ):
            send.return_value = {"errcode": 0}
            first = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            second = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertTrue(first["result"].get("pushed"))
        self.assertEqual(send.call_count, 1)
        self.assertTrue(second["result"].get("push_skipped"))
        self.assertEqual(second["result"].get("reason"), "already_pushed")
        self.assertEqual(second["result"].get("push_day"), "2026-08-03")

    def test_screen_push_wecom_allows_different_time_slots_or_content_same_day(self) -> None:
        """同任务同天不同时点（如 14:50 与 15:30）各自独立推送，同点同内容防重。"""
        job_id = self.store.create_job(
            name="screen:multi-slots",
            kind="screen",
            config={"strategy": "demo", "push_wecom": True},
        )
        self.store.set_setting(
            "wecom_webhook",
            {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefghijklmnop"},
        )

        picks_1450 = [{"code": "002809", "name": "红墙股份", "pct_chg": 4.6, "close": 9.1}]
        picks_1530 = [{"code": "002809", "name": "红墙股份", "pct_chg": 4.37, "close": 9.08}]

        def make_executor(picks):
            def _exec(_config, _ctx):
                return {
                    "strategy": "demo",
                    "trade_date": "2026-08-28",
                    "picks": picks,
                }
            return _exec

        with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
            send.return_value = {"errcode": 0}
            # 模拟 14:50 第一次执行
            with patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": make_executor(picks_1450)}):
                first = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
                # 14:50 再次重跑（同内容同时间）应被拦截
                dup_1450 = run_job(self.store, job_id, context=JobContext(ops_store=self.store))

            self.assertTrue(first["result"].get("pushed"))
            self.assertTrue(dup_1450["result"].get("push_skipped"))
            self.assertEqual(send.call_count, 1)

            # 模拟 15:30 第二次执行（即使同一只票，由于时点和内容不同/指纹不同，允许正常推送）
            with patch.dict("src.ops.application.jobs.registry.EXECUTORS", {"screen": make_executor(picks_1530)}):
                second = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
                # 15:30 再次重跑（同内容同时间）应被拦截
                dup_1530 = run_job(self.store, job_id, context=JobContext(ops_store=self.store))

            self.assertTrue(second["result"].get("pushed"))
            self.assertTrue(dup_1530["result"].get("push_skipped"))
            self.assertEqual(send.call_count, 2)

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
            patch("src.ops.application.notify_dispatch.send_wecom_text") as send,
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
            patch("src.ops.application.notify_dispatch.send_wecom_text") as send,
        ):
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
            send.assert_not_called()
        self.assertEqual(outcome["status"], "success")
        self.assertIsNone(outcome["result"].get("pushed"))


if __name__ == "__main__":
    unittest.main()
