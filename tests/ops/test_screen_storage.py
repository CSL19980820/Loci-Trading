from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from src.ops.application.screen import (
    ScreenPackageError,
    delete_screen_history,
    delete_screen_package,
    get_screen_package,
    list_screen_history,
    read_screen_archive,
    restore_screen_package,
    save_screen_package,
)
from src.ops.application.screen.storage import archive_declares_screen_capability


def _screen_files(slug: str = "demo-screen") -> dict[str, str]:
    return {
        "SKILL.md": (
            "---\n"
            f"slug: {slug}\n"
            "name: 示例战法\n"
            "version: 0.1.0\n"
            "description: 用于测试\n"
            "capability: screen\n"
            "enabled: true\n"
            "---\n\n"
            "放量均线战法。\n"
        ),
        "screen.yaml": (
            "schema_version: 1\n"
            "entry_timing: next_open\n"
            "min_bars: 5\n"
            "params:\n"
            "  N: { type: int, default: 3, min: 2, max: 10, label: 周期 }\n"
            "signal: PICK\n"
            "factors: [BASE]\n"
        ),
        "formula.tdx": "BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n",
        "references/readme.md": "# 说明\n",
    }


def _python_files(slug: str = "python-screen") -> dict[str, str]:
    return {
        "SKILL.md": (
            "---\n"
            f"slug: {slug}\n"
            "name: Python 战法\n"
            "version: 0.1.0\n"
            "description: Python 包测试\n"
            "capability: screen\n"
            "enabled: true\n"
            "---\n\n"
            "测试本地 Python 依赖导入。\n"
        ),
        "screen.yaml": (
            "schema_version: 2\n"
            "runtime: python\n"
            "dialect: python\n"
            "entrypoint: strategy.py:compute\n"
            "entry_timing: next_open\n"
            "min_bars: 5\n"
            "params:\n"
            "  N: { type: int, default: 3, min: 2, max: 10, label: 周期 }\n"
            "output:\n"
            "  signal: PICK\n"
            "factors: [BASE]\n"
            "data:\n"
            "  fields: [close, volume]\n"
            "  adjust: qfq\n"
            "  universe:\n"
            "    codes_include: [\"600001\"]\n"
        ),
        "strategy.py": (
            "from helpers import build_signal\n\n"
            "def compute(panels, params):\n"
            "    return build_signal(panels['close'])\n"
        ),
        "helpers.py": (
            "def build_signal(close):\n"
            "    return {'signals': close > close.rolling(2).mean(), 'factors': {}}\n"
        ),
    }


