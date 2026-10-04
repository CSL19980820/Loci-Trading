"""Positive-fixture causality and hard shortlist-cap tests; no real DB access."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.wechat_four_patterns import WechatFourPatternsStrategy, select_top_two
from src.strategy.domain.base import StrategyError


def platform_fixture(n: int = 170) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    codes = ["600004", "000003", "600002", "000001"]
    c = pd.DataFrame(np.repeat(np.linspace(10, 10.1, n)[:, None], 4, axis=1), index=dates, columns=codes)
    p = {"close": c, "open": c.copy(), "high": c + 0.01, "low": c - 0.01,
         "volume": c * 0 + 1_000_000, "amount": c * 0 + 100_000_000,
         "__eligible": pd.DataFrame(True, index=dates, columns=codes)}
    p["close"].iloc[149] = 10.30
    p["open"].iloc[149] = 10.12
    p["high"].iloc[149] = 10.31
    p["low"].iloc[149] = 10.08
    p["volume"].iloc[149] = 1_500_000
    return p


def compute(panels: dict[str, pd.DataFrame], **params: object):
    return WechatFourPatternsStrategy().compute(panels, {"min_market_count": 1, **params})


def test_positive_platform_and_global_two_cap():
    result = compute(platform_fixture())
    assert result.factors["pattern_platform"].iloc[149].all()
    assert result.factors["candidate"].iloc[149].sum() == 4
    assert result.signals.iloc[149].sum() == 2
    assert result.picks_on(result.signals.index[149]) == ["000001", "000003"]
    assert result.signals.sum(axis=1).max() <= 2


def test_column_order_does_not_change_ties():
    p = platform_fixture()
    original = compute(p)
    permuted = compute({k: v.iloc[:, ::-1] for k, v in p.items()})
    pd.testing.assert_frame_equal(original.signals, permuted.signals.reindex(columns=original.signals.columns))


@pytest.mark.parametrize("limit", [0, 3, -1, True, 2.0, "2"])
def test_cannot_raise_daily_limit(limit):
    with pytest.raises(StrategyError, match="daily_limit"):
        compute(platform_fixture(), daily_limit=limit)


def test_one_is_allowed_and_does_not_fill_up_to_two():
    result = compute(platform_fixture(), daily_limit=1)
    assert result.signals.sum(axis=1).max() == 1


def test_prefix_consistency_contains_real_positive():
    p = platform_fixture()
    full = compute(p)
    truncated = compute({k: v.iloc[:150] for k, v in p.items()})
    assert truncated.signals.iloc[-1].sum() == 2
    pd.testing.assert_frame_equal(full.signals.iloc[:150], truncated.signals)
    for key in full.factors:
        pd.testing.assert_frame_equal(full.factors[key].iloc[:150], truncated.factors[key])


def test_future_extremes_cannot_change_past_picks_or_scores():
    p = platform_fixture()
    old = compute(p)
    for key in ("open", "high", "low", "close", "volume", "amount"):
        p[key].iloc[150:] *= 20
    new = compute(p)
    pd.testing.assert_frame_equal(old.signals.iloc[:150], new.signals.iloc[:150])
    pd.testing.assert_frame_equal(old.factors["score"].iloc[:150], new.factors["score"].iloc[:150])


def test_explicit_eligibility_required():
    p = platform_fixture()
    del p["__eligible"]
    with pytest.raises(StrategyError, match="eligibility"):
        compute(p)


def test_eligibility_suspension_and_missing_quotes_never_select():
    p = platform_fixture()
    p["__eligible"].iloc[149, 0] = False
    p["volume"].iloc[149, 1] = 0
    p["close"].iloc[149, 2] = np.nan
    result = compute(p)
    assert result.signals.iloc[149].sum() == 1
    assert result.signals.iloc[149, 3]


def test_warmup_and_empty_market_do_not_fabricate_signals():
    p = platform_fixture()
    result = compute({k: v.iloc[50:150] for k, v in p.items()})
    assert not result.signals.any().any()
    p["__eligible"].iloc[:] = False
    assert not compute(p).signals.any().any()


def test_non_mainboard_is_excluded():
    p = {k: v.rename(columns={"000001": "300001", "000003": "688001"}) for k, v in platform_fixture().items()}
    result = compute(p)
    assert not result.signals[["300001", "688001"]].any().any()


def test_nonfinite_rank_and_no_filler():
    candidates = pd.DataFrame([[True, True, False]], columns=["a", "b", "c"])
    scores = pd.DataFrame([[np.nan, 5, 100]], columns=candidates.columns)
    assert select_top_two(candidates, scores).iloc[0].tolist() == [False, True, False]


def test_misaligned_inputs_rejected():
    p = platform_fixture()
    p["volume"] = p["volume"].iloc[1:]
    with pytest.raises(StrategyError, match="misaligned"):
        compute(p)


def test_not_a_close_or_live_auto_registered_strategy():
    from src.strategy.domain.base import is_builtin_registered
    engine = WechatFourPatternsStrategy()
    assert engine.entry_timing == "next_open"
    assert not is_builtin_registered(engine.slug)


def execution_fixture():
    dates = pd.bdate_range("2025-01-02", periods=7).strftime("%Y-%m-%d").tolist()
    base = pd.DataFrame(10.0, index=dates, columns=["000001"])
    panels = {"open": base.copy(), "close": base.copy(), "high": base + 0.1,
              "low": base - 0.1, "volume": base * 0 + 1_000_000,
              "__adjust_factor": base * 0 + 1}
    signals = pd.DataFrame(False, index=dates, columns=base.columns)
    signals.iloc[1, 0] = True
    return dates, panels, signals


def execute(panels, signals, **kwargs):
    from src.backtest.application.engine import run_backtest
    from src.backtest.domain.models import BacktestConfig
    config = BacktestConfig(hold_days=2, strict_limit_prices=True, economic_returns=True, **kwargs)
    return run_backtest(signals, panels, entry_timing="next_open", config=config)


def test_entry_day_stop_is_not_same_day_sale():
    dates, panels, signals = execution_fixture()
    panels["low"].iloc[2, 0] = 8.0
    result = execute(panels, signals)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_date == dates[2] and trade.exit_date == dates[4]
    assert trade.exit_reason == "hold_expired"
    assert trade.net_return_pct == pytest.approx(-0.26)


def test_gap_through_stop_uses_worse_open_not_stop_line():
    _, panels, signals = execution_fixture()
    for key, value in {"open": 9.2, "close": 9.4, "high": 9.5, "low": 9.1}.items():
        panels[key].iloc[3, 0] = value
    trade = execute(panels, signals).trades[0]
    assert trade.exit_price == pytest.approx(9.2)
    assert trade.net_return_pct == pytest.approx(-8.26)


def test_limit_up_open_is_not_filled():
    _, panels, signals = execution_fixture()
    for key in ("open", "close", "high", "low"):
        panels[key].iloc[2, 0] = 11.0
    assert not execute(panels, signals).trades


def test_split_does_not_create_false_loss():
    _, panels, signals = execution_fixture()
    for key in ("open", "close", "high", "low"):
        panels[key].iloc[3:] /= 2
    panels["__adjust_factor"].iloc[3:] = 2.0
    trade = execute(panels, signals).trades[0]
    assert trade.entry_price == 10.0 and trade.exit_price == 5.0
    assert trade.net_return_pct == pytest.approx(-0.26)


def test_terminal_position_stays_open_and_account_marks_loss():
    from src.backtest.application.research_portfolio import PortfolioResearchConfig, analyze_portfolio
    dates, panels, signals = execution_fixture()
    panels["close"].iloc[2, 0] = 9.5
    panels["low"].iloc[2, 0] = 9.4
    events = execute(panels, signals, valuation_end=dates[2])
    assert events.trades[0].exit_reason == "data_end"
    account = analyze_portfolio(events.trades,
        config=PortfolioResearchConfig(account_model="daily_close"), trading_dates=dates[:3],
        closing_prices=panels["close"], adjustment_factors=panels["__adjust_factor"])
    assert not account.allocations and len(account.open_allocations) == 1
    assert account.daily[-1].equity < 200_000
    assert account.daily[-1].cash >= 0
    assert account.daily[-1].unrealized_pnl < 0
