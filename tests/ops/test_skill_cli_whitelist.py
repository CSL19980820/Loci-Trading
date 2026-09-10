"""技能包 CLI 的 argv 白名单边界。

2026-09 安全审查（RCE-SKILL-CLI-001，critical）：旧 build_command 靠「像不像
路径」决定要不要 jail —— bash / sh / curl / node 既没有路径分隔符也没有后缀，
于是原样入 argv 交给 subprocess 经 PATH 解析。文件 docstring 声称的「可执行路径
必须落在 skill 根内」在实现里根本不成立，而技能包上传与 Skill Run 启动都只需要
write 权限（任意已登录租户），等于容器内任意命令执行。

这个文件钉住白名单的五条边界。它**不声称**技能包整体是沙箱：包内的 run.py 仍然
是上传者可控的任意 Python 代码，那条要靠上传授权管，不是这里。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ops.application.skill_cli import build_command
from src.ops.application.skills import SkillError


class BuildCommandWhitelistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bare_executables_are_rejected(self) -> None:
        """裸可执行名是 critical 的根因：不在白名单、也不是包内文件。"""
        for token in ("bash", "sh", "curl", "node", "powershell"):
            with self.subTest(token=token):
                with self.assertRaises(SkillError) as caught:
                    build_command(self.root, [token, "-x"])
                self.assertIn("已拒绝", str(caught.exception))

    def test_interpreter_plus_packaged_script_is_allowed(self) -> None:
        argv = build_command(self.root, ["python", "scripts/run.py"], {"date": "2026-09-09"})
        self.assertTrue(argv[0].lower().endswith(("python", "python.exe", "python3")))
        self.assertTrue(argv[1].endswith("run.py"))
        self.assertIn("--date", argv)

    def test_packaged_script_as_argv0_must_actually_exist(self) -> None:
        """包内文件可以直接当 argv[0]，但必须真的在包里。"""
        (self.root / "entry.sh").write_text("echo hi", encoding="utf-8")
        argv = build_command(self.root, ["entry.sh"])
        self.assertTrue(argv[0].endswith("entry.sh"))
        with self.assertRaises(SkillError):
            build_command(self.root, ["missing.sh"])

    def test_path_escape_is_still_rejected(self) -> None:
        with self.assertRaises(SkillError):
            build_command(self.root, ["python", "../outside.py"])
        with self.assertRaises(SkillError):
            build_command(self.root, ["../../bin/bash"])

    def test_inline_code_flags_are_rejected(self) -> None:
        """python -c 让 SKILL.md 本身成为可执行载荷，绕过「脚本在包内」。"""
        for flag in ("-c", "-m", "--command"):
            with self.subTest(flag=flag):
                with self.assertRaises(SkillError) as caught:
                    build_command(self.root, ["python", flag, "print(1)"])
                self.assertIn("不允许从命令行喂代码", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
