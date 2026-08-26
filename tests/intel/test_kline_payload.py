"""悟道 kline 返回体解析。"""
from __future__ import annotations

import json

from src.intel import kline_payload_frames, kline_payload_to_frame


def test_parses_flat_rows_and_sorts_by_date() -> None:
    payload = {
        "structured": {
            "rows": [
                {"date": "2025-01-03", "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 200},
                {"date": "2025-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5, "vol": 100},
            ]
        }
    }
    frame = kline_payload_to_frame(payload)
    assert list(frame["date"]) == ["2025-01-02", "2025-01-03"]
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert frame.iloc[0]["volume"] == 100.0


def test_parses_batch_items_and_text_fallback() -> None:
    payload = {
        "text": json.dumps(
            {
                "batch": {
                    "items": [
                        {
                            "rows": [
                                {
                                    "trade_date": "2025-01-02T00:00:00",
                                    "open": 8,
                                    "high": 9.5,
                                    "low": 7.5,
                                    "close": 9,
                                    "turnover": 5,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    }
    frame = kline_payload_to_frame(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["date"] == "2025-01-02"
    assert frame.iloc[0]["amount"] == 5.0


def test_unparsable_or_empty_payload_gives_empty_frame() -> None:
    assert kline_payload_to_frame({"text": "not json"}).empty
    assert kline_payload_to_frame({"structured": {"rows": []}}).empty
    assert kline_payload_to_frame({"structured": {"rows": [{"close": 1}]}}).empty


def test_rows_missing_prices_are_dropped_not_zero_filled() -> None:
    """字段缺失/改名时补 0 等于凭空造出一根 0 元 K 线，必须整行丢弃。"""
    payload = {
        "structured": {
            "rows": [
                {"date": "2025-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5},
                {"date": "2025-01-03", "close": 2.5, "volume": 200},
                {"date": "2025-01-06", "open": 0, "high": 0, "low": 0, "close": 0},
                {"date": "2025-01-07", "open": "--", "high": 2, "low": 1, "close": 1.8},
            ]
        }
    }
    frame = kline_payload_to_frame(payload)

    assert list(frame["date"]) == ["2025-01-02"]
    assert not (frame[["open", "high", "low", "close"]] <= 0).any().any()


def test_batch_frames_drop_codes_left_without_any_valid_bar() -> None:
    payload = {
        "structured": {
            "batch": {
                "items": [
                    {
                        "code": "600519",
                        "rows": [
                            {"date": "2025-01-02", "open": 1, "high": 2, "low": 1, "close": 1.5}
                        ],
                    },
                    {"code": "000001", "rows": [{"date": "2025-01-02", "close": 9}]},
                ]
            }
        }
    }

    assert list(kline_payload_frames(payload)) == ["600519"]
