"""AI 决策留痕单测。

留痕要回答的是「模型当时看到什么价、被喂了什么 prompt、原话说了什么」——
缺任何一样，事后都没法判断它凭什么这么判，调 prompt 只能靠猜。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ops.application.jobs.paper_monitor_llm import record_ai_decision
from src.ops.application.share_pack_sanitize import PERSONAL_TABLES
from src.ops.infrastructure.store import OpsStore


class AiDecisionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _payload(self, **over: object) -> dict:
        payload = {
            "slug": "dragon-return",
            "trade_date": "2026-08-11",
            "session_phase": "regular",
            "model": "test-model",
            "system_prompt": "你是纸面执行助手",
            "user_payload": {"positions": [], "plan": {"items": []}},
            "raw_output": '{"orders":[],"notes":"观望"}',
            "parsed_orders": [{"code": "600519", "action": "hold"}],
            "quotes": {"600519": {"price": 1680.0}},
            "status": "ok",
            "latency_ms": 1234,
        }
        payload.update(over)
        return payload

    def test_round_trip_keeps_prompt_and_quote_values(self) -> None:
        decision_id = self.store.insert_ai_decision(self._payload())

        got = self.store.get_ai_decision(decision_id)

        assert got is not None
        self.assertEqual(got["model"], "test-model")
        self.assertEqual(got["system_prompt"], "你是纸面执行助手")
        # 报价的**数值**必须留下，只存代码列表等于没留痕
        self.assertEqual(got["quotes"]["600519"]["price"], 1680.0)
        self.assertEqual(got["raw_output"], '{"orders":[],"notes":"观望"}')
        self.assertEqual(got["latency_ms"], 1234)

    def test_list_omits_bulky_fields_by_default(self) -> None:
        """列表是面板热查询，几十 KB 的 prompt 不能默认拉出来。"""
        self.store.insert_ai_decision(self._payload())

        rows = self.store.list_ai_decisions("dragon-return")

        self.assertEqual(len(rows), 1)
        self.assertNotIn("system_prompt", rows[0])
        self.assertNotIn("quotes", rows[0])
        self.assertEqual(rows[0]["parsed_orders"][0]["code"], "600519")

    def test_list_can_include_prompt_on_demand(self) -> None:
        self.store.insert_ai_decision(self._payload())

        rows = self.store.list_ai_decisions("dragon-return", include_prompt=True)

        self.assertEqual(rows[0]["user_payload"]["plan"]["items"], [])
        self.assertEqual(rows[0]["quotes"]["600519"]["price"], 1680.0)

    def test_records_failure_modes(self) -> None:
        """失语也要留痕——恰恰是这种轮次最需要事后查。"""
        decision_id = self.store.insert_ai_decision(
            self._payload(
                status="unusable",
                error_text="模型未产出可执行 JSON 输出",
                raw_output="我觉得今天应该观望",
                parsed_orders=[],
            )
        )

        got = self.store.get_ai_decision(decision_id)

        assert got is not None
        self.assertEqual(got["status"], "unusable")
        self.assertEqual(got["raw_output"], "我觉得今天应该观望")

    def test_long_text_is_clipped_not_dropped(self) -> None:
        decision_id = self.store.insert_ai_decision(
            self._payload(raw_output="x" * 50_000)
        )

        got = self.store.get_ai_decision(decision_id)

        assert got is not None
        self.assertLess(len(got["raw_output"]), 50_000)
        self.assertIn("已截断", got["raw_output"])

    def test_purge_is_supported(self) -> None:
        """留痕是可重建缓存语义，必须能整表删。"""
        self.store.insert_ai_decision(self._payload())

        removed = self.store.purge_ai_decisions()

        self.assertEqual(removed, 1)
        self.assertEqual(self.store.list_ai_decisions("dragon-return"), [])

    def test_registered_for_share_pack_scrubbing(self) -> None:
        """含 prompt 与报价快照，属个人记录，分享包必须清空。"""
        self.assertIn("ai_decisions", PERSONAL_TABLES)


class RecordAiDecisionTests(unittest.TestCase):
    def test_audit_failure_never_breaks_trading(self) -> None:
        """审计写挂了顶多丢复盘能力，不能把这一轮交易带崩。"""

        class Broken:
            def insert_ai_decision(self, payload: dict) -> str:
                raise RuntimeError("db locked")

        self.assertEqual(record_ai_decision(Broken(), {"slug": "x"}), "")


if __name__ == "__main__":
    unittest.main()
