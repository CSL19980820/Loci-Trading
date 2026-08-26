from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ops.application.skills import (
    SkillError,
    discover_skills,
    install_skill_dir,
    sync_skills_from_templates,
)

GOOD_MANIFEST = """---
name: 模板战法
slug: tpl-alpha
version: 1.0.0
description: 模板同步测试
---

# 步骤

1. 做一件事
"""


class SyncSkillTemplatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.template_root = self.base / "templates" / "skills"
        self.skill_root = self.base / "data" / "skills"
        self.template_root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_template(self, slug: str, *, manifest: str = GOOD_MANIFEST) -> Path:
        folder = self.template_root / slug
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(manifest, encoding="utf-8")
        return folder

    def test_sync_installs_all_templates(self) -> None:
        self._write_template("tpl-alpha")
        self._write_template("tpl-beta", manifest=GOOD_MANIFEST.replace("tpl-alpha", "tpl-beta"))

        result = sync_skills_from_templates(
            template_root=self.template_root,
            skill_root=self.skill_root,
        )

        self.assertEqual(result["total"], 2)
        self.assertEqual(sorted(result["installed"]), ["tpl-alpha", "tpl-beta"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["errors"], [])
        slugs = {pkg.slug for pkg in discover_skills(skill_root=self.skill_root)}
        self.assertEqual(slugs, {"tpl-alpha", "tpl-beta"})

    def test_sync_respects_slug_filter(self) -> None:
        self._write_template("tpl-alpha")
        self._write_template("tpl-beta", manifest=GOOD_MANIFEST.replace("tpl-alpha", "tpl-beta"))

        result = sync_skills_from_templates(
            template_root=self.template_root,
            skill_root=self.skill_root,
            slugs=["tpl-beta"],
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["installed"], ["tpl-beta"])
        slugs = {pkg.slug for pkg in discover_skills(skill_root=self.skill_root)}
        self.assertEqual(slugs, {"tpl-beta"})

    def test_sync_skips_existing_when_not_overwriting(self) -> None:
        source = self._write_template("tpl-alpha")
        install_skill_dir(source, skill_root=self.skill_root)

        result = sync_skills_from_templates(
            template_root=self.template_root,
            skill_root=self.skill_root,
            overwrite=False,
        )

        self.assertEqual(result["installed"], [])
        self.assertEqual(result["skipped"], ["tpl-alpha"])
        self.assertEqual(result["errors"], [])

    def test_sync_reports_missing_template_root(self) -> None:
        missing = self.base / "nope" / "skills"
        result = sync_skills_from_templates(
            template_root=missing,
            skill_root=self.skill_root,
        )
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["installed"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("不存在", result["errors"][0]["error"])

    def test_sync_collects_invalid_template_errors(self) -> None:
        bad = self.template_root / "bad-skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n\n", encoding="utf-8")
        self._write_template("tpl-alpha")

        result = sync_skills_from_templates(
            template_root=self.template_root,
            skill_root=self.skill_root,
        )

        self.assertEqual(result["installed"], ["tpl-alpha"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["slug"], "bad-skill")
        self.assertIn("正文为空", result["errors"][0]["error"])

    def test_sync_rejects_invalid_slug_filter(self) -> None:
        self._write_template("tpl-alpha")
        result = sync_skills_from_templates(
            template_root=self.template_root,
            skill_root=self.skill_root,
            slugs=["../../etc"],
        )
        self.assertEqual(result["installed"], [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(len(result["errors"]), 1)
        with self.assertRaises(SkillError):
            from src.ops.application.skills import _normalise_slug

            _normalise_slug("../../etc")


if __name__ == "__main__":
    unittest.main()
