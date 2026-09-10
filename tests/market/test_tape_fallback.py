from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.market import MarketStore, legacy_call_tool
from src.market.domain.tape import TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.market.infrastructure.tape.cache import write_tape_cache
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.router import route_tape
from src.market.infrastructure.tape.wudao_provider import WudaoTapeProvider


class _FakeTapeProvider:
    provider_id = "local_fake"
    lanes = TAPE_LANES

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, request: TapeRequest) -> TapeResult:
        self.calls.append(request.lane)
        return TapeResult(
            data={
                "actualTradeDate": request.requested_date,
                "dateStatus": "exact",
                "rows": [],
                "lane": request.lane,
            }
        )


def test_legacy_bridge_maps_tools_to_one_tape_lane() -> None:
    provider = _FakeTapeProvider()

    for tool, lane in {
        "short_term_emotion": "market_emotion",
        "limit_up_filter": "limit_up_pool",
        "limit_up_ladder": "limit_up_pool",
        "broken_limit_up": "broken_limit_up",
        "theme_intraday_capital": "theme_board",
        "theme_stocks": "theme_members",
        "auction_opening_snapshot": "auction_snapshot",
        "sector_analysis": "sector_analysis",
    }.items():
        payload = legacy_call_tool(
            tool,
            {"tradeDate": "2026-08-07"},
            providers=[provider],
        )
        assert payload["provider_id"] == "local_fake"
        assert payload["provenance"]["lane"] == lane
        assert payload["structured"]["lane"] == lane

    assert provider.calls == [
        "market_emotion",
        "limit_up_pool",
        "limit_up_pool",
        "broken_limit_up",
        "theme_board",
        "theme_members",
        "auction_snapshot",
        "sector_analysis",
    ]


def test_router_all_providers_unavailable_is_degraded() -> None:
    result = route_tape(
        TapeRequest(lane="market_emotion", requested_date="2026-08-07"),
        providers=[],
    )

    assert result.data is None
    assert result.provenance.degraded is True
    assert result.provenance.provider_id is None
    assert "no_provider_available" in result.provenance.warnings


