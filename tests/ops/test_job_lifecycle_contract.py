from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import time
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from src.ops.application.jobs import JobContext, run_job
from src.ops.application.jobs import registry
from src.ops.application.jobs.intel_fetch import execute_intel_fetch
from src.ops.infrastructure.store import OpsError, OpsStore


def test_cancel_request_converges_to_cancelled_terminal_state(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "ops.db"
    with OpsStore(db_path) as store:
        job_id = store.create_job(name="cancel-me", kind="sync")
    started = Event()

    def cooperative_executor(_: dict, context: JobContext) -> dict:
        started.set()
        while True:
            context.check_cancelled()
            time.sleep(0.001)

    monkeypatch.setitem(registry.EXECUTORS, "sync", cooperative_executor)

    def invoke() -> dict:
        with OpsStore(db_path) as worker_store:
            return run_job(
                worker_store,
                job_id,
                context=JobContext(ops_store=worker_store),
                trigger="test",
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke)
        assert started.wait(timeout=2)
        with OpsStore(db_path) as store:
            run = store.list_runs(job_id=job_id)[0]
            assert store.request_cancel(run["id"], reason="测试取消")
        outcome = future.result(timeout=2)

    assert outcome["status"] == "cancelled"
    with OpsStore(db_path) as store:
        run = store.list_runs(job_id=job_id)[0]
        assert run["status"] == "cancelled"
        assert run["cancel_requested"] is True


def test_timeout_converges_to_timed_out_terminal_state(tmp_path: Path, monkeypatch) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="timeout-me", kind="sync", config={"timeout_sec": 0.005})

        def slow_executor(_: dict, context: JobContext) -> dict:
            time.sleep(0.03)
            context.check_cancelled()
            return {"unexpected": True}

        monkeypatch.setitem(registry.EXECUTORS, "sync", slow_executor)
        outcome = run_job(
            store,
            job_id,
            context=JobContext(ops_store=store, timeout_seconds=0.005),
        )

        assert outcome["status"] == "timed_out"
        assert store.list_runs(job_id=job_id)[0]["status"] == "timed_out"


def test_idempotency_reuses_terminal_result_without_reexecution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[int] = []
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="once", kind="sync")

        def executor(_: dict, __: JobContext) -> dict:
            calls.append(1)
            return {"value": len(calls)}

        monkeypatch.setitem(registry.EXECUTORS, "sync", executor)
        first = run_job(store, job_id, idempotency_key="request-1")
        second = run_job(store, job_id, idempotency_key="request-1")

        assert first["status"] == "success"
        assert second["status"] == "success"
        assert second["idempotent"] is True
        assert calls == [1]
        assert len(store.list_runs(job_id=job_id)) == 1


def test_heartbeat_keeps_old_started_run_claimed(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="heartbeat", kind="sync")
        job = store.get_job(job_id)
        assert job is not None
        run_id = store.start_run(job)
        with store._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET started_at = datetime('now', '-60 minutes'), "
                "heartbeat_at = datetime('now', '-1 seconds') WHERE id = ?",
                (run_id,),
            )
        assert store.heartbeat_run(run_id)
        claimed_id, claimed = store.claim_run(job)

        assert claimed is False
        assert claimed_id == run_id
        assert store.get_run(run_id)["status"] == "running"


def test_finish_run_cannot_overwrite_terminal_state(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="terminal", kind="sync")
        run_id = store.start_run(store.get_job(job_id))
        store.finish_run(run_id, status="cancelled", error="cancelled")
        with pytest.raises(OpsError, match="已进入终态"):
            store.finish_run(run_id, status="success")


@contextmanager
def _market_slot(*_args: object, **_kwargs: object) -> Iterator[None]:
    yield


@pytest.mark.parametrize(
    ("kind", "executor_result"),
    [
        ("sync", {"failed": 3, "succeeded": 10, "total": 13}),
        (
            "intel_fetch",
            {
                "phase": "open",
                "stats": {"ok": 1, "failed": 2, "cached": 0, "quota_skipped": 0},
                "receipts": [],
            },
        ),
    ],
)
def test_partial_executor_result_marks_run_failed(
    kind: str,
    executor_result: dict[str, object],
) -> None:
    store = MagicMock()
    job = {
        "id": f"job-{kind}",
        "kind": kind,
        "name": kind,
        "config": {},
        "enabled": True,
    }

    def executor(_config: dict, _context: object) -> dict[str, object]:
        return executor_result

    with (
        patch.dict(registry.EXECUTORS, {kind: executor}),
        patch.object(registry, "_maybe_push_wecom", return_value=None),
        patch.object(registry, "_maybe_seed_nextday_plan"),
        patch.object(registry, "market_heavy_slot", _market_slot),
    ):
        outcome = registry.run_job(store, job, run_id=f"run-{kind}")

    assert outcome["status"] == "failed"
    assert store.finish_run.call_args.kwargs["status"] == "failed"


def test_intel_fetch_soft_skips_when_wudao_unavailable() -> None:
    context = JobContext(ops_store=MagicMock())
    with (
        patch(
            "src.intel.wudao_availability",
            return_value={"available": False, "reason": "悟道 MCP 未配置 API Key"},
        ),
        patch("src.intel.quota_snapshot", return_value={"remaining": 0}),
        patch("src.intel.application.daily_recipe.build_static_calls") as static_calls,
    ):
        result = execute_intel_fetch({"phase": "open"}, context)

    assert result["skipped"] is True
    assert result["reason"] == "mcp_unavailable"
    assert "未装配" in result["summary"]
    static_calls.assert_not_called()

def test_intel_fetch_preflight_warns_instead_of_truncating() -> None:
    """启动自检：超预算写中文告警，但**不**替用户少拿数据。"""
    from src.ops.application.jobs.intel_fetch import _quota_preflight

    context = JobContext()
    quota = {"limits": {"structured": 3000, "skill": 2000}}
    greedy = {
        "theme_top_n": 120,
        "stock_flow_top_n": 120,
        "screener_count": 10,
        "intraday_theme_top_n": 120,
    }
    estimate, alert = _quota_preflight(
        {"phase": "intraday"},
        context,
        phase="intraday",
        live_knobs=greedy,
        pool="structured",
        quota=quota,
    )
    assert estimate["intraday_runs"] == 24, "轮次要从托管 cron 推"
    assert alert is not None
    assert "超出日预算" in alert["message"]
    assert "不会自动少拿数据" in alert["message"]

    _capped, no_alert = _quota_preflight(
        {"phase": "intraday"},
        context,
        phase="intraday",
        live_knobs={**greedy, "intraday_theme_top_n": 40},
        pool="structured",
        quota=quota,
    )
    assert no_alert is None
    assert _capped["within_budget"] is True


def test_job_finished_event_keeps_run_and_job_correlation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LOCI_OBSERVABILITY", "1")
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="observed", kind="sync")
        monkeypatch.setitem(
            registry.EXECUTORS,
            "sync",
            lambda _config, _context: {"ok": True},
        )
        with caplog.at_level(logging.INFO):
            result = run_job(store, job_id, context=JobContext(ops_store=store))

    events = [
        json.loads(record.getMessage().split(" ", 1)[1])
        for record in caplog.records
        if "loci_observation" in record.getMessage()
    ]
    finished = next(item for item in events if item["event"] == "job_finished")
    assert result["status"] == "success"
    assert finished["trace_id"]
    assert finished["run_id"] == result["run_id"]
    assert finished["job_id"] == job_id
