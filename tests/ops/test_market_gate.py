from __future__ import annotations

import threading
import time
import unittest
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ops.application.jobs.context import JobError, JobSkipped
from src.ops.application.jobs.market_gate import _slot_label, market_heavy_slot
from src.ops.application.jobs.registry import run_job
from src.ops.infrastructure.store import OpsStore


@contextmanager
def held_by_sync(label: str) -> Iterator[None]:
    """后台线程占住写锁，直到退出上下文。"""
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold() -> None:
        try:
            with market_heavy_slot("sync", label):
                entered.set()
                release.wait(timeout=10)
        except BaseException as exc:  # noqa: BLE001 — collect for main thread
            errors.append(exc)
            entered.set()

    worker = threading.Thread(target=hold, daemon=True)
    worker.start()
    if not entered.wait(timeout=2):
        raise AssertionError("holder did not acquire the market slot")
    try:
        yield
    finally:
        release.set()
        worker.join(timeout=2)
    assert errors == [], errors


class MarketGateTests(unittest.TestCase):
    def test_slot_label_dedupes_kind_prefix(self) -> None:
        self.assertEqual(
            _slot_label("screen", "screen:qianlong-close-v3"),
            "screen:qianlong-close-v3",
        )
        self.assertEqual(_slot_label("sync", "sync:01"), "sync:01")
        self.assertEqual(_slot_label("sync", "日终重刷"), "sync:日终重刷")

    def test_screens_can_overlap_as_shared_readers(self) -> None:
        barrier = threading.Barrier(2, timeout=2)
        both_inside = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []
        inside = 0
        counter = threading.Lock()

        def hold(name: str) -> None:
            nonlocal inside
            try:
                with market_heavy_slot("screen", f"screen:{name}"):
                    with counter:
                        inside += 1
                        if inside >= 2:
                            both_inside.set()
                    barrier.wait()
                    release.wait(timeout=5)
            except BaseException as exc:  # noqa: BLE001 — collect for main thread
                errors.append(exc)

        workers = [
            threading.Thread(target=hold, args=("a",), daemon=True),
            threading.Thread(target=hold, args=("b",), daemon=True),
        ]
        for worker in workers:
            worker.start()
        # 若仍是排他锁，第二个 screen 进不来，both_inside 不会置位
        self.assertTrue(both_inside.wait(timeout=2), "两路 screen 应并行持有共享读锁")
        release.set()
        for worker in workers:
            worker.join(timeout=2)
        self.assertEqual(errors, [])

    def test_screen_waits_out_when_sync_holds_lock(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def hold_sync() -> None:
            try:
                with market_heavy_slot("sync", "holder"):
                    entered.set()
                    release.wait(timeout=5)
            except BaseException as exc:  # noqa: BLE001 — collect for main thread
                errors.append(exc)

        worker = threading.Thread(target=hold_sync, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        from src.ops.application.jobs import market_gate as gate

        old = gate.MARKET_LOCK_WAIT_SEC
        old_screen = gate.MARKET_SCREEN_LOCK_WAIT_SEC
        gate.MARKET_LOCK_WAIT_SEC = 0.3
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = 0.3
        try:
            with self.assertRaises(JobError) as ctx:
                with market_heavy_slot("screen", "waiter"):
                    pass
            self.assertIn("行情库正被占用", str(ctx.exception))
            self.assertIn("同步任务", str(ctx.exception))
        finally:
            gate.MARKET_LOCK_WAIT_SEC = old
            gate.MARKET_SCREEN_LOCK_WAIT_SEC = old_screen
            release.set()
            worker.join(timeout=2)
        self.assertEqual(errors, [])

    def test_sync_waits_out_when_screen_holds_lock(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def hold_screen() -> None:
            try:
                with market_heavy_slot("screen", "screen:sanyuan-tail-v1"):
                    entered.set()
                    release.wait(timeout=5)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        worker = threading.Thread(target=hold_screen, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        from src.ops.application.jobs import market_gate as gate

        old = gate.MARKET_LOCK_WAIT_SEC
        gate.MARKET_LOCK_WAIT_SEC = 0.3
        try:
            with self.assertRaises(JobSkipped) as ctx:
                with market_heavy_slot("sync", "sync:01"):
                    pass
            msg = str(ctx.exception)
            self.assertIn("行情库正被占用", msg)
            self.assertIn("选股任务", msg)
            self.assertNotIn("screen:screen:", msg)
            # 选股还在租期内 = 正常排队，不是故障：同步下一轮再跑。
            # 报成 JobError 会让「选股正常执行」这件事在运维页显示成红色失败，
            # 用户看到的就是「老是报冲突」。真卡死（超租期）另有分支，见下一条。
            self.assertNotIn("疑似卡死", msg)
            self.assertIn("下一轮再跑", msg)
        finally:
            gate.MARKET_LOCK_WAIT_SEC = old
            release.set()
            worker.join(timeout=2)
        self.assertEqual(errors, [])

    def test_sync_behind_running_peer_sync_asks_to_skip(self) -> None:
        from src.ops.application.jobs import market_gate as gate

        old = gate.MARKET_LOCK_WAIT_SEC
        gate.MARKET_LOCK_WAIT_SEC = 0.3
        try:
            with held_by_sync("sync:01 盘后同步行情"):
                with self.assertRaises(JobSkipped) as ctx:
                    with market_heavy_slot("sync", "行情日终重刷"):
                        pass
        finally:
            gate.MARKET_LOCK_WAIT_SEC = old
        msg = str(ctx.exception)
        self.assertIn("01 盘后同步行情", msg)
        self.assertIn("本轮跳过", msg)
        self.assertNotIn("卡死", msg)

    def test_sync_behind_stuck_peer_sync_still_fails(self) -> None:
        from src.ops.application.jobs import market_gate as gate

        old = gate.MARKET_LOCK_WAIT_SEC
        gate.MARKET_LOCK_WAIT_SEC = 0.3
        try:
            with held_by_sync("sync:01 盘后同步行情"):
                # 持锁久到超过 stale 窗：这时候安静跳过等于替卡死的同步遮丑
                gate._WRITER_SINCE = time.monotonic() - gate.MARKET_SYNC_STUCK_SEC - 1
                with self.assertRaises(JobError) as ctx:
                    with market_heavy_slot("sync", "行情日终重刷"):
                        pass
        finally:
            gate.MARKET_LOCK_WAIT_SEC = old
        self.assertNotIsInstance(ctx.exception, JobSkipped)
        self.assertIn("疑似卡死", str(ctx.exception))

    def test_run_job_records_peer_sync_wait_as_skipped(self) -> None:
        from src.ops.application.jobs import market_gate as gate
        from src.ops.application.jobs import registry

        with TemporaryDirectory() as tmp:
            store = OpsStore(Path(tmp) / "ops.db")
            job_id = store.create_job(
                name="行情日终重刷",
                kind="sync",
                # today_refresh 不吃 14:35–15:00 尾盘保护，避免测试随真实时钟漂移
                config={"mode": "today_refresh"},
            )
            job = store.get_job(job_id)
            assert job is not None

            called = {"n": 0}

            def boom(_cfg, _ctx):
                called["n"] += 1
                raise AssertionError("排队等锁的同步不该真的跑起来")

            old_wait = gate.MARKET_LOCK_WAIT_SEC
            old_exec = registry.EXECUTORS["sync"]
            gate.MARKET_LOCK_WAIT_SEC = 0.2
            registry.EXECUTORS["sync"] = boom
            try:
                with held_by_sync("sync:01 盘后同步行情"):
                    result = run_job(store, job, trigger="schedule")
            finally:
                gate.MARKET_LOCK_WAIT_SEC = old_wait
                registry.EXECUTORS["sync"] = old_exec

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(called["n"], 0)
            reason = str((result.get("result") or {}).get("reason") or "")
            self.assertIn("01 盘后同步行情", reason)
            runs = store.list_runs(job_id=job_id, limit=1)
            self.assertEqual(runs[0]["status"], "skipped")
            self.assertEqual(runs[0]["error_text"], "")
            store.close()

    def test_run_job_records_lock_timeout_as_failed(self) -> None:
        from src.ops.application.jobs import market_gate as gate
        from src.ops.application.jobs import registry

        with TemporaryDirectory() as tmp:
            store = OpsStore(Path(tmp) / "ops.db")
            job_id = store.create_job(
                name="screen:lock-test",
                kind="screen",
                config={"strategy": "qianlong-close-v3"},
            )
            job = store.get_job(job_id)
            assert job is not None

            held = threading.Event()
            release = threading.Event()

            def hold() -> None:
                with market_heavy_slot("sync", "blocker"):
                    held.set()
                    release.wait(timeout=10)

            t = threading.Thread(target=hold, daemon=True)
            t.start()
            self.assertTrue(held.wait(timeout=2))

            old_wait = gate.MARKET_LOCK_WAIT_SEC
            old_screen = gate.MARKET_SCREEN_LOCK_WAIT_SEC
            old_exec = registry.EXECUTORS["screen"]
            gate.MARKET_LOCK_WAIT_SEC = 0.2
            gate.MARKET_SCREEN_LOCK_WAIT_SEC = 0.2
            registry.EXECUTORS["screen"] = lambda _cfg, _ctx: {"ok": True}
            try:
                result = run_job(store, job, trigger="manual")
            finally:
                gate.MARKET_LOCK_WAIT_SEC = old_wait
                gate.MARKET_SCREEN_LOCK_WAIT_SEC = old_screen
                registry.EXECUTORS["screen"] = old_exec
                release.set()
                t.join(timeout=2)

            self.assertEqual(result["status"], "failed")
            self.assertIn("行情库正被占用", result["error"])
            self.assertNotIn("OperationalError", result["error"])
            runs = store.list_runs(job_id=job_id, limit=1)
            self.assertEqual(runs[0]["status"], "failed")
            store.close()


class TailScreenProtectTests(unittest.TestCase):
    def test_protect_window_covers_1450_not_eod(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.ops.application.jobs.market_gate import (
            in_tail_screen_protect_window,
            skip_reason_for_intraday_sync,
        )

        tz = ZoneInfo("Asia/Shanghai")

        at_1450 = datetime(2026, 8, 17, 14, 50, tzinfo=tz)
        at_1435 = datetime(2026, 8, 17, 14, 35, tzinfo=tz)
        at_1420 = datetime(2026, 8, 17, 14, 20, tzinfo=tz)
        at_1525 = datetime(2026, 8, 17, 15, 25, tzinfo=tz)
        self.assertTrue(in_tail_screen_protect_window(at_1450))
        self.assertTrue(in_tail_screen_protect_window(at_1435))
        self.assertFalse(in_tail_screen_protect_window(at_1420))
        self.assertFalse(in_tail_screen_protect_window(at_1525))
        job = {"kind": "sync", "config": {"mode": "full"}}
        self.assertIsNotNone(skip_reason_for_intraday_sync("sync", job, now=at_1450))
        self.assertIsNotNone(skip_reason_for_intraday_sync("sync", job, now=at_1435))
        self.assertIsNone(skip_reason_for_intraday_sync("sync", job, now=at_1420))
        eod = {"kind": "sync", "config": {"mode": "today_refresh"}}
        self.assertIsNone(skip_reason_for_intraday_sync("sync", eod, now=at_1450))

    def test_run_job_skips_intraday_sync_without_taking_lock(self) -> None:
        from src.ops.application.jobs import market_gate as gate
        from src.ops.application.jobs import registry

        with TemporaryDirectory() as tmp:
            store = OpsStore(Path(tmp) / "ops.db")
            job_id = store.create_job(
                name="行情盘中增量",
                kind="sync",
                config={"mode": "full"},
            )
            job = store.get_job(job_id)
            assert job is not None

            called = {"n": 0}

            def boom(_cfg, _ctx):
                called["n"] += 1
                raise AssertionError("tail protect should skip before executor")

            old_exec = registry.EXECUTORS["sync"]
            registry.EXECUTORS["sync"] = boom
            gate_old = gate.in_tail_screen_protect_window
            gate.in_tail_screen_protect_window = lambda now=None: True
            try:
                result = run_job(store, job, trigger="manual")
            finally:
                registry.EXECUTORS["sync"] = old_exec
                gate.in_tail_screen_protect_window = gate_old

            self.assertEqual(result["status"], "skipped")
            self.assertIn("尾盘选股", str((result.get("result") or {}).get("reason") or ""))
            self.assertEqual(called["n"], 0)
            runs = store.list_runs(job_id=job_id, limit=1)
            self.assertEqual(runs[0]["status"], "skipped")
            store.close()


if __name__ == "__main__":
    unittest.main()
