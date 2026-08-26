"""单实例锁：二次启动应前置已有进程窗口。"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.shared.single_instance import (
    claim_or_focus,
    clear_instance,
    lock_path,
    read_instance,
    write_instance,
)


class SingleInstanceTests(unittest.TestCase):
    def test_write_read_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_instance(lock_path(root), pid=4242, port=9000)
            data = read_instance(lock_path(root))
            self.assertEqual(data, {"pid": 4242, "port": 9000})
            clear_instance(lock_path(root))
            self.assertIsNone(read_instance(lock_path(root)))

    def test_first_claim_writes_pid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("src.shared.single_instance.acquire_mutex", return_value=True):
                self.assertTrue(claim_or_focus(root))
            data = read_instance(lock_path(root))
            assert data is not None
            self.assertEqual(data["pid"], os.getpid())

    def test_second_claim_focuses_and_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_instance(lock_path(root), pid=111)
            with mock.patch(
                "src.shared.single_instance.acquire_mutex", return_value=False
            ):
                with mock.patch(
                    "src.shared.single_instance.pid_alive", return_value=True
                ):
                    with mock.patch(
                        "src.shared.single_instance.focus_pid_windows",
                        return_value=True,
                    ) as focus:
                        self.assertFalse(claim_or_focus(root))
                        focus.assert_called_once_with(111)

    def test_mutex_names_differ_by_install_root(self) -> None:
        from src.shared.single_instance import mutex_name_for

        a = mutex_name_for(Path("E:/entertainment_software/Loci"))
        b = mutex_name_for(Path("E:/my_space/stock-analyzer"))
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("Local\\LociDesktopSingleInstance_"))


if __name__ == "__main__":
    unittest.main()
