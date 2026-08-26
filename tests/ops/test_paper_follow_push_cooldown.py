"""盘中观察预警按票/原因冷却。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ops.application.jobs.paper_follow_push import (
    filter_observe_alert_lines,
    should_push_hold_snapshot,
)
from src.ops.infrastructure.store import OpsStore


_NOW = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)
_POSITION = [{"code": "600519", "layers": 1.0, "mark_cost": 100.0}]


def _hold_kwargs(alert: str, *, slug: str = "dragon-return") -> dict:
    return {
        "slug": slug,
        "trade_date": "2026-08-07",
        "phase": "regular",
        "positions": _POSITION,
        "notes": "观望",
        "market_gate": {"state": "dragon"},
        "observe_alert_fp": alert,
    }


def test_alert_is_pushed_once_per_reason_during_cooldown(tmp_path: Path) -> None:
    line = "⚠️观察预警 茅台 600519 · 跌破分线"
    with OpsStore(tmp_path / "ops.db") as store:
        kwargs = _hold_kwargs(line)
        assert should_push_hold_snapshot(store, **kwargs, now=_NOW) is True
        assert (
            should_push_hold_snapshot(
                store,
                **kwargs,
                now=_NOW + timedelta(minutes=29),
            )
            is False
        )
        assert (
            should_push_hold_snapshot(
                store,
                **kwargs,
                now=_NOW + timedelta(minutes=30),
            )
            is True
        )


def test_cooldown_survives_ops_store_restart(tmp_path: Path) -> None:
    line = "⚠️观察预警 茅台 600519 · 跌破分线"
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        assert should_push_hold_snapshot(store, **_hold_kwargs(line), now=_NOW) is True
    with OpsStore(db) as store:
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(line),
                now=_NOW + timedelta(minutes=1),
            )
            is False
        )


def test_reason_or_severity_change_pushes_immediately(tmp_path: Path) -> None:
    first = "⚠️观察预警 茅台 600519 · 走弱"
    changed_reason = "⚠️观察预警 茅台 600519 · 结构破坏"
    first_severity = "⚠️观察预警 茅台 600519 · -5.0%"
    changed_severity = "⚠️观察预警 茅台 600519 · -7.0%"
    with OpsStore(tmp_path / "ops.db") as store:
        assert should_push_hold_snapshot(store, **_hold_kwargs(first), now=_NOW) is True
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(changed_reason),
                now=_NOW + timedelta(minutes=1),
            )
            is True
        )
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(first_severity),
                now=_NOW + timedelta(minutes=2),
            )
            is True
        )
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(changed_severity),
                now=_NOW + timedelta(minutes=3),
            )
            is True
        )


def test_different_codes_and_slugs_do_not_share_cooldown(tmp_path: Path) -> None:
    first = "⚠️观察预警 茅台 600519 · 跌破分线"
    other_code = "⚠️观察预警 平安 000001 · 跌破分线"
    with OpsStore(tmp_path / "ops.db") as store:
        assert should_push_hold_snapshot(store, **_hold_kwargs(first), now=_NOW) is True
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(other_code),
                now=_NOW + timedelta(minutes=1),
            )
            is True
        )
        assert (
            should_push_hold_snapshot(
                store,
                **_hold_kwargs(first, slug="other-strategy"),
                now=_NOW + timedelta(minutes=2),
            )
            is True
        )


def test_alert_cooldown_does_not_suppress_changed_hold_body(tmp_path: Path) -> None:
    line = "⚠️观察预警 茅台 600519 · 跌破分线"
    with OpsStore(tmp_path / "ops.db") as store:
        assert should_push_hold_snapshot(store, **_hold_kwargs(line), now=_NOW) is True
        changed_positions = [{"code": "600519", "layers": 2.0, "mark_cost": 100.0}]
        changed = _hold_kwargs(line)
        changed["positions"] = changed_positions
        assert (
            should_push_hold_snapshot(
                store,
                **changed,
                now=_NOW + timedelta(minutes=1),
            )
            is True
        )


def test_alert_filter_keeps_only_new_warning_rows(tmp_path: Path) -> None:
    first = "⚠️观察预警 茅台 600519 · 跌破分线"
    other = "⚠️观察预警 平安 000001 · 走弱"
    with OpsStore(tmp_path / "ops.db") as store:
        assert filter_observe_alert_lines(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            alert_lines=[first, other],
            now=_NOW,
        ) == [first, other]
        assert filter_observe_alert_lines(
            store,
            slug="dragon-return",
            trade_date="2026-08-07",
            alert_lines=[first, other],
            now=_NOW + timedelta(minutes=1),
        ) == []
