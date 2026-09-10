"""多时点 cron 的补跑：逐时点判「到点未跑」，成功判定精确到触发点。"""
from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

from src.ops.application.eod_catchup import (
    CATCHUP_SLOT_KEY,
    job_succeeded_on_trading_day,
    jobs_due_for_eod_catchup,
    parse_once_slots,
    run_eod_catchup,
    slot_for_day,
)

_TZ = ZoneInfo("Asia/Shanghai")
_MULTI = "50 14 * * mon-fri\n30 15 * * mon-fri"


def _job(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "JOB-1",
        "name": "screen:yangshi-tail-v1",
        "kind": "screen",
        "cron": _MULTI,
        "enabled": True,
        "last_run_at": "",
    }
    row.update(overrides)
    return row


class _Store:
    """只提供 ``list_runs`` / ``list_jobs`` 的假 ops 库。"""

    def __init__(self, runs: list[dict[str, Any]], jobs: list[dict[str, Any]] | None = None) -> None:
        self._runs = runs
        self._jobs = jobs or []

    def list_runs(self, **_: Any) -> list[dict[str, Any]]:
        return list(self._runs)

    def list_jobs(self, **_: Any) -> list[dict[str, Any]]:
        return list(self._jobs)

    def __enter__(self) -> "_Store":
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def _success_run(started: str) -> dict[str, Any]:
    return {
        "status": "success",
        "started_at": started,
        "finished_at": started,
        "result": {"trade_date": "2026-09-02"},
    }


class ParseOnceSlotsTests(unittest.TestCase):
    def test_multiline_and_semicolon_forms(self) -> None:
        self.assertEqual(parse_once_slots(_MULTI), [(14, 50), (15, 30)])
        self.assertEqual(
            parse_once_slots("50 14 * * 1-5; 30 15 * * mon-fri"), [(14, 50), (15, 30)]
        )
        self.assertEqual(parse_once_slots("30 15 * * mon-fri"), [(15, 30)])

    def test_interval_lines_are_ignored(self) -> None:
        self.assertEqual(parse_once_slots("*/5 9-14 * * mon-fri"), [])
        self.assertEqual(
            parse_once_slots("*/5 9-14 * * mon-fri\n30 15 * * mon-fri"), [(15, 30)]
        )


class MultiSlotDueTests(unittest.TestCase):
    def test_missing_later_slot_is_due_even_if_earlier_slot_ran(self) -> None:
        """14:50 跑过、15:30 没跑：last_run_at 停在 14:50，15:30 必须进补跑名单。"""
        jobs = [_job(last_run_at="2026-09-02T14:50:51+08:00")]
        now = datetime(2026, 9, 2, 17, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(jobs, last_trading_day="2026-09-02", now=now)
        self.assertEqual([j["name"] for j in due], ["screen:yangshi-tail-v1"])
        self.assertEqual(due[0][CATCHUP_SLOT_KEY], slot_for_day("2026-09-02", 15, 30))

    def test_all_slots_covered_is_not_due(self) -> None:
        jobs = [_job(last_run_at="2026-09-02T15:31:00+08:00")]
        now = datetime(2026, 9, 2, 17, 0, tzinfo=_TZ)
        self.assertEqual(
            jobs_due_for_eod_catchup(jobs, last_trading_day="2026-09-02", now=now), []
        )

    def test_before_later_slot_only_earlier_slot_counts(self) -> None:
        """15:00 启动：14:50 到点未跑要补，15:30 还没到不算。"""
        jobs = [_job(last_run_at="")]
        now = datetime(2026, 9, 2, 15, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(jobs, last_trading_day="2026-09-02", now=now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0][CATCHUP_SLOT_KEY], slot_for_day("2026-09-02", 14, 50))

    def test_returned_item_does_not_mutate_input(self) -> None:
        job = _job()
        now = datetime(2026, 9, 2, 17, 0, tzinfo=_TZ)
        jobs_due_for_eod_catchup([job], last_trading_day="2026-09-02", now=now)
        self.assertNotIn(CATCHUP_SLOT_KEY, job)


class SlotAwareSuccessTests(unittest.TestCase):
    def test_earlier_success_does_not_cover_later_slot(self) -> None:
        store = _Store([_success_run("2026-09-02T14:50:00.025309+08:00")])
        slot = slot_for_day("2026-09-02", 15, 30)
        self.assertFalse(
            job_succeeded_on_trading_day(store, job_id="JOB-1", day="2026-09-02", slot=slot)
        )
        # 不传 slot 保持旧口径：当日有成功即视为已跑。
        self.assertTrue(job_succeeded_on_trading_day(store, job_id="JOB-1", day="2026-09-02"))

    def test_success_after_slot_covers_it(self) -> None:
        store = _Store([_success_run("2026-09-02T17:20:35.942516+08:00")])
        slot = slot_for_day("2026-09-02", 15, 30)
        self.assertTrue(
            job_succeeded_on_trading_day(store, job_id="JOB-1", day="2026-09-02", slot=slot)
        )

    def test_other_day_success_never_counts(self) -> None:
        run = _success_run("2026-09-01T15:31:00+08:00")
        run["result"] = {"trade_date": "2026-09-01"}
        store = _Store([run])
        self.assertFalse(
            job_succeeded_on_trading_day(
                store, job_id="JOB-1", day="2026-09-02", slot=slot_for_day("2026-09-02", 15, 30)
            )
        )


class RunCatchupMultiSlotTests(unittest.TestCase):
    def test_failed_later_slot_gets_rerun_despite_earlier_success(self) -> None:
        """线上形态：14:50 success、15:30 failed，启动补跑必须真的跑一次。"""
        store = _Store(
            [_success_run("2026-09-02T14:50:00+08:00")],
            jobs=[_job(last_run_at="2026-09-02T14:50:51+08:00")],
        )
        now = datetime(2026, 9, 2, 17, 0, tzinfo=_TZ)
        with mock.patch("src.ops.application.jobs.run_job") as run_job:
            out = run_eod_catchup(
                ops_store_factory=lambda: store,
                context_factory=lambda: None,
                last_trading_day="2026-09-02",
                now=now,
            )
        run_job.assert_called_once()
        self.assertEqual(run_job.call_args.kwargs.get("trigger"), "catchup")
        self.assertEqual(out["ran"], ["screen:yangshi-tail-v1"])
        self.assertEqual(out["skipped"], [])

    def test_success_after_slot_is_skipped(self) -> None:
        store = _Store(
            [_success_run("2026-09-02T17:20:35+08:00")],
            jobs=[_job(last_run_at="2026-09-02T14:50:51+08:00")],
        )
        now = datetime(2026, 9, 2, 18, 0, tzinfo=_TZ)
        with mock.patch("src.ops.application.jobs.run_job") as run_job:
            out = run_eod_catchup(
                ops_store_factory=lambda: store,
                context_factory=lambda: None,
                last_trading_day="2026-09-02",
                now=now,
            )
        run_job.assert_not_called()
        self.assertEqual(out["skipped"], ["screen:yangshi-tail-v1"])


if __name__ == "__main__":
    unittest.main()
