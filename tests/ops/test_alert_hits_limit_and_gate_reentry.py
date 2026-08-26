"""两处 ops 层缺陷的回归。

1. ``GET /api/ops/alert-hits`` 的 ``limit`` 曾是裸 int：``?limit=99999999`` 会被原样
   塞进 SQL 的 ``LIMIT ?``（全表扫 + 无界响应），``?limit=-1`` 在 SQLite 里更等于
   「不限行数」。现在与 ``/api/jobs/runs`` 同口径钳到 1..500，越界由 FastAPI 判 422。
2. ``market_heavy_slot`` 的重入判据曾是「本线程持有**任意** kind 的槽」。screen 读槽
   里再要 sync 写槽是**跨 kind**，两者要的根本不是同一把槽——那正是本模块要防的
   「一边扫 market.db、一边写 WAL」组合，却被静默放行。现在只有同 kind（以及写槽内
   再要读槽，写槽本就涵盖读）才算重入。
"""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.application.jobs import market_gate as gate
from src.ops.application.jobs.context import JobError, JobSkipped
from src.ops.infrastructure.store import OpsStore


def _client(ops_db: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_paper_quant_router(write_dependency=lambda: None, ops_db=str(ops_db))
    )
    return TestClient(app, raise_server_exceptions=False)


