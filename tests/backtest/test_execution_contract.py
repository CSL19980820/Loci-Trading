"""统一成交引擎的严格价格/经济收益/估值截止可选契约。"""
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from src.backtest import BacktestConfig, Trade, run_backtest


def sample(code="600001", count=15):
    days = pd.bdate_range("2026-01-05", periods=count).strftime("%Y-%m-%d")
    base = pd.DataFrame({code: [10.] * count}, index=days)
    panels = {"open": base.copy(), "high": base + .2, "low": base - .2,
              "close": base.copy(), "volume": base * 100,
              "__adjust_factor": base / 10}
    signals = base.eq(-1)
    signals.iloc[0, 0] = True
    return signals, panels


def cfg(**kwargs):
    return BacktestConfig(**{"hold_days": 1, "stop_loss_pct": None, "benchmark": None, **kwargs})


@pytest.mark.parametrize("code,upper", [("600001", 11.), ("300001", 12.), ("301001", 12.)])
def test_strict_rejects_upper_limit_open_even_when_board_opens_intraday(code, upper):
    signals, panels = sample(code)
    panels["open"].iloc[1, 0] = upper
    panels["high"].iloc[1, 0] = upper
    panels["close"].iloc[1, 0] = upper - .2
    panels["low"].iloc[1, 0] = upper - .5
    assert len(run_backtest(signals, panels, entry_timing="next_open", config=cfg()).trades) == 1
    actual = run_backtest(signals, panels, entry_timing="next_open", config=cfg(strict_limit_prices=True))
    assert actual.trades == []
    assert actual.skipped["入场日涨停开盘买不进"] == 1


def test_chinext_ten_percent_open_is_not_its_limit():
    signals, panels = sample("300001")
    panels["open"].iloc[1, 0] = panels["high"].iloc[1, 0] = 11
    assert len(run_backtest(signals, panels, entry_timing="next_open", config=cfg(strict_limit_prices=True)).trades) == 1


def test_strict_mode_overrides_allow_limit_up_entry_optin():
    signals, panels = sample()
    panels["open"].iloc[1, 0] = panels["high"].iloc[1, 0] = 11
    actual = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(strict_limit_prices=True, allow_limit_up_entry=True))
    assert actual.trades == []


@pytest.mark.parametrize("code,lower", [("600001", 9.), ("300001", 8.)])
def test_strict_defers_limit_down_close_that_was_not_one_word(code, lower):
    signals, panels = sample(code)
    panels["close"].iloc[2, 0] = panels["low"].iloc[2, 0] = lower
    panels["open"].iloc[2, 0] = lower + .3
    legacy = run_backtest(signals, panels, entry_timing="next_open", config=cfg()).trades[0]
    strict = run_backtest(signals, panels, entry_timing="next_open", config=cfg(strict_limit_prices=True)).trades[0]
    assert legacy.exit_date == signals.index[2]
    assert strict.exit_date == signals.index[3]


def test_strict_uses_factor_adjusted_previous_close_on_ex_date():
    signals, panels = sample()
    for field in ("open", "high", "low", "close"):
        panels[field].iloc[1:] /= 2
    panels["__adjust_factor"].iloc[1:] = 2
    panels["open"].iloc[1, 0] = panels["high"].iloc[1, 0] = 5.5
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(strict_limit_prices=True, economic_returns=True))
    assert result.trades == []  # 当日前收参考是5元，而不是10元


def test_strict_one_word_direction_does_not_mistake_reverse_split_for_limit_up():
    signals, panels = sample()
    for field in ("open", "high", "low", "close"):
        panels[field].iloc[1:] = 20
    panels["__adjust_factor"].iloc[1:] = .5
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(strict_limit_prices=True, economic_returns=True))
    assert len(result.trades) == 1
    assert result.trades[0].gross_return_pct == 0


def test_economic_return_keeps_raw_prices_and_factor_pair():
    signals, panels = sample()
    for field in ("open", "high", "low", "close"):
        panels[field].iloc[2:] /= 2
    panels["close"].iloc[2, 0] = 5.25
    panels["high"].iloc[2, 0] = 5.5
    panels["low"].iloc[2, 0] = 4.8
    panels["__adjust_factor"].iloc[2:] = 2
    trade = run_backtest(signals, panels, entry_timing="next_open", config=cfg(economic_returns=True)).trades[0]
    assert trade.entry_price == 10 and trade.exit_price == 5.25
    assert trade.entry_factor == 1 and trade.exit_factor == 2
    assert trade.gross_return_pct == pytest.approx(5)
    assert trade.mfe_pct == pytest.approx(10)
    assert trade.mae_pct == pytest.approx(-4)
    assert trade.net_return_pct == pytest.approx(5 - cfg().round_trip_cost_pct())


