"""Multi-agent 弹药 + HITL ask_user 单元测试。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.ai.application.agent import run_agent
from src.ai.infrastructure.client import ChatMessage, ChatResponse, ProviderConfig, ToolCall
from src.ai.application.multi_agent import format_subagent_briefs, run_ammo_agents
from src.ai.application.toolbus import build_toolbus
from src.ops import skill_runs
from src.ops.application.skills import load_skill_from_disk


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="test",
        base_url="http://example.invalid",
        api_key="x",
        model="m",
        protocol="openai_compatible",
    )


class MultiAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "ammo-skill"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "scan.py").write_text(
            "print('{\"pool\":[\"600519\"]}')\n", encoding="utf-8"
        )
        (self.root / "SKILL.md").write_text(
            "---\n"
            "name: Ammo Demo\n"
            "slug: ammo-skill\n"
            "description: 测试多 agent 弹药并行\n"
            "tools:\n"
            "  - name: run_scan\n"
            "    kind: cli\n"
            "    command: [python, scripts/scan.py]\n"
            "agents:\n"
            "  - id: scan\n"
            "    role: ammo\n"
            "    kind: cli\n"
            "    tool: run_scan\n"
            "    description: 扫盘\n"
            "  - id: ignored_main\n"
            "    role: main\n"
            "    kind: cli\n"
            "    tool: run_scan\n"
            "---\n\n"
            "根据子 agent 弹药写结论。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parse_agents(self) -> None:
        pkg = load_skill_from_disk("ammo-skill", skill_root=self.root.parent)
        assert pkg is not None
        self.assertEqual(len(pkg.agents), 2)
        self.assertEqual(pkg.agents[0]["id"], "scan")

    def test_run_ammo_cli_only_role_ammo(self) -> None:
        pkg = load_skill_from_disk("ammo-skill", skill_root=self.root.parent)
        assert pkg is not None
        results = run_ammo_agents(pkg.to_record())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "scan")
        self.assertTrue(results[0]["ok"])
        self.assertIn("600519", results[0]["text"])
        briefs = format_subagent_briefs(results)
        self.assertIn("子任务弹药", briefs)
        self.assertIn("[成功]", briefs)


class HitlTests(unittest.TestCase):
    def test_ask_user_pauses_when_hitl_enabled(self) -> None:
        skill = {
            "slug": "hitl",
            "install_path": "",
            "tool_specs": [],
            "allowed_tools": [],
            "mcp_servers": [],
            "agents": [],
        }
        bus = build_toolbus(skill, hitl_enabled=True)
        assert bus is not None
        names = []
        for schema in bus.schemas:
            fn = schema.get("function") or schema
            names.append(fn.get("name"))
        self.assertIn("ask_user", names)

        calls = {"n": 0}

        def fake_chat(config, messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return ChatResponse(
                    text="",
                    model="m",
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="ask_user",
                            arguments={"prompt": "选哪条？", "options": ["1", "2"]},
                        )
                    ],
                    input_tokens=1,
                    output_tokens=1,
                )
            return ChatResponse(text="终稿", model="m", tool_calls=[], input_tokens=1, output_tokens=1)

        with patch("src.ai.application.agent.chat", side_effect=fake_chat):
            first = run_agent(
                _provider(),
                system="sys",
                user_prompt="go",
                tool_schemas=bus.schemas,
                tool_executor=bus.executor,
                allow_hitl=True,
            )
        self.assertEqual(first.stopped_reason, "waiting_user")
        self.assertEqual(first.pending_ask.get("prompt"), "选哪条？")
        self.assertTrue(first.messages)

        # 续跑：追加老板回复后再调一轮
        from src.ai.application.agent import messages_from_json

        resumed = list(messages_from_json(first.messages))
        resumed.append(ChatMessage(role="user", content="老板回复：1"))
        with patch("src.ai.application.agent.chat", side_effect=fake_chat):
            # reset counter so next chat returns final text
            calls["n"] = 0

            def fake_chat2(config, messages, **kwargs):
                return ChatResponse(
                    text="今天就干这一只",
                    model="m",
                    tool_calls=[],
                    input_tokens=1,
                    output_tokens=1,
                )

            with patch("src.ai.application.agent.chat", side_effect=fake_chat2):
                second = run_agent(
                    _provider(),
                    system="sys",
                    messages=resumed,
                    tool_schemas=bus.schemas,
                    tool_executor=bus.executor,
                    allow_hitl=True,
                )
        self.assertEqual(second.stopped_reason, "completed")
        self.assertIn("今天就干", second.text)

    def test_ask_user_errors_without_hitl(self) -> None:
        skill = {
            "slug": "job",
            "install_path": "",
            "tool_specs": [],
            "allowed_tools": [],
            "mcp_servers": [],
            "agents": [],
        }
        bus = build_toolbus(skill, hitl_enabled=False)
        assert bus is not None
        outcome = bus.executor("ask_user", {"prompt": "选？", "options": ["1"]})
        self.assertTrue(outcome["is_error"])
        self.assertIn("无人值守", outcome["text"])


class SkillRunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self._patch = patch("src.ops.application.skill_runs.skill_runs_dir", return_value=Path(self.temp.name))
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.temp.cleanup()

    def test_create_append_load(self) -> None:
        state = skill_runs.create_run(skill="demo", provider="p", config={"a": 1})
        skill_runs.append_event(state["id"], {"type": "phase", "name": "subagents"})
        loaded = skill_runs.load_run(state["id"])
        assert loaded is not None
        self.assertEqual(loaded["skill"], "demo")
        events = skill_runs.list_events(state["id"])
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[-1]["type"], "phase")


class DispatchSubagentsTests(unittest.TestCase):
    def test_dispatch_builtin(self) -> None:
        skill = {
            "slug": "x",
            "install_path": "",
            "tool_specs": [],
            "allowed_tools": [],
            "mcp_servers": [],
            "agents": [],
        }

        def fake_subs(args):
            return [{"id": "scan", "ok": True, "kind": "cli", "text": "pool ok", "description": ""}]

        bus = build_toolbus(skill, hitl_enabled=False, run_subagents=fake_subs)
        assert bus is not None
        out = bus.executor("dispatch_subagents", {"date": "2026-07-28"})
        self.assertFalse(out["is_error"])
        self.assertIn("scan", out["text"])


if __name__ == "__main__":
    unittest.main()
