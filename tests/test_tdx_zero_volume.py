"""TDX zero-value decoding must not create fictitious trading activity."""
from src.market.infrastructure.tdx_daily import _rows_to_frame


def test_tdx_wire_zero_sentinel_is_normalized_before_unit_conversion():
    zero = 2.0 ** -127
    rows = [
        {"datetime": "2026-10-26", "open": 0.58, "high": 0.58, "low": 0.58,
         "close": 0.58, "vol": zero, "amount": zero},
        {"datetime": "2026-10-27", "open": 10, "high": 11, "low": 9,
         "close": 10, "vol": 123.0, "amount": 123456.0},
    ]

    result = _rows_to_frame(rows)

    assert result.loc[0, "volume"] == 0
    assert result.loc[0, "amount"] == 0
    assert result.loc[1, "volume"] == 12300
    assert result.loc[1, "amount"] == 123456
