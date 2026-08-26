"""纸面跟随持仓行与 hold 节流。"""
from __future__ import annotations

from pathlib import Path

from src.ops.application.jobs.paper_follow_push import (
    format_position_lines,
    format_stance_line,
    phase_zh,
    scrub_follow_reason,
    should_push_hold_snapshot,
)
from src.ops.infrastructure.store import OpsStore


def test_format_position_lines_with_pnl() -> None:
    lines = format_position_lines(
        [{"code": "600519", "name": "茅台", "layers": 1.5, "mark_cost": 100.0}],
        {"600519": {"price": 110.0}},
    )
    assert len(lines) == 1
    assert "📦茅台" in lines[0]
    assert "1.5层" in lines[0]
    assert "成本100" in lines[0]
    assert "+10.0%" in lines[0]


def test_phase_and_stance_are_chinese() -> None:
    assert phase_zh("regular") == "盘中"
    line = format_stance_line(
        {
            "code": "600519",
            "name": "茅台",
            "stance": "abandon",
            "gap_pct": 1.01,
            "reason": "gap_up 情景预案不买",
        }
    )
    assert "茅台" in line
    assert "放弃" in line
    assert "高开" in line
    assert "预案不买" in line
    assert "abandon" not in line.lower()
    assert "gap_up" not in line.lower()
    assert scrub_follow_reason("gap_up abandon") == "高开 放弃"
    leaked = (
        "市场闸门为空仓窗口（entry_allowed=false），且两只票均为观察票（intent=observe），"
        "禁止开仓。百花医药高开9.96%接近涨停，竞价stance=放弃，不追高；"
        "人民同泰高开2.03%，其gap_up预案不买，均仅跟踪。"
    )
    cleaned = scrub_follow_reason(leaked)
    assert "gap_up" not in cleaned.lower()
    assert "entry_allowed" not in cleaned.lower()
    assert "intent=" not in cleaned.lower()
    assert "stance=" not in cleaned.lower()
    assert "高开预案不买" in cleaned or "其高开预案不买" in cleaned
    assert "不允许开仓" in cleaned
    assert "观察票" in cleaned


def test_hold_snapshot_throttles_same_state(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    positions = [{"code": "600519", "name": "茅台", "layers": 1.0, "mark_cost": 100.0}]
    with OpsStore(db) as store:
        assert (
            should_push_hold_snapshot(
                store,
                slug="dragon-return",
                trade_date="2026-08-07",
                phase="continuous",
                positions=positions,
                notes="观望",
                market_gate={"state": "dragon"},
            )
            is True
        )
        assert (
            should_push_hold_snapshot(
                store,
                slug="dragon-return",
                trade_date="2026-08-07",
                phase="continuous",
                positions=positions,
                notes="观望",
                market_gate={"state": "dragon"},
            )
            is False
        )
        assert (
            should_push_hold_snapshot(
                store,
                slug="dragon-return",
                trade_date="2026-08-07",
                phase="continuous",
                positions=positions,
                notes="观望→减仓",
                market_gate={"state": "dragon"},
            )
            is False
        )
