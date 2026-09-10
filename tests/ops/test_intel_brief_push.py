"""悟道简报 → 企微：取数格式、纯文本渲染、分片、四档托管任务与推送闸门。

为什么这些点值得单测：

1. **格式**：不传 ``format`` 时 ``content[0].text`` 只是一行带省略号的 headline，
   全文只在 ``detailLevel=raw`` 的 ``rawData[0].content.fullContent``，且是 Markdown。
   这条一旦回退（比如有人把 ``detailLevel`` 去掉「省点体积」），推出去的就是半句话。
2. **「还没出稿」不是失败**：悟道 09:00 出稿会延迟，我们刻意晚 10 分钟触发。
   把未出稿判成 failed，四档任务每天刷四个红叉。
3. **分片按字节**：企微 text 上限是 2048 **字节**，中文一字三字节。按字数切会
   悄悄超限。
4. **防重**：一档一天只推一条；悟道重算过（``generatedAt`` 变了）才允许再推。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.intel.application.briefing import (
    BRIEFING_SLOTS,
    briefing_arguments,
    briefing_body_text,
    briefing_header,
    markdown_to_text,
    parse_briefing,
    resolve_slot,
)
from src.ops.application.ensure_intel_brief_jobs import (
    MANAGED_BRIEF_SPECS,
    ensure_managed_intel_brief_jobs,
    managed_brief_job_names,
)
from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.intel_brief import (
    execute_intel_brief,
)
from src.ops.application.jobs.registry import EXECUTORS
from src.ops.application.notify import (
    WECOM_TEXT_MAX_BYTES,
    split_text_for_wecom,
)
from src.ops.application.wecom_push_mark import shanghai_today
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import JOB_KINDS

FULL_MARKDOWN = """### 【30秒核心】

地缘风险骤然升级，国际油价应声大涨，布油突破90美元。

---

### 【隔夜要闻】

#### 1. 宏观政策

