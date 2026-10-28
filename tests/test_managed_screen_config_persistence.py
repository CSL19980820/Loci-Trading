"""Startup reconciliation preserves explicitly bound formula strategy jobs."""

import pytest

from src.ops import OpsStore
from src.shared.tenancy import tenant_scope
from src.strategy import get


FORMULA_SLUGS = ("impulse-inside-breakout-v1", "contraction-rebreakout-v1")


@pytest.fixture
def formula_catalog(monkeypatch):
    import src.strategy

    engines = [get(slug) for slug in FORMULA_SLUGS]
    assert all(engine.screen_managed_job is False for engine in engines)
    monkeypatch.setattr(src.strategy, "all_strategies", lambda: engines)


@pytest.mark.parametrize("slug", FORMULA_SLUGS)
@pytest.mark.parametrize("enabled", [True, False])
def test_user_bound_formula_config_survives_reconcile_and_reopen(
    tmp_path, formula_catalog, slug, enabled,
):
    path = tmp_path / "ops.db"
    config = {
        "strategy": slug,
        "schedule": {
            "mode": "once", "run_hour": 14, "run_minute": 50,
            "interval_minutes": 10, "window_start_hour": 9,
            "window_start_minute": 30, "window_end_hour": 15,
            "window_end_minute": 0,
        },
        "universe": {
            "boards": ["main", "chi_next"], "min_list_days": 180,
            "exclude_st": True,
        },
        "params": {}, "top_n": 1, "trading_days": 240,
        "push_wecom": False, "record_candidates": True,
        "hold_days": 7, "stop_loss_pct": -4.5,
        "use_ai_pick": False,
    }
    with tenant_scope("__primary__"), OpsStore(path) as store:
        job_id = store.create_job(
            name=f"screen:{slug}", kind="screen", cron="50 14 * * mon-fri",
            config=config, enabled=enabled,
        )
        original = store.get_job(job_id)
        for _ in range(2):
            result = store.ensure_managed_screen_jobs()
            assert store.get_job(job_id) == original
            assert result["created"] == result["removed"] == 0
    with tenant_scope("__primary__"), OpsStore(path) as reopened:
        reopened.ensure_managed_screen_jobs()
        assert reopened.get_job(job_id) == original


@pytest.mark.parametrize("slug", FORMULA_SLUGS)
def test_formula_catalog_does_not_create_unrequested_or_opted_out_jobs(
    tmp_path, formula_catalog, slug,
):
    with tenant_scope("__primary__"), OpsStore(tmp_path / "ops.db") as store:
        store.ensure_managed_screen_jobs()
        assert store.get_job_by_name(f"screen:{slug}") is None
        store.set_screen_job_opt_out(slug)
        store.ensure_managed_screen_jobs()
        assert store.is_screen_job_opted_out(slug)
        assert store.get_job_by_name(f"screen:{slug}") is None


def test_unknown_bound_strategy_is_still_removed(tmp_path, formula_catalog):
    with tenant_scope("__primary__"), OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(
            name="screen:missing-strategy", kind="screen",
            config={"strategy": "missing-strategy"},
        )
        result = store.ensure_managed_screen_jobs()
        assert result["removed"] == 1
        assert result["removed_slugs"] == ["missing-strategy"]
        assert store.get_job(job_id) is None
