"""只为opt-in策略启用严格实时输入，禁止旧当日K回退。"""
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd
import pytest

from src.market.application.screen_live import reset_live_spot_cache
from src.market.domain.universe import ResolvedUniverse
from src.strategy.application.impulse_pullback import ImpulsePullbackTailV1
from src.strategy.application.screener import screen
from src.strategy.domain.base import StrategyError


class Store:
    def trading_days(self, *, end=None):
        return ["2026-01-01", date.today().isoformat()]

    def data_snapshot(self, **kwargs):
        return {"revision": "fixture"}

    def load_panel(self, **kwargs):
        return {name: pd.DataFrame({"000001": [10.0, 999.0]}, index=self.trading_days())
                for name in ("open", "high", "low", "close", "volume")}


@pytest.fixture(autouse=True)
def cache():
    reset_live_spot_cache()
    yield
    reset_live_spot_cache()


def run(engine):
    resolved = ResolvedUniverse(codes=["000001"], meta={"000001": {"name": "fixture"}},
                                spec={"preset": "fixture"})
    with patch("src.strategy.application.screener.resolve_universe", return_value=resolved), \
         patch("src.strategy.application.audit.guard_strategy"):
        return screen(Store(), engine, codes=["000001"], live_overlay=True, health_check=False)


@pytest.mark.parametrize("strict", [True, False])
def test_optin_keyword_and_fetch_interval_metadata(strict):
    engine = ImpulsePullbackTailV1()
    engine.live_candidate_codes = None
    engine.strict_live_ohlcv = strict
    live = {"000001": {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}}
    with patch("src.market.fetch_live_spot_bars", return_value=live) as fetch:
        result = run(engine)
    assert ("strict" in fetch.call_args.kwargs) is strict
    if strict:
        assert fetch.call_args.kwargs["strict"] is True
    snapshot = result.data_snapshot
    assert snapshot["strict_live_ohlcv"] is strict
    assert snapshot["live_fetch_atomic"] is False
    start = datetime.fromisoformat(snapshot["live_fetch_started_at"])
    finish = datetime.fromisoformat(snapshot["live_fetch_finished_at"])
    assert start.tzinfo is not None and finish >= start


def test_incomplete_live_input_aborts_before_engine_and_never_uses_old_day():
    bad = pd.DataFrame([{"code": "000001", "date": date.today().isoformat(), "close": 10.5}])
    engine = ImpulsePullbackTailV1()
    engine.live_candidate_codes = None
    with patch("src.market.infrastructure.adapters.fetch_spot_routed", return_value=(bad, "fixture")), \
         patch.object(engine, "compute") as compute:
        with pytest.raises(StrategyError, match="缺少1/1"):
            run(engine)
    compute.assert_not_called()


def test_no_history_candidates_never_fetch_and_no_old_today_survives():
    engine = ImpulsePullbackTailV1()
    with patch("src.market.fetch_live_spot_bars") as fetch:
        result = run(engine)
    fetch.assert_not_called()
    assert result.picks == []
    assert result.trade_date == date.today().isoformat()
    assert result.data_snapshot["pre_candidate_count"] == 0
    assert result.data_snapshot["live_requested_codes"] == 0
    assert result.data_snapshot["live_fetch_started_at"] is None


def candidate_history_store():
    days = pd.bdate_range(end=date.today(), periods=59).strftime("%Y-%m-%d").tolist()
    if days[-1] == date.today().isoformat():
        days = pd.bdate_range(end=pd.Timestamp(date.today()) - pd.Timedelta(days=1), periods=59).strftime("%Y-%m-%d").tolist()
    rows = [[9.9, 10.1, 9.8, 10, 100] for _ in days]
    rows[-3] = [10, 11, 10, 11, 1000]
    rows[-2] = [10.9, 10.95, 10.55, 10.8, 500]
    rows[-1] = [10.75, 10.85, 10.60, 10.70, 400]
    fields = ("open", "high", "low", "close", "volume")

    class CandidateStore(Store):
        load_min = None

        def trading_days(self, *, end=None):
            return [d for d in days if end is None or d <= end]

        def load_panel(self, **kwargs):
            self.load_min = kwargs["min_bars"]
            codes = ["000001", "300001"] if self.load_min <= 59 else []
            return {f: pd.DataFrame({code: [r[k] if code == "000001" else 10 for r in rows]
                                    for code in codes}, index=days) for k, f in enumerate(fields)}

    return CandidateStore()


def test_only_precandidates_fetch_and_today_becomes_sixtieth_bar():
    store = candidate_history_store()
    resolved = ResolvedUniverse(codes=["000001", "300001"], meta={}, spec={"preset": "fixture"})
    engine = ImpulsePullbackTailV1()
    live = {"000001": {"open": 10.8, "high": 11.05, "low": 10.65, "close": 11, "volume": 600}}
    with patch("src.strategy.application.screener.resolve_universe", return_value=resolved), \
         patch("src.market.fetch_live_spot_bars", return_value=live) as fetch, \
         patch("src.strategy.application.audit.guard_strategy"), \
         patch.object(engine, "compute", wraps=engine.compute) as compute:
        result = screen(store, engine, codes=resolved.codes, live_overlay=True, health_check=False)
    assert store.load_min == 59
    assert fetch.call_args.args[0] == ["000001"]
    assert fetch.call_args.kwargs["strict"] is True
    assert [r["code"] for r in result.picks] == ["000001"]
    assert result.picks[0]["factors"]["BARSCOUNT"] == 60
    assert result.data_snapshot["pre_candidate_count"] == 1
    assert result.data_snapshot["live_requested_codes"] == 1
    assert result.data_snapshot["live_ohlcv"] == live
    final_panels = compute.call_args.args[0]
    for field in ("open", "high", "low", "close", "volume"):
        assert pd.isna(final_panels[field].loc[date.today().isoformat(), "300001"])


