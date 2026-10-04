"""内置战法只计算传入股票池，不私设价格、板块、名称或股本范围。"""
from __future__ import annotations

from copy import copy

import pandas as pd
import pytest

from src.backtest.application.runner import resolve_backtest_config
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from src.strategy.application.impulse_inside_breakout import ImpulseInsideBreakoutV1
from src.strategy.application.qianlong import QianlongCloseePickerV3
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.application.yangshi_tail import YangshiTailPickerV1
from src.strategy.domain.base import StrategyError, merge_params
from tests.test_builtin_execution_profiles import _panels


BUILTINS = (ContractionRebreakoutV1, ImpulseInsideBreakoutV1, QianlongCloseePickerV3,
            SanyuanTailResonance, YangshiTailPickerV1)
PRICE_FIELDS = ("open", "high", "low", "close", "__raw_close")


@pytest.mark.parametrize("engine_type", BUILTINS)
def test_builtin_does_not_override_the_unified_universe_or_advertise_retired_limits(engine_type):
    engine = engine_type()
    assert getattr(engine, "default_universe", None) is None
    assert not {"price_min", "price_max", "shares_max"} & engine.default_params().keys()
    assert not {"universe", "price_min", "price_max", "shares_max"} & engine.backtest_config.keys()
    assert engine.backtest_metrics is None
    assert engine.version_history[-1]["status"] == "active"
    assert engine.version_history[-2]["status"] == "archived"
    assert engine.version_history[-2]["backtest_metrics"]


@pytest.mark.parametrize("engine_type", BUILTINS)
def test_scope_change_preserves_every_execution_default(engine_type):
    current = engine_type()
    previous = copy(current)
    previous.backtest_config = current.version_history[-2]["backtest_config"]
    assert resolve_backtest_config(current) == resolve_backtest_config(previous)
    fields = ("hold_days", "stop_loss_pct", "take_profit_pct", "commission_bps", "stamp_duty_bps",
              "slippage_bps", "benchmark", "strict_limit_prices", "economic_returns", "mode", "adjust",
              "execution_adjust", "start", "end")
    for field in fields:
        assert current.backtest_config.get(field) == previous.backtest_config.get(field), field


@pytest.mark.parametrize("engine_type", [QianlongCloseePickerV3, SanyuanTailResonance, YangshiTailPickerV1])
def test_saved_legacy_scope_params_are_accepted_ignored_and_do_not_hide_real_unknown_params(engine_type):
    engine = engine_type()
    params = dict.fromkeys(engine.ignored_legacy_params, 1e9)
    assert merge_params(engine, params) == engine.default_params()
    panels = _panels(seed=7)
    expected, actual = engine.compute(panels), engine.compute(panels, params)
    pd.testing.assert_frame_equal(actual.signals, expected.signals)
    pd.testing.assert_frame_equal(actual.watch_signals, expected.watch_signals)
    assert engine.execution_profile(params) == engine.execution_profile()
    with pytest.raises(StrategyError, match="不认识的参数"):
        merge_params(engine, {**params, "misspelled_param": 1})


@pytest.mark.parametrize("engine_type", [QianlongCloseePickerV3, SanyuanTailResonance, YangshiTailPickerV1])
@pytest.mark.parametrize("scale", [.1, 10.])
def test_valid_shape_is_selectable_below_old_price_floor_and_above_old_ceiling(engine_type, scale):
    engine = engine_type()
    panels = _panels(seed=7)
    # A real formula-generated signal provides the shape, without mocking its decisions.
    signals = engine.compute(panels).signals
    day, code = next((day, code) for day in reversed(signals.index)
                     for code in signals.columns if signals.at[day, code])
    single = {key: value.loc[:day, [code]].copy() if isinstance(value, pd.DataFrame) else value
              for key, value in panels.items()}
    assert engine.compute(single).signals.at[day, code]
    for field in PRICE_FIELDS:
        single[field] *= scale
    single["outstanding_share"][:] = 1e12
    result = engine.compute(single)
    assert result.signals.at[day, code]
    assert single["__raw_close"].at[day, code] < 3 if scale < 1 else single["__raw_close"].at[day, code] > 12


def test_yangshi_no_longer_requires_share_count_data():
    engine = YangshiTailPickerV1()
    assert "outstanding_share" not in engine.required_fields()
    panels = _panels(seed=7)
    expected = engine.compute(panels)
    panels.pop("outstanding_share")
    actual = engine.compute(panels)
    pd.testing.assert_frame_equal(actual.signals, expected.signals)


def test_qianlong_requests_instrument_names_for_actual_st_limit_prices():
    engine = QianlongCloseePickerV3()
    assert engine.requires_instrument_names
    panels = _panels(seed=7)
    code = "600001"
    day = panels["close"].index[-1]
    previous = panels["__raw_close"].iloc[-2][code]
    panels["__raw_close"].at[day, code] = int(previous * 1.05 * 100 + .5 + 1e-9) / 100
    panels["__instrument_names__"][code] = "ST样本"
    assert not engine.compute(panels).factors["非涨停价"].at[day, code]
    panels["__instrument_names__"][code] = "普通样本"
    assert engine.compute(panels).factors["非涨停价"].at[day, code]


def test_screener_attaches_st_name_when_unified_pool_explicitly_includes_it(tmp_path, monkeypatch):
    from src.market import MarketStore
    from src.strategy.application import screener

    code = "600001"
    panels = _panels(seed=7, days=60)
    day = panels["close"].index[-1]
    previous = panels["__raw_close"].iloc[-2][code]
    panels["__raw_close"].at[day, code] = int(previous * 1.05 * 100 + .5 + 1e-9) / 100
    captured = {}
    compute = screener.compute_result

    def capture(engine, inputs, params=None, **kwargs):
        captured["names"] = inputs.get("__instrument_names__")
        output = compute(engine, inputs, params, **kwargs)
        captured["below_limit"] = output.factors["非涨停价"].at[day, code]
        return output

    monkeypatch.setattr(screener, "compute_result", capture)
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments([{"code": code, "name": "ST样本", "market": "sh", "board": "main",
                                   "instrument_type": "STOCK", "list_date": "2010-01-01"}])
        rows = []
        for date in panels["close"].index:
            raw_close = panels["__raw_close"].at[date, code]
            rows.append((date, code, raw_close * .99, raw_close * 1.01, raw_close * .98,
                         raw_close, 1e6, 1e7, .05, "fixture", date))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,turnover,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows,
        )
        store.conn.commit()
        store.rebuild_calendar()
        result = screener.screen(store, QianlongCloseePickerV3(), trade_date=day, codes=[code], adjust="none",
                                 universe={"boards": ["main"], "exclude_st": False},
                                 health_check=False, live_overlay=False)
    assert result.universe["exclude_st"] is False
    assert captured["names"][code] == "ST样本"
    assert not captured["below_limit"]
