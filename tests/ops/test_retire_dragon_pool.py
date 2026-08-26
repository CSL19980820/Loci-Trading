"""龙池退役清理：存量安装里的任务、状态与候选都要真的消失。

只删源码是不够的——ops.db 里那条任务照样会被调度，执行器找不到引擎就每 5 分钟
推一条失败，比不删更吵。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.ops.application.ensure_managed_jobs import ensure_all_managed_jobs
from src.ops.application.retire_dragon_pool import (
    RETIRED_FEED,
    RETIRED_JOB_NAME,
    RETIRED_SLUG,
    retire_dragon_pool,
)
from src.ops.application.unified_monitor_pool import (
    drop_candidate_feed,
    reconcile_unified_monitor_pool,
)
from src.ops.infrastructure.store import OpsStore


def _install_legacy_pool(store: OpsStore) -> str:
    return store.create_job(
        name=RETIRED_JOB_NAME,
        kind="skill_watch",
        cron="*/5 9-14 * * mon-fri",
        config={"skill": RETIRED_SLUG, "push_wecom": True},
        enabled=True,
    )


def test_retire_removes_job_and_state(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        _install_legacy_pool(store)
        store.set_setting(f"dragon_pool_state:{RETIRED_SLUG}", {"items": {"600001": {}}})
        store.set_setting("watch_daily_brief", {RETIRED_SLUG: "2026-08-12"})

        with patch(
            "src.ops.application.skills.uninstall_skill", return_value=True
        ) as uninstall:
            out = retire_dragon_pool(store)

        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert store.get_setting(f"dragon_pool_state:{RETIRED_SLUG}", None) is None
        assert store.get_setting("watch_daily_brief", None) is None

    uninstall.assert_called_once_with(RETIRED_SLUG)
    assert out["removed_jobs"] == [RETIRED_JOB_NAME]
    assert out["removed_skill"] is True


def test_retire_clears_the_pools_own_snapshot(tmp_path: Path) -> None:
    """龙池自己那份统一池快照也要清掉。

    ``drop_candidate_feed`` 只摘龙回头池里的龙池候选，摘不到
    ``unified_monitor_pool:dragon-pool``；漏掉它就在 ops.db 里留一份没人再消费的
    孤儿名单（实测存量安装里是 7.7KB）。
    """
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(RETIRED_SLUG)
        reconcile_unified_monitor_pool(
            store,
            slug=RETIRED_SLUG,
            trade_date="2026-08-12",
            candidates=[{"code": "600001", "name": "池票", "candidate_feed": RETIRED_FEED}],
        )
        assert store.get_setting(f"unified_monitor_pool:{RETIRED_SLUG}", None) is not None

        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_dragon_pool(store)

        assert store.get_setting(f"unified_monitor_pool:{RETIRED_SLUG}", None) is None

    assert f"unified_monitor_pool:{RETIRED_SLUG}" in out["cleared_settings"]


def test_retire_is_idempotent_on_clean_install(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_dragon_pool(store)

    assert out["removed_jobs"] == []
    assert out["removed_skill"] is False
    assert out["dropped_candidates"] == 0


def test_retire_drops_pool_candidates_but_keeps_the_rest(tmp_path: Path) -> None:
    """只摘龙池那条来源，别把龙回头自己的观察池一起抹掉。"""
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-12",
            candidates=[
                {"code": "600001", "name": "池票", "candidate_feed": RETIRED_FEED},
                {
                    "code": "600002",
                    "name": "题材票",
                    "candidate_feed": "skill_watch:dragon-return",
                },
            ],
        )

        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            out = retire_dragon_pool(store)

        raw = store.get_setting("unified_monitor_pool:dragon-return", {})
        codes = [row["code"] for row in raw.get("items") or []]

    assert out["dropped_candidates"] == 1
    assert codes == ["600002"]


def test_drop_candidate_feed_keeps_snapshot_date(tmp_path: Path) -> None:
    """不能借道 replace_candidate_feed：日期对不上会把整池当空的重建。"""
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin("dragon-return")
        reconcile_unified_monitor_pool(
            store,
            slug="dragon-return",
            trade_date="2026-08-11",
            candidates=[
                {"code": "600001", "name": "池票", "candidate_feed": RETIRED_FEED}
            ],
        )

        dropped = drop_candidate_feed(store, slug="dragon-return", feed=RETIRED_FEED)
        raw = store.get_setting("unified_monitor_pool:dragon-return", {})

    assert dropped == 1
    assert raw["trade_date"] == "2026-08-11"
    assert raw["items"] == []


def test_startup_retires_the_pool(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        _install_legacy_pool(store)
        with patch("src.ops.application.skills.uninstall_skill", return_value=False):
            ensure_all_managed_jobs(store)

        assert store.get_job_by_name(RETIRED_JOB_NAME) is None
        assert not [
            job
            for job in store.list_jobs() or []
            if str((job.get("config") or {}).get("skill") or "") == RETIRED_SLUG
        ]
