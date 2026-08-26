"""行情闸门与写锁的抗挂死回归。

2026-08-24 现场：首启 bootstrap 同步（不走 run_job）占着 market.db 写锁卡在
apply_today_spot；15:30 三只选股补 spot 时被无超时的进程内 RLock 永久钉住，
又攥着闸门读槽不放，于是 15:35 盘后同步、16:00 日终重刷连续被判
「行情库正被选股占用」。这里锁住四条不可回退的性质。
"""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.market.infrastructure import write_lock as wl
from src.ops.application.jobs import market_gate as gate
from src.ops.application.jobs.context import JobError


class WriteLockNoHangTests(unittest.TestCase):
    """进程内等待必须有上限——这是整条故障链的起点。"""

    def setUp(self) -> None:
        self._wait = wl._LOCK_WAIT_SEC
        wl._LOCK_WAIT_SEC = 0.6
        self._dir = TemporaryDirectory()
        self.db = Path(self._dir.name) / "market.db"
        self.db.touch()

    def tearDown(self) -> None:
        wl._LOCK_WAIT_SEC = self._wait
        self._dir.cleanup()

    def test_blocked_thread_fails_fast_instead_of_hanging(self) -> None:
        holding = threading.Event()
        release = threading.Event()

        def hog() -> None:
            with wl.market_write_lock(self.db, label="sync:full"):
                holding.set()
                release.wait(10)

        worker = threading.Thread(target=hog, daemon=True)
        worker.start()
        self.assertTrue(holding.wait(5))
        try:
            started = time.monotonic()
            with self.assertRaises(wl.MarketWriteBusy) as ctx:
                with wl.market_write_lock(self.db, label="spot"):
                    pass
            waited = time.monotonic() - started
            # 关键：有界等待，而不是永久挂起
            self.assertLess(waited, 5.0)
            self.assertIn("sync:full", str(ctx.exception))
        finally:
            release.set()
            worker.join(5)

    def test_same_thread_reentry_still_allowed(self) -> None:
        """外层 sync 占锁后内层 spot 必须能直接进，否则同步自锁。"""
        with wl.market_write_lock(self.db, label="sync:full"):
            with wl.market_write_lock(self.db, label="spot"):
                holder = wl.current_write_holder(self.db)
            self.assertIsNotNone(holder)
        self.assertIsNone(wl.current_write_holder(self.db))


class GateStarvationTests(unittest.TestCase):
    """选股不得把同步饿死。"""

    def setUp(self) -> None:
        gate._WRITER = None
        gate._WRITER_SINCE = 0.0
        gate._READERS.clear()
        gate._READER_SINCE.clear()
        gate._WRITERS_WAITING = 0
        gate._LOCAL = threading.local()
        self._lease = gate.MARKET_SCREEN_HOLD_LEASE_SEC
        self._wait = gate.MARKET_LOCK_WAIT_SEC
        self._screen_wait = gate.MARKET_SCREEN_LOCK_WAIT_SEC

    def tearDown(self) -> None:
        gate.MARKET_SCREEN_HOLD_LEASE_SEC = self._lease
        gate.MARKET_LOCK_WAIT_SEC = self._wait
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = self._screen_wait
        gate._READERS.clear()
        gate._READER_SINCE.clear()
        gate._WRITERS_WAITING = 0

    def test_expired_screen_reader_is_evicted_so_sync_gets_in(self) -> None:
        """挂死的选股超过租约后必须被判废，日终同步照常拿到锁。"""
        gate.MARKET_SCREEN_HOLD_LEASE_SEC = 0.3
        stuck = (
            "screen:yangshi-tail-v1",
            "screen:sanyuan-tail-v1",
            "screen:qianlong-close-v3",
        )
        for name in stuck:
            gate._READERS[name] = 1
            gate._READER_SINCE[name] = time.monotonic()
        time.sleep(0.4)
        with gate.market_heavy_slot("sync", "行情日终重刷"):
            self.assertEqual(gate._WRITER, "sync:行情日终重刷")
        self.assertEqual(gate._READERS, {})

    def test_healthy_screens_block_sync_with_honest_message(self) -> None:
        """租约内的选股仍然互斥，但报错不再叫用户去停掉选股。"""
        gate.MARKET_LOCK_WAIT_SEC = 0.2
        gate._READERS["screen:yangshi-tail-v1"] = 1
        gate._READER_SINCE["screen:yangshi-tail-v1"] = time.monotonic()
        with self.assertRaises(JobError) as ctx:
            with gate.market_heavy_slot("sync", "行情日终重刷"):
                pass
        msg = str(ctx.exception)
        self.assertIn("行情库正被占用", msg)
        self.assertNotIn("请先停掉卡住的选股", msg)

    def test_waiting_writer_blocks_new_readers(self) -> None:
        """写者排队时不再放新选股进来，否则同步永远等不到空窗。"""
        gate._WRITERS_WAITING = 1
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = 0.2
        with self.assertRaises(JobError):
            with gate.market_heavy_slot("screen", "screen:yangshi-tail-v1"):
                pass

    def test_same_thread_reentry_is_passthrough(self) -> None:
        """run_job 外层 + execute_sync 内层同占 sync 槽时不得自锁。"""
        with gate.market_heavy_slot("sync", "行情日终重刷"):
            with gate.market_heavy_slot("sync", "sync:today_refresh"):
                self.assertEqual(gate._WRITER, "sync:行情日终重刷")
        self.assertIsNone(gate._WRITER)


if __name__ == "__main__":
    unittest.main()
