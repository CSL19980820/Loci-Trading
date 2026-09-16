"""严格尾盘行情输入契约；全部网络调用使用夹具。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import threading
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.market.application import screen_live


def row(code="000001", **updates):
    result = {"code": code, "date": date.today().isoformat(), "open": 10.0,
              "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000.0,
              "amount": 10500.0}
    result.update(updates)
    return result


@pytest.fixture(autouse=True)
def clear_cache():
    screen_live.reset_live_spot_cache()
    yield
    screen_live.reset_live_spot_cache()


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad", [None, np.nan, np.inf, -np.inf, "invalid"])
def test_missing_or_nonfinite_ohlcv_fails_entire_request(field, bad):
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([row(**{field: bad})]), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match="缺少1/1.*000001"):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_absent_column_fails_instead_of_filling_close(field):
    data = row()
    del data[field]
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([data]), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match="缺少1/1"):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)


@pytest.mark.parametrize("updates", [{"open": 0}, {"low": -1}, {"volume": -1}, {"date": "2000-01-01"}])
def test_invalid_prices_negative_volume_and_stale_date_fail(updates):
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([row(**updates)]), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match="缺少1/1"):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)


@pytest.mark.parametrize("rows,missing", [([], 2), ([row()], 1)])
def test_partial_or_empty_response_is_explicit_failure(rows, missing):
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame(rows), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match=f"缺少{missing}/2"):
            screen_live.fetch_live_spot_bars(["000001", "300001"], strict=True)


def test_strict_bypasses_completed_cache_and_does_not_share_legacy_cache():
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([row()]), "fixture")) as fetch:
        screen_live.fetch_live_spot_bars(["000001"])
        screen_live.fetch_live_spot_bars(["000001"])
        assert fetch.call_count == 1
        screen_live.fetch_live_spot_bars(["000001"], strict=True)
        screen_live.fetch_live_spot_bars(["000001"], strict=True)
        assert fetch.call_count == 3
        screen_live.fetch_live_spot_bars(["000001"])
        assert fetch.call_count == 4


def test_strict_does_not_cache_failed_request():
    with patch("src.market.infrastructure.adapters.fetch_spot_routed", side_effect=[
        (pd.DataFrame(), "fixture"), (pd.DataFrame([row()]), "fixture"),
    ]) as fetch:
        with pytest.raises(screen_live.ScreenLiveError):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)
        assert screen_live.fetch_live_spot_bars(["000001"], strict=True)["000001"]["close"] == 10.5
        assert fetch.call_count == 2


def test_legacy_fallback_unchanged_but_strict_preserves_zero_and_raw_volume():
    data = row(volume=0)
    del data["open"]
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([data]), "fixture")):
        legacy = screen_live.fetch_live_spot_bars(["000001", "300001"])
        assert legacy["000001"]["open"] == 10.5
        assert set(legacy) == {"000001"}
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([row(volume=0)]), "fixture")):
        assert screen_live.fetch_live_spot_bars(["000001"], strict=True)["000001"]["volume"] == 0
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([row(volume=10, amount=10500)]), "fixture")):
        assert screen_live.fetch_live_spot_bars(["000001"], strict=True)["000001"]["volume"] == 10


def test_explicit_complete_zero_volume_snapshot_keeps_raw_zero_prices():
    data = row(open=0, high=0, low=0, volume=0, amount=0)
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([data]), "fixture")):
        strict = screen_live.fetch_live_spot_bars(["000001"], strict=True)["000001"]
        assert [strict[k] for k in ("open", "high", "low", "close", "volume")] == [0, 0, 0, 10.5, 0]
        legacy = screen_live.fetch_live_spot_bars(["000001"])["000001"]
        assert [legacy[k] for k in ("open", "high", "low")] == [10.5, 10.5, 10.5]


@pytest.mark.parametrize("change", [{"close": 0}, {"low": -1}, {"volume": None},
                                     {"volume": np.nan}, {"volume": -1}, {"open": np.nan}])
def test_zero_volume_exception_never_accepts_invalid_or_missing_fields(change):
    data = row(open=0, high=0, low=0, volume=0, amount=0)
    data.update(change)
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([data]), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match="缺少1/1"):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)


def test_absent_volume_in_zero_price_snapshot_is_not_treated_as_zero():
    data = row(open=0, high=0, low=0, amount=0)
    del data["volume"]
    with patch("src.market.infrastructure.adapters.fetch_spot_routed",
               return_value=(pd.DataFrame([data]), "fixture")):
        with pytest.raises(screen_live.ScreenLiveError, match="缺少1/1"):
            screen_live.fetch_live_spot_bars(["000001"], strict=True)


def test_concurrent_strict_callers_share_only_inflight_fetch():
    entered, release, waiter_entered = threading.Event(), threading.Event(), threading.Event()
    real_event = threading.Event

    class ObservedEvent:
        def __init__(self):
            self.event = real_event()

        def wait(self, timeout=None):
            waiter_entered.set()
            return self.event.wait(timeout)

        def set(self):
            self.event.set()

    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return pd.DataFrame([row()]), "fixture"

    # 替换当前在途事件实例，不替换全局threading.Event工厂，避免影响线程池。
    with patch("src.market.infrastructure.adapters.fetch_spot_routed", side_effect=fetch) as mocked:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(screen_live.fetch_live_spot_bars, ["000001"], strict=True)
            assert entered.wait(5)
            with screen_live._CACHE_LOCK:
                screen_live._INFLIGHT = ObservedEvent()
            second = pool.submit(screen_live.fetch_live_spot_bars, ["000001"], strict=True)
            try:
                assert waiter_entered.wait(5)
            finally:
                release.set()
            assert first.result(timeout=5) == second.result(timeout=5)
        assert mocked.call_count == 1
