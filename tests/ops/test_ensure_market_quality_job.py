"""托管行情库体检:创建、幂等、执行器接线、阈值覆盖、告警推送。

这个任务是换源后唯一的日常防线。它要是没被注册进 JOB_KINDS / EXECUTORS,
创建时就会抛「未知任务类型」——那种失败在启动期只会写一行 warning,没人看得见。
判据报出来之后还要真的推到人手上,所以推送分支的「推 / 不推」也在这里守。
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.ops.application.ensure_market_quality_job import (
    DEFAULT_MARKET_QUALITY_CONFIG,
    MARKET_QUALITY_CRON,
    ensure_managed_market_quality_job,
)
from src.ops.application.jobs.data_quality import _thresholds, execute_data_quality
from src.ops.application.jobs.notify import _maybe_push_wecom
from src.ops.application.jobs.registry import EXECUTORS
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import JOB_KINDS, MANAGED_MARKET_QUALITY


class EnsureMarketQualityJobTests(unittest.TestCase):
    def test_kind_is_registered_on_both_sides(self) -> None:
        """两张名单缺一不可:JOB_KINDS 管建、EXECUTORS 管跑。"""
        self.assertIn("data_quality", JOB_KINDS)
        self.assertIn("data_quality", EXECUTORS)

    def test_creates_enabled_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                plan = ensure_managed_market_quality_job(store)
                self.assertEqual(plan, {"created": 1, "updated": 0})
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                self.assertEqual(job["kind"], "data_quality")
                self.assertEqual(job["cron"], MARKET_QUALITY_CRON)
                self.assertTrue(job["enabled"])

    def test_second_call_keeps_user_switch(self) -> None:
        """运维在页面上关掉之后,下次启动不能被 ensure 强行打开。"""
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                ensure_managed_market_quality_job(store)
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                store.update_job(job["id"], enabled=False)

                plan = ensure_managed_market_quality_job(store)
                self.assertEqual(plan, {"created": 0, "updated": 1})
                again = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert again is not None
                self.assertFalse(again["enabled"])


class ThresholdOverrideTests(unittest.TestCase):
    def test_config_overrides_apply(self) -> None:
        limits = _thresholds({"max_fabricated_rows": 7, "min_authoritative_ratio": 0.5})
        self.assertEqual(limits.max_fabricated_rows, 7)
        self.assertAlmostEqual(limits.min_authoritative_ratio, 0.5)

    def test_bad_config_falls_back_to_default_instead_of_crashing(self) -> None:
        """配置写错就不体检 = 最需要体检的时候正好没体检。"""
        from src.market import QualityThresholds

        limits = _thresholds({"max_fabricated_rows": "很多"})
        self.assertEqual(
            limits.max_fabricated_rows, QualityThresholds().max_fabricated_rows
        )

    def test_unknown_config_keys_are_ignored(self) -> None:
        limits = _thresholds({"不是阈值": 1})
        self.assertEqual(limits.lookback_days, 90)


class ManagedConfigTests(unittest.TestCase):
    """托管配置：默认开企微推送，但已存在的任务只补键、不改用户改过的东西。"""

    def test_default_config_enables_wecom_push(self) -> None:
        r"""体检报出来的东西不推出去，就要靠人主动去运维页翻——不会有人翻。

        降噪由 notify 侧负责（全绿 ``push_skipped``），所以默认开不会变成
        天天一条正常播报。
        """
        self.assertTrue(DEFAULT_MARKET_QUALITY_CONFIG.get("push_wecom"))
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                ensure_managed_market_quality_job(store)
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                self.assertTrue(job["config"]["push_wecom"])

    def test_second_call_keeps_user_edited_config_and_cron(self) -> None:
        r"""幂等只补缺失键：用户关掉的推送、改过的 cron 都不许被 ensure 顶回去。"""
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                ensure_managed_market_quality_job(store)
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                store.update_job(
                    job["id"],
                    cron="0 20 * * mon-fri",
                    config={"push_wecom": False, "max_fabricated_rows": 9},
                )

                plan = ensure_managed_market_quality_job(store)
                self.assertEqual(plan, {"created": 0, "updated": 1})
                again = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert again is not None
                self.assertEqual(again["cron"], "0 20 * * mon-fri")
                self.assertFalse(again["config"]["push_wecom"])
                self.assertEqual(again["config"]["max_fabricated_rows"], 9)


class DataQualityPushTests(unittest.TestCase):
    """体检 → 企微：有告警才推，全绿必须闭嘴。

    全绿也推会让这条天天跑的任务变成每日「一切正常」播报，两周之后没人再点
    开它——真出事那天的告警跟着一起被划过去。这是同一个仓里 skill_watch 与
    sync 都栽过的坑（``push_only_when_actionable`` / 「仅失败才推」）。
    """

    _ALERT = "行情库体检发现 1 项问题：\n【提醒】最后交易日 2026-08-25 的权威源占比只有 0.0%"

    @staticmethod
    def _job() -> dict:
        return {
            "id": "JOB-DQ",
            "name": "行情库体检",
            "kind": "data_quality",
            "config": {"push_wecom": True},
        }

    def _push(self, result: dict, *, status: str = "success"):
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                with patch(
                    "src.ops.application.notify_dispatch.dispatch_text",
                    return_value={"sent": True},
                ) as dispatch:
                    outcome = _maybe_push_wecom(
                        store=store,
                        job=self._job(),
                        status=status,
                        result=result,
                    )
        return outcome, dispatch

    def test_alert_is_pushed_verbatim(self) -> None:
        outcome, dispatch = self._push(
            {"blocked": False, "warn_count": 1, "alert": self._ALERT}
        )
        self.assertTrue(outcome and outcome.get("pushed"))
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["body"], self._ALERT)
        self.assertEqual(dispatch.call_args.kwargs["title"], "行情库体检")

    def test_blocked_report_is_pushed(self) -> None:
        outcome, dispatch = self._push(
            {"blocked": True, "block_count": 1, "alert": self._ALERT}
        )
        self.assertTrue(outcome and outcome.get("pushed"))
        dispatch.assert_called_once()

    def test_all_green_is_not_pushed(self) -> None:
        outcome, dispatch = self._push(
            {"blocked": False, "block_count": 0, "warn_count": 0, "alert": ""}
        )
        self.assertEqual(
            outcome, {"push_skipped": True, "reason": "quality_all_green"}
        )
        dispatch.assert_not_called()

    def test_failed_run_still_pushes_even_without_alert(self) -> None:
        r"""体检自己不抛异常，能失败就是打不开行情库这类真故障，必须出声。"""
        outcome, dispatch = self._push({"alert": ""}, status="failed")
        self.assertTrue(outcome and outcome.get("pushed"))
        dispatch.assert_called_once()

    def test_push_failure_does_not_break_the_job(self) -> None:
        r"""推送是附带动作。``run_job`` 调 ``_maybe_push_wecom`` 那一行不在任何
        try 里，这里漏一个异常出去，整次运行会卡在 ``running`` 上收不了尾——
        一条推送顺带把它本该通知的那次体检记录也毁掉。
        """
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                with patch(
                    "src.ops.application.notify_dispatch.dispatch_text",
                    side_effect=RuntimeError("webhook 配置坏了"),
                ):
                    outcome = _maybe_push_wecom(
                        store=store,
                        job=self._job(),
                        status="success",
                        result={"blocked": True, "alert": self._ALERT},
                    )
        assert outcome is not None
        self.assertIn("webhook 配置坏了", outcome["push_error"])


class AlertReachesPayloadTests(unittest.TestCase):
    """``execute_data_quality`` 的返回值就是 ``result_json``，推送只读它。

    日志里那条 ``logger.warning`` 通知不到任何人；告警必须真的在返回值里，
    否则 ``_maybe_push_wecom`` 读到的永远是空串，全链路悄无声息。
    """

    class _Ctx:
        def __init__(self, store) -> None:
            self._store = store

        @contextmanager
        def market(self):
            yield self._store

    def test_alert_and_blocked_are_in_the_returned_payload(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE quotes_daily (code TEXT, trade_date TEXT, close REAL,"
            " volume REAL, amount REAL, source TEXT, receipt_id TEXT,"
            " high REAL DEFAULT 2.0, low REAL DEFAULT 1.0)"
        )
        conn.executemany(
            "INSERT INTO quotes_daily(code, trade_date, close, volume, amount,"
            " source, receipt_id) VALUES (?,?,?,?,?,?,?)",
            [
                ("%06d" % (600000 + i), "2026-08-25", 10.0, 1000.0, 12345.0, "tencent", "r")
                for i in range(600)
            ],
        )
        conn.execute("CREATE TABLE trading_calendar (trade_date TEXT)")
        conn.execute("INSERT INTO trading_calendar VALUES ('2026-08-25')")
        conn.execute(
            "CREATE TABLE instruments (code TEXT, status TEXT,"
            " instrument_type TEXT DEFAULT 'STOCK')"
        )
        conn.execute(
            "CREATE TABLE ingest_watermark (code TEXT, source TEXT, status TEXT,"
            " last_trade_date TEXT)"
        )

        class _Store:
            pass

        store = _Store()
        store.conn = conn
        report = execute_data_quality(dict(), self._Ctx(store))

        self.assertIn("alert", report)
        self.assertIn("最后交易日 2026-08-25", report["alert"])
        self.assertIn("last_day_authoritative", [f["key"] for f in report["findings"]])
        # 阈值旋钮要在 payload 里露出来，运维页才知道有哪些可调
        self.assertIn("min_last_day_authoritative_ratio", report["config"])


if __name__ == "__main__":
    unittest.main()