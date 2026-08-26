"""纸面舱启用时同步盯盘 / 日终 Job。"""
from __future__ import annotations

from pathlib import Path

from src.ops.application.ensure_paper_monitor_jobs import (
    eod_job_name,
    ensure_paper_monitor_jobs,
    monitor_job_name,
)
from src.ops.infrastructure.store import OpsStore


def test_ensure_paper_monitor_jobs_create_and_disable(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        out = ensure_paper_monitor_jobs(
            store,
            "demo",
            enabled=True,
            interval="*/10 9-14 * * 1-5",
        )
        assert out["actions"]["strategy_monitor"] == "created"
        assert out["actions"]["paper_eod"] == "created"
        mon = store.get_job_by_name(monitor_job_name("demo"))
        eod = store.get_job_by_name(eod_job_name("demo"))
        assert mon is not None
        assert mon["kind"] == "strategy_monitor"
        assert mon["enabled"] is True
        assert mon["cron"] == "*/10 9-14 * * 1-5"
        assert mon["config"]["slug"] == "demo"
        assert eod is not None and eod["kind"] == "paper_eod"
        assert eod["cron"] == "30 15 * * mon-fri"

        out2 = ensure_paper_monitor_jobs(store, "demo", enabled=False)
        assert out2["actions"]["strategy_monitor"] == "disabled"
        mon2 = store.get_job_by_name(monitor_job_name("demo"))
        assert mon2 is not None
        assert mon2["enabled"] is False

        out3 = ensure_paper_monitor_jobs(
            store,
            "demo",
            enabled=True,
            interval="*/15 9-14 * * 1-5",
        )
        assert out3["actions"]["strategy_monitor"] == "enabled"
        mon3 = store.get_job_by_name(monitor_job_name("demo"))
        assert mon3 is not None
        assert mon3["enabled"] is True
        assert mon3["cron"] == "*/15 9-14 * * 1-5"
