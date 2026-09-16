"""Daily account fixtures test bookkeeping, not strategy profitability."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest.application.research_portfolio import (
    PortfolioResearchConfig,
    PortfolioResearchError,
    analyze_portfolio,
)
from src.backtest.domain.models import Trade

DAYS = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]


def _trade(
    code: str = "000001",
    entry: str = DAYS[0],
    exit_: str = DAYS[1],
    *,
    entry_price: float = 10.0,
    exit_price: float = 10.0,
    fee_pct: float = 0.0,
    entry_factor: float = 1.0,
    exit_factor: float = 1.0,
    reason: str = "hold_expired",
    gross_pct: float | None = None,
) -> Trade:
    gross = (
        (exit_price * exit_factor / (entry_price * entry_factor) - 1) * 100
        if gross_pct is None
        else gross_pct
    )
    return Trade(
        code=code,
        signal_date=entry,
        entry_date=entry,
        exit_date=exit_,
        entry_price=entry_price,
        exit_price=exit_price,
        hold_days=2,
        gross_return_pct=gross,
        net_return_pct=gross - fee_pct,
        mae_pct=-5.0,
        mfe_pct=10.0,
        exit_reason=reason,
        entry_factor=entry_factor,
        exit_factor=exit_factor,
    )


def _config(
    initial: float = 20_000, slots: int = 1, **kwargs: object
) -> PortfolioResearchConfig:
    return PortfolioResearchConfig(
        initial_capital=initial,
        max_positions=slots,
        account_model="daily_close",
        **kwargs,
    )


def test_default_and_explicit_legacy_serialization_are_unchanged() -> None:
    trade = _trade(exit_=DAYS[2], exit_price=11, fee_pct=0.3)
    legacy = analyze_portfolio(
        [trade],
        config=PortfolioResearchConfig(
            initial_capital=20_000,
            max_positions=1,
        ),
        trading_dates=DAYS[:3],
    )
    explicit = analyze_portfolio(
        [trade],
        config=PortfolioResearchConfig(
            initial_capital=20_000,
            max_positions=1,
            account_model="cost_until_exit",
        ),
        trading_dates=DAYS[:3],
        closing_prices=pd.DataFrame({"unused": [0]}),
        adjustment_factors=pd.DataFrame({"unused": [-1]}),
    )
    assert legacy.to_dict() == explicit.to_dict()
    assert legacy.metrics["final_equity"] == pytest.approx(21_940)
    assert legacy.metrics["assumption"]["marks_to_market"] is False
    assert "open_allocations" not in legacy.to_dict()
    assert "market_value" not in legacy.daily[0].to_dict()


def test_opening_cost_is_reserved_before_lot_sizing_and_split_on_exit() -> None:
    result = analyze_portfolio(
        [_trade(exit_price=11, fee_pct=0.3)],
        config=_config(),
        closing_prices=pd.DataFrame({"000001": [10.5, 11]}, index=DAYS[:2]),
    )
    allocation = result.allocations[0]
    assert allocation.quantity == 1900
    assert result.daily[0].cash == pytest.approx(971.5)
    assert result.daily[0].equity == pytest.approx(20_921.5)
    assert result.daily[0].market_value == pytest.approx(19_950)
    assert result.daily[0].unrealized_pnl == pytest.approx(921.5)
    assert allocation.to_dict()["entry_cost"] == pytest.approx(28.5)
    assert allocation.to_dict()["exit_cost"] == pytest.approx(28.5)
    assert allocation.exit_notional == pytest.approx(20_871.5)
    assert allocation.pnl == pytest.approx(1843)
    assert result.metrics["final_equity"] == pytest.approx(21_843)
    assert result.metrics["fees_paid"] == pytest.approx(57)


def test_same_day_exit_does_not_fund_entry_and_next_day_reinvests_equity() -> None:
    result = analyze_portfolio(
        [
            _trade("A", exit_price=11),
            _trade("B", DAYS[1], DAYS[2], exit_price=12),
            _trade("C", DAYS[2], DAYS[3]),
        ],
        config=_config(10_000),
        trading_dates=DAYS,
        closing_prices=pd.DataFrame(
            {"A": [10, 11, 11, 11], "B": [10, 10, 12, 12], "C": [10, 10, 10, 10]},
            index=DAYS,
        ),
    )
    assert [a.code for a in result.allocations] == ["A", "C"]
    assert result.allocations[1].quantity == 1100
    assert result.daily[1].entries == 0
    assert result.daily[1].exits == 1
    assert result.skipped["资金槽位已占用"] == 1


def test_position_size_uses_prior_day_marked_equity_not_todays_close() -> None:
    result = analyze_portfolio(
        [
            _trade("A", exit_=DAYS[2], exit_price=20, reason="data_end"),
            _trade("B", DAYS[1], DAYS[2]),
        ],
        config=_config(60_000, 3),
        closing_prices=pd.DataFrame(
            {"A": [20, 100, 20], "B": [10, 10, 10]}, index=DAYS[:3]
        ),
    )
    # Prior-day NAV is80k, leaving40k cash. 80k/3 buys2600 shares;
    # using initial NAV would buy2000, using today's A quote would buy4000.
    assert result.allocations[0].code == "B"
    assert result.allocations[0].quantity == 2600
    assert result.daily[0].equity == pytest.approx(80_000)
    assert result.daily[1].equity == pytest.approx(240_000)
    assert result.metrics["final_equity"] == pytest.approx(80_000)
    assert result.metrics["unrealized_pnl"] == pytest.approx(20_000)
    # Large unrealized gains are not leverage: amount ratios use current NAV.
    utilization = result.metrics["avg_capital_utilization_pct"]
    idle_cash = result.metrics["avg_idle_cash_pct"]
    assert utilization + idle_cash == pytest.approx(100, abs=1e-4)
    assert result.metrics["max_capital_utilization_pct"] <= 100
    for day in result.daily:
        assert day.market_value / day.equity <= 1
        assert (day.market_value + day.cash) / day.equity == pytest.approx(1)
    for segment in result.to_dict()["segments"]:
        assert segment["max_capital_utilization_pct"] <= 100
        assert segment["avg_capital_utilization_pct"] + segment[
            "avg_idle_cash_pct"
        ] == pytest.approx(100, abs=1e-4)


def test_split_is_economically_neutral_and_fees_are_not_lost() -> None:
    result = analyze_portfolio(
        [_trade(exit_price=5, exit_factor=2, fee_pct=0.3)],
        config=_config(),
        closing_prices=pd.DataFrame({"000001": [10, 5]}, index=DAYS[:2]),
        adjustment_factors=pd.DataFrame({"000001": [1, 2]}, index=DAYS[:2]),
    )
    assert result.allocations[0].gross_return_pct == pytest.approx(0)
    assert result.allocations[0].net_return_pct == pytest.approx(-0.3)
    assert result.metrics["final_equity"] == pytest.approx(19_943)
    assert result.metrics["realized_pnl"] == pytest.approx(-57)


@pytest.mark.parametrize("include", [False, True])
def test_data_end_is_open_and_does_not_pay_a_future_exit_cost(include: bool) -> None:
    result = analyze_portfolio(
        [
            _trade(
                exit_=DAYS[2],
                exit_price=999,
                fee_pct=0.4,
                gross_pct=0,
                reason="data_end",
            )
        ],
        config=_config(10_000, include_data_end=include),
        closing_prices=pd.DataFrame({"000001": [10, 11, 12]}, index=DAYS[:3]),
    )
    assert result.accepted_trades == 1
    assert result.allocations == []
    assert result.metrics["closed_trades"] == 0
    assert result.metrics["realized_pnl"] == 0
    assert result.metrics["exit_cost_total"] == 0
    assert result.metrics["entry_cost_total"] == pytest.approx(18)
    assert result.metrics["final_equity"] == pytest.approx(11_782)
    assert result.metrics["unrealized_pnl"] == pytest.approx(1782)
    assert result.open_allocations[0]["quantity"] == 900
    assert result.open_allocations[0]["raw_close"] == 12
    assert result.open_allocations[0]["status"] == "open"
    assert result.to_dict()["open_allocations"][0]["entry_cost"] == 18
    assert result.metrics["profit_factor"] is None
    assert result.segments[0].sample_size == 0
    assert result.metrics["assumption"]["marks_to_market"] is True
    assert result.metrics["assumption"]["daily_close"] is True


@pytest.mark.parametrize("last_close", [5.0, np.nan])
def test_missing_quotes_carry_the_whole_economic_mark(last_close: float) -> None:
    result = analyze_portfolio(
        [_trade(exit_=DAYS[2], exit_price=10, reason="data_end")],
        config=_config(10_000),
        closing_prices=pd.DataFrame(
            {"000001": [10, np.nan, last_close]}, index=DAYS[:3]
        ),
        adjustment_factors=pd.DataFrame({"000001": [1, 2, 2]}, index=DAYS[:3]),
    )
    assert [day.equity for day in result.daily] == pytest.approx([10_000] * 3)
    assert result.daily[1].market_value == pytest.approx(10_000)
    expected_mark_date = DAYS[0] if pd.isna(last_close) else DAYS[2]
    assert result.open_allocations[0]["mark_date"] == expected_mark_date


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"000001": [10, np.nan, 11]}, index=DAYS[:3]),
        pd.DataFrame({"000001": [11]}, index=[DAYS[2]]),
    ],
)
def test_missing_opening_day_close_never_uses_past_or_future_quote(
    frame: pd.DataFrame,
) -> None:
    with pytest.raises(PortfolioResearchError, match="开仓日"):
        analyze_portfolio(
            [_trade(entry=DAYS[1], exit_=DAYS[2], exit_price=11)],
            config=_config(),
            closing_prices=frame,
        )


def test_missing_factor_cannot_backfill_from_a_later_action() -> None:
    with pytest.raises(PortfolioResearchError, match="没有已知有效复权因子"):
        analyze_portfolio(
            [_trade(exit_=DAYS[2], exit_price=5, exit_factor=2)],
            config=_config(),
            closing_prices=pd.DataFrame({"000001": [10, 10, 5]}, index=DAYS[:3]),
            adjustment_factors=pd.DataFrame({"000001": [2]}, index=[DAYS[2]]),
        )


def test_observation_cutoff_does_not_settle_a_known_future_exit() -> None:
    result = analyze_portfolio(
        [_trade(exit_=DAYS[3], exit_price=100, fee_pct=0.3)],
        config=_config(10_000),
        trading_dates=DAYS[:2],
        closing_prices=pd.DataFrame({"000001": [10, 11, 500, 100]}, index=DAYS),
    )
    assert result.time_range["end"] == DAYS[1]
    assert result.metrics["closed_trades"] == 0
    assert result.metrics["exit_cost_total"] == 0
    assert result.metrics["final_equity"] == pytest.approx(10_886.5)
    assert result.open_allocations[0]["mark_date"] == DAYS[1]


def test_numpy_string_calendar_and_datetime_panel_are_supported() -> None:
    result = analyze_portfolio(
        [_trade()],
        config=_config(),
        trading_dates=np.array(DAYS[:2]).tolist(),
        closing_prices=pd.DataFrame(
            {"000001": [10, 10]}, index=pd.to_datetime(DAYS[:2])
        ),
    )
    second = analyze_portfolio(
        [_trade()],
        config=_config(),
        trading_dates=list(np.array(DAYS[:2])),
        closing_prices=pd.DataFrame({"000001": [10, 10]}, index=np.array(DAYS[:2])),
    )
    assert result.to_dict() == second.to_dict()


def test_code_priority_is_deterministic_with_different_signal_dates() -> None:
    first = _trade("000002")
    first.signal_date = "2025-12-30"
    second = _trade("000001")
    second.signal_date = "2025-12-31"
    result = analyze_portfolio(
        [first, second],
        config=_config(),
        closing_prices=pd.DataFrame(
            {"000001": [10, 10], "000002": [10, 10]}, index=DAYS[:2]
        ),
    )
    assert [a.code for a in result.allocations] == ["000001"]


def test_invalid_negative_cost_cannot_create_cash() -> None:
    with pytest.raises(PortfolioResearchError, match="成本率"):
        analyze_portfolio(
            [_trade(fee_pct=-1)],
            config=_config(),
            closing_prices=pd.DataFrame({"000001": [10, 10]}, index=DAYS[:2]),
        )


def test_entry_factor_must_match_its_price_panel() -> None:
    with pytest.raises(PortfolioResearchError, match="entry_factor"):
        analyze_portfolio(
            [_trade()],
            config=_config(),
            closing_prices=pd.DataFrame({"000001": [10, 10]}, index=DAYS[:2]),
            adjustment_factors=pd.DataFrame({"000001": [2, 2]}, index=DAYS[:2]),
        )


@pytest.mark.parametrize("model", ["invalid", None, []])
def test_invalid_account_model_reports_a_configuration_error(model: object) -> None:
    with pytest.raises(PortfolioResearchError, match="account_model"):
        PortfolioResearchConfig(account_model=model)
