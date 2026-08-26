"""tape 层的「诚实度」回归：失败与过期不许伪装成健康的当日结果。

这一组覆盖的都是「读起来像有数据、其实没有」的坑：正文被截断、拿到的是
T-1、把接近涨停算成涨停。任何一条退化都会让盘中闸门与复盘悄悄读到假象。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.market import MarketStore
from src.market.domain.tape import TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.router import route_tape
from src.market.infrastructure.tape.wudao_provider import (
    TRUNCATED_WARNING,
    UNPARSED_ERROR,
    WudaoTapeProvider,
    wudao_tool_arguments,
)


class _LocalStub:
    provider_id = "local_fake"
    lanes = TAPE_LANES

    def fetch(self, request: TapeRequest) -> TapeResult:
        return TapeResult(
            data={
                "actualTradeDate": request.requested_date,
                "dateStatus": "exact",
                "rows": [],
                "lane": request.lane,
            }
        )


def _wudao_result(request: TapeRequest, payload: dict[str, Any]) -> TapeResult:
    with (
        patch("src.intel.wudao_availability", return_value={"available": True, "reason": ""}),
        patch("src.intel.call_mcp_tool", return_value=payload),
    ):
        return WudaoTapeProvider().fetch(request)


def _routed(request: TapeRequest, payload: dict[str, Any]) -> TapeResult:
    with (
        patch("src.intel.wudao_availability", return_value={"available": True, "reason": ""}),
        patch("src.intel.call_mcp_tool", return_value=payload),
    ):
        return route_tape(
            request,
            providers=[WudaoTapeProvider(), _LocalStub()],
            failure_cooldown_seconds=0,
        )


def test_truncated_payload_names_the_truncation_and_yields_to_local() -> None:
    """正文超限被截断 → JSON 解析不出结构化段。这不是「今天没涨停」。"""
    request = TapeRequest(lane="market_emotion", requested_date="2026-08-07")
    payload = {
        "tool": "short_term_emotion",
        "server": "wudao",
        "text": '{"limitUpCount": 31, "temperat',
        "is_error": False,
        "structured": None,
        "truncated": True,
    }

    direct = _wudao_result(request, payload)
    routed = _routed(request, payload)

    assert direct.data is None
    assert direct.provenance.degraded is True
    assert direct.error == f"{UNPARSED_ERROR}:{TRUNCATED_WARNING}"
    assert routed.provenance.provider_id == "local_fake"


def test_stale_trade_date_is_degraded_so_the_gate_can_still_close() -> None:
    """悟道给的是 T-1：可以用，但必须标降级，否则闸门 fail-closed 会失效。"""
    request = TapeRequest(lane="market_emotion", requested_date="2026-08-07")
    payload = {
        "tool": "short_term_emotion",
        "server": "wudao",
        "is_error": False,
        "structured": {
            "actualTradeDate": "2026-08-06",
            "dateStatus": "mismatch",
            "limitUpCount": 31,
        },
    }

    direct = _wudao_result(request, payload)

    assert direct.data is not None
    assert direct.provenance.stale is True
    assert direct.provenance.degraded is True
    assert "wudao:stale_trade_date" in direct.provenance.warnings


def _seed_two_days(store: MarketStore, *, close_today: float, high_today: float) -> None:
    store.upsert_instruments([{"code": "600001", "name": "测试票"}])
    store.upsert_quote_bars(
        [
            {
                "code": "600001",
                "date": "2026-08-06",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 100,
                "amount": 1000,
            },
            {
                "code": "600001",
                "date": "2026-08-07",
                "open": 10.0,
                "high": high_today,
                "low": 10.0,
                "close": close_today,
                "volume": 100,
                "amount": 1000,
            },
        ]
    )


def _limit_up_count(store: MarketStore) -> Any:
    result = LocalTapeProvider(store).fetch(
        TapeRequest(lane="market_emotion", requested_date="2026-08-07")
    )
    return result.data["limit_up_count"]


def test_near_limit_close_is_not_counted_as_a_board(tmp_path: Path) -> None:
    """昨收 10.00 收 10.95（+9.5%）不是涨停。

    容差按「涨停价的百分比」算时，10.95 会落进 11.00×0.995 的窗口里被记成封板，
    涨停家数、最高板、炸板率分母会一起虚增。容差只该吸收分位取整噪声。
    """
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_two_days(store, close_today=10.95, high_today=10.95)
        assert _limit_up_count(store) == 0
    finally:
        store.close()


def test_real_board_is_still_counted(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        _seed_two_days(store, close_today=11.0, high_today=11.0)
        assert _limit_up_count(store) == 1
    finally:
        store.close()


def test_cache_reads_the_key_the_intel_writer_actually_used(tmp_path: Path) -> None:
    """悟道 lane 写缓存时会补 format/detailLevel 并过裁剪。

    读侧若只按请求原参数算 key，两边永远不相等——「悟道挂了还有缓存兜底」
    就成了空话。
    """
    from src.intel import clamp_mcp_arguments
    from src.intel.infrastructure.intel_cache import write_cached_snapshot

    store = MarketStore(tmp_path / "market.db")
    try:
        request = TapeRequest(
            lane="market_emotion",
            tool="short_term_emotion",
            requested_date="2026-08-07",
            arguments={"tradeDate": "2026-08-07"},
            context={"market_store": store},
        )
        write_cached_snapshot(
            store,
            trade_date=request.requested_date,
            tool="short_term_emotion",
            arguments=clamp_mcp_arguments(
                wudao_tool_arguments(request, "short_term_emotion")
            ),
            server="wudao",
            payload={"actualTradeDate": "2026-08-07", "limit_up_count": 31},
        )

        result = CachedTapeProvider().fetch(request)
    finally:
        store.close()

    assert result.data is not None
    assert result.data["limit_up_count"] == 31
    assert result.provenance.from_cache is True


def test_clamped_arguments_are_reported_not_silently_truncated() -> None:
    """静默截断会让「只扫了前 50 只」被读成「全市场都没有」。"""
    from src.intel.application.arg_clamp import clamp_mcp_arguments_with_notes

    clamped, notes = clamp_mcp_arguments_with_notes(
        {"codes": [f"{i:06d}" for i in range(120)], "limit": 999}
    )

    assert len(clamped["codes"]) < 120
    assert any(note.startswith("codes:") for note in notes)
    assert any(note.startswith("limit:") for note in notes)
