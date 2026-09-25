"""The opening auction starts with a small, usable catalog and can expand it safely."""

import json
import time
from types import SimpleNamespace

from src.ops.application import guardian_agent, guardian_config
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_tool_catalog import ResearchToolCatalog


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name,
            "description": "行情口径、来源与时间必须核对。" * 45,
            "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                           "additionalProperties": False}}}


def _production_sized_catalog() -> list[dict]:
    opening = ["guardian_quotes", "guardian_runtime", "guardian_account_read",
               "guardian_calculate", "guardian_preflight", "wudao__market_overview",
               "wudao__intraday_main_flow", "wudao__theme_intraday_capital",
               "wudao__auction_theme_strength", "wudao__auction_opening_snapshot",
               "wudao__auction_data", "wudao__auction_market_scan", "wudao__kline"]
    names = opening + [f"wudao__research_{index}" for index in range(84 - len(opening))]
    return [_schema(name) for name in names]


def _names(schemas: list[dict]) -> set[str]:
    return {(schema.get("function") or schema)["name"] for schema in schemas}


def test_opening_catalog_keeps_actual_auction_tools_ready_and_other_tools_discoverable():
    schemas = _production_sized_catalog()
    catalog = ResearchToolCatalog("openai", schemas, lambda: None, opening_auction=True)
    initial = catalog.schemas
    assert len(catalog.catalog) == 84
    assert {"wudao__auction_theme_strength", "wudao__auction_opening_snapshot",
            "wudao__auction_data", "wudao__auction_market_scan", "wudao__kline"} <= _names(initial)
    assert "wudao__research_70" not in _names(initial)
    assert len(json.dumps(initial, ensure_ascii=False)) < len(json.dumps(schemas, ensure_ascii=False)) / 4

    found = json.loads(catalog.search({"names": ["wudao__research_70"]})["text"])
    assert found["loaded"][0]["name"] == "wudao__research_70"
    assert catalog.schemas is initial and "wudao__research_70" in _names(initial)
    assert catalog.metrics()["available_tools"] == 84
    assert catalog.metrics()["loaded_tools"] == 14

    intraday = ResearchToolCatalog("openai", schemas, lambda: None)
    assert "wudao__auction_data" not in _names(intraday.schemas)
    assert "wudao__auction_data" in intraday.catalog


def test_trader_passes_mutable_catalog_to_next_round_and_gates_unloaded_tools(monkeypatch):
    import src.ai

    calls = []
    schemas = _production_sized_catalog()
    monkeypatch.setattr(src.ai, "resolve_config", lambda *_args, **_kwargs:
                        SimpleNamespace(model="fixture", protocol="openai"))
    monkeypatch.setattr(guardian_agent, "compose_research_tools", lambda *_args, **_kwargs:
                        (schemas, lambda name, args: calls.append((name, args)) or {"text": '{"ok":true}'}, {}))

    def complete(_provider, _store, **kwargs):
        offered = kwargs["schemas"]
        execute = kwargs["execute"]
        assert "wudao__auction_data" in _names(offered)
        assert "wudao__research_70" not in _names(offered)
        assert execute("wudao__research_70", {})["is_error"]
        assert not calls
        search = execute("guardian_tools_search", {"names": ["wudao__research_70"]})
        assert json.loads(search["text"])["loaded"][0]["name"] == "wudao__research_70"
        assert "wudao__research_70" in _names(offered)
        assert json.loads(execute("wudao__research_70", {"code": "600000"})["text"])["ok"]
        assert calls == [("wudao__research_70", {"code": "600000"})]
        return GuardianDecision(summary="等待开盘", orders=[]), {"tools": []}

    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    _, usage = guardian_agent.decide(None, {**guardian_config.DEFAULTS, "model": "fixture"},
                                     {"as_of": "2026-09-23T09:25:00+08:00",
                                      "portfolio": {"positions": [], "watchlist": []}})
    assert usage["context_usage"]["available_tools"] == 84
    assert usage["context_usage"]["final_loaded_tools"] == 14
    assert usage["context_usage"]["loaded_tool_schema_characters"] < len(json.dumps(schemas, ensure_ascii=False)) / 4


def test_catalog_cannot_cross_tenant_boundary(monkeypatch):
    from src.ops.application import guardian_tool_catalog

    active = ["owner"]
    monkeypatch.setattr(guardian_tool_catalog, "current_tenant", lambda: active[0])
    catalog = ResearchToolCatalog("openai", [_schema("wudao__research_0")], lambda: None)
    active[0] = "other"
    denied = catalog.search({"names": ["wudao__research_0"]})
    assert denied["is_error"]
    assert "wudao__research_0" not in catalog.loaded


def test_real_agent_model_round_receives_newly_discovered_schema(monkeypatch):
    from src.ai.application import agent
    from src.ai.infrastructure.client import ChatResponse, ProviderConfig, ToolCall

    catalog = ResearchToolCatalog("openai_compatible", [_schema("wudao__research_0")], lambda: None)
    seen = []

    def stream(_config, _messages, **options):
        names = _names(options["tools"])
        seen.append(names)
        if len(seen) == 1:
            assert "wudao__research_0" not in names
            return ChatResponse("", tool_calls=[ToolCall("search", "guardian_tools_search",
                                                     {"names": ["wudao__research_0"]})],
                                raw={"finish_reason": "tool_calls"})
        if len(seen) == 2:
            assert "wudao__research_0" in names
            return ChatResponse("", tool_calls=[ToolCall("query", "wudao__research_0",
                                                     {"code": "600000"})],
                                raw={"finish_reason": "tool_calls"})
        return ChatResponse('{"summary":"完成","orders":[]}', raw={"finish_reason": "stop"})

    def execute(name, arguments):
        if name == "guardian_tools_search":
            return catalog.search(arguments)
        assert name in catalog.loaded and arguments == {"code": "600000"}
        return {"text": '{"price":10}'}

    monkeypatch.setattr(agent, "chat_stream", stream)
    result = agent.run_agent(
        ProviderConfig("fixture", "openai_compatible", "https://example.com", "fixture", model="fixture"),
        system="fixture", user_prompt="fixture", tool_executor=execute, tool_schemas=catalog.schemas,
        deadline=time.monotonic() + 30)
    assert result.text == '{"summary":"完成","orders":[]}'
    assert len(seen) == 3
