"""Finalized sync runs warm the reproducible current-day and recent-month caches."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from src.ops.application.jobs import registry


def test_post_close_warm_is_tenant_safe_deduplicated_and_does_not_record(monkeypatch):
    spawned = []
    market_calls = []
    screen_calls = []
    store = SimpleNamespace()
    context = SimpleNamespace(market=lambda: market_calls.append(store) or nullcontext(store))

    def spawn(target, *, name=None):
        spawned.append((target, name))
        return SimpleNamespace(name=name)

    monkeypatch.setattr("src.shared.tenancy.spawn_tenant_thread", spawn)
    with registry._POST_CLOSE_WARM_LOCK:
        registry._POST_CLOSE_WARM_INFLIGHT.clear()
    try:
        registry._schedule_post_close_screen_warm(context)
        registry._schedule_post_close_screen_warm(context)
        assert len(spawned) == 1
        assert spawned[0][1] == "loci-warm-first-wave"
    finally:
        with registry._POST_CLOSE_WARM_LOCK:
            registry._POST_CLOSE_WARM_INFLIGHT.clear()

    monkeypatch.setattr(
        "src.shared.tenancy.spawn_tenant_thread",
        lambda target, *, name=None: (target(), SimpleNamespace(name=name))[1],
    )
    monkeypatch.setattr("src.market.resolve_screen_trade_date", lambda actual_store: "2026-10-27")
    days = [
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-09",
        "2026-10-10",
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
        "2026-10-17",
        "2026-10-20",
        "2026-10-21",
        "2026-10-22",
        "2026-10-23",
        "2026-10-24",
        "2026-10-26",
        "2026-10-27",
    ]
    store.trading_days = lambda **_kwargs: days
    monkeypatch.setattr("src.strategy.get", lambda slug: SimpleNamespace(slug=slug))
    monkeypatch.setattr(
        "src.ops.application.screen_job_config.resolve_screen_universe",
        lambda slug, requested, *, store: {"preset": "default_a_share"},
    )
    monkeypatch.setattr(
        "src.strategy.screen",
        lambda *args, **kwargs: screen_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "src.shared.screen_capacity.screen_capacity_permit",
        lambda **_kwargs: nullcontext(),
    )
    registry._schedule_post_close_screen_warm(context)
    assert market_calls == [store]
    assert len(screen_calls) == len(days) * 2
    assert [call[1]["trade_date"] for call in screen_calls] == [*days, *days]
    assert [call[0][1].slug for call in screen_calls] == [
        *(["first-wave-pullback-v1"] * len(days)),
        *(["yangshi-tail-v1"] * len(days)),
    ]
    assert screen_calls[0][1]["health_check"] is True
    assert screen_calls[len(days)][1]["health_check"] is True
    assert all(call[1]["health_check"] is False for i, call in enumerate(screen_calls)
               if i not in {0, len(days)})
    assert all(call[1]["universe"] == {"preset": "default_a_share"} for call in screen_calls)
    assert all(call[1]["live_overlay"] is False for call in screen_calls)
    assert all(call[1]["result_cache"] is True for call in screen_calls)
