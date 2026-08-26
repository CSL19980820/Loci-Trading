from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from src.ops.application.skills import (
    MAX_ARCHIVE_BYTES,
    SkillError,
    install_skill,
    parse_manifest,
    read_skill_file,
    uninstall_skill,
)

GOOD_MANIFEST = """---
name: 龙回头复盘
slug: dragon-return
version: 1.2.0
description: 扫描龙回头形态并生成复盘简报
tools:
  - get_quotes_daily
  - run_screen
risk_note: 仅供研究
---

# 龙回头复盘

1. 取当日全市场行情
2. 按龙回头规则筛选
3. 输出结论与待核验项
"""


def _make_zip(path: Path, files: dict[str, bytes | str]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return path


class ManifestParsingTests(unittest.TestCase):
    def test_splits_frontmatter_and_body(self) -> None:
        meta, body = parse_manifest(GOOD_MANIFEST)
        self.assertEqual(meta["slug"], "dragon-return")
        self.assertIn("龙回头复盘", body)
        self.assertNotIn("---", body.splitlines()[0])

    def test_scheduling_fields_are_rejected(self) -> None:
        manifest = "---\nname: demo\ndescription: test\ncron: '30 15 * * 1-5'\n---\nbody\n"
        with self.assertRaisesRegex(SkillError, "调度字段"):
            parse_manifest(manifest)
        nested = (
            "---\nname: demo\ndescription: test\n"
            "monitor:\n  schedule:\n    interval_minutes: 10\n---\nbody\n"
        )
        with self.assertRaisesRegex(SkillError, "monitor.schedule"):
            parse_manifest(nested)

    def test_missing_frontmatter_is_rejected(self) -> None:
        with self.assertRaises(SkillError) as ctx:
            parse_manifest("# 只有正文，没有元数据\n")
        self.assertIn("frontmatter", str(ctx.exception))

    def test_malformed_yaml_is_rejected(self) -> None:
        with self.assertRaises(SkillError):
            parse_manifest("---\nname: [unclosed\n---\nbody\n")

    def test_non_mapping_frontmatter_is_rejected(self) -> None:
        with self.assertRaises(SkillError):
            parse_manifest("---\n- just\n- a\n- list\n---\nbody\n")


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install(self, files: dict[str, bytes | str], **kwargs):
        archive = _make_zip(self.work / "pkg.zip", files)
        return install_skill(archive, skill_root=self.root, **kwargs)

    def test_installs_and_parses_metadata(self) -> None:
        package = self._install(
            {"SKILL.md": GOOD_MANIFEST, "references/rules.md": "# 规则明细\n"}
        )
        self.assertEqual(package.slug, "dragon-return")
        self.assertEqual(package.name, "龙回头复盘")
        self.assertEqual(package.version, "1.2.0")
        self.assertEqual(package.allowed_tools, ["get_quotes_daily", "run_screen"])
        self.assertIn("risk_note", package.metadata)
        self.assertIn("references/rules.md", package.files)
        self.assertTrue((self.root / "dragon-return" / "SKILL.md").is_file())

    def test_slug_defaults_to_name_when_absent(self) -> None:
        manifest = "---\nname: my-scan\ndescription: 测试\n---\n步骤一\n"
        package = self._install({"SKILL.md": manifest})
        self.assertEqual(package.slug, "my-scan")

    def test_handles_the_common_extra_top_level_folder(self) -> None:
        """zip 常见的"多套一层目录"，不该因此装不上。"""
        package = self._install({"dragon-return-1.2.0/SKILL.md": GOOD_MANIFEST})
        self.assertEqual(package.slug, "dragon-return")
        self.assertTrue((self.root / "dragon-return" / "SKILL.md").is_file())

    def test_reinstall_replaces_previous_content(self) -> None:
        self._install({"SKILL.md": GOOD_MANIFEST, "old.md": "旧文件"})
        self._install({"SKILL.md": GOOD_MANIFEST, "new.md": "新文件"})
        self.assertFalse((self.root / "dragon-return" / "old.md").exists())
        self.assertTrue((self.root / "dragon-return" / "new.md").exists())

    def test_overwrite_can_be_refused(self) -> None:
        self._install({"SKILL.md": GOOD_MANIFEST})
        with self.assertRaises(SkillError):
            self._install({"SKILL.md": GOOD_MANIFEST}, overwrite=False)

    def test_failed_replace_keeps_previous_content(self) -> None:
        self._install({"SKILL.md": GOOD_MANIFEST, "old.md": "旧文件"})
        with patch("src.ops.application.skill_files.shutil.move", side_effect=RuntimeError("move failed")):
            with self.assertRaises(RuntimeError):
                self._install({"SKILL.md": GOOD_MANIFEST, "new.md": "新文件"})
        self.assertTrue((self.root / "dragon-return" / "old.md").exists())
        self.assertFalse((self.root / "dragon-return" / "new.md").exists())

    def test_records_content_hash_for_provenance(self) -> None:
        package = self._install({"SKILL.md": GOOD_MANIFEST})
        self.assertEqual(len(package.content_sha256), 64)


class ManifestValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install(self, files):
        return install_skill(_make_zip(self.work / "pkg.zip", files), skill_root=self.root)

    def test_missing_skill_md_is_rejected(self) -> None:
        with self.assertRaises(SkillError) as ctx:
            self._install({"readme.md": "# 没有 SKILL.md"})
        self.assertIn("SKILL.md", str(ctx.exception))

    def test_missing_description_is_rejected(self) -> None:
        """没有 description，模型就无从判断什么时候该用这个技能。"""
        with self.assertRaises(SkillError) as ctx:
            self._install({"SKILL.md": "---\nname: x\n---\n正文\n"})
        self.assertIn("description", str(ctx.exception))

    def test_empty_body_is_rejected(self) -> None:
        with self.assertRaises(SkillError) as ctx:
            self._install({"SKILL.md": "---\nname: x\ndescription: 有描述\n---\n\n"})
        self.assertIn("正文", str(ctx.exception))

    def test_illegal_slug_is_rejected(self) -> None:
        manifest = "---\nname: x\nslug: ../escape\ndescription: 有描述\n---\n正文\n"
        with self.assertRaises(SkillError) as ctx:
            self._install({"SKILL.md": manifest})
        self.assertIn("非法的技能标识", str(ctx.exception))


class ArchiveSecurityTests(unittest.TestCase):
    """每条都对应一种真实攻击。解压前拦截，而不是解完再检查。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install(self, files):
        return install_skill(_make_zip(self.work / "pkg.zip", files), skill_root=self.root)

    def test_rejects_zip_slip_relative_escape(self) -> None:
        """条目名含 ..，解压会逃出目标目录覆盖任意文件。"""
        with self.assertRaises(SkillError) as ctx:
            self._install({"SKILL.md": GOOD_MANIFEST, "../../evil.md": "pwned"})
        self.assertIn("Zip Slip", str(ctx.exception))
        self.assertFalse((Path(self.temp.name) / "evil.md").exists())

    def test_rejects_absolute_path_entry(self) -> None:
        with self.assertRaises(SkillError) as ctx:
            self._install({"SKILL.md": GOOD_MANIFEST, "/etc/cron.d/evil": "pwned"})
        self.assertIn("绝对路径", str(ctx.exception))

    def test_rejects_windows_drive_path(self) -> None:
        with self.assertRaises(SkillError):
            self._install({"SKILL.md": GOOD_MANIFEST, "C:/Windows/evil.md": "pwned"})

    def test_rejects_symlink_entries(self) -> None:
        """zip 可以存符号链接，指向 /etc/shadow 之类后读它就等于读系统文件。"""
        archive_path = self.work / "pkg.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("SKILL.md", GOOD_MANIFEST)
            info = zipfile.ZipInfo("link.md")
            info.external_attr = (0o120777 << 16)  # symlink 模式位
            archive.writestr(info, "/etc/shadow")
        with self.assertRaises(SkillError) as ctx:
            install_skill(archive_path, skill_root=self.root)
        self.assertIn("符号链接", str(ctx.exception))

    def test_rejects_executable_payloads(self) -> None:
        """技能包是指令与资料，不是原生二进制可执行程序。"""
        for name in ("evil.so", "evil.dll", "evil.exe"):
            with self.subTest(name=name), self.assertRaises(SkillError) as ctx:
                self._install({"SKILL.md": GOOD_MANIFEST, name: b"\x00binary"})
            self.assertIn("不允许的文件类型", str(ctx.exception))

    def test_rejects_zip_bomb_by_declared_size(self) -> None:
        """几十 KB 解出几百 MB，按解压后总大小拦截。"""
        archive_path = self.work / "bomb.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("SKILL.md", GOOD_MANIFEST)
            archive.writestr("payload.txt", b"\0" * (250 * 1024 * 1024))
        with self.assertRaises(SkillError) as ctx:
            install_skill(archive_path, skill_root=self.root)
        self.assertIn("zip 炸弹", str(ctx.exception))

    def test_rejects_too_many_entries(self) -> None:
        files = {"SKILL.md": GOOD_MANIFEST}
        files.update({f"ref/{i}.md": "x" for i in range(2100)})
        with self.assertRaises(SkillError) as ctx:
            self._install(files)
        self.assertIn("条目过多", str(ctx.exception))

    def test_rejects_non_zip_file(self) -> None:
        plain = self.work / "not-a-zip.zip"
        plain.write_text("just text", encoding="utf-8")
        with self.assertRaises(SkillError) as ctx:
            install_skill(plain, skill_root=self.root)
        self.assertIn("合法的 zip", str(ctx.exception))

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(SkillError):
            install_skill(self.work / "nope.zip", skill_root=self.root)

    def test_a_rejected_package_leaves_nothing_behind(self) -> None:
        """安装失败必须不留残骸，否则下次会读到半个包。"""
        with self.assertRaises(SkillError):
            self._install({"SKILL.md": GOOD_MANIFEST, "../evil.md": "pwned"})
        self.assertFalse((self.root / "dragon-return").exists())


class SkillFileAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir(parents=True)
        install_skill(
            _make_zip(
                self.work / "pkg.zip",
                {"SKILL.md": GOOD_MANIFEST, "references/rules.md": "# 细则\n"},
            ),
            skill_root=self.root,
        )
        (Path(self.temp.name) / "outside.md").write_text("机密", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_reads_bundled_reference(self) -> None:
        text = read_skill_file("dragon-return", "references/rules.md", skill_root=self.root)
        self.assertIn("细则", text)

    def test_cannot_escape_the_skill_directory(self) -> None:
        """技能之间不能互相读，更不能读到包外面去。"""
        with self.assertRaises(SkillError) as ctx:
            read_skill_file("dragon-return", "../../outside.md", skill_root=self.root)
        self.assertIn("路径越界", str(ctx.exception))

    def test_missing_file_reports_clearly(self) -> None:
        with self.assertRaises(SkillError):
            read_skill_file("dragon-return", "nope.md", skill_root=self.root)

    def test_uninstall_removes_the_directory(self) -> None:
        self.assertTrue(uninstall_skill("dragon-return", skill_root=self.root))
        self.assertFalse((self.root / "dragon-return").exists())
        self.assertFalse(uninstall_skill("dragon-return", skill_root=self.root))

    def test_uninstall_rejects_traversal(self) -> None:
        with self.assertRaises(SkillError):
            uninstall_skill("../../etc", skill_root=self.root)


if __name__ == "__main__":
    unittest.main()
