from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ledger import GuardianStore, new_guardian_account
from src.ops.api.guardian import build_guardian_router
from src.ops.application.guardian_config import DEFAULTS, JOB_NAME, get_config, save_config
from src.ops.application.guardian_decision import parse_decision, render_digest, simulate
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobContext, JobError, JobSkipped
from src.ops.infrastructure.store import OpsStore
from src.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
EMPTY = new_guardian_account()
CANDIDATES = [{"code": "600001", "name": "测试股票", "strategies": ["trend"]}]


def quotes(price, now=NOW):
    return {"600001": {"price": price, "trade_date": now.strftime("%Y-%m-%d"), "trade_time": now.strftime("%H:%M:%S")}}


def decision(action="buy", quantity=100, code="600001"):
    return parse_decision(json.dumps({"summary": "战法确认", "orders": [{"code": code, "action": action, "quantity": quantity, "reason": "量价确认", "execution": {"kind": "market", "valid_until": "2026-12-31T15:00:00+08:00"}}]}))


def test_buy_add_reduce_sell_and_reenter():
    state, fills, rejects = simulate(EMPTY, decision(), CANDIDATES, quotes(10), NOW)
    assert fills[0]["after_quantity"] == 100 and not rejects
    state, _, _ = simulate(state, decision("add"), CANDIDATES, quotes(12), NOW)
    assert state["positions"][0]["quantity"] == 200
    tomorrow = NOW.replace(day=14)
    state, fills, rejects = simulate(state, decision("reduce", 100), CANDIDATES, quotes(13, tomorrow), tomorrow)
    assert state["positions"][0]["quantity"] == 100 and not rejects
    state, fills, rejects = simulate(state, decision("sell", 100), CANDIDATES, quotes(13, tomorrow), tomorrow)
    assert state["positions"] == [] and not rejects
    assert fills[0]["after_quantity"] == 0
    state, fills, rejects = simulate(state, decision(), [], quotes(13, tomorrow), tomorrow)
    assert fills and not rejects


@pytest.mark.parametrize("price", [None, -1, 0, float("nan"), float("inf")])
def test_missing_or_invalid_quote_never_fills(price):
    state, fills, rejects = simulate(EMPTY, decision(), CANDIDATES, {"600001": {"price": price}}, NOW)
    assert state["cash_cents"] == EMPTY["cash_cents"] and not state["positions"] and not fills and rejects


def test_model_selects_outside_pool_but_account_enforces_cash_and_t1():
    state, _, _ = simulate(EMPTY, decision(), [], quotes(10), NOW)
    _, fills, rejects = simulate(state, decision("sell"), [], quotes(10), NOW)
    assert not fills and "T+1" in rejects[0]["reason"]
    _, fills, rejects = simulate(EMPTY, decision("buy", 19900), [], quotes(10), NOW)
    assert fills[0]["after_quantity"] == 19900 and not rejects
    _, fills, rejects = simulate(EMPTY, decision("buy", 20000), [], quotes(10), NOW)
    assert not fills and "现金不足" in rejects[0]["reason"]


def test_context_includes_enabled_strategies_and_parameters(monkeypatch):
    from src.ops.application.guardian_context import active_strategies
    monkeypatch.setattr("src.strategy.describe_all", lambda: [{"slug": "trend", "name": "趋势", "entry_instructions": "按趋势研判"}])
    with OpsStore(None) as store:
        store.create_job(name="启用战法", kind="screen", enabled=True, config={"strategy": "trend", "params": {"lookback": 20}, "webhook": "must-not-leak"})
        store.create_job(name="关闭战法", kind="screen", enabled=False, config={"strategy": "disabled"})
        rows = active_strategies(store)
    assert len(rows) == 1 and rows[0]["slug"] == "trend"
    assert rows[0]["jobs"][0]["params"] == {"lookback": 20}
    assert rows[0]["entry_instructions"] == "按趋势研判"
    assert "must-not-leak" not in json.dumps(rows)