def test_cache_provider_can_replace_unavailable_wudao(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        request = TapeRequest(
            lane="market_emotion",
            tool="short_term_emotion",
            requested_date="2026-08-07",
            arguments={"tradeDate": "2026-08-07"},
            context={"market_store": store},
        )
        write_tape_cache(
            store,
            request,
            {"actualTradeDate": "2026-08-07", "promotion_rate": 0.4},
            server="wudao",
        )
        result = CachedTapeProvider().fetch(request)
    finally:
        store.close()

    assert result.data["promotion_rate"] == 0.4
    assert result.provenance.provider_id == "cache"
    assert result.provenance.from_cache is True


def test_cache_provider_requires_same_day_fresh_payload_and_cache_enabled(
    tmp_path: Path,
) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        request = TapeRequest(
            lane="market_emotion",
            tool="short_term_emotion",
            requested_date="2026-08-07",
            arguments={"tradeDate": "2026-08-07"},
            context={"market_store": store},
        )
        write_tape_cache(
            store,
            request,
            {"actualTradeDate": "2026-08-07", "promotion_rate": 0.4},
            server="wudao",
        )
        provider = CachedTapeProvider()
        assert provider.fetch(request).data["promotion_rate"] == 0.4

        store.conn.execute(
            "UPDATE intel_snapshots SET fetched_at = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(),),
        )
        store.conn.commit()
        assert provider.fetch(request).data is None
        assert (
            provider.fetch(
                TapeRequest(
                    lane=request.lane,
                    tool=request.tool,
                    requested_date="2026-08-08",
                    arguments={"tradeDate": "2026-08-08"},
                    context={"market_store": store},
                )
            ).data
            is None
        )
        assert provider.fetch(
            TapeRequest(
                lane=request.lane,
                tool=request.tool,
                requested_date=request.requested_date,
                arguments=request.arguments,
                context=request.context,
                cache=False,
            )
        ).data is None
    finally:
        store.close()


def test_wudao_blank_payload_is_degraded_and_yields_to_local(tmp_path: Path) -> None:
    """悟道回了个没有结构化正文的「成功」响应：不能算健康结果吃掉本地兜底。"""
    blank = {
        "tool": "short_term_emotion",
        "server": "wudao",
        "text": "服务器开小差，请稍后重试",
        "is_error": False,
        "structured": None,
        "cached": False,
    }
    request = TapeRequest(lane="market_emotion", requested_date="2026-08-07")
    fallback = _FakeTapeProvider()

    with (
        patch("src.intel.wudao_availability", return_value={"available": True, "reason": ""}),
        patch("src.intel.call_mcp_tool", return_value=blank) as remote,
    ):
        direct = WudaoTapeProvider().fetch(request)
        routed = route_tape(
            request,
            providers=[WudaoTapeProvider(), fallback],
            failure_cooldown_seconds=0,
        )

    assert remote.called
    assert direct.data is None
    assert direct.provenance.degraded is True
    assert routed.provenance.provider_id == "local_fake"
    assert [attempt.status for attempt in routed.provenance.attempts] == [
        "degraded",
        "succeeded",
    ]


def test_cache_hit_carries_the_instant_it_was_fetched(tmp_path: Path) -> None:
    """`as_of_date` 只到「日」；盘中必须知道这份梯队是几点几分抓的。"""
    store = MarketStore(tmp_path / "market.db")
    try:
        request = TapeRequest(
            lane="limit_up_pool",
            tool="limit_up_filter",
            requested_date="2026-08-07",
            arguments={"tradeDate": "2026-08-07"},
            context={"market_store": store},
        )
        write_tape_cache(
            store,
            request,
            {"actualTradeDate": "2026-08-07", "rows": [{"code": "600001"}]},
            server="wudao",
        )
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(
            timespec="seconds"
        )
        store.conn.execute("UPDATE intel_snapshots SET fetched_at = ?", (stamp,))
        store.conn.commit()

        result = CachedTapeProvider().fetch(request)
        bridged = legacy_call_tool(
            "limit_up_filter",
            {"tradeDate": "2026-08-07"},
            providers=[CachedTapeProvider()],
            store=store,
        )
    finally:
        store.close()

    assert result.provenance.from_cache is True
    assert result.provenance.fetched_at == stamp
    assert bridged["provenance"]["fetched_at"] == stamp


def test_local_provider_derives_daily_emotion_and_ladder(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        store.upsert_instruments(
            [
                {"code": "600001", "name": "测试龙"},
                {"code": "600002", "name": "测试跌停"},
            ]
        )
        store.upsert_quote_bars(
            [
                {
                    "code": "600001",
                    "date": "2026-08-05",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                    "amount": 1000,
                },
                {
                    "code": "600001",
                    "date": "2026-08-06",
                    "open": 11,
                    "high": 11,
                    "low": 11,
                    "close": 11,
                    "volume": 100,
                    "amount": 1100,
                },
                {
                    "code": "600001",
                    "date": "2026-08-07",
                    "open": 12.1,
                    "high": 12.1,
                    "low": 12.1,
                    "close": 12.1,
                    "volume": 100,
                    "amount": 1210,
                },
                {
                    "code": "600002",
                    "date": "2026-08-06",
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                    "amount": 1000,
                },
                {
                    "code": "600002",
                    "date": "2026-08-07",
                    "open": 9.0,
                    "high": 9.0,
                    "low": 9.0,
                    "close": 9.0,
                    "volume": 100,
                    "amount": 900,
                },
            ]
        )
        provider = LocalTapeProvider(store)
        emotion = provider.fetch(
            TapeRequest(lane="market_emotion", requested_date="2026-08-07")
        )
        ladder = provider.fetch(
            TapeRequest(lane="limit_up_pool", requested_date="2026-08-07")
        )
    finally:
        store.close()

    assert emotion.provenance.provider_id == "local"
    assert emotion.provenance.degraded is False
    assert emotion.data["breadth"] == 0.5
    assert emotion.data["limit_up_count"] == 1
    assert emotion.data["limit_down_count"] == 1
    assert ladder.data["highestBoard"] == 2