class AlertHitsLimitTests(unittest.TestCase):
    """客户端可控的 limit 必须有界。"""

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.db = Path(self._dir.name) / "ops.db"
        with OpsStore(self.db) as store:
            # alert_hits.rule_id 有外键指向 alert_rules，且 (rule_id, bucket) 唯一：
            # 不先建规则、或复用同一个 bucket，insert_alert_hit 会静默吞掉。
            rule = store.upsert_alert_rule({"id": "AR-1", "code": "600519", "name": "测试"})
            for i in range(5):
                store.insert_alert_hit(
                    {
                        "rule_id": rule["id"],
                        "trigger_bucket": f"2026-08-25T09:3{i}",
                        "trigger_time": f"2026-08-25T09:3{i}:00+08:00",
                        "snapshot": {"i": i},
                    }
                )
        self.client = _client(self.db)

    def tearDown(self) -> None:
        self.client.close()
        self._dir.cleanup()

    def test_absurd_limit_is_rejected_by_validation(self) -> None:
        """?limit=99999999 不该走到 SQL，直接 422。"""
        response = self.client.get("/api/ops/alert-hits?limit=99999999")
        self.assertEqual(response.status_code, 422)

    def test_non_positive_limit_is_rejected(self) -> None:
        """-1 在 SQLite 里是「不限行数」，0 是无意义查询，都得挡在门外。"""
        for bad in ("-1", "0"):
            with self.subTest(limit=bad):
                self.assertEqual(
                    self.client.get(f"/api/ops/alert-hits?limit={bad}").status_code, 422
                )

    def test_boundary_limits_still_pass(self) -> None:
        """钳位不能把正常用法一起挡掉：1 和 500 都是合法值。"""
        for good in ("1", "500"):
            with self.subTest(limit=good):
                self.assertEqual(
                    self.client.get(f"/api/ops/alert-hits?limit={good}").status_code, 200
                )

    def test_limit_still_actually_limits(self) -> None:
        """钳位之后 limit 仍要真传进查询，别改成一个摆设参数。"""
        response = self.client.get("/api/ops/alert-hits?limit=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_default_and_rule_filter_keep_working(self) -> None:
        default = self.client.get("/api/ops/alert-hits")
        self.assertEqual(default.status_code, 200)
        self.assertEqual(len(default.json()), 5)
        self.assertEqual(
            len(self.client.get("/api/ops/alert-hits?rule_id=AR-1&limit=3").json()), 3
        )
        self.assertEqual(self.client.get("/api/ops/alert-hits?rule_id=AR-404").json(), [])


class GateReentryKindTests(unittest.TestCase):
    """重入判据必须按 kind 分，且不能把原有的防自锁能力改坏。"""

    def setUp(self) -> None:
        gate._WRITER = None
        gate._WRITER_SINCE = 0.0
        gate._READERS.clear()
        gate._READER_SINCE.clear()
        gate._WRITERS_WAITING = 0
        gate._LOCAL = threading.local()
        self._wait = gate.MARKET_LOCK_WAIT_SEC
        self._screen_wait = gate.MARKET_SCREEN_LOCK_WAIT_SEC
        # 等锁上限压到亚秒级：万一判据退化成「等自己那把读槽」，用例是超时失败，
        # 而不是把整个测试进程挂住。
        gate.MARKET_LOCK_WAIT_SEC = 0.5
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = 0.5

    def tearDown(self) -> None:
        gate.MARKET_LOCK_WAIT_SEC = self._wait
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = self._screen_wait
        gate._WRITER = None
        gate._WRITER_SINCE = 0.0
        gate._READERS.clear()
        gate._READER_SINCE.clear()
        gate._WRITERS_WAITING = 0
        gate._LOCAL = threading.local()

    # —— 原有能力：同 kind 仍然算重入，不得自锁 ——

    def test_same_kind_sync_nesting_is_reentrant(self) -> None:
        """run_job 外层 sync + execute_sync 内层 sync：同一把槽，直接放行。"""
        with gate.market_heavy_slot("sync", "行情日终重刷"):
            with gate.market_heavy_slot("sync", "sync:today_refresh"):
                self.assertEqual(gate._WRITER, "sync:行情日终重刷")
            # 内层退出不许把外层的写槽顺手放掉
            self.assertEqual(gate._WRITER, "sync:行情日终重刷")
        self.assertIsNone(gate._WRITER)

    def test_same_kind_screen_nesting_is_reentrant(self) -> None:
        """同一条选股内部再取一次读槽也是重入，读者计数不该翻倍。"""
        with gate.market_heavy_slot("screen", "screen:sanyuan-tail-v1"):
            with gate.market_heavy_slot("screen", "screen:sanyuan-tail-v1"):
                self.assertEqual(gate._READERS, {"screen:sanyuan-tail-v1": 1})
            self.assertEqual(gate._READERS, {"screen:sanyuan-tail-v1": 1})
        self.assertEqual(gate._READERS, {})

    def test_screen_inside_sync_is_reentrant(self) -> None:
        """写槽里再要读槽仍按重入放行：独占写槽本就涵盖读，排队等于等自己。"""
        with gate.market_heavy_slot("sync", "sync:full"):
            with gate.market_heavy_slot("screen", "screen:yangshi-tail-v1"):
                self.assertEqual(gate._WRITER, "sync:full")
                self.assertEqual(gate._READERS, {})
        self.assertIsNone(gate._WRITER)
        self.assertEqual(gate._READERS, {})

    # —— 缺陷本体：跨 kind 不是重入 ——

    def test_sync_inside_screen_really_takes_the_write_slot(self) -> None:
        """screen 读槽里再要 sync 写槽：必须真独占，而不是被当成重入放行。"""
        with gate.market_heavy_slot("screen", "screen:sanyuan-tail-v1"):
            self.assertEqual(gate._READERS, {"screen:sanyuan-tail-v1": 1})
            started = time.monotonic()
            with gate.market_heavy_slot("sync", "sync:today_refresh"):
                # 旧判据在这里 _WRITER 恒为 None：独占写锁被静默跳过。
                self.assertEqual(gate._WRITER, "sync:today_refresh")
                # 自家读槽临时让出，免得 _acquire_writer 等自己。
                self.assertEqual(gate._READERS, {})
            # 没有别的排队对象，抢锁应当立刻完成，而不是熬满 wait_sec。
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIsNone(gate._WRITER)
            # 内层写完，外层选股的读槽必须原样回来。
            self.assertEqual(gate._READERS, {"screen:sanyuan-tail-v1": 1})
        self.assertEqual(gate._READERS, {})
        self.assertEqual(gate._READER_SINCE, {})

    def test_ceded_read_slot_keeps_its_original_lease_clock(self) -> None:
        """让位再取回不能把租约时钟洗白，否则卡死的选股永远等不到回收。"""
        with gate.market_heavy_slot("screen", "screen:qianlong-close-v3"):
            since = gate._READER_SINCE["screen:qianlong-close-v3"]
            time.sleep(0.05)
            with gate.market_heavy_slot("sync", "sync:full"):
                pass
            self.assertEqual(gate._READER_SINCE["screen:qianlong-close-v3"], since)

    def test_cross_kind_upgrade_still_waits_for_other_readers(self) -> None:
        """只让出自己那把读槽——别人的读槽照样挡路，也不许被顺手吞掉。"""
        entered = threading.Event()
        release = threading.Event()
        failures: list[BaseException] = []

        def other_screen() -> None:
            try:
                with gate.market_heavy_slot("screen", "screen:yangshi-tail-v1"):
                    entered.set()
                    release.wait(timeout=5)
            except BaseException as exc:  # noqa: BLE001 — 交回主线程断言
                failures.append(exc)
                entered.set()

        worker = threading.Thread(target=other_screen, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(5))
        try:
            with gate.market_heavy_slot("screen", "screen:sanyuan-tail-v1"):
                with self.assertRaises(JobError) as ctx:
                    with gate.market_heavy_slot("sync", "sync:full"):
                        pass
                # 别人还在正常读 → 这是排队，不是故障。
                self.assertIsInstance(ctx.exception, JobSkipped)
                self.assertIsNone(gate._WRITER)
                # 抢锁失败也要把自家读槽还回来。
                self.assertEqual(gate._READERS.get("screen:sanyuan-tail-v1"), 1)
                self.assertEqual(gate._READERS.get("screen:yangshi-tail-v1"), 1)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(failures, [])
        self.assertEqual(gate._READERS, {})

    def test_non_heavy_kind_still_passes_through(self) -> None:
        with gate.market_heavy_slot("notify", "推送"):
            self.assertIsNone(gate._WRITER)
            self.assertEqual(gate._READERS, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