def test_stale_quote_cannot_fill():
    _, fills, rejects = simulate(EMPTY, decision(), CANDIDATES, quotes(10, NOW.replace(hour=9)), NOW)
    assert not fills and "报价过期" in rejects[0]["reason"]


def test_model_uses_full_mcp_results_and_accounts_all_rounds(monkeypatch):
    from src.ai import ChatResponse, ProviderConfig, ToolCall
    from src.intel import BUILTIN_WUDAO_NAME, McpTool
    from src.ops.application.guardian_agent import decide
    provider = ProviderConfig(name="test", protocol="openai_compatible", base_url="https://example.invalid", api_key="test", model="test")
    monkeypatch.setattr("src.ai.resolve_config", lambda *a, **kw: provider)
    tool_name = f"{BUILTIN_WUDAO_NAME}__quotes"
    monkeypatch.setattr("src.intel.collect_tools", lambda *a: ([McpTool(name="quotes", description="quotes", input_schema={}, server=BUILTIN_WUDAO_NAME)], {tool_name: BUILTIN_WUDAO_NAME}))
    monkeypatch.setattr("src.intel.wudao_availability", lambda: {"available": True})
    complete = "完整数据" * 4000 + "END_OF_DATA"
    client = SimpleNamespace(call_tool=Mock(return_value={"text": complete, "is_error": False}))
    monkeypatch.setattr("src.intel.build_client", lambda *a: client)
    turns = []
    def chat(config, messages, **kw):
        turns.append(messages[:])
        if len(turns) == 1:
            return ChatResponse(text="", model="test", tool_calls=[ToolCall(id="call1", name=tool_name, arguments={})], input_tokens=10, output_tokens=2, raw={"finish_reason": "tool_calls"})
        assert messages[-1].content == complete
        return ChatResponse(text='{"summary":"无动作","orders":[]}', model="test", input_tokens=20, output_tokens=5, raw={"finish_reason": "stop"})
    monkeypatch.setattr("src.ai.application.agent.chat_stream", chat)
    usage = Mock()
    monkeypatch.setattr("src.ai.record_llm_usage", usage)
    parsed, meta = decide(SimpleNamespace(db_path="test"), {**DEFAULTS, "provider": "test", "model": "test"}, {})
    assert parsed.orders == [] and meta["tool_calls"] == 1 and len(turns) == 2
    assert usage.call_args.kwargs["input_tokens"] == 30
    assert usage.call_args.kwargs["output_tokens"] == 7


@pytest.mark.parametrize("raw", ['{}', '{"summary":"无动作"}', '{"summary":"x","orders":{}}', '{"summary":"x","orders":[{"code":"600001","action":"buy","layers":1,"reason":"x","price":10}]}'])
def test_malformed_output_is_not_no_action(raw):
    with pytest.raises(ValueError):
        parse_decision(raw)


def test_empty_and_combined_digest():
    assert "本轮无成交" in render_digest("市场平稳", [], [], EMPTY)
    state, fills, rejects = simulate(EMPTY, decision(), CANDIDATES, quotes(10), NOW)
    body = render_digest("确认后试仓", fills, rejects, state)
    assert "买入" in body and "100 股" in body and "账户" in body
    assert "暂未执行" in render_digest("无动作", [], [{"code": "600001", "quantity": 100, "reason": "数据缺失"}], EMPTY)


def test_observe_exact_dates_selected_only_and_keep_old_positions():
    palace = Mock()
    palace.candidates_payload.side_effect = [
        [{"code": "600001", "name": "A", "decision": "精选", "strategy_slug": "trend"},
         {"code": "600002", "name": "B", "decision": "观察", "strategy_slug": "trend"}],
        [{"code": "600001", "name": "A", "decision": "精选", "strategy_slug": "other"}],
    ]
    state = {**EMPTY, "positions": [{"code": "600003", "name": "老仓", "layers": 1}], "retired": ["600001"]}
    rows = guardian.observe(palace, ["2026-09-10", "2026-09-11"], state, [])
    assert [r["code"] for r in rows] == ["600001", "600003"]
    assert palace.candidates_payload.call_args_list[0].args == ("2026-09-10",)


