"""Research capabilities remain available without mutating the trading ledger."""
from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore
from src.ops.application import guardian_research_tools as workbench
from src.ops.application.guardian_compute import calculate
from src.ops.application.guardian_research_tools import GuardianResearchTools, compose_research_tools
from src.shared.tenancy import submit_with_tenant, tenant_scope
from tests.ops.test_guardian import EMPTY, NOW, decision, quotes


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    leaked = []
    def denied(*args, **kwargs):
        leaked.append(True)
        raise AssertionError("External IO must be mocked")
    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr(workbench, "datetime", SimpleNamespace(now=lambda tz: NOW))
    yield
    assert not leaked


@pytest.fixture
def tools(tmp_path):
    return GuardianResearchTools("openai_compatible", payload={"portfolio": EMPTY, "as_of": NOW.isoformat()},
        palace_path=tmp_path / "isolated.db", deadline=time.monotonic() + 60)


def test_workbench_contains_market_web_history_calculator_and_preview(tools):
    assert {"guardian_preflight", "guardian_quotes", "guardian_calculate", "guardian_scenario",
            "guardian_account_read", "guardian_runtime", "guardian_decision_history",
            "system__web_search", "system__web_fetch", "system__strategy_catalog"} <= tools.names
    assert len(tools.names) == len(tools.schemas)
    assert not any("ask_user" in name or "ledger_upsert" in name for name in tools.names)


def test_preflight_charges_fees_only_on_copy_and_keeps_fixed_reference(tools, monkeypatch):
    monkeypatch.setattr("src.ops.application.guardian_tools.snapshot", lambda *a, **kw: SimpleNamespace(quotes=quotes(9.01)))
    with GuardianStore(tools.palace_path) as ledger:
        original = ledger.state()
        proposed = decision().model_dump(mode="json")
        result = tools.execute("guardian_preflight", proposed)["structured"]
        assert result["preflight_only"] and not result["ledger_committed"]
        assert result["preflight_fills"][0]["price_cents"] == 901
        assert result["preflight_fills"][0]["fees_cents"] > 0
        assert result["decision_with_fixed_references"]["orders"][0]["execution"]["reference_price"] == 9.01
        assert ledger.state() == original and ledger.trades()["total"] == 0
        assert proposed["orders"][0]["execution"]["reference_price"] is None
        assert tools.payload["portfolio"] == EMPTY


def test_model_can_change_stock_and_quantity_in_research_preview(tools, monkeypatch):
    def snapshot(codes, **kwargs):
        return SimpleNamespace(quotes={c: {**quotes(10)["600001"], "code": c} for c in codes})
    monkeypatch.setattr("src.ops.application.guardian_tools.snapshot", snapshot)
    for code, quantity in [("600001", 100), ("600002", 200), ("600003", 500)]:
        proposed = decision(code=code, quantity=quantity).model_dump(mode="json")
        result = tools.execute("guardian_preflight", proposed)["structured"]
        assert not result["rejects"]
        assert result["preflight_fills"][0]["quantity"] == quantity
        assert result["preflight_fills"][0]["code"] == code


def test_quote_errors_are_explicit_not_an_empty_market(tools, monkeypatch):
    monkeypatch.setattr("src.ops.application.guardian_tools.snapshot", lambda *a, **kw: SimpleNamespace(quotes=quotes(10)))
    result = tools.execute("guardian_quotes", {"codes": ["600001", "600002"]})["structured"]
    assert result["valid_codes"] == ["600001"]
    assert result["quote_errors"]["600002"]


def test_system_tools_return_full_structured_payload(tools):
    value = {"rows": ["long evidence" * 2000]}
    tools.sessions.bus.executor = Mock(return_value={"text": "short display", "structured": value})
    result = tools.execute("system__web_search", {"query": "fixture"})
    assert json.loads(result["text"]) == value


def test_primary_discovery_failure_retains_system_capabilities():
    def failed(*a, **kw):
        raise ValueError("primary unavailable")
    schemas, execute, source = compose_research_tools("openai_compatible", primary_loader=failed,
        payload={"portfolio": EMPTY}, deadline=time.monotonic()+30)
    assert source["primary_error"] == "primary unavailable"
    assert "system__web_search" in {(s.get("function") or s)["name"] for s in schemas}
    assert execute("guardian_calculate", {"expression": "9 * 1.02"})["structured"]["decimal_result"] == "9.18"


def test_cross_tenant_reference_cannot_read_another_account():
    with tenant_scope("workbench_a"):
        tools = GuardianResearchTools("anthropic", payload={"portfolio": EMPTY})
    with tenant_scope("workbench_b"), pytest.raises(ValueError, match="租户"):
        tools.execute("guardian_account_read", {})


def test_parallel_workers_have_separate_system_toolbus(tools):
    barrier = Barrier(2)
    def identity():
        value = id(tools._bus())
        barrier.wait(3)
        return value
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [submit_with_tenant(pool, identity) for _ in range(2)]
        assert len({f.result(4) for f in futures}) == 2


def test_scenario_reports_locked_shares_without_imposing_loss_threshold(tools):
    from src.ledger import settle_guardian_order
    state = copy.deepcopy(EMPTY)
    settle_guardian_order(state, decision().orders[0].model_dump(mode="json"), quotes(10)["600001"], NOW, {})
    tools.payload["portfolio"] = state
    result = tools.execute("guardian_scenario", {"shocks": [{"code": "600001", "change_pct": -10}]})["structured"]
    assert result["hypothetical"] and result["change_cents"] == -10000
    exposure = tools.execute("guardian_account_read", {})["structured"]["exposure"]
    assert exposure["positions"][0]["locked_quantity"] == 100
    assert tools.payload["portfolio"] == state


@pytest.mark.parametrize("expression,expected", [("0.1+0.2", "0.3"), ("9*1.02", "9.18"),
    ("(9.01-9)/9*100", "0.11111111111111111111111111111111111111111111111111"), ("2**10", "1024")])
def test_decimal_calculation(expression, expected):
    assert calculate(expression)["decimal_result"] == expected


@pytest.mark.parametrize("expression", ["1/0", "True+1", "open('data')", "__import__('os')", "2**101"])
def test_calculator_is_not_a_code_execution_side_channel(expression):
    with pytest.raises((ValueError, SyntaxError)):
        calculate(expression)
