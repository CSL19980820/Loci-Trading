"""实时信号的**可维护性**：规则开关 / 阈值配置 / 缓存失效 / 落库 / 租户隔离。

``tests/market/test_realtime_signals.py`` 管的是规则算得对不对；这里管的是
「规则能不能在系统内改」以及「改完到底生不生效」。
"""
from __future__ import annotations

from datetime import datetime, timedelta
import types

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.market.api.signal_rules_router import build_signal_rules_router
from src.market.api.stream_router import _SIGNAL_CACHE, _evaluate_once
from src.market.application.realtime_signals import (
    RULES,
    RULES_BY_ID,
    RULE_CONFIG_TTL_SECONDS,
    RealtimeSignalEngine,
    RuleParamError,
    RuleSetting,
    invalidate_rule_settings,
    reset_signal_engine,
    rule_settings,
)
from src.ops import OpsStore
from src.shared.tenancy import tenant_scope

CODE = "600000"
NOW = datetime(2026, 8, 27, 10, 30, 0)


@pytest.fixture(autouse=True)
def _drop_singleton_and_config_cache():
    # stream_router 的 (feed, seq) 结果缓存是模块级全局：不清就会跨用例串味
    # （tests/market/test_live_hub.py 也用 "index" 这个 key，seq 从 1 开始）。
    _SIGNAL_CACHE.clear()
    reset_signal_engine()
    yield
    _SIGNAL_CACHE.clear()
    reset_signal_engine()


def make_panel():
    """60 根平盘日 K，够所有规则起步。"""
    dates = pd.date_range("2026-05-01", periods=60).strftime("%Y-%m-%d").tolist()
    close = pd.DataFrame({CODE: [10.0] * 60}, index=dates)
    volume = pd.DataFrame({CODE: [1000.0] * 60}, index=dates)

    def loader(codes):
        return {"close": close, "volume": volume, "high": close, "low": close}

    return loader


def quote(**overrides):
    row = {
        "code": CODE,
        "name": "浦发测试",
        "price": 10.0,
        "prev_close": 10.0,
        "high": 10.0,
        "low": 10.0,
        "pct": 0.0,
        "volume": 1000.0,
        "volume_ratio": 0.0,
        "speed": 0.0,
    }
    row.update(overrides)
    row.setdefault("high", row["price"])
    return row


def engine_with(settings, *, rules=RULES):
    """注入固定配置的引擎。不开库、不联网。"""
    return RealtimeSignalEngine(
        panel_loader=make_panel(),
        rules=rules,
        settings_loader=lambda _tenant: dict(settings),
)


# --------------------------------------------------------------- ① 停用规则


def test_disabled_rule_stops_producing_that_signal() -> None:
    """① 停用之后，这一类信号不再产生；别的规则不受影响。"""
    baseline = engine_with(dict()).evaluate([quote(price=20.0)], now=NOW)
    assert {item["rule_id"] for item in baseline} == {"ma_golden_cross", "macd_golden_cross"}

    off = {"ma_golden_cross": RuleSetting("ma_golden_cross", False, dict())}
    after = engine_with(off).evaluate([quote(price=20.0)], now=NOW)
    assert {item["rule_id"] for item in after} == {"macd_golden_cross"}, after


def test_disabled_rule_does_not_burn_its_debounce_slot() -> None:
    """停用期间不占去抖位：重新启用的当天必须还能报，而不是「今天已经报过了」。"""
    off = {"ma_golden_cross": RuleSetting("ma_golden_cross", False, dict())}
    settings = dict(off)
    engine = RealtimeSignalEngine(
        panel_loader=make_panel(),
        rules=(RULES_BY_ID["ma_golden_cross"],),
        settings_loader=lambda _tenant: settings,
    )
    assert engine.evaluate([quote(price=20.0)], now=NOW) == []
    settings.clear()  # 用户在同一天把它重新打开
    again = engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=5))
    assert [item["rule_id"] for item in again] == ["ma_golden_cross"]


# --------------------------------------------------------------- ② 阈值生效


