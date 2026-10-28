"""Quote-cache trust boundaries using synthetic prices and mocked I/O only."""

import gzip
import json
from unittest.mock import Mock

import pandas as pd
import pytest

from scripts import first_wave_quote_research as research


CODE = "600001"
DAY = "2024-01-09"


@pytest.fixture
def collector(tmp_path, monkeypatch):
    cache = research.QuoteCache(
        tmp_path / "unused.db", tmp_path / "cache", {}, tmp_path / "probes"
    )
    con = Mock()
    con.execute.return_value.fetchone.return_value = (10.0, 10.2, 9.8, 10.0, 10000)
    provider = Mock(
        return_value=pd.DataFrame(
            {
                "datetime": [f"{DAY} 14:50", f"{DAY} 15:00"],
                "close": [10.1, 10.0],
                "volume": [100.0, 200.0],
            }
        )
    )
    monkeypatch.setattr(research, "_open_client", Mock(return_value=object()))
    monkeypatch.setattr(research, "_fetch_day", provider)
    monkeypatch.setattr(research, "_close_client", Mock())
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        research, "ro_connect", Mock(side_effect=AssertionError("No real database"))
    )
    yield cache, con, provider
    cache.close()


@pytest.mark.parametrize(
    "prices,inside_range,closing_difference",
    [
        pytest.param([10.1, 10.05], True, 0.05, id="wrong-close-within-range"),
        pytest.param([10.3, 10.0], False, 0.0, id="out-of-range-with-correct-close"),
    ],
)
def test_daily_price_mismatch_is_cached_but_not_exposed_as_quotes(
    collector, prices, inside_range, closing_difference
):
    cache, con, provider = collector
    provider.return_value["close"] = prices

    frame, receipt = cache.frame(con, CODE, DAY)
    reopened = research.QuoteCache(cache.db, cache.root, {}, cache.probes)
    cached_frame, cached_receipt = reopened.frame(con, CODE, DAY)

    assert frame is None and cached_frame is None
    assert receipt["status"] == "daily_price_mismatch"
    assert receipt["all_prices_inside_daily_range"] is inside_range
    assert receipt["closing_difference"] == pytest.approx(closing_difference)
    assert cached_receipt == receipt
    provider.assert_called_once_with(research._open_client.return_value, CODE, DAY)


def test_zero_daily_volume_preserves_confirmed_no_trades_without_provider(collector):
    cache, con, provider = collector
    con.execute.return_value.fetchone.return_value = (10.0, 10.2, 9.8, 10.0, 0)

    frame, receipt = cache.frame(con, CODE, DAY)
    reopened = research.QuoteCache(cache.db, cache.root, {}, cache.probes)
    cached_frame, cached_receipt = reopened.frame(con, CODE, DAY)

    assert receipt["status"] == "confirmed_no_trades"
    assert receipt["records"] == []
    assert cached_receipt == receipt
    for result in (frame, cached_frame):
        assert result is not None and result.empty
        assert isinstance(result.index, pd.DatetimeIndex)
        assert list(result.columns) == ["close", "volume"]
        assert result.attrs["confirmed_no_trades"] is True
    provider.assert_not_called()
    research._open_client.assert_not_called()


def test_empty_history_stays_unknown_and_is_not_retried_after_reopening(collector):
    cache, con, provider = collector
    provider.return_value = pd.DataFrame()

    frame, receipt = cache.frame(con, CODE, DAY)
    reopened = research.QuoteCache(cache.db, cache.root, {}, cache.probes)
    cached_frame, cached_receipt = reopened.frame(con, CODE, DAY)

    assert frame is None and cached_frame is None
    assert receipt["status"] == "history_empty"
    assert receipt["records"] == []
    assert cached_receipt == receipt
    provider.assert_called_once()


def test_source_error_receipt_survives_reopening_without_retry(collector):
    cache, con, provider = collector
    provider.side_effect = TimeoutError("synthetic provider timeout")

    frame, receipt = cache.frame(con, CODE, DAY)
    reopened = research.QuoteCache(cache.db, cache.root, {}, cache.probes)
    cached_frame, cached_receipt = reopened.frame(con, CODE, DAY)

    assert frame is None and cached_frame is None
    assert receipt["status"] == "source_error"
    assert receipt["error_type"] == "TimeoutError"
    assert receipt["error"] == "synthetic provider timeout"
    assert receipt["records"] == []
    assert cached_receipt == receipt
    provider.assert_called_once()
    research._open_client.assert_called_once()
    research._close_client.assert_called_once_with(research._open_client.return_value)


def test_quote_samples_without_daily_reference_cannot_be_verified(collector):
    cache, con, provider = collector
    con.execute.return_value.fetchone.return_value = None

    frame, receipt = cache.frame(con, CODE, DAY)

    assert frame is None
    assert receipt["status"] == "daily_validation_missing"
    assert receipt["records"] == provider.return_value.to_dict("records")
    assert "daily_reference" not in receipt


def test_matching_prices_from_wrong_response_date_cannot_be_verified(collector):
    cache, con, provider = collector
    provider.return_value["datetime"] = ["2024-01-08 14:50", "2024-01-08 15:00"]

    frame, receipt = cache.frame(con, CODE, DAY)

    provider.assert_called_once_with(research._open_client.return_value, CODE, DAY)
    assert receipt["requested_date"] == DAY
    assert receipt["status"] != "verified"
    assert frame is None


def test_cached_receipt_for_wrong_requested_date_cannot_be_reused(collector):
    cache, con, provider = collector
    frame, receipt = cache.frame(con, CODE, DAY)
    assert receipt["status"] == "verified"
    assert frame is not None
    assert frame.index.strftime("%Y-%m-%d").tolist() == [DAY, DAY]

    receipt["requested_date"] = "2024-01-08"
    path = cache.root / CODE / f"{DAY}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as target:
        json.dump(receipt, target)
    reopened = research.QuoteCache(cache.db, cache.root, {}, cache.probes)

    frame, receipt = reopened.frame(con, CODE, DAY)

    provider.assert_called_once()
    assert frame is None