def test_economic_stop_is_not_triggered_by_split_and_keeps_real_gap_fill():
    signals, panels = sample()
    for field in ("open", "high", "low", "close"):
        panels[field].iloc[2:] /= 2
    panels["__adjust_factor"].iloc[2:] = 2
    unchanged = run_backtest(signals, panels, entry_timing="next_open",
                             config=cfg(hold_days=3, economic_returns=True, stop_loss_pct=-6)).trades[0]
    assert unchanged.exit_reason == "hold_expired"
    panels["open"].iloc[3, 0] = 4.5
    panels["low"].iloc[3, 0] = 4.4
    trade = run_backtest(signals, panels, entry_timing="next_open",
                         config=cfg(hold_days=3, economic_returns=True, stop_loss_pct=-6)).trades[0]
    assert trade.exit_reason == "stop_loss" and trade.exit_price == 4.5
    assert trade.gross_return_pct == pytest.approx(-10)


@pytest.mark.parametrize("bad", [0, -1, np.nan, np.inf])
def test_economic_factors_must_be_finite_and_positive(bad):
    signals, panels = sample()
    panels["__adjust_factor"].iloc[2, 0] = bad
    with pytest.raises(ValueError, match="有限正数"):
        run_backtest(signals, panels, entry_timing="next_open", config=cfg(economic_returns=True))


@pytest.mark.parametrize("bad_kind", ["missing", "columns", "index"])
def test_economic_factors_must_exist_and_align(bad_kind):
    signals, panels = sample()
    if bad_kind == "missing":
        del panels["__adjust_factor"]
    elif bad_kind == "columns":
        panels["__adjust_factor"].columns = ["600002"]
    else:
        panels["__adjust_factor"].index = panels["__adjust_factor"].index[::-1]
    with pytest.raises(ValueError, match="__adjust_factor"):
        run_backtest(signals, panels, entry_timing="next_open", config=cfg(economic_returns=True))


def test_economic_precision_and_default_rounding_are_distinct():
    signals, panels = sample()
    panels["open"].iloc[1, 0] = 7.13
    panels["close"].iloc[2, 0] = 7.21
    legacy = run_backtest(signals, panels, entry_timing="next_open", config=cfg()).trades[0]
    economic = run_backtest(signals, panels, entry_timing="next_open", config=cfg(economic_returns=True)).trades[0]
    expected = (7.21 / 7.13 - 1) * 100
    assert legacy.gross_return_pct == round(expected, 4)
    assert economic.gross_return_pct == expected
    assert economic.gross_return_pct != legacy.gross_return_pct


def test_valuation_end_preserves_unmatured_trade_as_open_data_end():
    signals, panels = sample()
    end = signals.index[4]
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(hold_days=9, valuation_end=end, economic_returns=True))
    trade = result.trades[0]
    assert trade.exit_reason == "data_end" and trade.exit_date == end
    assert trade.hold_days == 3
    assert result.metrics["trades"] == 0
    assert result.performance.get("assumption", {}).get("model") == "trade_sequence_compounding"
    for field in ("open", "high", "low", "close", "volume"):
        panels[field].iloc[5:] = 99999
    after = run_backtest(signals, panels, entry_timing="next_open",
                         config=cfg(hold_days=9, valuation_end=end, economic_returns=True))
    assert asdict(after.trades[0]) == asdict(trade)


def test_valuation_end_never_uses_later_entry_or_exit():
    signals, panels = sample()
    signals.iloc[:, :] = False
    signals.iloc[4, 0] = True
    result = run_backtest(signals, panels, entry_timing="next_open", config=cfg(valuation_end=signals.index[4]))
    assert result.trades == []
    assert result.skipped["入场日超出数据范围"] == 1


def test_untradable_mature_exit_is_still_open_at_valuation_end():
    signals, panels = sample()
    panels["close"].iloc[2, 0] = panels["low"].iloc[2, 0] = 9
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(strict_limit_prices=True, valuation_end=signals.index[2]))
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "data_end"
    assert result.trades[0].exit_price == 9
    assert result.metrics["trades"] == 0


def test_zero_volume_ex_date_does_not_double_valuation_or_distort_excursions():
    signals, panels = sample()
    panels["__adjust_factor"].iloc[2:] = 2
    for field in ("open", "high", "low", "volume"):
        panels[field].iloc[2, 0] = 0
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(hold_days=9, economic_returns=True, valuation_end=signals.index[2]))
    trade = result.trades[0]
    assert trade.exit_date == signals.index[2] and trade.exit_reason == "data_end"
    assert trade.exit_price == 10 and trade.exit_factor == 1
    assert trade.gross_return_pct == 0 and trade.mae_pct == pytest.approx(-2)
    for field in ("open", "high", "low", "close"):
        panels[field].iloc[3:] /= 2
    resumed = run_backtest(signals, panels, entry_timing="next_open",
                           config=cfg(strict_limit_prices=True, economic_returns=True)).trades[0]
    assert resumed.exit_date == signals.index[3]
    assert resumed.gross_return_pct == 0


def test_fixed9_means_entry_day_counts_as_first_of_ten_days():
    signals, panels = sample()
    trade = run_backtest(signals, panels, entry_timing="next_open",
                         config=cfg(hold_days=9, strict_limit_prices=True, economic_returns=True)).trades[0]
    assert trade.entry_date == signals.index[1]
    assert trade.exit_date == signals.index[10]
    assert trade.exit_reason == "hold_expired"


