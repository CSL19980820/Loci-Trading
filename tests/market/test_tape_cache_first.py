"""tape provider 顺序：缓存排在悟道前面，且不许因此拿到更陈的数据。

调换顺序的收益是真金白银（两条在产链路没注入 store，`call_mcp_tool(cache=True)`
在那里是空转，每轮盯盘都真调真扣）；风险是「盘中兑现陈数据」。这个文件钉的是
风险那一半——顺序改了，时效口径一格都不许松。

**不发任何真实 MCP 调用**：悟道 provider 全部由假实现顶替。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.market import MarketStore
from src.market.domain.tape import TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.tape.base import provider_id_of
from src.market.infrastructure.tape.cache import write_tape_cache
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.registry import all_providers, reset_registry
from src.market.infrastructure.tape.router import clear_provider_cooldown, route_tape

TRADE_DATE = "2026-08-07"
LANE = "market_emotion"
TOOL = "short_term_emotion"


class _CountingWudao:
    """假悟道：只记「被问过几次」。真悟道每被问一次就是一次配额。"""

    provider_id = "wudao"
    label = "悟道(假)"

    def __init__(self) -> None:
        self.fetches = 0

    def supports(self, _lane: str) -> bool:
        return True

    def is_available(self, _request: TapeRequest) -> tuple[bool, str]:
        return True, ""

    def fetch(self, request: TapeRequest) -> TapeResult:
        self.fetches += 1
        return TapeResult(
            data={"actualTradeDate": TRADE_DATE, "source": "wudao"},
            provenance=TapeProvenance(
                provider_id=self.provider_id,
                lane=request.lane,
                requested_date=request.requested_date,
            ),
        )


def _request(store: MarketStore, **kwargs: Any) -> TapeRequest:
    fields: dict[str, Any] = {
        "lane": LANE,
        "tool": TOOL,
        "requested_date": TRADE_DATE,
        "arguments": {"tradeDate": TRADE_DATE},
        "context": {"market_store": store},
    }
    fields.update(kwargs)
    return TapeRequest(**fields)


def _seed(store: MarketStore, payload: dict[str, Any], *, age_minutes: float = 0.0) -> None:
    write_tape_cache(store, _request(store), payload, server="wudao")
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat(
        timespec="seconds"
    )
    store.conn.execute("UPDATE intel_snapshots SET fetched_at = ?", (stamp,))
    store.conn.commit()


def _settled(value: bool):
    """钉住收盘态：时效结论不该跟着测试机的钟点变。"""
    return patch("src.intel.application.fetch._settled_at", lambda *_a, **_k: value)


def test_default_provider_order_puts_cache_before_wudao() -> None:
    """缓存必须排在悟道前面，否则健康日永远走不到它（理由见 registry.py）。"""
    reset_registry(None)
    try:
        order = [provider_id_of(item) for item in all_providers()]
    finally:
        reset_registry(None)
    assert order == ["cache", "wudao", "local"], order


def test_a_cache_hit_means_wudao_is_never_asked(tmp_path: Path) -> None:
    """命中即止：省下的正是一次真调 + 一次 skill 池配额。"""
    clear_provider_cooldown()
    store = MarketStore(tmp_path / "market.db")
    wudao = _CountingWudao()
    try:
        _seed(store, {"actualTradeDate": TRADE_DATE, "promotion_rate": 0.4})
        with _settled(False):
            hit = route_tape(
                _request(store),
                providers=[CachedTapeProvider(), wudao],
                failure_cooldown_seconds=0,
            )
    finally:
        store.close()

    assert hit.provenance.provider_id == "cache"
    assert hit.provenance.from_cache is True
    assert hit.data["promotion_rate"] == 0.4
    assert wudao.fetches == 0, "缓存命中还去问悟道 = 白扣一次配额"


def test_a_cache_miss_falls_straight_through_to_wudao(tmp_path: Path) -> None:
    """未命中不许把 lane 卡住：照旧落到悟道，行为与改顺序前一致。"""
    clear_provider_cooldown()
    store = MarketStore(tmp_path / "market.db")
    wudao = _CountingWudao()
    try:
        with _settled(False):
            result = route_tape(
                _request(store),
                providers=[CachedTapeProvider(), wudao],
                failure_cooldown_seconds=0,
            )
    finally:
        store.close()

    assert result.provenance.provider_id == "wudao"
    assert wudao.fetches == 1


def test_intraday_ttl_is_clamped_even_when_the_caller_asks_for_two_hours(
    tmp_path: Path,
) -> None:
    """**这条是「缓存优先」的安全底座**。

    悟道那条路读同一张表时会把盘中 TTL 压到 10 分钟（`_effective_cache_max_age`），
    缓存 provider 原来却是 `request.cache_max_age_minutes or 5` 照单全收。把它排到
    前面而不修这一条，盘后档的 120 分钟 TTL 就会变成「盘中兑现两小时前的快照」。
    现在两边共用同一个函数：盘中钳到 10 分钟，收盘后才认长 TTL。
    """
    store = MarketStore(tmp_path / "market.db")
    provider = CachedTapeProvider()
    try:
        _seed(
            store,
            {"actualTradeDate": TRADE_DATE, "promotion_rate": 0.4},
            age_minutes=30.0,
        )
        request = _request(store, cache_max_age_minutes=120)
        with _settled(False):
            intraday = provider.fetch(request)
        with _settled(True):
            after_close = provider.fetch(request)
    finally:
        store.close()

    assert intraday.data is None, "盘中不许兑现 30 分钟前的快照，哪怕调用方要 120 分钟"
    assert after_close.data is not None, "收盘定稿后长 TTL 才生效"


def test_after_close_an_intraday_snapshot_is_not_served_as_settled(tmp_path: Path) -> None:
    """缓存 key 只锁到「日」：10:03 的半截 bar 和 15:40 的收盘 bar 落在同一行。

    收盘后兑现盘中那份，等于把半截数据当权威收盘价发下去。判定与 `call_mcp_tool`
    共用同一个 `_cache_matches_session`，不在 tape 层另写一份。
    """
    store = MarketStore(tmp_path / "market.db")
    provider = CachedTapeProvider()
    live_payload = {
        "actualTradeDate": TRADE_DATE,
        "promotion_rate": 0.4,
        "session_state": "live",
    }
    settled_payload = {
        "actualTradeDate": TRADE_DATE,
        "promotion_rate": 0.4,
        "session_state": "settled",
    }
    try:
        _seed(store, live_payload)
        with _settled(True):
            live_after_close = provider.fetch(_request(store))
        with _settled(False):
            live_intraday = provider.fetch(_request(store))
        _seed(store, settled_payload)
        with _settled(True):
            settled_after_close = provider.fetch(_request(store))
    finally:
        store.close()

    assert live_after_close.data is None, "收盘后不该兑现盘中抓的半截数据"
    assert live_intraday.data is not None, "盘中读盘中快照没问题"
    assert settled_after_close.data is not None, "收盘定稿那份照常兑现"


def test_cache_never_serves_another_trade_date(tmp_path: Path) -> None:
    """「缓存优先会不会盘中拿到昨天的数据」——结构上就不可能。

    行的主键含 trade_date，读侧按 requested_date 取，还会再比一次载荷自报的
    actualTradeDate。这条把它钉死，免得以后有人放宽查询条件。
    """
    store = MarketStore(tmp_path / "market.db")
    provider = CachedTapeProvider()
    try:
        _seed(store, {"actualTradeDate": TRADE_DATE, "promotion_rate": 0.4})
        tomorrow_request = _request(
            store,
            requested_date="2026-08-08",
            arguments={"tradeDate": "2026-08-08"},
        )
        dateless_request = _request(store, requested_date="", arguments=dict())
        with _settled(False):
            tomorrow = provider.fetch(tomorrow_request)
            available, reason = provider.is_available(dateless_request)
    finally:
        store.close()

    assert tomorrow.data is None
    assert available is False
    assert reason == "cache_requires_trade_date"


def test_a_failed_payload_in_the_cache_is_not_served_as_a_fact(tmp_path: Path) -> None:
    """老库里可能留着直接写进正缓存的失败行：不能把一条错误正文当盘口事实。"""
    store = MarketStore(tmp_path / "market.db")
    provider = CachedTapeProvider()
    failed_payload = {
        "actualTradeDate": TRADE_DATE,
        "is_error": True,
        "text": "今日无数据",
    }
    try:
        _seed(store, failed_payload)
        with _settled(False):
            result = provider.fetch(_request(store))
    finally:
        store.close()

    assert result.data is None
    assert "tape_cache_miss" in result.provenance.warnings
