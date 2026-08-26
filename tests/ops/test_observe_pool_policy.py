"""观察池题材集中度与观察寿命策略。"""
from __future__ import annotations

from src.ops.application.skill_watch.observe_pool import (
    format_observe_change_report,
    merge_observe_pool,
)
from src.ops.application.skill_watch.tuning import normalize_tuning


def _row(code: str, score: int, **extra: object) -> dict[str, object]:
    return {"code": code, "name": code, "intent": "observe", "score": score, **extra}


def test_same_theme_is_limited_but_other_theme_can_enter() -> None:
    fresh = [
        _row("a", 70, theme_code="T1", theme_name="主线一"),
        _row("b", 69, theme_code="T1", theme_name="主线一"),
        _row("c", 68, theme_code="T1", theme_name="主线一"),
        _row("d", 67, theme_code="T2", theme_name="主线二"),
    ]
    merged, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=fresh,
        previous_items=[],
        max_pool=5,
        max_daily_adds=4,
        max_same_theme=2,
    )

    assert [row["code"] for row in merged] == ["a", "b", "d"]
    assert report["limited"][0]["code"] == "c"
    assert "同题材上限" in report["limited"][0]["reason"]
    assert "主线一" in format_observe_change_report(report)


def test_old_theme_overage_is_sticky() -> None:
    previous = [
        _row("a", 70, theme_code="T1", theme_name="主线一"),
        _row("b", 69, theme_code="T1", theme_name="主线一"),
        _row("c", 68, theme_code="T1", theme_name="主线一"),
    ]
    merged, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=[],
        previous_items=previous,
        max_pool=5,
        max_same_theme=2,
        max_miss_days=10,
    )

    assert {row["code"] for row in merged} == {"a", "b", "c"}
    assert report["limited"] == []


def test_observe_age_marks_qualified_ticket_as_stale() -> None:
    previous = [
        _row(
            "old",
            60,
            observe_since="2026-08-01",
            last_seen_date="2026-08-10",
            miss_days=0,
        )
    ]
    merged, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=[],
        previous_items=previous,
        trade_date="2026-08-11",
        max_miss_days=20,
        max_age_days=10,
    )

    row = merged[0]
    assert row["age_days"] == 10
    assert row["stale_observe"] is True
    assert "久观无果" in row["observe_reason"]
    assert report["stale"][0]["code"] == "old"
    assert "久观无果" in format_observe_change_report(report)


def test_stale_ticket_can_be_replaced_without_eight_point_margin() -> None:
    previous = [
        _row("old", 80, theme_code="T1", observe_since="2026-08-01", miss_days=0),
        _row("keep", 90, theme_code="T2", observe_since="2026-08-10", miss_days=0),
    ]
    fresh = [_row("new", 51, theme_code="T3")]
    merged, report = merge_observe_pool(
        held_codes=set(),
        fresh_observes=fresh,
        previous_items=previous,
        max_pool=2,
        max_daily_adds=1,
        replace_margin=8,
        trade_date="2026-08-11",
        max_miss_days=20,
        max_age_days=10,
    )

    assert {row["code"] for row in merged} == {"keep", "new"}
    assert report["added"] == []
    assert report["replaced"][0]["out_code"] == "old"
    assert "久观无果" in report["replaced"][0]["reason"]
    assert "优先换新" in format_observe_change_report(report)


def test_observe_tuning_has_bounded_defaults() -> None:
    tuning = normalize_tuning(
        {
            "scan": {
                "observe_max_same_theme": 99,
                "observe_max_age_days": 99,
            }
        }
    )
    scan = tuning["scan"]
    assert scan["observe_max_same_theme"] == 20.0
    assert scan["observe_max_age_days"] == 60.0
    assert normalize_tuning(None)["scan"]["observe_max_age_days"] == 10.0


def test_observe_tuning_scan_fields_are_consumed_by_unified_pool_upstream() -> None:
    """观察策略由扫描入口消费；次日预案只消费统一池，不再自建第二套合并。"""
    from pathlib import Path

    plan = Path("src/ops/application/jobs/paper_quant_plan.py").read_text(encoding="utf-8")
    eod = Path("src/ops/application/jobs/paper_quant_eod.py").read_text(encoding="utf-8")
    dragon = Path("src/ops/application/skill_watch/dragon_return.py").read_text(encoding="utf-8")
    runner = Path("src/ops/application/skill_watch/runner.py").read_text(encoding="utf-8")
    assert "reconcile_unified_monitor_pool" in plan
    assert "merge_observe_pool" not in plan
    assert "max_same_theme=" in runner and "max_age_days=" in runner
    assert "observe_max_same_theme" in runner and "observe_max_age_days" in runner
    assert "observe_max_same_theme" in eod and "observe_max_age_days" in eod
    assert "observe_max_same_theme" in dragon
    assert "max_same_theme=" in eod and "max_age_days=" in eod
    assert "max_same_theme=" in dragon
