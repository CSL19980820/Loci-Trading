"""行情写锁：崩溃留下的锁文件必须靠 pid 探活立刻接管，不能陪死进程站满 30 分钟。

现场（2026-08-26，开发机 ``data/.market.db.write.lock``）：文件里躺着
``18848:sync:full``，而 18848 这个进程 08-25 就没了。旧逻辑只认两条接管理由——
holder 前缀是本进程 pid，或锁文件超过 ``_LOCK_STALE_SEC``（30 分钟）——于是一次
崩溃换来半小时行情库全面瘫痪：同步、spot、选股补数全部 ``MarketWriteBusy``。
"""
from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.market.infrastructure import write_lock as wl
from src.market.infrastructure.write_lock import MarketWriteBusy, market_write_lock


class DeadHolderTakeoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.db.write_bytes(b"")
        self.lock = self.db.parent / f".{self.db.name}.write.lock"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _plant(self, holder: str, *, age_sec: float) -> None:
        """埋一把别的进程留下的锁，并把 mtime 拨老到指定秒数。"""
        self.lock.write_text(holder, encoding="ascii")
        old = time.time() - age_sec
        os.utime(self.lock, (old, old))

    def test_dead_holder_evicted_without_waiting_out_stale_window(self) -> None:
        """holder 进程已死 → 立刻接管，不等 30 分钟。

        判据必须是「那个 pid 还在不在」，而不是「锁文件够不够老」。这里故意用一个
        **远小于** ``_LOCK_STALE_SEC`` 的 age：走时间窗的旧逻辑在这个 age 上只会超时。
        """
        self._plant("999001:sync:full", age_sec=60.0)
        self.assertLess(60.0, wl._LOCK_STALE_SEC)
        with patch.object(wl, "pid_alive", return_value=False) as probe:
            with market_write_lock(self.db, label="sync:接管"):
                self.assertTrue(self.lock.exists())
                self.assertTrue(
                    self.lock.read_text(encoding="ascii").startswith(f"{os.getpid()}:")
                )
        probe.assert_called()
        self.assertFalse(self.lock.exists())

    def test_live_holder_is_never_evicted(self) -> None:
        """holder 还活着 → 绝不接管，照旧等到 deadline 报 MarketWriteBusy。

        误判活着只是多等一会儿；误判已死会把正在写库的进程踢掉、双写 market.db。
        所以「探活说还在」这一侧必须是硬的。
        """
        self._plant("999002:sync:full", age_sec=60.0)
        with (
            patch.object(wl, "pid_alive", return_value=True),
            patch.object(wl, "_LOCK_WAIT_SEC", 0.2),
        ):
            with self.assertRaises(MarketWriteBusy):
                with market_write_lock(self.db, label="sync:排队"):
                    pass
        # 锁文件必须原样留着 —— 掀掉别人的锁比等不到锁严重得多。
        self.assertEqual(self.lock.read_text(encoding="ascii"), "999002:sync:full")

    def test_fresh_lock_is_protected_by_grace_window(self) -> None:
        """刚写下的锁即使探活说死也不接管。

        ``os.open`` 与 ``os.write`` 之间锁文件是空的，pid 也会被系统回收复用；
        没有这段宽限，两个同时启动的进程会互相掀锁。
        """
        self._plant("999003:sync:full", age_sec=1.0)
        with (
            patch.object(wl, "pid_alive", return_value=False),
            patch.object(wl, "_LOCK_WAIT_SEC", 0.2),
        ):
            with self.assertRaises(MarketWriteBusy):
                with market_write_lock(self.db, label="sync:太新"):
                    pass
        self.assertEqual(self.lock.read_text(encoding="ascii"), "999003:sync:full")

    def test_unparseable_holder_falls_back_to_time_window(self) -> None:
        """holder 解析不出 pid（旧格式/写坏/空文件）→ 回落时间窗，不乱接管。"""
        for holder in ("", "sync:no-pid", "-1:sync", "abc:sync"):
            with self.subTest(holder=holder):
                self.assertFalse(wl._holder_pid_is_dead(holder, 10_000.0))

    def test_helper_reports_dead_only_for_a_real_dead_pid(self) -> None:
        """守住 ``pid_alive`` 的接线方向没有取反。"""
        with patch.object(wl, "pid_alive", return_value=True):
            self.assertFalse(wl._holder_pid_is_dead("999004:sync", 10_000.0))
        with patch.object(wl, "pid_alive", return_value=False):
            self.assertTrue(wl._holder_pid_is_dead("999004:sync", 10_000.0))


if __name__ == "__main__":
    unittest.main()
