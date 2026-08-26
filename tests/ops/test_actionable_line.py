"""纸面介入一行：层数 / 买价 / 单一盈亏比例。"""
from __future__ import annotations

from src.ops.application.skill_watch.actionable_line import (
    enrich_actionable_fields,
    format_actionable_line,
    layers_for_candidate,
)


def test_format_has_single_pnl_pct_no_slash() -> None:
    text = format_actionable_line(
        name="百花医药",
        layers=3,
        buy_price=11.2,
        pnl_pct=-20,
    )
    assert text == "💰百花医药 · 3层 · 买11.2 · -20%"
    assert "/" not in text


def test_format_prefers_one_value_when_both_passed() -> None:
    text = format_actionable_line(
        name="百花医药",
        layers=3,
        buy_price=11.2,
        stop_loss_pct=-15,
        take_profit_pct=25,
    )
    assert text == "💰百花医药 · 3层 · 买11.2 · -15%"
    assert "+25%" not in text
    assert "/" not in text


def test_layers_scale_with_score() -> None:
    assert layers_for_candidate(90, role="leader") == 3.0
    assert layers_for_candidate(80, role="leader") == 2.0
    assert layers_for_candidate(70, role="leader") == 1.0
    assert layers_for_candidate(90, role="secondary") == 1.5


def test_enrich_does_not_invent_default_band() -> None:
    row = enrich_actionable_fields(
        {"code": "600721", "name": "百花医药", "close": 11.2, "score": 88, "role": "leader"}
    )
    assert row["planned_layers"] == 3.0
    assert row["buy_price"] == 11.2
    assert "pnl_pct" not in row
    assert format_actionable_line(
        name=row["name"], layers=row["planned_layers"], buy_price=row["buy_price"]
    ) == "💰百花医药 · 3层 · 买11.2"


def test_enrich_keeps_observe_layers_at_zero() -> None:
    row = enrich_actionable_fields(
        {
            "code": "600721",
            "name": "百花医药",
            "close": 11.2,
            "score": 88,
            "role": "leader",
            "intent": "observe",
            "planned_layers": 0.0,
            "planned_layers_max": 0.0,
        }
    )
    assert row["planned_layers"] == 0.0
    assert row["planned_layers_max"] == 0.0
    assert "buy_price" not in row