def test_default_modes_ignore_unrequested_factor_panel_and_keep_legacy_output():
    signals, panels = sample()
    expected = run_backtest(signals, panels, entry_timing="next_open", config=cfg())
    panels["__adjust_factor"].iloc[:, :] = np.nan
    actual = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(strict_limit_prices=False, economic_returns=False, valuation_end=None))
    assert asdict(actual) == asdict(expected)


def test_valuation_end_rejects_unsorted_dates_instead_of_reading_wrong_future():
    signals, panels = sample()
    signals = signals.iloc[::-1]
    panels = {name: panel.iloc[::-1] for name, panel in panels.items()}
    with pytest.raises(ValueError, match="按时间升序"):
        run_backtest(signals, panels, entry_timing="next_open", config=cfg(valuation_end="2026-01-10"))


def test_invalid_factors_after_valuation_end_are_not_consumed():
    signals, panels = sample()
    panels["__adjust_factor"].iloc[4:] = np.nan
    result = run_backtest(signals, panels, entry_timing="next_open",
                          config=cfg(economic_returns=True, valuation_end=signals.index[3]))
    assert result.trades[0].exit_reason == "hold_expired"


def test_raw_exit_is_kept_exactly_despite_nonbinary_factor():
    signals, panels = sample()
    panels["close"].iloc[2, 0] = 6.15
    panels["__adjust_factor"].iloc[:, :] = 1.23
    trade = run_backtest(signals, panels, entry_timing="next_open",
                         config=cfg(economic_returns=True)).trades[0]
    assert trade.exit_price == 6.15


@pytest.mark.parametrize("dataset", ["../dataset", "C:/data", "a.b", "", "a" * 97])
def test_dataset_id_is_not_a_path(dataset):
    with pytest.raises(ValueError, match="signal_dataset"):
        cfg(signal_dataset=dataset)


def test_dataset_id_is_frozen_configuration_only():
    signals, panels = sample()
    result = run_backtest(signals, panels, entry_timing="next_open", config=cfg(signal_dataset="tail_1450-v1"))
    assert result.config["signal_dataset"] == "tail_1450-v1"


@pytest.mark.parametrize("end", ["20260911", "2026-02-30", "../date"])
def test_invalid_valuation_date_is_rejected(end):
    with pytest.raises(ValueError):
        cfg(valuation_end=end)


@pytest.mark.parametrize("name", ["strict_limit_prices", "economic_returns"])
def test_new_flags_reject_truthy_strings(name):
    with pytest.raises(ValueError, match="布尔值"):
        cfg(**{name: "false"})


def test_legacy_configuration_and_trade_dictionaries_are_exactly_unchanged():
    old_config = {
        "hold_days": 3, "stop_loss_pct": -6., "take_profit_pct": None,
        "commission_bps": 3., "stamp_duty_bps": 10., "slippage_bps": 5.,
        "allow_limit_up_entry": False, "benchmark": "000300",
    }
    configuration = BacktestConfig(**old_config)
    assert configuration.to_dict() == old_config
    # 内部冻结上下文仍允许完整asdict，旧字典恢复时新增字段得到默认值。
    assert asdict(configuration)["economic_returns"] is False
    old_trade = {
        "code": "600001", "signal_date": "2026-01-05", "entry_date": "2026-01-06",
        "entry_price": 10., "exit_date": "2026-01-07", "exit_price": 11., "hold_days": 1,
        "gross_return_pct": 10., "net_return_pct": 9.74, "mae_pct": -1., "mfe_pct": 11.,
        "exit_reason": "hold_expired", "benchmark_return_pct": None,
    }
    trade = Trade(**old_trade)
    assert trade.to_dict() == old_trade
    signals, panels = sample()
    result = run_backtest(signals, panels, entry_timing="next_open", config=configuration)
    assert result.config == old_config
    assert result.to_frame().columns.tolist() == [*old_trade, "alpha_pct"]


def test_economic_serialization_keeps_enabled_config_and_factor_fields():
    signals, panels = sample()
    panels["__adjust_factor"].iloc[:, :] = 1.25
    configuration = cfg(economic_returns=True, strict_limit_prices=True,
                        valuation_end=signals.index[4], signal_dataset="tail-v1")
    result = run_backtest(signals, panels, entry_timing="next_open", config=configuration)
    assert result.config["economic_returns"] is True
    assert result.config["strict_limit_prices"] is True
    assert result.config["valuation_end"] == signals.index[4]
    assert result.config["signal_dataset"] == "tail-v1"
    trade = result.trades[0]
    assert trade.to_dict(include_factors=True)["entry_factor"] == 1.25
    assert trade.to_dict(include_factors=True)["exit_factor"] == 1.25
    frame = result.to_frame()
    assert frame.entry_factor.iloc[0] == frame.exit_factor.iloc[0] == 1.25
