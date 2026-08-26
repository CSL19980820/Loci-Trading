"""P2-1：theme_members 只拉成分代码，不先全市场 JOIN。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.market import MarketStore
from src.market.domain.tape import TapeRequest
from src.market.infrastructure.tape.local_provider import LocalTapeProvider, _rows_for_date


def _seed(store: MarketStore) -> None:
    store.upsert_instruments(
        [
            {"code": "600001", "name": "科技龙", "industry": "本地科技"},
            {"code": "600002", "name": "科技二号", "industry": "本地科技"},
            {"code": "600003", "name": "银行票", "industry": "银行"},
        ]
    )
    store.upsert_quote_bars(
        [
            {
                "code": code,
                "date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": amount,
            }
            for code, day, close, amount in (
                ("600001", "2026-08-06", 10.0, 1000.0),
                ("600001", "2026-08-07", 11.0, 1100.0),
                ("600002", "2026-08-06", 10.0, 1000.0),
                ("600002", "2026-08-07", 10.5, 1050.0),
                ("600003", "2026-08-06", 10.0, 1000.0),
                ("600003", "2026-08-07", 9.0, 900.0),
            )
        ]
    )


def test_theme_members_fetch_scopes_rows_by_industry(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed(store)
        provider = LocalTapeProvider(store)
        calls: list[tuple | None] = []

        real = _rows_for_date

        def spy(store_arg, day, *, codes=None):
            calls.append(tuple(codes) if codes is not None else None)
            return real(store_arg, day, codes=codes)

        with patch(
            "src.market.infrastructure.tape.local_provider._rows_for_date",
            side_effect=spy,
        ):
            members = provider.fetch(
                TapeRequest(
                    lane="theme_members",
                    requested_date="2026-08-07",
                    as_of_date="2026-08-07",
                    arguments={"themeName": "本地科技", "limit": 10},
                )
            )
    finally:
        store.close()

    assert members.data is not None
    assert {row["code"] for row in members.data["rows"]} == {"600001", "600002"}
    assert calls and calls[0] is not None
    assert set(calls[0]) == {"600001", "600002"}


def test_rows_for_date_codes_filter(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed(store)
        rows = _rows_for_date(store, "2026-08-07", codes=["600001"])
    finally:
        store.close()
    assert len(rows) == 1
    assert rows[0]["code"] == "600001"
