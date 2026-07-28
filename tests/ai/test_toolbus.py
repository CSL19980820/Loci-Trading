"""ToolBus / Skill CLI 单元测试。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ai.application.toolbus import build_toolbus
from src.ops.application.skill_cli import build_command, run_skill_cli
from src.ops.application.skills import SkillError, load_skill_from_disk, parse_manifest


class SkillCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "echo_args.py").write_text(
            "import sys\nprint(' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_command_jails_script_path(self) -> None:
        argv = build_command(self.root, ["python", "scripts/echo_args.py"], {"date": "2026-07-28"})
        self.assertTrue(argv[1].endswith("echo_args.py"))
        self.assertIn("--date", argv)
        self.assertIn("2026-07-28", argv)

    def test_path_escape_rejected(self) -> None:
        with self.assertRaises(SkillError):
            build_command(self.root, ["python", "../outside.py"])

    def test_run_cli_returns_stdout(self) -> None:
        result = run_skill_cli(
            self.root,
            ["python", "scripts/echo_args.py"],
            arguments={"hello": "world"},
        )
        self.assertFalse(result["is_error"])
        self.assertIn("world", result["text"])


class ToolBusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "demo-skill"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "hi.py").write_text(
            "print('skill-cli-ok')\n", encoding="utf-8"
        )
        (self.root / "SKILL.md").write_text(
            "---\n"
            "name: Demo Skill\n"
            "slug: demo-skill\n"
            "description: 测试 CLI 工具总线\n"
            "tools:\n"
            "  - name: say_hi\n"
            "    description: 打印一行确认\n"
            "    kind: cli\n"
            "    command: [python, scripts/hi.py]\n"
            "    timeout_sec: 30\n"
            "---\n\n"
            "调用 say_hi 后总结输出。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_load_tool_specs_from_frontmatter(self) -> None:
        pkg = load_skill_from_disk("demo-skill", skill_root=self.root.parent)
        self.assertIsNotNone(pkg)
        assert pkg is not None
        self.assertEqual(len(pkg.tool_specs), 1)
        self.assertEqual(pkg.tool_specs[0]["name"], "say_hi")
        self.assertEqual(pkg.tool_specs[0]["kind"], "cli")

    def test_toolbus_executes_cli(self) -> None:
        pkg = load_skill_from_disk("demo-skill", skill_root=self.root.parent)
        assert pkg is not None
        bus = build_toolbus(pkg.to_record(), protocol="openai_compatible")
        self.assertIsNotNone(bus)
        assert bus is not None
        # CLI + 内置 ask_user / write_journal / dispatch_subagents
        self.assertGreaterEqual(len(bus.schemas), 4)
        outcome = bus.executor("say_hi", {})
        self.assertFalse(outcome["is_error"])
        self.assertIn("skill-cli-ok", outcome["text"])

    def test_parse_trading_policy(self) -> None:
        meta, _ = parse_manifest(
            "---\nname: X\ndescription: d\npolicy: trading_voice\nisolation: skill_only\n---\n\nbody\n"
        )
        from src.ops.application.skills import _meta_isolation, _meta_policy

        self.assertEqual(_meta_policy(meta), "trading_voice")
        self.assertEqual(_meta_isolation(meta), "skill_only")


if __name__ == "__main__":
    unittest.main()
