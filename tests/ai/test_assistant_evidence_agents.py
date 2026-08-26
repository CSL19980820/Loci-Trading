"""助手角色化证据子 Agent 单元测试。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.ai.application.assistant_evidence_agents import (
    format_evidence_briefs,
    plan_evidence_roles,
    run_evidence_agents,
)
from src.ai.application.system_toolbus import build_system_toolbus


def test_plan_evidence_roles_qianlong_and_market() -> None:
    roles = plan_evidence_roles("帮我看潜龙候选精选")
    assert [r.role for r in roles] == ["qianlong", "market"]
    assert "qianlong_candidate_pool" in roles[0].allow_tools
    assert not roles[0].allow_web


def test_holdings_wording_no_longer_spawns_ledger_role() -> None:
    """实盘账本下线后没有持仓/成交可查，这类话术不该再起一个空工具面的子 Agent。"""
    assert plan_evidence_roles("查询当前持仓和成本") == []


def test_plan_evidence_roles_web_slot() -> None:
    roles = plan_evidence_roles("搜一下这条政策新闻的外网消息")
    assert any(r.role == "web" for r in roles)
    web = next(r for r in roles if r.role == "web")
    assert web.allow_web
    assert web.allow_tools == frozenset({"web_search", "web_fetch"})


def test_plan_evidence_roles_caps_at_three() -> None:
    roles = plan_evidence_roles("潜龙精选持仓成本政策新闻研究画像")
    assert len(roles) <= 3


def test_format_evidence_briefs_marks_non_verdict() -> None:
    text = format_evidence_briefs(
        [
            {"id": "a", "name": "候选核对", "role": "qianlong", "ok": True, "text": "池内 2 只"},
            {"id": "b", "name": "外网", "role": "web", "ok": False, "text": "超时"},
        ]
    )
    assert "非终裁" in text
    assert "[成功] 候选核对" in text
    assert "[失败] 外网" in text


def test_allow_tools_filters_system_toolbus(tmp_path) -> None:
    bus = build_system_toolbus(
        palace_db=str(tmp_path / "palace.db"),
        market_db=str(tmp_path / "market.db"),
        ops_db=str(tmp_path / "ops.db"),
        read_only=True,
        attach_mcp=False,
        allow_tools={"qianlong_candidate_pool", "web_search"},
    )
    names = {spec["name"] for spec in bus.catalog()}
    assert names == {"qianlong_candidate_pool", "web_search"}


def test_run_evidence_agents_injectable_brief(tmp_path) -> None:
    events: list[dict] = []
    config = SimpleNamespace(name="t", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(
        text="池内 8 只，缺口：缺日 K",
        stopped_reason="completed",
        rounds=1,
        input_tokens=1,
        output_tokens=1,
        model="m",
    )

    with patch("src.ai.application.assistant_evidence_agents.run_agent", return_value=outcome):
        rows = run_evidence_agents(
            config=config,
            prompt="潜龙候选核对",
            palace_db=str(tmp_path / "palace.db"),
            market_db=str(tmp_path / "market.db"),
            ops_db=str(tmp_path / "ops.db"),
            on_event=events.append,
        )
    assert len(rows) == 2
    assert all(row["ok"] for row in rows)
    brief = format_evidence_briefs(rows)
    assert "候选证据" in brief or "行情证据" in brief
    assert any(e.get("type") == "plan" for e in events)
    assert any(e.get("type") == "subagent_end" for e in events)
