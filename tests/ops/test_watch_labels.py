"""监测推送标题/跳过原因：全中文、不复读任务行。"""
from __future__ import annotations

from src.ops.application.skill_watch.watch_labels import format_watch_status_push


def test_skipped_push_has_chinese_title_without_task_echo() -> None:
    title, body = format_watch_status_push(
        slug="dragon-return",
        job_name="监测·dragon-return",
        status="skipped",
        reason="market_gate_degraded",
    )
    assert title == "监测·龙回头"
    assert "dragon-return" not in title
    assert "dragon-return" not in body
    assert "skill_watch" not in body
    assert "任务" not in body
    assert "关键指标不全" in body


def test_success_summary_is_body_only() -> None:
    title, body = format_watch_status_push(
        slug="market-leader-map",
        status="success",
        summary="2026-08-07\n闸门：空仓\n→ 今日不扩仓",
    )
    assert title == "监测·龙头地图"
    assert body.startswith("2026-08-07")
    assert "【任务" not in body
