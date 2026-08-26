"""角色演进推导：存活、转移、预警提前量、持仓告警与日终消费。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ops.application.jobs.context import JobContext
from src.ops.application.skill_watch.role_stats import (
    format_role_review,
    format_tuning_suggestions,
    position_role_alerts,
    role_lessons,
    role_transitions,
    suggest_tuning_adjustments,
    summarize_role_history,
)
from src.ops.infrastructure.store import OpsStore


def _row(day: str, hour: int, role: str, *, code: str = "600001") -> dict[str, Any]:
    return {
        "code": code,
        "name": "测试龙",
        "role": role,
        "role_basis": f"{role} 判定依据",
        "theme_name": "机器人",
        "trade_date": day,
        "observed_at": f"{day}T{hour:02d}:30:00+08:00",
        "metrics": {},
    }


#: 连续三日龙头，第四日走弱，第五日破位。留痕是时间倒序的。
_HISTORY = list(
    reversed(
        [
            _row("2026-08-03", 10, "leader"),
            _row("2026-08-04", 10, "leader"),
            _row("2026-08-05", 10, "leader"),
            _row("2026-08-06", 10, "weakened"),
            _row("2026-08-07", 10, "failed"),
        ]
    )
)


def test_transitions_only_report_real_role_changes() -> None:
    transitions = role_transitions(_HISTORY)

    assert [(item["from_role"], item["to_role"]) for item in transitions] == [
        ("weakened", "failed"),
        ("leader", "weakened"),
    ]
    assert transitions[0]["theme_name"] == "机器人"


def test_summary_counts_leader_survival_and_warning_lead() -> None:
    summary = summarize_role_history(_HISTORY)

    assert summary["codes"] == 1
    assert summary["trade_days"] == 5
    survival = summary["leader_survival"][0]
    assert survival["leader_days"] == 3
    assert survival["still_leader"] is False
    assert survival["current_role"] == "failed"
    # 走弱比破位早一个交易日 —— 这就是这套判定给出的提前量
    assert summary["warning_lead"]["samples"] == 1
    assert summary["warning_lead"]["avg_days"] == 1.0
    assert summary["transition_matrix"]["leader->weakened"] == 1


def test_summary_is_safe_on_empty_history() -> None:
    summary = summarize_role_history([])

    assert summary["observations"] == 0
    assert summary["leader_survival"] == []
    assert summary["warning_lead"]["samples"] == 0
    assert format_role_review(summary, []) == ""
    assert suggest_tuning_adjustments([]) == []


def test_suggest_tuning_when_leader_weakened_is_frequent() -> None:
    """两只票、多日留痕，龙头→走弱多次时应给出收紧建议。"""
    history = list(
        reversed(
            [
                _row("2026-08-01", 10, "leader", code="600001"),
                _row("2026-08-02", 10, "leader", code="600001"),
                _row("2026-08-03", 10, "weakened", code="600001"),
                _row("2026-08-01", 10, "leader", code="600002"),
                _row("2026-08-02", 10, "leader", code="600002"),
                _row("2026-08-03", 10, "weakened", code="600002"),
                _row("2026-08-04", 10, "failed", code="600002"),
            ]
        )
    )

    suggestions = suggest_tuning_adjustments(history)

    directions = {item["direction"] for item in suggestions}
    assert "tighten_weakened_drawdown" in directions
    assert all("message" in item for item in suggestions)
    assert format_tuning_suggestions(suggestions).startswith("🔧【调参建议·仅参考】")


def test_suggest_tuning_empty_on_short_history() -> None:
    history = list(reversed([_row("2026-08-07", 10, "leader")]))

    assert suggest_tuning_adjustments(history) == []


def test_regained_strength_resets_the_warning_window() -> None:
    """走弱后又变回龙头，再破位不应算成一次超长提前量。"""
    history = list(
        reversed(
            [
                _row("2026-08-03", 10, "weakened"),
                _row("2026-08-04", 10, "leader"),
                _row("2026-08-05", 10, "failed"),
            ]
        )
    )

    assert summarize_role_history(history)["warning_lead"]["samples"] == 0


def test_position_alerts_only_fire_for_weakened_or_failed_holdings() -> None:
    positions = [
        {"code": "600001", "name": "测试龙", "layers": 1.0},
        {"code": "600002", "name": "没留痕", "layers": 0.5},
    ]

    alerts = position_role_alerts(positions=positions, history=_HISTORY)

    assert [alert["code"] for alert in alerts] == ["600001"]
    assert alerts[0]["role"] == "failed"
    assert alerts[0]["layers"] == 1.0

    lessons = role_lessons(slug="dragon-return", trade_date="2026-08-07", alerts=alerts)
    assert lessons[0]["kind"] == "role_alert"
    assert "结构破坏" in lessons[0]["title"]


def test_eod_consumes_role_history_into_body_and_lessons(tmp_path: Path, monkeypatch) -> None:
    """留痕的唯一消费端：日终把它读成正文段落 + 教训。"""
    from src.ops.application.jobs import paper_quant
    from src.ops.application.jobs import paper_quant_eod
    from src.ops.application.jobs import paper_quant_support as pq_support

    monkeypatch.setattr(pq_support, "_today", lambda: "2026-08-07")
    monkeypatch.setattr(pq_support, "_next_trade_date", lambda *_a, **_k: "2026-08-10")
    monkeypatch.setattr(
        "src.ops.application.paper_style_memory.run_eod_learning",
        lambda *a, **k: {"critique": "", "lessons": [], "absorbed": 0, "style": {}},
    )
    monkeypatch.setattr(paper_quant_eod, "dispatch_text", lambda *a, **k: {"sent": False})
    monkeypatch.setattr(
        pq_support,
        "resolve_trading_day_gate",
        lambda *a, **k: {
            "trade_date": "2026-08-07",
            "is_trading_day": True,
            "last_trading_day": "2026-08-07",
            "calendar_source": "test",
            "buy_execution_allowed": True,
            "note": "test trading day",
        },
    )

    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin(
            "dragon-return", config={"eod_style_learn": True}
        )
        store.upsert_paper_position(
            cabin["id"], code="600001", name="测试龙", layers=1.0, mark_cost=10.0
        )
        for row in reversed(_HISTORY):
            store.record_leader_roles(
                "dragon-return",
                trade_date=row["trade_date"],
                observed_at=row["observed_at"],
                gate_state="dragon",
                entries=[row],
            )

        result = paper_quant.execute_paper_eod(
            {"slug": "dragon-return", "push": False}, JobContext(ops_store=store)
        )
        lessons = store.list_paper_lessons("dragon-return", limit=10)

    assert result["role_review"]["lessons"] == 1
    assert result["role_review"]["summary"]["leader_survival"][0]["leader_days"] == 3
    assert [alert["code"] for alert in result["role_review"]["alerts"]] == ["600001"]
    assert any(lesson["kind"] == "role_alert" for lesson in lessons)