def _screen_archive(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(name, data)
    return path


class ScreenStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_save_load_and_delete_with_revision_lock(self) -> None:
        created = save_screen_package("demo-screen", _screen_files(), skill_root_path=self.root)
        self.assertEqual(created.slug, "demo-screen")
        self.assertTrue(created.package_revision)
        self.assertTrue(created.updated_at)

        loaded = get_screen_package("demo-screen", skill_root_path=self.root)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.package_revision, created.package_revision)

        changed = _screen_files()
        changed["formula.tdx"] = "BASE:=MA(CLOSE,N);\nPICK: CLOSE>=BASE;\n"
        updated = save_screen_package(
            "demo-screen",
            changed,
            expected_revision=created.package_revision,
            skill_root_path=self.root,
        )
        self.assertNotEqual(updated.package_revision, created.package_revision)

        with self.assertRaises(ScreenPackageError):
            save_screen_package(
                "demo-screen",
                changed,
                expected_revision=created.package_revision,
                skill_root_path=self.root,
            )

        self.assertTrue(
            delete_screen_package(
                "demo-screen",
                expected_revision=updated.package_revision,
                skill_root_path=self.root,
            )
        )
        self.assertIsNone(get_screen_package("demo-screen", skill_root_path=self.root))

    def test_failed_archive_during_update_keeps_previous_version(self) -> None:
        created = save_screen_package("demo-screen", _screen_files(), skill_root_path=self.root)
        changed = _screen_files()
        changed["formula.tdx"] = "BASE:=MA(CLOSE,N);\nPICK: CLOSE>=BASE;\n"
        with patch(
            "src.ops.application.screen.storage._archive_snapshot",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                save_screen_package(
                    "demo-screen",
                    changed,
                    expected_revision=created.package_revision,
                    skill_root_path=self.root,
                )
        loaded = get_screen_package("demo-screen", skill_root_path=self.root)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.package_revision, created.package_revision)

    def test_failed_delete_restores_previous_version(self) -> None:
        created = save_screen_package("demo-screen", _screen_files(), skill_root_path=self.root)
        real_rmtree = shutil.rmtree

        def fail_delete(path, *args, **kwargs):
            if Path(path).name.startswith(".screen-delete-demo-screen-"):
                raise RuntimeError("boom")
            return real_rmtree(path, *args, **kwargs)

        with patch("src.ops.application.screen.storage.shutil.rmtree", side_effect=fail_delete):
            with self.assertRaises(RuntimeError):
                delete_screen_package(
                    "demo-screen",
                    expected_revision=created.package_revision,
                    skill_root_path=self.root,
                )
        loaded = get_screen_package("demo-screen", skill_root_path=self.root)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.package_revision, created.package_revision)

    def test_history_restore_and_deleted_archive_does_not_reappear(self) -> None:
        first = save_screen_package("demo-screen", _screen_files(), skill_root_path=self.root)
        changed = _screen_files()
        changed["formula.tdx"] = "BASE:=MA(CLOSE,N);\nPICK: CLOSE>=BASE;\n"
        second = save_screen_package(
            "demo-screen",
            changed,
            expected_revision=first.package_revision,
            skill_root_path=self.root,
        )
        self.assertEqual(
            [item["version"] for item in list_screen_history("demo-screen", skill_root_path=self.root)],
            [first.package_revision],
        )

        restored = restore_screen_package(
            "demo-screen",
            first.package_revision,
            expected_revision=second.package_revision,
            skill_root_path=self.root,
        )
        self.assertEqual(restored.package_revision, first.package_revision)
        # 当前修订不应同时展示为历史；回滚前的 active 版本必须只保留一份历史。
        self.assertEqual(
            [item["version"] for item in list_screen_history("demo-screen", skill_root_path=self.root)],
            [second.package_revision],
        )
        self.assertTrue(delete_screen_history(
            "demo-screen", second.package_revision, skill_root_path=self.root
        ))

        third_files = _screen_files()
        third_files["formula.tdx"] = "BASE:=MA(CLOSE,N);\nPICK: CLOSE<BASE;\n"
        save_screen_package(
            "demo-screen",
            third_files,
            expected_revision=restored.package_revision,
            skill_root_path=self.root,
        )
        revisions = {
            item["version"]
            for item in list_screen_history("demo-screen", skill_root_path=self.root)
        }
        self.assertIn(first.package_revision, revisions)
        self.assertNotIn(second.package_revision, revisions)

    def test_archive_rejects_script_payload(self) -> None:
        archive = Path(self.temp.name) / "screen.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in _screen_files().items():
                zf.writestr(name, content)
            zf.writestr("evil.ps1", "Write-Host boom\n")
        with self.assertRaises(ScreenPackageError):
            read_screen_archive(archive)

    def test_archive_rejects_zip_slip_payload(self) -> None:
        archive = _screen_archive(
            Path(self.temp.name) / "screen-slip.zip",
            {**_screen_files(), "../evil.md": "pwned"},
        )
        with self.assertRaises(ScreenPackageError) as ctx:
            read_screen_archive(archive)
        self.assertIn("上跳路径", str(ctx.exception))

    def test_archive_rejects_absolute_path_payload(self) -> None:
        archive = _screen_archive(
            Path(self.temp.name) / "screen-absolute.zip",
            {**_screen_files(), "/etc/cron.d/evil.md": "pwned"},
        )
        with self.assertRaises(ScreenPackageError) as ctx:
            read_screen_archive(archive)
        self.assertIn("绝对路径", str(ctx.exception))

    def test_archive_rejects_symlink_payload(self) -> None:
        archive = Path(self.temp.name) / "screen-symlink.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in _screen_files().items():
                zf.writestr(name, content)
            info = zipfile.ZipInfo("references/link.md")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "/etc/shadow")
        with self.assertRaises(ScreenPackageError) as ctx:
            read_screen_archive(archive)
        self.assertIn("符号链接", str(ctx.exception))

    def test_archive_rejects_declared_size_limit(self) -> None:
        archive = _screen_archive(
            Path(self.temp.name) / "screen-large.zip",
            {**_screen_files(), "references/big.txt": "12345678901"},
        )
        with patch("src.ops.application.screen.storage._MAX_EXTRACTED_BYTES", 10):
            with self.assertRaises(ScreenPackageError) as ctx:
                read_screen_archive(archive)
            self.assertFalse(archive_declares_screen_capability(archive))
        self.assertIn("体积过大", str(ctx.exception))

    def test_archive_accepts_common_top_level_folder(self) -> None:
        archive = Path(self.temp.name) / "screen.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in _screen_files().items():
                zf.writestr(f"demo-screen/{name}", content)
        bundle = read_screen_archive(archive)
        self.assertEqual(bundle.record.slug, "demo-screen")
        self.assertIn("formula.tdx", bundle.files)

    def test_python_runtime_package_keeps_entrypoint_and_local_py_files(self) -> None:
        created = save_screen_package(
            "python-screen",
            _python_files(),
            skill_root_path=self.root,
        )
        self.assertEqual(created.runtime, "python")
        self.assertEqual(created.dialect, "python")
        self.assertEqual(created.entrypoint, "strategy.py:compute")
        self.assertIn("helpers.py", created.files)
        self.assertIn("def compute", created.code)

        archive = _screen_archive(Path(self.temp.name) / "python.zip", _python_files())
        bundle = read_screen_archive(archive)
        self.assertEqual(bundle.record.runtime, "python")
        self.assertEqual(bundle.record.entrypoint, "strategy.py:compute")
        self.assertIn("helpers.py", bundle.files)


if __name__ == "__main__":
    unittest.main()