def test_changing_speed_threshold_actually_changes_the_hit() -> None:
    """② 涨速 3%：默认阈值 2% 命中；把 speed_pct 改成 5.0 之后不再命中。"""
    rules = (RULES_BY_ID["fast_surge"],)
    hit = engine_with(dict(), rules=rules).evaluate([quote(speed=3.0)], now=NOW)
    assert [item["rule_id"] for item in hit] == ["fast_surge"]
    assert hit[0]["params"] == {"speed_pct": 2.0}

    raised = {"fast_surge": RuleSetting("fast_surge", True, {"speed_pct": 5.0})}
    miss = engine_with(raised, rules=rules).evaluate([quote(speed=3.0)], now=NOW)
    assert miss == [], miss

    # 抬高之后 6% 仍然命中，且信号自述用的是新阈值。
    still = engine_with(raised, rules=rules).evaluate([quote(speed=6.0)], now=NOW)
    assert still[0]["params"] == {"speed_pct": 5.0}


def test_changing_a_period_changes_the_required_history() -> None:
    """慢线拉长到 200，60 根 bar 就不够了——``min_bars`` 必须跟着参数走。"""
    long = {"ma_golden_cross": RuleSetting("ma_golden_cross", True, {"slow": 200})}
    rules = (RULES_BY_ID["ma_golden_cross"],)
    assert engine_with(long, rules=rules).evaluate([quote(price=20.0)], now=NOW) == []


def test_defaults_live_in_code_not_in_the_database() -> None:
    """空配置 = 全部默认。库里没有行时六条规则一条不少地按代码默认值跑。"""
    engine = engine_with(dict())
    signals = engine.evaluate([quote(price=20.0)], now=NOW)
    assert signals
    for item in signals:
        assert item["params"] == RULES_BY_ID[item["rule_id"]].defaults


def test_unknown_or_broken_stored_params_fall_back_to_defaults() -> None:
    """库里留着旧版本的键 / 坏值时，热路径回落默认值而不是抛异常。"""
    junk = {"fast_surge": RuleSetting("fast_surge", True, {"speed": 9, "speed_pct": "abc"})}
    rules = (RULES_BY_ID["fast_surge"],)
    signals = engine_with(junk, rules=rules).evaluate([quote(speed=3.0)], now=NOW)
    assert [item["params"] for item in signals] == [{"speed_pct": 2.0}]


# --------------------------------------------------------------- ③ 缓存


def test_rule_config_is_cached_and_invalidated_by_writes() -> None:
    """热路径每 tick 都跑：读一次就要缓存住；PUT 之后必须立刻失效。"""
    calls: list[str] = []

    def loader(tenant):
        calls.append(tenant)
        return dict()

    rule_settings("u_a", loader=loader, now=100.0)
    rule_settings("u_a", loader=loader, now=101.0)
    rule_settings("u_a", loader=loader, now=100.0 + RULE_CONFIG_TTL_SECONDS - 0.1)
    assert calls == ["u_a"], "TTL 内不该重复读库"

    invalidate_rule_settings("u_a")
    rule_settings("u_a", loader=loader, now=101.0)
    assert len(calls) == 2, "PUT 之后必须立刻重新读"

    # TTL 到期也会重新读（别的进程改了配置时的兜底）。
    rule_settings("u_a", loader=loader, now=101.0 + RULE_CONFIG_TTL_SECONDS + 1)
    assert len(calls) == 3


def test_cache_is_per_tenant() -> None:
    calls: list[str] = []

    def loader(tenant):
        calls.append(tenant)
        return dict()

    rule_settings("u_a", loader=loader, now=100.0)
    rule_settings("u_b", loader=loader, now=100.0)
    assert calls == ["u_a", "u_b"]
    invalidate_rule_settings("u_a")
    rule_settings("u_b", loader=loader, now=100.5)
    assert calls == ["u_a", "u_b"], "清 A 的缓存不该顺手清掉 B 的"


