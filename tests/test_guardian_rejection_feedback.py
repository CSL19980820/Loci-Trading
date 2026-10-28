"""预演拒单与工具错误不结束模型研究，始终保留模拟账户的硬保护。"""
from copy import deepcopy
from datetime import datetime
import json
import time
from types import SimpleNamespace

import pytest

from src.ai.application import agent
from src.ai.infrastructure.client import ChatResponse, ProviderConfig, ToolCall
from src.ledger import GuardianStore
from src.ledger.domain.guardian_account import new_guardian_account
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application import guardian_research_tools as research


NOW = datetime.fromisoformat("2026-10-14T10:00:00+08:00")
CODE = "000823"


def research_tools(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(research, "datetime", Clock)
    monkeypatch.setattr(research.GuardianResearchTools, "_bus", lambda _: SimpleNamespace(schemas=[]))
    state = new_guardian_account()
    path = tmp_path / "palace.db"
    tools = research.GuardianResearchTools("openai_compatible", palace_path=path,
        payload={"as_of": NOW.isoformat(), "portfolio": state}, deadline=time.monotonic() + 30)
    row = {"code": CODE, "name": "超声电子", "price": 22.32, "prev_close": 20.29,
           "source": "fixture", "trade_date": NOW.date().isoformat(), "trade_time": "10:00:00"}
    monkeypatch.setattr(tools, "_snapshot", lambda codes: {code: deepcopy(row) for code in codes})
    return tools, state, path


def buy():
    return {"summary": "拟买入", "orders": [{"code": CODE, "action": "buy", "quantity": 1200,
        "reason": "核验计划", "execution": {"kind": "market", "valid_until": "2026-10-14T10:05:00+08:00"}}]}


@pytest.mark.parametrize("first", ["limit_reject", "invalid_order", "tool_timeout"])
def test_model_continues_after_rejected_preflight_or_failed_tool(tmp_path, monkeypatch, first):
    tools, state, path = research_tools(tmp_path, monkeypatch)
    original = deepcopy(state)
    requests, calls = [], []
    proposed = buy()
    if first == "invalid_order":
        proposed["orders"][0].pop("execution")
    if first == "tool_timeout":
        monkeypatch.setattr(tools, "_snapshot", lambda _codes: (_ for _ in ()).throw(TimeoutError("行情源单次请求超时")))

    def stream(_provider, messages, **_options):
        requests.append(messages)
        if len(requests) == 1:
            return ChatResponse("", tool_calls=[ToolCall("preflight", "guardian_preflight", proposed)],
                                raw={"finish_reason": "tool_calls"})
        if len(requests) == 2:
            feedback = json.loads(messages[-1].content)
            if first == "limit_reject":
                assert feedback["ledger_committed"] is False and feedback["preflight_fills"] == []
                assert feedback["rejects"][0]["code"] == CODE and "涨停" in feedback["rejects"][0]["reason"]
            else:
                assert feedback["recoverable"] and feedback["tool"] == "guardian_preflight"
                assert "execution" in feedback["error"] if first == "invalid_order" else "超时" in feedback["error"]
            return ChatResponse("", tool_calls=[ToolCall("account", "guardian_account_read", {})],
                                raw={"finish_reason": "tool_calls"})
        account = json.loads(messages[-1].content)
        assert account["portfolio"]["cash_cents"] == state["cash_cents"]
        return ChatResponse(json.dumps({"summary": "涨停只观察，保留现金", "orders": [
            {"code": CODE, "action": "watch", "reason": "等待开板后重新核验"}]}, ensure_ascii=False),
            raw={"finish_reason": "stop"})

    def execute(name, arguments):
        calls.append(name)
        return tools.execute(name, arguments)

    monkeypatch.setattr(agent, "chat_stream", stream)
    result = agent.run_agent(ProviderConfig("fixture", "openai_compatible", "https://example.invalid", "fixture", model="fixture"),
        system="fixture", user_prompt="fixture", tool_schemas=tools.schemas, tool_executor=execute,
        deadline=time.monotonic() + 30, max_rounds=None, max_calls_per_round=None)
    final = GuardianDecision.model_validate_json(result.text)
    assert final.orders[0].action == "watch" and result.stopped_reason == "completed"
    assert len(requests) == 3 and calls == ["guardian_preflight", "guardian_account_read"]
    assert state == original
    with GuardianStore(path) as ledger:
        assert ledger.trades()["total"] == 0 and ledger.state()["positions"] == []
        assert ledger.state()["cash_cents"] == original["cash_cents"]