def test_atomic_slot_replay_and_cross_connection_lock(tmp_path):
    path = tmp_path / "ledger.db"
    with GuardianStore(path) as first, GuardianStore(path) as second:
        assert first.claim("a")
        assert not second.claim("a") and not second.claim("b")
        state = {**EMPTY, "retired": ["600001"]}
        first.finish("a", {"body": "done"}, state)
        assert not second.claim("a")
        assert second.state() == state
        with pytest.raises(RuntimeError):
            second.finish("a", {}, EMPTY)
        assert second.state() == state
        assert second.claim("b")


def test_tenant_isolation_for_state_and_settings():
    for tenant in ["guardian_a", "guardian_b"]:
        with tenant_scope(tenant), OpsStore(None) as ops, GuardianStore() as ledger:
            assert ledger.state() == EMPTY and not get_config(ops)["enabled"]
            save_config(ops, {"enabled": False, "prompt": tenant})
            assert ledger.claim("same-slot")
            ledger.finish("same-slot", {}, {**EMPTY, "tag": tenant})
    for tenant in ["guardian_a", "guardian_b"]:
        with tenant_scope(tenant), OpsStore(None) as ops, GuardianStore() as ledger:
            assert ledger.state()["tag"] == tenant
            assert get_config(ops)["prompt"] == tenant


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    class Clock:
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(guardian, "datetime", Clock)
    market = SimpleNamespace(trading_days=lambda **kw: ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"])
    monkeypatch.setattr(guardian, "observe", lambda *a: CANDIDATES)
    monkeypatch.setattr(guardian, "build_monitor_snapshot", lambda *a, **kw: SimpleNamespace(quotes=quotes(10)))
    decide = Mock(return_value=(decision(), {"model": "test"}))
    notify = Mock(return_value={"success": True})
    monkeypatch.setattr(guardian, "decide", decide)
    monkeypatch.setattr(guardian, "dispatch_text", notify)
    with OpsStore(tmp_path / "ops.db") as ops:
        cfg = {**DEFAULTS, "enabled": True, "provider": "test", "model": "test"}
        ops.create_job(name=JOB_NAME, kind="guardian", config=cfg, enabled=True)
        context = JobContext(ops_store=ops, palace_db=str(tmp_path / "palace.db"))
        monkeypatch.setattr(context, "market", lambda: nullcontext(market))
        yield context, decide, notify


def test_full_round_commits_and_sends_once(runtime):
    context, decide, notify = runtime
    result = guardian.execute_guardian({}, context)
    assert len(result["fills"]) == 1
    with pytest.raises(JobSkipped):
        guardian.execute_guardian({}, context)
    assert decide.call_count == notify.call_count == 1
    with GuardianStore(context.palace_db) as store:
        assert store.state()["positions"][0]["quantity"] == 100
        assert store.recent()[0]["result"]["notify"]["success"]
        saved = store.recent()[0]["result"]["decision_context"]
        assert saved["account_before"]["positions"] == []
        assert saved["account_before"]["cash_cents"] == EMPTY["cash_cents"]
        assert saved["candidates"] == CANDIDATES


def test_empty_reference_pool_can_trade_outside_stock(runtime, monkeypatch):
    context, decide, _ = runtime
    monkeypatch.setattr(guardian, "observe", lambda *a: [])
    decide.return_value = (decision(code="603920"), {})
    snapshot = Mock(return_value=SimpleNamespace(quotes={"603920": {"code": "603920", "price": 10,
                    "trade_date": NOW.date().isoformat(), "trade_time": "10:00:00"}}))
    monkeypatch.setattr(guardian, "build_monitor_snapshot", snapshot)
    result = guardian.execute_guardian({}, context)
    assert decide.call_count == 1 and result["fills"][0]["code"] == "603920"
    assert snapshot.call_args.args[0] == ["603920"]
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["items"][0]["quantity"] == 100


def test_short_reference_history_does_not_block_independent_trading(runtime,monkeypatch):
    context,decide,_=runtime
    monkeypatch.setattr(context,'market',lambda:nullcontext(SimpleNamespace(trading_days=lambda **kw:[])))
    result=guardian.execute_guardian({},context)
    assert result['fills'] and decide.call_args.args[2]['reference_history_note']


def test_chinext_302_codes_are_tradeable_without_strategy_membership():
    code='302132'
    updated,fills,rejects=simulate(EMPTY,decision(code=code),[],{code:{'code':code,'name':'中航成飞','price':10,'trade_date':NOW.date().isoformat(),'trade_time':'10:00:00'}},NOW)
    assert len(fills)==1 and not rejects and updated['positions'][0]['code']==code


def test_guardian_push_preserves_complete_text_within_each_wecom_byte_limit(runtime, monkeypatch):
    context, _, notify = runtime
    body = "自主判断与模拟调仓。" * 250
    monkeypatch.setattr(guardian, "render_digest", lambda *args: body)
    result = guardian.execute_guardian({}, context)
    assert result["body"] == body
    assert notify.call_count > 1
    fragments = []
    for call in notify.call_args_list:
        sent = call.kwargs
        wire_text = f"【{sent['title']}】\n{sent['body']}"
        assert len(wire_text.encode("utf-8")) <= 2048
        assert "截断" not in sent["body"]
        fragments.append(sent["body"])
    assert "".join(fragments) == body


def test_scheduled_context_resolves_current_tenant_ledger_lazily(runtime):
    context, _, _ = runtime
    context.palace_db = None
    with tenant_scope("guardian_schedule"):
        result = guardian.execute_guardian({}, context)
        assert len(result["fills"]) == 1
        with GuardianStore() as ledger:
            assert ledger.state()["positions"][0]["code"] == "600001"


def test_model_gets_context_and_chooses_data_tools_without_forced_prefetch(runtime, monkeypatch):
    context, decide, _ = runtime
    decide.return_value = (parse_decision('{"summary":"无动作","orders":[]}'), {})
    snapshot = Mock(side_effect=AssertionError("不应强制预取数据"))
    monkeypatch.setattr(guardian, "build_monitor_snapshot", snapshot)
    result = guardian.execute_guardian({}, context)
    assert "本轮无成交" in result["body"]
    snapshot.assert_not_called()
    payload = decide.call_args.args[2]
    assert payload["candidates"] == CANDIDATES
    assert "active_strategies" in payload and "recent_runs" in payload
    assert "limits" not in payload


def test_hold_keeps_shares_and_marks_valuation(runtime, monkeypatch):
    context, decide, notify = runtime
    old, seed_fills, _ = simulate(EMPTY, decision(), CANDIDATES, quotes(10), NOW)
    with GuardianStore(context.palace_db) as ledger:
        ledger.claim("seed")
        ledger.finish("seed", {"fills": seed_fills}, old)
    hold = parse_decision(json.dumps({"summary": "继续持有", "orders": [
        {"code": "600001", "action": "hold", "reason": "结构未破坏", "holding_plan": "趋势持续就持有"}
    ]}))
    decide.return_value = (hold, {})
    result = guardian.execute_guardian({}, context)
    assert result["fills"] == [] and result["rejects"] == []
    notify.assert_not_called()
    assert result['outcome']=='no_action' and result['notify']['skipped']=='no_action'
    with GuardianStore(context.palace_db) as ledger:
        p = ledger.state()["positions"][0]
        assert p["quantity"] == 100 and p["market_value_cents"] == 100000
        assert p["holding_plan"] == "趋势持续就持有"
    from src.ops.application.guardian_context import observe
    palace = Mock()
    palace.candidates_payload.return_value = []
    assert observe(palace, ["2026-09-11"], old, [])[0]["code"] == "600001"


def test_failed_model_keeps_portfolio_and_reports_failure(runtime):
    context, decide, notify = runtime
    decide.side_effect = ValueError("模型输出无效")
    with pytest.raises(JobError, match="模型输出无效"):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as store:
        assert store.state() == EMPTY
        assert store.recent()[0]["status"] == "failed"
        saved = store.recent()[0]["result"]["decision_context"]["account_before"]
        assert saved["positions"] == [] and saved["cash_cents"] == EMPTY["cash_cents"]
    assert "未完成" in notify.call_args.kwargs["body"]


def test_failure_notification_displays_overview_not_position_cost(runtime):
    context, decide, notify = runtime
    state, fills, _ = simulate(EMPTY, decision(), CANDIDATES, quotes(10), NOW)
    with GuardianStore(context.palace_db) as ledger:
        ledger.claim("seed")
        ledger.finish("seed", {"status": "success", "fills": fills}, state)
    decide.side_effect = ValueError("模型调用失败")
    with pytest.raises(JobError):
        guardian.execute_guardian({}, context)
    body = notify.call_args.kwargs["body"]
    assert "持仓 1 只" in body and "总资产" in body
    assert "600001" not in body and "持仓成本" not in body
    assert "交易研判" in body and "模型调用失败" in body and "本轮无已落账成交" in body


def test_config_change_during_analysis_cancels_orders(runtime):
    context, decide, _ = runtime
    def change(*args, **kwargs):
        save_config(context.ops_store, {"enabled": False})
        return decision(), {}
    decide.side_effect = change
    with pytest.raises(JobError, match="设置已变更"):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as store:
        assert store.state() == EMPTY


def test_api_write_auth_and_strict_payload(monkeypatch):
    def denied():
        raise HTTPException(403, "forbidden")
    app = FastAPI()
    app.include_router(build_guardian_router(write_dependency=denied))
    with TestClient(app) as client:
        assert client.put("/api/ops/guardian", json={}).status_code == 403
    app = FastAPI()
    app.include_router(build_guardian_router(write_dependency=lambda: None))
    with TestClient(app) as client:
        assert client.get("/api/ops/guardian").json()["config"]["enabled"] is False
        assert client.put("/api/ops/guardian", json={"unexpected": True}).status_code == 422
        assert client.put("/api/ops/guardian", json={"enabled": True}).status_code == 200
        result = client.put("/api/ops/guardian", json={"prompt": "自定义战法"})
        assert result.status_code == 200 and result.json()["config"]["prompt"] == "自定义战法"
        monkeypatch.setattr(
            "src.ops.application.guardian_session.in_review_window",
            lambda now: False,
        )
        assert client.post("/api/ops/guardian/scan").status_code == 409


def test_background_scan_retains_request_tenant(monkeypatch):
    monkeypatch.setattr("src.ops.application.guardian_session.in_review_window", lambda now: True)
    app = FastAPI()
    @app.middleware("http")
    async def tenant(request, call_next):
        with tenant_scope("guardian_bg"):
            return await call_next(request)
    with tenant_scope("guardian_bg"), OpsStore(None) as store:
        store.create_job(name=JOB_NAME, kind="guardian", enabled=True, config=DEFAULTS)
    worker = Mock()
    monkeypatch.setattr("src.ops.api.guardian.run_guardian_once", worker)
    app.include_router(build_guardian_router(write_dependency=lambda: None))
    with TestClient(app) as client:
        assert client.post("/api/ops/guardian/scan").status_code == 202
    worker.assert_called_once_with("guardian_bg")