def test_unreadable_config_keeps_the_last_known_good() -> None:
    """TTL 到期时库正好抖了一下，不能让「刚被停用的规则」重新开始推送。

    回落「全部默认」的话，症状是用户已经关掉的规则又开始推送，而且没有任何提示；
    沿用上一份已知good 最多是晚半分钟拿到新配置。

    注意这只覆盖 **TTL 刷新** 这条路径。``invalidate_rule_settings()`` 是「我刚写
    成功了，忘掉旧的」的显式信号，它连同上一份一起丢——那正是想要的语义。
    """
    state = {"fail": False}

    def loader(tenant):
        if state["fail"]:
            raise RuntimeError("ops.db is locked")
        return {"fast_surge": RuleSetting("fast_surge", False, dict())}

    first = rule_settings("u_a", loader=loader, now=100.0)
    assert first["fast_surge"].enabled is False
    state["fail"] = True
    again = rule_settings("u_a", loader=loader, now=100.0 + RULE_CONFIG_TTL_SECONDS + 1)
    assert "fast_surge" in again and again["fast_surge"].enabled is False


# --------------------------------------------------------------- ④ HTTP 契约


def build_app():
    app = FastAPI()
    app.include_router(build_signal_rules_router(write_dependency=lambda: None))
    return TestClient(app)


def test_get_rules_exposes_human_readable_description_and_specs() -> None:
    payload = build_app().get("/api/market/signals/rules").json()
    assert payload["count"] == len(RULES)
    assert payload["enabled_count"] == len(RULES)
    by_id = {item["rule_id"]: item for item in payload["rules"]}
    assert set(by_id) == {rule.id for rule in RULES}
    for item in payload["rules"]:
        # description 是给用户看的口径，前端直接展示；空着等于没做。
        assert item["description"], item["rule_id"]
        assert item["defaults"] == RULES_BY_ID[item["rule_id"]].defaults
        assert item["overrides"] == dict()
        assert item["customized"] is False
    ma = by_id["ma_golden_cross"]
    assert "MA5" in ma["description"] and "MA20" in ma["description"]
    assert {spec["key"] for spec in ma["param_specs"]} == {"fast", "slow"}


def test_put_persists_only_the_keys_that_differ_from_defaults() -> None:
    client = build_app()
    body = {"enabled": True, "params": {"speed_pct": 5.0}}
    updated = client.put("/api/market/signals/rules/fast_surge", json=body).json()
    assert updated["params"] == {"speed_pct": 5.0}
    assert updated["overrides"] == {"speed_pct": 5.0}
    assert updated["defaults"] == {"speed_pct": 2.0}

    # 改回默认值 → 覆盖集清空，这样以后代码里改默认值用户能跟着走。
    back = client.put(
        "/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 2.0}}
    ).json()
    assert back["overrides"] == dict()


