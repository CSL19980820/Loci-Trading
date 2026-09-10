"""选股内存闸门：同进程内的选股任务按 ``LOCI_SCREEN_JOB_CONCURRENCY`` 串行。"""
from __future__ import annotations

import os
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ops.application.jobs import market_gate as gate
from src.ops.application.jobs.context import JobError
from src.ops.application.jobs.market_gate import screen_memory_slot
from src.ops.application.jobs.registry import run_job
from src.ops.infrastructure.store import OpsStore
from src.shared import screen_capacity


class _CapacityIsolation(unittest.TestCase):
    """把进程级许可恢复成「容量 1、无人持有」。

    容量经环境变量读取（`LOCI_SCREEN_JOB_CONCURRENCY`），开发机导出过就会让这几条
    用例在另一档并发上跑绿；排队上限有 10 秒下限，要测超时只能换掉取值函数本身。
    """

    def setUp(self) -> None:
        self._concurrency = os.environ.get("LOCI_SCREEN_JOB_CONCURRENCY")
        os.environ["LOCI_SCREEN_JOB_CONCURRENCY"] = "1"
        self._wait = gate.screen_permit_wait_sec
        screen_capacity._LOCAL = threading.local()
        gate._LOCAL = threading.local()

    def tearDown(self) -> None:
        gate.screen_permit_wait_sec = self._wait
        if self._concurrency is None:
            os.environ.pop("LOCI_SCREEN_JOB_CONCURRENCY", None)
        else:
            os.environ["LOCI_SCREEN_JOB_CONCURRENCY"] = self._concurrency
        screen_capacity._LOCAL = threading.local()
        gate._LOCAL = threading.local()


class ScreenMemorySlotTests(_CapacityIsolation):
    def test_second_screen_waits_for_first_to_release(self) -> None:
        first_in = threading.Event()
        second_in = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def first() -> None:
            try:
                with screen_memory_slot("screen", "screen:a"):
                    first_in.set()
                    release.wait(timeout=5)
            except BaseException as exc:  # noqa: BLE001 — 交回主线程断言
                errors.append(exc)

        def second() -> None:
            try:
                with screen_memory_slot("screen", "screen:b"):
                    second_in.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=first, daemon=True)
        t2 = threading.Thread(target=second, daemon=True)
        t1.start()
        self.assertTrue(first_in.wait(timeout=2))
        t2.start()
        # 第一档没放行之前，第二档必须还在门外。
        self.assertFalse(second_in.wait(timeout=0.5), "并发上限 1 时第二档选股不该进来")
        release.set()
        self.assertTrue(second_in.wait(timeout=2), "第一档放行后第二档必须能进")
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(errors, [])

    def test_non_screen_and_reentry_pass_through(self) -> None:
        with screen_memory_slot("sync", "行情日终重刷"):
            # 非 screen 不占名额：此时 screen 仍能立刻进。
            with screen_memory_slot("screen", "screen:a"):
                with screen_memory_slot("screen", "screen:a"):
                    pass

    def test_timeout_is_a_job_error_and_keeps_semaphore_balanced(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with screen_memory_slot("screen", "screen:holder"):
                entered.set()
                release.wait(timeout=5)

        t = threading.Thread(target=hold, daemon=True)
        t.start()
        self.assertTrue(entered.wait(timeout=2))
        gate.screen_permit_wait_sec = lambda: 0.2
        try:
            with self.assertRaises(JobError) as ctx:
                with screen_memory_slot("screen", "screen:waiter"):
                    pass
            self.assertIn("放弃排队", str(ctx.exception))
        finally:
            release.set()
            t.join(timeout=2)
        # 持有者放行后名额必须回到 1：再进一次不应再等。
        started = time.monotonic()
        with screen_memory_slot("screen", "screen:after"):
            pass
        self.assertLess(time.monotonic() - started, 0.2)


class RunJobSerializesScreensTests(_CapacityIsolation):
    def test_two_screen_jobs_never_execute_concurrently(self) -> None:
        from src.ops.application.jobs import registry

        with TemporaryDirectory() as tmp:
            store = OpsStore(Path(tmp) / "ops.db")
            ids = [
                store.create_job(name=f"screen:{slug}", kind="screen", config={"strategy": slug})
                for slug in ("alpha", "beta")
            ]
            jobs = [store.get_job(job_id) for job_id in ids]
            assert all(jobs)

            counter = threading.Lock()
            state = {"inside": 0, "peak": 0}

            def fake_screen(_cfg, _ctx):
                with counter:
                    state["inside"] += 1
                    state["peak"] = max(state["peak"], state["inside"])
                time.sleep(0.3)
                with counter:
                    state["inside"] -= 1
                return {"picks": [], "pick_count": 0}

            old_exec = registry.EXECUTORS["screen"]
            registry.EXECUTORS["screen"] = fake_screen
            results: list[dict] = []

            def worker(job: dict) -> None:
                # 每个线程各开一条 ops.db 连接：OpsStore 不是线程共享的。
                with OpsStore(Path(tmp) / "ops.db") as own:
                    results.append(run_job(own, job, trigger="schedule"))

            threads = [threading.Thread(target=worker, args=(job,), daemon=True) for job in jobs]
            try:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=15)
            finally:
                registry.EXECUTORS["screen"] = old_exec
                store.close()

            self.assertEqual(sorted(r["status"] for r in results), ["success", "success"])
            self.assertEqual(state["peak"], 1, "两档选股必须串行执行")


if __name__ == "__main__":
    unittest.main()
