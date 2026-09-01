"""二波监测退役：启动时把任务、技能包、状态键幂等清干净。

盯的是同一个坑：只删源码的话，用户 ops.db 里那条 `*/5 9-14` 的托管任务照样触发，
执行器找不到技能就每 5 分钟推一条失败。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.ops.application.ensure_managed_jobs import ensure_all_managed_jobs
from src.ops.application.retire_second_wave import (
    RETIRED_JOB_NAME,
    RETIRED_SLUG,
    retire_second_wave,
)
from src.ops.infrastructure.store import OpsStore


def _make_watch_job(store: OpsStore, name: str = RETIRED_JOB_NAME) -> None:
    store.create_job(
        name=name,
        kind="skill_watch",
        cron="*/5 9-14 * * mon-fri",
        config={"skill": RETIRED_SLUG, "push_wecom": True},
        enabled=True,
    )


def test_retire_removes_job_skill_and_settings(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        _make_watch_job(store)
        store.set_setting("second_wave_latest", {"slug": RETIRED_SLUG, "pool_size": 12})
        store.set_setting(f"watch_tuning:{RETIRED_SLUG}", {"second_wave": {"min_strength": 45}})
        store.set_setting(f"unified_monitor_pool:{RETIRED_SLUG}", {"items": []})

        with patch(
            "src.ops.application.skills.uninstall_skill", return_value=True
        ) as uninstall:
            out = retire_second_wave(store)

        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert store.get_setting("second_wave_latest", None) is None
        assert store.get_setting(f"watch_tuning:{RETIRED_SLUG}", None) is None
        assert store.get_setting(f"unified_monitor_pool:{RETIRED_SLUG}", None) is None

    uninstall.assert_called_once_with(RETIRED_SLUG)
    assert RETIRED_JOB_NAME in out["removed_jobs"]
    assert out["removed_skill"] is True


def test_retire_matches_legacy_job_name(tmp_path: Path) -> None:
    """老安装里这条任务叫「监测·dragon-second-wave」，同样要清掉。"""
    with OpsStore(tmp_path / "ops.db") as store:
        store.create_job(
            name=f"监测·{RETIRED_SLUG}",
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={},
            enabled=True,
        )
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_second_wave(store)

        assert store.get_job_by_name(f"监测·{RETIRED_SLUG}") is None
    assert out["removed_jobs"] == [f"监测·{RETIRED_SLUG}"]


def test_retire_keeps_other_strategy_jobs(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        store.create_job(
            name="监测·龙头地图",
            kind="skill_watch",
            cron="*/10 9-14 * * mon-fri",
            config={"skill": "market-leader-map"},
            enabled=True,
        )
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            retire_second_wave(store)

        assert store.get_job_by_name("监测·龙头地图") is not None


def test_retire_is_idempotent(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_second_wave(store)

    assert out["removed_jobs"] == []
    assert out["removed_skill"] is False
    assert out["cleared_settings"] == []


def test_startup_retires_and_never_recreates(tmp_path: Path) -> None:
    """启动路径：既要清掉存量任务，也不许再把它挂回来。"""
    with OpsStore(tmp_path / "ops.db") as store:
        _make_watch_job(store)
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            ensure_all_managed_jobs(store)
            ensure_all_managed_jobs(store)

        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        names = [str(job.get("name") or "") for job in store.list_jobs() or []]

    assert not [name for name in names if "二波" in name]


def test_signals_table_is_dropped(tmp_path: Path) -> None:
    """留痕表由迁移里的 DROP 收走；旧库重新打开后不该再有这张表。"""
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.conn.execute(
            "CREATE TABLE IF NOT EXISTS second_wave_signals (id TEXT PRIMARY KEY)"
        )
        store.conn.commit()

    with OpsStore(db) as store:
        found = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='second_wave_signals'"
        ).fetchall()

    assert found == []