def test_precandidate_missing_live_still_fails():
    store = candidate_history_store()
    resolved = ResolvedUniverse(codes=["000001", "300001"], meta={}, spec={"preset": "fixture"})
    with patch("src.strategy.application.screener.resolve_universe", return_value=resolved), \
         patch("src.market.infrastructure.adapters.fetch_spot_routed", return_value=(pd.DataFrame(), "fixture")), \
         patch("src.strategy.application.audit.guard_strategy"):
        with pytest.raises(StrategyError, match="缺少1/1"):
            screen(store, ImpulsePullbackTailV1(), codes=resolved.codes, live_overlay=True, health_check=False)


def test_empty_history_columns_return_empty_without_live_fetch():
    empty = {k: pd.DataFrame() for k in ("open", "high", "low", "close", "volume")}
    with patch.object(Store, "load_panel", return_value=empty), \
         patch("src.market.fetch_live_spot_bars") as fetch:
        result = run(ImpulsePullbackTailV1())
    fetch.assert_not_called()
    assert result.picks == []
    assert result.data_snapshot["pre_candidate_count"] == 0


def test_explicit_zero_volume_does_not_block_active_candidate_or_reuse_yesterday_signal():
    store = candidate_history_store()
    history = store.load_panel(min_bars=59)
    names = ("open", "high", "low", "close", "volume")
    last_four = ([10, 11, 10, 11, 1000], [10.9, 10.95, 10.55, 10.8, 500],
                 [10.75, 10.85, 10.60, 10.70, 400], [10.8, 11.05, 10.65, 11, 600])
    for k, field in enumerate(names):
        frame = history[field]
        earlier = (pd.Timestamp(frame.index[0]) - pd.offsets.BDay(1)).strftime("%Y-%m-%d")
        frame.loc[earlier] = frame.iloc[0]
        frame.sort_index(inplace=True)
        for offset, row in enumerate(last_four):
            frame.iloc[-4 + offset, 0] = row[k]
        frame["300001"] = frame["000001"]
    engine = ImpulsePullbackTailV1()
    assert engine.compute(history).signals.iloc[-1].all()  # 昨日两票均命中
    today = date.today().isoformat()
    spot = pd.DataFrame([
        {"code": "000001", "date": today, "open": 10.9, "high": 11.2,
         "low": 10.7, "close": 11.1, "volume": 700, "amount": 7770},
        {"code": "300001", "date": today, "open": 0, "high": 0,
         "low": 0, "close": 11, "volume": 0, "amount": 0},
    ])
    resolved = ResolvedUniverse(codes=["000001", "300001"], meta={}, spec={"preset": "fixture"})
    with patch.object(store, "load_panel", return_value=history), \
         patch("src.strategy.application.screener.resolve_universe", return_value=resolved), \
         patch("src.market.infrastructure.adapters.fetch_spot_routed", return_value=(spot, "fixture")), \
         patch("src.strategy.application.audit.guard_strategy"), \
         patch.object(engine, "compute", wraps=engine.compute) as compute:
        result = screen(store, engine, codes=resolved.codes, live_overlay=True, health_check=False)
    assert [r["code"] for r in result.picks] == ["000001"]
    assert result.data_snapshot["zero_volume_codes"] == ["300001"]
    assert result.data_snapshot["live_overlay_codes"] == 1
    assert result.data_snapshot["live_requested_codes"] == 2
    raw = result.data_snapshot["live_ohlcv"]["300001"]
    assert [raw[k] for k in names] == [0, 0, 0, 11, 0]
    actual = compute.call_args.args[0]
    for field in names:
        assert pd.isna(actual[field].loc[today, "300001"])


def test_all_precandidates_zero_volume_return_empty_success():
    store = candidate_history_store()
    resolved = ResolvedUniverse(codes=["000001"], meta={}, spec={"preset": "fixture"})
    spot = pd.DataFrame([{"code": "000001", "date": date.today().isoformat(),
                          "open": 0, "high": 0, "low": 0, "close": 10.7, "volume": 0}])
    with patch("src.strategy.application.screener.resolve_universe", return_value=resolved), \
         patch("src.market.infrastructure.adapters.fetch_spot_routed", return_value=(spot, "fixture")), \
         patch("src.strategy.application.audit.guard_strategy"):
        result = screen(store, ImpulsePullbackTailV1(), codes=resolved.codes,
                        live_overlay=True, health_check=False)
    assert result.picks == []
    assert result.data_snapshot["zero_volume_codes"] == ["000001"]
    assert result.data_snapshot["live_overlay_codes"] == 0
