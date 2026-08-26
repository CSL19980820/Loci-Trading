"""龙回头纸面舱退役：删舱、卸技能、清任务，启动后不再挂回来。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.application.ensure_managed_jobs import ensure_all_managed_jobs
from src.ops.application.ensure_paper_monitor_jobs import (
    eod_job_name,
    ensure_paper_monitor_jobs,
    reconcile_dragon_return_jobs,
)
from src.ops.application.retire_dragon_return import (
    RETIRED_JOB_NAME,
    RETIRED_SLUG,
    retire_dragon_return,
)
from src.ops.application.skill_watch.watch_labels import watch_job_title
from src.ops.application.unified_monitor_pool import reconcile_unified_monitor_pool
from src.ops.infrastructure.store import OpsStore


def test_retire_removes_cabin_jobs_and_pool(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(RETIRED_SLUG)
        store.create_job(
            name=RETIRED_JOB_NAME,
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": RETIRED_SLUG, "paper_monitor_slug": RETIRED_SLUG},
            enabled=True,
        )
        store.create_job(
            name=eod_job_name(RETIRED_SLUG),
            kind="paper_eod",
            cron="30 15 * * mon-fri",
            config={"slug": RETIRED_SLUG},
            enabled=True,
        )
        reconcile_unified_monitor_pool(
            store,
            slug=RETIRED_SLUG,
            trade_date="2026-08-13",
            candidates=[{"code": "000859", "name": "国风新材", "intent": "observe"}],
        )
        store.set_setting(f"paper_follow_hold:{RETIRED_SLUG}", "fingerprint")

        with patch(
            "src.ops.application.skills.uninstall_skill", return_value=True
        ) as uninstall:
            out = retire_dragon_return(store)

        assert store.get_paper_cabin(RETIRED_SLUG) is None
        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert store.get_job_by_name(eod_job_name(RETIRED_SLUG)) is None
        assert store.get_setting(f"unified_monitor_pool:{RETIRED_SLUG}", None) is None
        assert store.get_setting(f"paper_follow_hold:{RETIRED_SLUG}", None) is None

    uninstall.assert_called_once_with(RETIRED_SLUG)
    assert out["removed_cabin"] is True
    assert RETIRED_JOB_NAME in out["removed_jobs"]
    assert out["removed_skill"] is True


def test_retire_keeps_second_wave_jobs(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.create_job(
            name="监测·二波监测",
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": "dragon-second-wave"},
            enabled=True,
        )
        store.create_job(
            name="龙回头·二波监测",
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": "dragon-second-wave"},
            enabled=True,
        )
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            retire_dragon_return(store)

        assert store.get_job_by_name("监测·二波监测") is not None
        assert store.get_job_by_name("龙回头·二波监测") is not None


def test_retire_is_idempotent(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_dragon_return(store)

    assert out["removed_jobs"] == []
    assert out["removed_cabin"] is False
    assert out["removed_skill"] is False


def test_ensure_paper_monitor_jobs_does_not_recreate(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.create_job(
            name=RETIRED_JOB_NAME,
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": RETIRED_SLUG},
            enabled=True,
        )
        out = ensure_paper_monitor_jobs(store, RETIRED_SLUG, enabled=True)
        assert out["retired"] is True
        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert store.get_job_by_name(watch_job_title(slug=RETIRED_SLUG)) is None


def test_startup_retires_instead_of_reconciling(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(RETIRED_SLUG, config={"paper_quant": {"enabled": True}})
        store.create_job(
            name=RETIRED_JOB_NAME,
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": RETIRED_SLUG},
            enabled=True,
        )
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            ensure_all_managed_jobs(store)

        assert store.get_paper_cabin(RETIRED_SLUG) is None
        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert reconcile_dragon_return_jobs(store)["removed_cabin"] is False


def test_get_cabin_is_gone_when_missing(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db):
        pass
    app = FastAPI()
    app.include_router(
        build_paper_quant_router(write_dependency=lambda: None, ops_db=str(db))
    )
    with TestClient(app) as client:
        response = client.get(f"/api/ops/paper-cabins/{RETIRED_SLUG}")
    assert response.status_code == 410


def test_strategy_monitor_does_not_resurrect(tmp_path: Path) -> None:
    from src.ops.application.jobs.context import JobContext
    from src.ops.application.jobs.paper_quant_monitor import execute_strategy_monitor

    with OpsStore(tmp_path / "ops.db") as store:
        out = execute_strategy_monitor(
            {"slug": RETIRED_SLUG, "force": True},
            JobContext(ops_store=store),
        )
        assert out["skipped"] is True
        assert out["reason"] == "retired_paper_cabin"
        assert store.get_paper_cabin(RETIRED_SLUG) is None


def test_paper_eod_does_not_resurrect(tmp_path: Path) -> None:
    from src.ops.application.jobs.context import JobContext
    from src.ops.application.jobs.paper_quant_eod import execute_paper_eod

    with OpsStore(tmp_path / "ops.db") as store:
        out = execute_paper_eod(
            {"slug": RETIRED_SLUG},
            JobContext(ops_store=store),
        )
        assert out["skipped"] is True
        assert out["reason"] == "retired_paper_cabin"
        assert store.get_paper_cabin(RETIRED_SLUG) is None


def test_get_cabin_does_not_resurrect(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        assert store.get_paper_cabin(RETIRED_SLUG) is None
    app = FastAPI()
    app.include_router(
        build_paper_quant_router(write_dependency=lambda: None, ops_db=str(db))
    )
    with TestClient(app) as client:
        client.get(f"/api/ops/paper-cabins/{RETIRED_SLUG}")
    with OpsStore(db) as store:
        assert store.get_paper_cabin(RETIRED_SLUG) is None