- **房地产“超级政策包”落地**：央行等多部门联合发文（新闻14）。
  - 事件影响：政策力度超预期。
  - 相关公司：[万科A(000002)](https://stock.quicktiny.cn/quote/000002)

### 【⚠️ 风险提示】

- **地缘政治风险**：冲突升级。
  - 风险等级：高
"""


def _payload(
    *,
    date: str,
    status: str = "published",
    generated_at: str = "2026-08-31T01:00:17.159Z",
    full_text: str = FULL_MARKDOWN,
    count: int = 1,
) -> dict:
    """与 ``call_mcp_tool`` 同形的载荷：``structured`` 已被解包成服务端 ``data`` 段。"""
    items = []
    raw_data = []
    if count:
        items.append(
            {
                "type": "opening",
                "date": date,
                "time": "09:00",
                "status": status,
                "coreSummary": "地缘风险骤然升级。",
                "generatedAt": generated_at,
                "hotTopics": [{"title": "房地产政策包"}],
                "risks": [{"content": "地缘政治风险", "level": "medium"}],
            }
        )
        raw_data.append({"content": {"fullContent": full_text}})
    return {
        "tool": "briefings",
        "server": "wudao",
        "text": "地缘风险骤然升级，国际油价应声大涨…",
        "is_error": False,
        "cached": False,
        "structured": {
            "success": True,
            "data": {"count": count, "items": items, "headline": "地缘风险骤然升级…"},
            "rawData": raw_data,
        },
    }


class BriefingFormatTests(unittest.TestCase):
    def test_arguments_ask_for_raw_detail_only(self) -> None:
        """``detailLevel=raw`` 是全文的必要条件；``format`` **刻意不传**。

        全文在 ``structuredContent.rawData[0].content.fullContent``，由
        ``fetch._resolve_structured`` 专门保住（解包成 ``data`` 段时 ``rawData`` 是兄弟节点，
        原先会整段丢掉——线上实测推出去只剩 410 字的摘要兜底）。改用 ``format=json`` 把全文
        塞进 ``text`` 那条路走不通：``McpClient`` 对正文有 12000 字截断，raw 档 JSON 实测 41KB。
        """
        args = briefing_arguments("open", trade_date="2026-08-31")
        self.assertEqual(args["type"], "opening")
        self.assertEqual(args["detailLevel"], "raw")
        self.assertEqual(args["date"], "2026-08-31")
        self.assertNotIn("format", args)

    def test_full_text_survives_structured_unwrapping(self) -> None:
        """生产载荷形状：``structured`` 是解包后的 ``data`` 段 + 保住的 ``rawData``。"""
        raw = _payload(date="2026-08-31")
        unwrapped = {
            **raw,
            "structured": {
                **raw["structured"]["data"],
                "rawData": raw["structured"]["rawData"],
            },
            "text": "地缘风险骤然升级，国际油价应声大涨…",
        }
        doc = parse_briefing(unwrapped, slot="open")
        assert doc is not None
        self.assertIn("【隔夜要闻】", briefing_body_text(doc))
        self.assertGreater(len(doc.full_text), 200)

    def test_resolve_structured_keeps_raw_data(self) -> None:
        """这条不变量在 fetch 侧：解包 ``data`` 时必须把 ``rawData`` 带过去。"""
        from src.intel.application.fetch import _resolve_structured

        result = {
            "structured": {
                "tool": "briefings",
                "success": True,
                "data": {"count": 1, "items": [{"type": "opening"}]},
                "rawData": [{"content": {"fullContent": "### 【30秒核心】"}}],
            },
            "text": "headline",
        }
        structured = _resolve_structured(result)
        assert structured is not None
        self.assertEqual(structured["count"], 1)
        self.assertIn("rawData", structured)
        self.assertEqual(
            structured["rawData"][0]["content"]["fullContent"], "### 【30秒核心】"
        )

    def test_slots_cover_four_daily_briefings(self) -> None:
        self.assertEqual(
            [kind for kind, _label, _at in BRIEFING_SLOTS.values()],
            ["opening", "midday", "closing", "evening"],
        )
        self.assertEqual(
            [at for _kind, _label, at in BRIEFING_SLOTS.values()],
            ["09:00", "12:00", "15:30", "21:00"],
        )

    def test_resolve_slot_accepts_server_type_names(self) -> None:
        self.assertEqual(resolve_slot("closing"), "close")
        self.assertEqual(resolve_slot("midday"), "midday")
        self.assertEqual(resolve_slot("premarket"), "open")
        self.assertEqual(resolve_slot(""), "open")

    def test_parse_returns_none_when_not_published(self) -> None:
        self.assertIsNone(parse_briefing(_payload(date="2026-08-31", count=0), slot="open"))
        self.assertIsNone(
            parse_briefing(_payload(date="2026-08-31", status="draft"), slot="open")
        )
        self.assertIsNone(parse_briefing({"is_error": True}, slot="open"))
        self.assertIsNone(parse_briefing(None, slot="open"))

    def test_markdown_becomes_plain_text(self) -> None:
        doc = parse_briefing(_payload(date="2026-08-31"), slot="open")
        assert doc is not None
        text = briefing_body_text(doc)
        # 企微不渲染 markdown：井号、星号、分割线、链接语法都不许留在正文里
        self.assertNotIn("###", text)
        self.assertNotIn("**", text)
        self.assertNotIn("---", text)
        self.assertNotIn("](http", text)
        # 可见内容保留，链接只留文字
        self.assertIn("【30秒核心】", text)
        self.assertIn("万科A(000002)", text)
        self.assertIn("· 房地产“超级政策包”落地", text)

    def test_header_marks_ai_origin(self) -> None:
        doc = parse_briefing(_payload(date="2026-08-31"), slot="open")
        assert doc is not None
        header = briefing_header(doc)
        self.assertIn("开盘简报", header)
        self.assertIn("2026-08-31", header)
        self.assertIn("悟道 AI", header)

    def test_fingerprint_tracks_regeneration(self) -> None:
        first = parse_briefing(_payload(date="2026-08-31"), slot="open")
        same = parse_briefing(_payload(date="2026-08-31"), slot="open")
        again = parse_briefing(
            _payload(date="2026-08-31", generated_at="2026-08-31T03:00:00.000Z"), slot="open"
        )
        assert first is not None and same is not None and again is not None
        self.assertEqual(first.fingerprint, same.fingerprint)
        self.assertNotEqual(first.fingerprint, again.fingerprint)

    def test_digest_fallback_without_full_text(self) -> None:
        doc = parse_briefing(_payload(date="2026-08-31", full_text=""), slot="open")
        assert doc is not None
        text = briefing_body_text(doc)
        self.assertIn("【核心】", text)
        self.assertIn("房地产政策包", text)

    def test_markdown_to_text_is_total(self) -> None:
        self.assertEqual(markdown_to_text(""), "")
        self.assertEqual(markdown_to_text("# 标题"), "标题")


class WecomChunkTests(unittest.TestCase):
    def test_chunks_respect_byte_budget(self) -> None:
        body = "隔夜英伟达财报超预期暴涨，带动纳指收涨。" * 60
        chunks = split_text_for_wecom(body, limit_bytes=1800)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode("utf-8")), WECOM_TEXT_MAX_BYTES)
            self.assertLessEqual(len(chunk.encode("utf-8")), 1800)
        # 分片不许丢内容
        self.assertEqual("".join(chunks).replace("\n", ""), body.replace("\n", ""))

    def test_short_text_stays_one_chunk(self) -> None:
        self.assertEqual(split_text_for_wecom("一句话"), ["一句话"])
        self.assertEqual(split_text_for_wecom("   "), [])

    def test_truncation_is_explicit(self) -> None:
        body = "地缘风险骤然升级。" * 400
        chunks = split_text_for_wecom(body, limit_bytes=1800, max_chunks=2)
        self.assertEqual(len(chunks), 2)
        self.assertIn("已截断", chunks[-1])
        self.assertLessEqual(len(chunks[-1].encode("utf-8")), 1800)


class ManagedBriefJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(str(Path(self.temp.name) / "ops.db"))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_kind_registered_on_both_sides(self) -> None:
        self.assertIn("intel_brief", JOB_KINDS)
        self.assertIn("intel_brief", EXECUTORS)

    def test_schedule_is_ten_minutes_after_upstream(self) -> None:
        """比悟道出稿晚 10 分钟，且每档多个触发点兜它的延迟。"""
        crons = dict((slot, cron) for slot, _name, cron in MANAGED_BRIEF_SPECS)
        self.assertEqual(crons["open"], "10,25,40 9 * * mon-fri")
        self.assertEqual(crons["midday"], "10,25,40 12 * * mon-fri")
        self.assertEqual(crons["close"], "40,55 15 * * mon-fri")
        self.assertEqual(crons["evening"], "10,25,40 21 * * mon-fri")
        for cron in crons.values():
            self.assertIn("mon-fri", cron, "工作日必须写 mon-fri，1-5 会整周跳过周一")

    def test_create_is_idempotent_and_keeps_user_switches(self) -> None:
        first = ensure_managed_intel_brief_jobs(self.store)
        self.assertEqual(len(first["created"]), 4)
        self.assertEqual(first["updated"], [])

        job = self.store.get_job_by_name("简报·晚间")
        assert job is not None
        self.assertTrue(job["enabled"])
        self.assertEqual(job["config"]["slot"], "evening")
        self.assertTrue(job["config"]["push_wecom"])

        self.store.update_job(
            job["id"],
            enabled=False,
            cron="15 21 * * mon-fri",
            config={**job["config"], "push_wecom": False, "max_chunks": 2},
        )
        second = ensure_managed_intel_brief_jobs(self.store)
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["updated"]), 4)

        after = self.store.get_job_by_name("简报·晚间")
        assert after is not None
        self.assertFalse(after["enabled"], "用户关掉的简报任务不能被重启复活")
        self.assertEqual(after["cron"], "15 21 * * mon-fri")
        self.assertFalse(after["config"]["push_wecom"])
        self.assertEqual(after["config"]["max_chunks"], 2)
        self.assertEqual(after["config"]["slot"], "evening")

    def test_store_wrapper_creates_all_four(self) -> None:
        self.store.ensure_managed_intel_brief_jobs()
        for name in managed_brief_job_names():
            self.assertIsNotNone(self.store.get_job_by_name(name), name)

    def test_managed_jobs_do_not_eat_user_quota(self) -> None:
        """四条简报任务必须被 ``job_quota`` 认成托管，否则会吃掉用户 5 条自建额度。"""
        from src.ops.application.job_quota import is_managed_job, managed_job_names

        names = managed_job_names()
        for name in managed_brief_job_names():
            self.assertIn(name, names, name)
            self.assertTrue(is_managed_job({"name": name, "kind": "intel_brief"}), name)


class BriefPushExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = OpsStore(str(root / "ops.db"))
        self.context = JobContext(
            market_db=str(root / "market.db"),
            ops_store=self.store,
            job_id="job-brief-open",
        )
        self.sent: list[dict] = []

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _dispatch(self, store, **kwargs):  # noqa: ANN001, ANN003
        self.sent.append(kwargs)
        return {"success": True, "sent": ["wecom"], "errors": []}

    def _run(self, payload, config=None, dispatch=None):  # noqa: ANN001
        with patch("src.intel.wudao_availability", return_value={"available": True}), patch(
            "src.intel.application.briefing.fetch_briefing_payload", return_value=payload
        ), patch(
            "src.ops.application.notify_dispatch.dispatch_text", dispatch or self._dispatch
        ):
            return execute_intel_brief(dict(config or {"slot": "open"}), self.context)

    def test_pushes_chunks_and_blocks_repeat(self) -> None:
        payload = _payload(date=shanghai_today())
        result = self._run(payload)
        self.assertTrue(result["pushed"])
        self.assertGreaterEqual(result["sent_chunks"], 1)
        self.assertTrue(result["full_text_used"])
        self.assertEqual(len(self.sent), result["chunks"])
        body = self.sent[0]["body"]
        self.assertIn("开盘简报", body)
        self.assertIn("悟道 AI", body)
        self.assertNotIn("###", body)
        # 正文自带标题，别让企微再前缀一次
        self.assertFalse(self.sent[0]["prepend_title_to_wecom"])


    def test_pushes_chunks_in_order_with_interval(self) -> None:
        """验证分片按 1/N 到 N/N 严格顺序发送，且每片之间有间隔防止服务端时序错乱。"""
        payload = _payload(date=shanghai_today(), full_text=FULL_MARKDOWN * 20)
        slept: list[float] = []
        with patch("src.ops.application.jobs.intel_brief.time.sleep", side_effect=slept.append):
            result = self._run(payload, config={"slot": "open", "chunk_interval_sec": 1.5})
        self.assertTrue(result["pushed"])
        self.assertGreater(result["chunks"], 1)
        total = result["chunks"]
        self.assertEqual(len(self.sent), total)
        # 验证标记按（1/total）,（2/total）... 严格单调递增
        for idx, item in enumerate(self.sent, start=1):
            self.assertIn(f"（{idx}/{total}）", item["body"])
        # N 片消息共间隔 N-1 次
        self.assertEqual(len(slept), total - 1)
        for interval in slept:
            self.assertEqual(interval, 1.5)
        self.sent.clear()
        again = self._run(payload)
        self.assertTrue(again["skipped"])
        self.assertEqual(again["reason"], "already_pushed")
        self.assertEqual(self.sent, [])

    def test_skips_when_wudao_missing(self) -> None:
        with patch(
            "src.intel.wudao_availability",
            return_value={"available": False, "reason": "未配置 API Key"},
        ):
            result = execute_intel_brief({"slot": "open"}, self.context)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "mcp_unavailable")
        self.assertIn("未配置 API Key", result["summary"])

    def test_skips_when_not_published_yet(self) -> None:
        result = self._run(_payload(date=shanghai_today(), count=0))
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "not_published")
        self.assertEqual(self.sent, [])

    def test_skips_stale_briefing_from_previous_day(self) -> None:
        result = self._run(_payload(date="2020-01-02"))
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "stale_briefing")
        self.assertEqual(self.sent, [])

    def test_push_switch_off_only_fetches(self) -> None:
        result = self._run(
            _payload(date=shanghai_today()), config={"slot": "open", "push_wecom": False}
        )
        self.assertFalse(result["pushed"])
        self.assertEqual(result["push_skipped"], "push_disabled")
        self.assertEqual(self.sent, [])
        self.assertGreater(result["chars"], 0)

    def test_quiet_hours_is_skipped_not_failed(self) -> None:
        def quiet(store, **kwargs):  # noqa: ANN001, ANN003
            return {"success": False, "skipped": "quiet_hours", "sent": []}

        result = self._run(_payload(date=shanghai_today()), dispatch=quiet)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "quiet_hours")

    def test_dispatch_failure_is_reported(self) -> None:
        def broken(store, **kwargs):  # noqa: ANN001, ANN003
            return {"success": False, "sent": [], "error": "企微 Webhook 未配置"}

        result = self._run(_payload(date=shanghai_today()), dispatch=broken)
        self.assertFalse(result["pushed"])
        self.assertIn("企微 Webhook 未配置", result["push_error"])

    def test_unavailable_payload_is_soft_skip(self) -> None:
        payload = {
            "is_error": True,
            "unavailable": True,
            "unavailable_reason": "配额用尽",
            "structured": None,
        }
        result = self._run(payload)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "mcp_unavailable")

    def test_status_push_is_suppressed_for_brief_runs(self) -> None:
        """正文由执行器自己分片推；通用「任务状态」推送必须闭嘴，否则一天 12 条噪音。"""
        from src.ops.application.jobs.notify import _maybe_push_wecom

        job = {
            "id": "job-brief-open",
            "name": "简报·开盘",
            "kind": "intel_brief",
            "config": {"slot": "open", "push_wecom": True},
        }
        for status in ("success", "skipped"):
            outcome = _maybe_push_wecom(
                store=self.store,
                job=job,
                status=status,
                result={"slot": "open", "pushed": True, "chunks": 5},
            )
            assert outcome is not None
            self.assertTrue(outcome.get("push_skipped"), status)
            self.assertEqual(outcome.get("push_reason"), "brief_pushes_its_own_body")
                # 别用 reason：那是执行器写「为什么跳过」的键，合并时会被盖掉

    def test_push_error_is_not_green(self) -> None:
        """简报取回来了却一条都没发出去 → 运行必须记 failed（这条任务的价值就是发到人手上）。"""
        from src.ops.application.jobs import registry

        job_id = self.store.create_job(
            name="简报·开盘",
            kind="intel_brief",
            cron="10,25,40 9 * * mon-fri",
            config={"slot": "open", "push_wecom": True},
            enabled=True,
        )
        job = self.store.get_job(job_id)
        assert job is not None

        def fake_executor(config, context):  # noqa: ANN001, ARG001
            return {"slot": "open", "pushed": False, "push_error": "企微 Webhook 未配置"}

        with patch.dict(registry.EXECUTORS, {"intel_brief": fake_executor}), patch.object(
            registry, "_maybe_push_wecom", return_value=None
        ):
            outcome = registry.run_job(self.store, job, context=self.context)
        self.assertEqual(outcome["status"], "failed")

        def skipped_executor(config, context):  # noqa: ANN001, ARG001
            return {"slot": "open", "skipped": True, "reason": "quiet_hours"}

        with patch.dict(registry.EXECUTORS, {"intel_brief": skipped_executor}), patch.object(
            registry, "_maybe_push_wecom", return_value=None
        ):
            outcome = registry.run_job(self.store, job, context=self.context)
        self.assertEqual(outcome["status"], "skipped", "刻意没发不是故障")

if __name__ == "__main__":
    unittest.main()
