from __future__ import annotations

from pathlib import Path

from src.market import MarketStore, legacy_call_tool
from src.market.domain.tape import TapeRequest
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.router import route_tape
from src.ops.application.skill_watch import payload as skill_payload


def _seed_market(store: MarketStore) -> None:
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


def test_local_theme_board_and_members_are_explicitly_derived(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_market(store)
        provider = LocalTapeProvider(store)
        board = provider.fetch(
            TapeRequest(
                lane="theme_board",
                requested_date="2026-08-07",
                limit=10,
            )
        )
        members = provider.fetch(
            TapeRequest(
                lane="theme_members",
                requested_date="2026-08-07",
                arguments={"themeName": "本地科技", "limit": 1},
            )
        )
    finally:
        store.close()

    assert board.provenance.provider_id == "local"
    assert board.provenance.degraded is True
    assert "local_industry_derived" in board.provenance.warnings
    assert board.data["rows"][0]["themeCode"] == "本地科技"
    assert board.data["rows"][0]["themeName"] == "本地科技"
    assert board.data["rows"][0]["strength_source"] == "local_industry_derived"
    assert board.data["rows"][0]["pct_chg"] > 0
    assert board.data["rows"][0]["amount"] == 2150.0
    assert board.data["rows"][0]["strength"] == 100.0

    assert members.provenance.provider_id == "local"
    assert members.data["themeName"] == "本地科技"
    assert [row["code"] for row in members.data["rows"]] == ["600001"]
    assert members.data["rows"][0]["name"] == "科技龙"
    assert members.data["rows"][0]["pct_chg"] == 10.0
    assert members.data["rows"][0]["amount"] == 1100.0


def test_local_theme_members_never_fall_back_to_unrelated_market_rows(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_market(store)
        result = LocalTapeProvider(store).fetch(
            TapeRequest(
                lane="theme_members",
                requested_date="2026-08-07",
                arguments={"themeCode": "不存在的题材", "limit": 20},
            )
        )
    finally:
        store.close()

    assert result.provenance.provider_id == "local"
    assert result.provenance.degraded is True
    assert result.data["rows"] == []
    assert "local_theme_members_not_found" in result.provenance.warnings


def test_degraded_local_theme_remains_available_for_repeated_scans(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_market(store)
        provider = LocalTapeProvider(store)
        request = TapeRequest(
            lane="theme_board",
            requested_date="2026-08-07",
            context={"market_store": store},
        )
        first = route_tape(request, providers=[provider])
        second = route_tape(request, providers=[provider])
    finally:
        store.close()

    assert first.data["rows"]
    assert second.data["rows"]
    assert second.provenance.attempts[-1].status == "degraded"


def test_legacy_theme_payload_keeps_rows_and_daily_limit_shapes(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_market(store)
        store.upsert_instruments(
            [{"code": "600004", "name": "炸板票", "industry": "本地科技"}]
        )
        store.upsert_quote_bars(
            [
                {
                    "code": "600004",
                    "date": "2026-08-06",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100,
                    "amount": 1000,
                },
                {
                    "code": "600004",
                    "date": "2026-08-07",
                    "open": 11.0,
                    "high": 11.0,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100,
                    "amount": 1050,
                },
            ]
        )
        provider = LocalTapeProvider(store)
        theme_payload = legacy_call_tool(
            "theme_stocks",
            {"tradeDate": "2026-08-07", "themeName": "本地科技", "limit": 2},
            providers=[provider],
            store=store,
        )
        ladder_payload = legacy_call_tool(
            "limit_up_filter",
            {"tradeDate": "2026-08-07", "limit": 20},
            providers=[provider],
            store=store,
        )
        broken_payload = legacy_call_tool(
            "broken_limit_up",
            {"tradeDate": "2026-08-07", "limit": 20},
            providers=[provider],
            store=store,
        )
    finally:
        store.close()

    assert theme_payload["provider_id"] == "local"
    assert theme_payload["structured"]["rows"][0]["code"] == "600001"
    assert theme_payload["structured"]["rows"][0]["pct_chg"] == 10.0

    assert ladder_payload["structured"]["highestBoard"] == 1
    assert ladder_payload["structured"]["boardSummary"] == [{"level": 1, "count": 1}]
    ladder_rows = skill_payload.rows_by_code(ladder_payload, limit=20)
    assert ladder_rows["600001"]["isLimitUp"] is True

    assert broken_payload["structured"]["rows"][0]["code"] == "600004"
    assert broken_payload["structured"]["rows"][0]["isBrokenLimitUp"] is True
    broken_rows = skill_payload.rows_by_code(broken_payload, limit=20)
    assert broken_rows["600004"]["isBrokenLimitUp"] is True