def test_put_can_toggle_enabled_without_touching_params() -> None:
    client = build_app()
    client.put("/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 5.0}})
    off = client.put("/api/market/signals/rules/fast_surge", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert off["overrides"] == {"speed_pct": 5.0}, "只改开关不该把阈值一起抹掉"


def test_unknown_rule_is_404_with_the_known_list() -> None:
    response = build_app().put("/api/market/signals/rules/nope", json={"enabled": False})
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]
    assert "fast_surge" in response.json()["detail"]


@pytest.mark.parametrize(
    "rule_id, params, needle",
    [
        ("fast_surge", {"speed": 3}, "没有参数"),
        ("fast_surge", {"speed_pct": 0}, "0.1"),
        ("fast_surge", {"speed_pct": -1}, "0.1"),
        ("fast_surge", {"speed_pct": "很快"}, "必须是数字"),
        ("near_limit_up", {"gap_pct": 12}, "10.0"),
        ("ma_golden_cross", {"fast": 30, "slow": 20}, "金叉"),
        ("ma_golden_cross", {"fast": 5.5}, "必须是整数"),
    ],
)
def test_bad_params_are_400_with_a_human_reason(rule_id, params, needle) -> None:
    response = build_app().put(f"/api/market/signals/rules/{rule_id}", json={"params": params})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert needle in detail, detail
    assert detail.strip(), "400 必须带人话原因"


def test_rejected_put_changes_nothing() -> None:
    client = build_app()
    client.put("/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 5.0}})
    client.put("/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 99}})
    current = client.get("/api/market/signals/rules").json()
    by_id = {item["rule_id"]: item for item in current["rules"]}
    assert by_id["fast_surge"]["params"] == {"speed_pct": 5.0}


def test_put_then_engine_actually_uses_the_new_threshold() -> None:
    """端到端：PUT 之后，**默认走缓存的引擎**下一 tick 就用新阈值。"""
    client = build_app()
    client.put("/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 5.0}})
    # 不注入 settings_loader：走真实的 ops.db + 模块级缓存。
    engine = RealtimeSignalEngine(
        panel_loader=make_panel(), rules=(RULES_BY_ID["fast_surge"],)
    )
    assert engine.evaluate([quote(speed=3.0)], now=NOW) == []
    assert engine.evaluate([quote(speed=6.0)], now=NOW) != []


def test_put_then_disable_silences_the_engine_end_to_end() -> None:
    client = build_app()
    client.put("/api/market/signals/rules/near_limit_up", json={"enabled": False})
    engine = RealtimeSignalEngine(
        panel_loader=make_panel(), rules=(RULES_BY_ID["near_limit_up"],)
    )
    assert engine.evaluate([quote(price=10.95, high=10.95)], now=NOW) == []


# --------------------------------------------------------------- ⑤ 历史 / 落库


def fake_snapshot(seq: int):
    return types.SimpleNamespace(
        seq=seq,
        rows=[{"symbol": CODE, "name": "浦发测试", "price": 10.0}],
        as_of="2026-08-27 10:30:00",
    )


class StubEngine:
    """固定吐一条信号的引擎替身，形状与 ``_signal_row`` 对齐。"""

    def __init__(self):
        self.calls = 0

    def evaluate(self, rows, *, now=None):
        self.calls += 1
        return [
            {
                "code": row["code"],
                "name": row.get("name", ""),
                "rule": "fast_surge",
                "rule_id": "fast_surge",
                "rule_label": "快速拉升",
                "title": "浦发测试(600000) 快速拉升",
                "detail": "涨速 3.00%",
                "direction": "watch",
                "strength": 0.6,
                "price": 10.0,
                "pct": 1.5,
                "at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "trade_date": "2026-08-27",
                "repeatable": True,
            }
            for row in rows
        ]


def test_evaluated_signals_land_in_the_journal() -> None:
    """信号日志确实落 ops.db，且只在**真的算了**那一次落。"""
    engine = StubEngine()
    signals = _evaluate_once(engine, "index", fake_snapshot(1))
    assert len(signals) == 1
    with OpsStore() as store:
        rows = store.list_signal_journal(tenant="__primary__")
    assert [row["rule_id"] for row in rows] == ["fast_surge"]
    assert rows[0]["title"] == "浦发测试(600000) 快速拉升"
    assert rows[0]["direction"] == "watch"

    # 同一 (feed, seq) 再来一次：缓存命中，不重算也不重写。
    _evaluate_once(engine, "index", fake_snapshot(1))
    assert engine.calls == 1
    with OpsStore() as store:
        assert len(store.list_signal_journal(tenant="__primary__")) == 1


def test_journal_failure_never_breaks_the_stream() -> None:
    """落库炸了只记日志：大屏是主线，历史是副产品。"""

    def boom(_signals):
        raise RuntimeError("ops.db 只读")

    signals = _evaluate_once(StubEngine(), "index-boom", fake_snapshot(7), boom)
    assert [item["rule_id"] for item in signals] == ["fast_surge"]


def test_recent_endpoint_is_capped_server_side() -> None:
    client = build_app()
    with OpsStore() as store:
        for index in range(85):
            moment = NOW - timedelta(minutes=85 - index)
            store.append_signal_journal(
                [
                    {
                        "code": f"60{index:04d}",
                        "name": "测试",
                        "rule": "fast_surge",
                        "rule_label": "快速拉升",
                        "at": moment.strftime("%Y-%m-%d %H:%M:%S"),
                        "trade_date": "2026-08-27",
                        "repeatable": True,
                    }
                ],
                tenant="__primary__",
                now=NOW,
            )
    payload = client.get("/api/market/signals/recent?limit=80").json()
    assert payload["retention_days"] == 7
    assert payload["max_rows"] == 80
    assert payload["count"] == 80
    times = [item["triggered_at"] for item in payload["signals"]]
    assert times == sorted(times, reverse=True), "必须按 triggered_at 倒序"


def test_recent_endpoint_rejects_an_oversized_limit() -> None:
    assert build_app().get("/api/market/signals/recent?limit=500").status_code == 422


def test_one_tenants_history_never_leaks_into_another() -> None:
    """⑤ 租户 A 的信号不会出现在租户 B 的历史里（端到端走 HTTP）。"""
    client = build_app()
    for tenant, code in (("u_a", "600000"), ("u_b", "300750")):
        with tenant_scope(tenant):
            with OpsStore() as store:
                store.append_signal_journal(
                    [
                        {
                            "code": code,
                            "name": f"{tenant} 的票",
                            "rule": "fast_surge",
                            "rule_label": "快速拉升",
                            "at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "trade_date": "2026-08-27",
                        }
                    ],
                    tenant=tenant,
                    now=NOW,
                )
    with tenant_scope("u_a"):
        mine = client.get("/api/market/signals/recent").json()
    with tenant_scope("u_b"):
        yours = client.get("/api/market/signals/recent").json()
    assert [item["code"] for item in mine["signals"]] == ["600000"]
    assert [item["code"] for item in yours["signals"]] == ["300750"]


def test_rule_config_is_also_per_tenant_over_http() -> None:
    client = build_app()
    with tenant_scope("u_a"):
        client.put("/api/market/signals/rules/fast_surge", json={"enabled": False})
        mine = client.get("/api/market/signals/rules").json()
    with tenant_scope("u_b"):
        yours = client.get("/api/market/signals/rules").json()
    assert {item["rule_id"]: item["enabled"] for item in mine["rules"]}["fast_surge"] is False
    assert {item["rule_id"]: item["enabled"] for item in yours["rules"]}["fast_surge"] is True


def test_validate_raises_the_reason_not_a_bare_valueerror() -> None:
    rule = RULES_BY_ID["near_limit_up"]
    with pytest.raises(RuleParamError) as excinfo:
        rule.validate({"gap_pct": 50})
    assert "距涨停幅度" in str(excinfo.value)


def test_recent_payload_carries_as_of_for_the_first_screen() -> None:
    """``as_of`` = 最新一条的时刻。前端首屏拿它显示「最近一次信号在什么时候」。"""
    client = build_app()
    empty = client.get("/api/market/signals/recent").json()
    assert empty["as_of"] == "", "一条都没有时不能谎报一个时刻"

    with OpsStore() as store:
        for minutes in (30, 5):
            moment = NOW - timedelta(minutes=minutes)
            store.append_signal_journal(
                [
                    {
                        "code": f"6000{minutes:02d}",
                        "name": "测试",
                        "rule": "fast_surge",
                        "rule_label": "快速拉升",
                        "at": moment.strftime("%Y-%m-%d %H:%M:%S"),
                        "trade_date": "2026-08-27",
                    }
                ],
                tenant="__primary__",
                now=NOW,
            )
    payload = client.get("/api/market/signals/recent").json()
    assert payload["as_of"] == payload["signals"][0]["triggered_at"]
    assert payload["as_of"] == (NOW - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")


def test_signal_direction_uses_the_consumer_vocabulary() -> None:
    """方向词表是**消费方**钉死的：前端只认 long / watch / exit。

    用 bullish / bearish 的后果不是报错，是炸板信号在界面上写着「买入」——
    前端的 parseSignalItem 把认不出的值一律落回 'long'。
    """
    payload = build_app().get("/api/market/signals/rules").json()
    directions = {item["rule_id"]: item["direction"] for item in payload["rules"]}
    assert set(directions.values()) <= {"long", "watch", "exit"}
    assert directions["broken_limit_up"] == "exit", "炸板不该被展示成买入"
    assert directions["ma_golden_cross"] == "long"
