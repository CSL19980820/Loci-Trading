"""实时信号引擎：规则命中、去抖 / cooldown、面板缓存、口径与铁律。

面板加载器全部注入假实现，测试不开库、不联网。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.market.application.realtime_signals import (
    LIVE_ADJUST,
    RULES,
    RULES_BY_ID,
    RealtimeSignalEngine,
    Rule,
    get_signal_engine,
    limit_up_price,
    reset_signal_engine,
)
from src.shared.tenancy import tenant_scope


CODE = "600000"
NOW = datetime(2026, 8, 27, 10, 30, 0)


def make_panel(*, closes: list[float] | None = None, volumes: list[float] | None = None):
    """60 根平盘日 K；返回 (loader, calls) —— calls 用来数面板到底加载了几次。"""
    dates = pd.date_range("2026-05-01", periods=60).strftime("%Y-%m-%d").tolist()
    close = pd.DataFrame({CODE: closes or [10.0] * 60}, index=dates)
    volume = pd.DataFrame({CODE: volumes or [1000.0] * 60}, index=dates)
    calls: list[list[str]] = []

    def loader(codes):
        calls.append(list(codes))
        return {"close": close, "volume": volume, "high": close, "low": close}

    return loader, calls


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


def engine_with(loader, *, rules=RULES, cooldown: float = 300.0) -> RealtimeSignalEngine:
    return RealtimeSignalEngine(panel_loader=loader, rules=rules, cooldown_seconds=cooldown)


@pytest.fixture(autouse=True)
def _drop_singleton():
    reset_signal_engine()
    yield
    reset_signal_engine()


def test_cross_rules_fire_once_per_code_rule_and_trading_day() -> None:
    """去抖：同 (code, rule, 交易日) 只报一次——CROSS 类信号盘中会反复抹去重生。"""
    loader, _calls = make_panel()
    engine = engine_with(loader)
    first = engine.evaluate([quote(price=20.0)], now=NOW)
    assert {item["rule"] for item in first} == {"ma_golden_cross", "macd_golden_cross"}

    again = engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=3))
    assert again == []

    # 换到下一个交易日，去抖键换了，同一条规则可以再报。
    tomorrow = engine.evaluate([quote(price=20.0)], now=NOW + timedelta(days=1))
    assert {item["rule"] for item in tomorrow} == {"ma_golden_cross", "macd_golden_cross"}


def test_debounce_is_per_tenant_not_per_process() -> None:
    """行情是全局共享事实，「谁已经被提醒过」是私人事实。

    key 里不带租户的话，A 命中一条不可重复规则后，B 当天就永远收不到同一条
    信号，而且没有任何提示——用户只会觉得「今天怎么一条推送都没有」。
    """
    loader, _calls = make_panel()
    engine = engine_with(loader)

    with tenant_scope("u_a"):
        first = engine.evaluate([quote(price=20.0)], now=NOW)
    assert {item["rule"] for item in first} == {"ma_golden_cross", "macd_golden_cross"}

    with tenant_scope("u_b"):
        other = engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=3))
    assert {item["rule"] for item in other} == {"ma_golden_cross", "macd_golden_cross"}, (
        f"A 命中后 B 当天就收不到同一条信号了：{other}"
    )

    # 各自的去抖仍然生效：同一个租户重放同一条行情不再报。
    with tenant_scope("u_b"):
        assert engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=6)) == []
    with tenant_scope("u_a"):
        assert engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=6)) == []

    stats = engine.stats()
    assert stats["fired_tenants"] == 2, stats


def test_fired_table_drops_yesterday_when_the_day_rolls() -> None:
    """按日清理：去抖表不能按 租户 x 代码 x 规则 一天天堆下去。"""
    loader, _calls = make_panel()
    engine = engine_with(loader)
    with tenant_scope("u_a"):
        assert engine.evaluate([quote(price=20.0)], now=NOW)
    with tenant_scope("u_b"):
        assert engine.evaluate([quote(price=20.0)], now=NOW + timedelta(days=1))
    stats = engine.stats()
    assert stats["fired_day"] == "2026-08-28", stats
    assert stats["fired_tenants"] == 1, stats


def test_every_signal_is_provisional_and_unadjusted() -> None:
    loader, _calls = make_panel()
    signals = engine_with(loader).evaluate([quote(price=20.0)], now=NOW)
    assert signals
    for item in signals:
        assert item["provisional"] is True
        assert item["adjust"] == LIVE_ADJUST == "none"
        assert item["trade_date"] == "2026-08-27"
        assert item["code"] == CODE
        assert item["detail"]  # detail 必须说清来源
        assert item["source"] == "live_hub"


def test_repeatable_rule_is_gated_by_cooldown() -> None:
    loader, _calls = make_panel()
    engine = engine_with(loader, rules=(RULES_BY_ID["near_limit_up"],), cooldown=300.0)
    near = quote(price=10.95, high=10.95)

    assert len(engine.evaluate([near], now=NOW)) == 1
    assert engine.evaluate([near], now=NOW + timedelta(seconds=30)) == []
    assert engine.evaluate([near], now=NOW + timedelta(seconds=299)) == []
    assert len(engine.evaluate([near], now=NOW + timedelta(seconds=301))) == 1


def test_panel_is_loaded_once_per_trading_day() -> None:
    """日 K 当日不变：同一天同一批代码只加载一次，剩下的 tick 全走缓存。"""
    loader, calls = make_panel()
    engine = engine_with(loader)
    for offset in range(5):
        engine.evaluate([quote(price=20.0)], now=NOW + timedelta(seconds=offset))
    assert len(calls) == 1
    assert engine.stats()["panel_loads"] == 1

    engine.evaluate([quote(price=20.0)], now=NOW + timedelta(days=1))
    assert len(calls) == 2


def test_volume_breakout_needs_both_ratio_and_new_high() -> None:
    loader, _calls = make_panel()
    rule = (RULES_BY_ID["volume_breakout"],)

    quiet = engine_with(loader, rules=rule)
    assert quiet.evaluate([quote(price=12.0, volume_ratio=1.2)], now=NOW) == []

    flat = engine_with(loader, rules=rule)
    assert flat.evaluate([quote(price=9.5, volume_ratio=3.0)], now=NOW) == []

    hit = engine_with(loader, rules=rule)
    signals = hit.evaluate([quote(price=12.0, volume_ratio=3.0)], now=NOW)
    assert [item["rule"] for item in signals] == ["volume_breakout"]


def test_broken_limit_up_only_after_the_board_opens() -> None:
    loader, _calls = make_panel()
    rule = (RULES_BY_ID["broken_limit_up"],)

    sealed = engine_with(loader, rules=rule)
    assert sealed.evaluate([quote(price=11.0, high=11.0)], now=NOW) == []

    opened = engine_with(loader, rules=rule)
    signals = opened.evaluate([quote(price=10.5, high=11.0)], now=NOW)
    assert [item["rule"] for item in signals] == ["broken_limit_up"]


def test_fast_surge_uses_declared_speed_then_falls_back_to_sampling() -> None:
    loader, _calls = make_panel()
    rule = (RULES_BY_ID["fast_surge"],)

    declared = engine_with(loader, rules=rule)
    assert len(declared.evaluate([quote(price=10.0, speed=2.5)], now=NOW)) == 1

    sampled = engine_with(loader, rules=rule)
    assert sampled.evaluate([quote(price=10.0)], now=NOW) == []
    jump = sampled.evaluate([quote(price=10.5)], now=NOW + timedelta(seconds=6))
    assert [item["rule"] for item in jump] == ["fast_surge"]


@pytest.mark.parametrize(
    "code, name, expected",
    [
        ("600000", "浦发测试", 11.0),
        ("300001", "创业测试", 12.0),
        ("688001", "科创测试", 12.0),
        ("830001", "北证测试", 13.0),
        ("600000", "ST测试", 10.5),
    ],
)
def test_limit_up_price_by_board(code, name, expected) -> None:
    assert limit_up_price(code, name, 10.0) == pytest.approx(expected)


def test_limit_up_price_rounds_half_up_to_the_cent() -> None:
    # 银行家舍入会给 10.04；交易所口径是逢五进一 → 10.05。
    assert limit_up_price("600000", "测试", 9.135) == pytest.approx(10.05)


def test_a_broken_rule_never_takes_down_the_batch() -> None:
    def boom(_ctx, _params):
        raise ValueError("规则写坏了")

    loader, _calls = make_panel()
    rules = (
        Rule("boom", "会炸的规则", 1, False, boom),
        RULES_BY_ID["near_limit_up"],
    )
    signals = engine_with(loader, rules=rules).evaluate(
        [quote(price=10.95, high=10.95)], now=NOW
    )
    assert [item["rule"] for item in signals] == ["near_limit_up"]


def test_missing_panel_degrades_to_history_free_rules() -> None:
    def broken_loader(_codes):
        raise RuntimeError("热库不可用")

    engine = engine_with(broken_loader)
    signals = engine.evaluate([quote(price=10.95, high=10.95)], now=NOW)
    # 需要历史的规则被 min_bars 挡住，不需要历史的照常出。
    assert [item["rule"] for item in signals] == ["near_limit_up"]


def test_stats_declares_the_unadjusted_contract_and_rule_table() -> None:
    loader, _calls = make_panel()
    engine = engine_with(loader)
    engine.evaluate([quote(price=20.0)], now=NOW)
    stats = engine.stats()
    assert stats["adjust"] == "none"
    assert {item["id"] for item in stats["rules"]} == {rule.id for rule in RULES}
    assert stats["fired_keys"] >= 1
    engine.reset()
    assert engine.stats()["fired_keys"] == 0


def test_singleton_engine_is_shared() -> None:
    engine = get_signal_engine()
    assert get_signal_engine() is engine
    reset_signal_engine()
    assert get_signal_engine() is not engine


def test_registry_has_six_lightweight_rules() -> None:
    assert len(RULES) == 6
    assert len(RULES_BY_ID) == len(RULES)


def test_every_rule_declares_a_human_readable_contract() -> None:
    """口径说明与参数表是**对外契约**：前端直接展示，不能有一条是空的。"""
    for rule in RULES:
        assert rule.description, f"{rule.id} 缺人话口径"
        assert rule.direction in {"long", "watch", "exit"}, rule.id
        assert 0.0 < rule.strength <= 1.0, rule.id
        assert rule.params, f"{rule.id} 一个可调参数都没有，等于又把阈值焊死了"
        for spec in rule.params:
            assert spec.label, f"{rule.id}.{spec.key} 缺人话标签"
            assert spec.minimum <= spec.default <= spec.maximum, f"{rule.id}.{spec.key}"
        # 默认值必须原样通过自己的校验，否则「恢复默认」会当场 400。
        assert rule.validate(rule.defaults) == rule.defaults


def test_universe_to_signal_is_wired_end_to_end() -> None:
    """**「都 12 点了还没信号」的整链回归钉**。

    把上游那张按代码倒序的全市场截面原样喂进来：只要宇宙切法是对的（四榜合集），
    临近涨停那只票就必须出信号。旧实现取 ``rows[:400]``，代码最大的 400 只清一色
    北交所，涨停就在屏幕上而信号栏整天是「无信号」。
    """
    from src.market.application.watchlist import MAX_PRESET_CODES, resolve_preset

    # 900 只“死水”票 + 一只逼近涨停的（代码故意取最小，排在整表最末）
    rows = [
        {
            "code": f"{830000 + i:06d}",
            "name": f"北交票{i}",
            "price": 10.0,
            "prev_close": 10.0,
            "pct": 0.0,
            "amount": 1.0,
            "turnover": 0.1,
        }
        for i in range(900)
    ]
    rows.append(
        {
            "code": "600000",
            "name": "临停测试",
            "price": 10.95,   # 距 10% 涨停价 11.00 只差 0.45%
            "prev_close": 10.0,
            "high": 10.95,
            "pct": 9.5,
            "amount": 9.9e9,
            "turnover": 30.0,
        }
    )
    rows.sort(key=lambda row: row["code"], reverse=True)  # 上游就是这个顺序

    resolved = resolve_preset("signals", cross_section=lambda: rows)
    assert len(resolved.codes) <= MAX_PRESET_CODES
    assert "600000" in resolved.codes, "在动的票必须进信号池"

    # 面板加载失败（新装机 / 热库还没建）也不许把不需要历史的规则一起哑掉
    def no_panel(codes):
        raise RuntimeError("热库不可用")

    engine = RealtimeSignalEngine(panel_loader=no_panel, settings_loader=lambda tenant: {})
    signals = engine.evaluate(resolved.rows, now=NOW)
    hit = [item for item in signals if item["code"] == "600000"]
    assert hit, "距涨停 0.45% 必须出「临近涨停」"
    assert hit[0]["rule"] == "near_limit_up"
    assert hit[0]["provisional"] is True
