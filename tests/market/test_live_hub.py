"""LiveHub：单采集器 / 多订阅者广播、周期预算、失败退避、自动停表。

外部 HTTP 一律注入假实现（``resolve`` / ``fetch_quotes``），这里不碰网络。
"""
from __future__ import annotations

import threading
import time

import pytest

from src.market.application.live_hub import (
    LiveHub,
    get_live_hub,
    reset_live_hub,
)
from src.market.application.watchlist import Resolution

LIVE_SESSION = {"live_allowed": True, "live_reason": "live_window", "is_trading_day": True}
CLOSED_SESSION = {"live_allowed": False, "live_reason": "after_close", "is_trading_day": True}


class FakeUpstream:
    """记账用的假上游：数清楚到底打了几次「外部请求」。"""

    def __init__(self, *, kind: str = "static", rows: int = 3, boom: bool = False) -> None:
        self.kind = kind
        self.rows = rows
        self.boom = boom
        self.resolves = 0
        self.fetches = 0
        self.lock = threading.Lock()

    def _quotes(self, codes):
        return [
            {"code": code, "name": f"票{code}", "price": 10.0 + i, "prev_close": 10.0}
            for i, code in enumerate(codes)
        ]

    def resolve(self, preset, codes=None, *, top_n=50):
        with self.lock:
            self.resolves += 1
        picked = list(codes or [])[:top_n] or [f"{600000 + i:06d}" for i in range(self.rows)]
        rows = self._quotes(picked) if self.kind == "ranked" else []
        return Resolution(
            preset=preset,
            kind=self.kind,
            codes=picked,
            source="fake_ranked" if self.kind == "ranked" else "fake_static",
            instrument_types={code: "STOCK" for code in picked},
            rows=rows,
        )

    def fetch(self, codes, instrument_types=None):
        with self.lock:
            self.fetches += 1
        if self.boom:
            raise RuntimeError("上游 403")
        return self._quotes(list(codes))


def make_hub(upstream: FakeUpstream, **kwargs) -> LiveHub:
    options = {
        "resolve": upstream.resolve,
        "fetch_quotes": upstream.fetch,
        "session_provider": lambda: dict(LIVE_SESSION),
        "phase_provider": lambda: "morning",
        "autostart": False,
    }
    options.update(kwargs)
    return LiveHub(**options)


@pytest.fixture(autouse=True)
def _drop_singleton():
    reset_live_hub()
    yield
    reset_live_hub()


def test_one_collector_feeds_many_subscribers() -> None:
    """**本任务的核心不变量**：N 个订阅者 = 1 条 feed = 1 次上游取数。"""
    upstream = FakeUpstream()
    hub = make_hub(upstream)
    subs = [hub.subscribe("index") for _ in range(5)]
    try:
        assert hub.tick_once() == 1  # 5 个订阅者只折叠成一条 feed
        assert upstream.fetches == 1
        assert upstream.resolves == 1
        snapshots = [sub.wait(0.0) for sub in subs]
        assert all(snap is not None for snap in snapshots)
        assert {snap.seq for snap in snapshots} == {1}
        assert {len(snap.rows) for snap in snapshots} == {3}
    finally:
        for sub in subs:
            sub.close()


def test_seq_is_monotonic_and_wait_blocks_until_a_new_frame() -> None:
    upstream = FakeUpstream()
    hub = make_hub(upstream)
    with hub.subscribe("index") as sub:
        hub.tick_once()
        first = sub.wait(0.0)
        assert first is not None and first.seq == 1
        # 没有新帧：不重放旧的，直接超时。
        assert sub.wait(0.05) is None
        hub.tick_once()
        second = sub.wait(0.0)
        assert second is not None and second.seq == 2
    assert upstream.fetches == 2


def test_ranked_resolution_rows_avoid_a_second_upstream_hit() -> None:
    upstream = FakeUpstream(kind="ranked")
    hub = make_hub(upstream)
    with hub.subscribe("gainers", top_n=3) as sub:
        hub.tick_once()
        snapshot = sub.wait(0.0)
    assert snapshot is not None
    assert snapshot.source == "fake_ranked"
    assert upstream.resolves == 1
    # 截面表本身就是报价：一次 spot_batch 都不许多打。
    assert upstream.fetches == 0


def test_upstream_failure_is_counted_and_never_kills_the_loop() -> None:
    upstream = FakeUpstream(boom=True)
    hub = make_hub(upstream)
    with hub.subscribe("index") as sub:
        hub.tick_once()
        hub.tick_once()
        stats = hub.stats()
        feed = stats["feeds"][0]
        assert feed["errors"] == 2
        assert feed["last_error"].startswith("RuntimeError")
        assert stats["errors"] == 2
        assert sub.wait(0.0) is None  # 失败不发帧，也不发假数据
        # 退避是指数的，但有上限，不会无限拉长。
        upstream.boom = False
        hub.tick_once()
        recovered = sub.wait(0.0)
        assert recovered is not None and recovered.seq == 1
        assert hub.stats()["feeds"][0]["errors"] == 2


@pytest.mark.parametrize(
    "session, phase, preset, expected",
    [
        (LIVE_SESSION, "morning", "index", 3.0),
        (LIVE_SESSION, "pre_market", "index", 3.0),
        (LIVE_SESSION, "afternoon", "gainers", 6.0),
        # 午休：闸门（in_live_clock 到 15:00）还开着，靠相位把 3s 压回 60s。
        (LIVE_SESSION, "noon_break", "index", 60.0),
        (LIVE_SESSION, "closed", "index", 60.0),
        (CLOSED_SESSION, "morning", "index", 60.0),
    ],
)
def test_period_budget(session, phase, preset, expected) -> None:
    """3s 逐票 / 6s 全市场截面 / 60s 非交易时段——闸门与时钟必须同时点头。"""
    upstream = FakeUpstream(kind="ranked" if preset == "gainers" else "static")
    hub = make_hub(
        upstream,
        session_provider=lambda: dict(session),
        phase_provider=lambda: phase,
        codes_period=3.0,
        cross_period=6.0,
        idle_period=60.0,
    )
    with hub.subscribe(preset):
        hub.tick_once()
        assert hub.stats()["feeds"][0]["period_seconds"] == expected


def test_background_thread_starts_on_demand_and_stops_when_idle() -> None:
    upstream = FakeUpstream()
    hub = make_hub(upstream, autostart=True, codes_period=0.01)
    subs = [hub.subscribe("index") for _ in range(4)]
    try:
        received = [sub.wait(5.0) for sub in subs]
        assert all(snap is not None for snap in received)
        stats = hub.stats()
        assert stats["running"] is True
        assert stats["feed_count"] == 1
        assert stats["subscribers"] == 4
        # 一个 tick 一次取数，跟订阅者数量无关。
        assert upstream.fetches == stats["feeds"][0]["ticks"]
    finally:
        for sub in subs:
            sub.close()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and hub.stats()["running"]:
        time.sleep(0.02)
    assert hub.stats()["running"] is False  # 订阅者归零 → 自动停表
    assert hub.stats()["feed_count"] == 0


def test_latest_exposes_the_shared_snapshot_without_subscribing() -> None:
    upstream = FakeUpstream()
    hub = make_hub(upstream)
    assert hub.latest("index") is None
    with hub.subscribe("index"):
        hub.tick_once()
        snapshot = hub.latest("index")
        assert snapshot is not None and snapshot.seq == 1
        assert hub.latest("gainers") is None
    # 退订后 feed 摘除，latest 归空。
    assert hub.latest("index") is None


def test_explicit_codes_get_their_own_feed() -> None:
    upstream = FakeUpstream()
    hub = make_hub(upstream)
    with hub.subscribe("watchlist", ["600000"]), hub.subscribe("watchlist", ["000001"]):
        assert hub.tick_once() == 2
        assert upstream.fetches == 2
    # 同一批代码（顺序不同）必须落到同一条 feed。
    with hub.subscribe("watchlist", ["600000", "000001"]) as a, hub.subscribe(
        "watchlist", ["000001", "600000"]
    ) as b:
        assert a.key == b.key
        assert hub.tick_once() == 1


def test_stats_reports_the_budget_and_singleton_is_stable() -> None:
    hub = get_live_hub()
    assert get_live_hub() is hub
    budget = hub.stats()["budget"]
    assert budget["codes_seconds"] == 3.0
    assert budget["cross_section_seconds"] == 6.0
    assert budget["idle_seconds"] == 60.0
    reset_live_hub()
    assert get_live_hub() is not hub


class FakeEngine:
    """信号引擎替身：stats/evaluate 两个方法就够 stream_router 用。"""

    def evaluate(self, rows, *, now=None):
        return [{"code": row["code"], "rule": "fake", "provisional": True} for row in rows]

    def stats(self):
        return {"rules": [], "adjust": "none"}


def build_stream_app(hub: LiveHub):
    from fastapi import FastAPI
    from src.market.api.stream_router import build_market_stream_router

    app = FastAPI()
    app.include_router(
        build_market_stream_router(
            write_dependency=lambda: None,
            hub_factory=lambda: hub,
            engine_factory=FakeEngine,
        )
    )
    return app


def _events(text: str) -> list[tuple[str, dict]]:
    """SSE 文本 → [(事件名, 载荷)]。注释行（`: xxx`）忽略。"""
    import json

    out: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name and data:
            out.append((name, json.loads(data)))
    return out


def test_sse_says_hello_before_any_quote_frame() -> None:
    """**连上就得说清「现在几点、数据源好不好」**。

    上游挂掉时第一帧永远不来，而 `: keepalive` 是注释、前端看不见——大屏于是
    一边显示「已连接」，一边把早上的数字冻到收盘。hello 就是为这种时候存在的。
    """
    from fastapi.testclient import TestClient

    upstream = FakeUpstream()
    hub = make_hub(upstream, autostart=True, codes_period=0.05)
    try:
        with TestClient(build_stream_app(hub)) as client:
            response = client.get("/api/market/stream/quotes?preset=index&events=1")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response.text)
        assert events[0][0] == "hello"
        hello = events[0][1]
        assert hello["preset"] == "index"
        assert hello["session"]["phase"] == "morning"
        assert hello["session"]["live"] is True
        assert hello["source_error"] == ""
    finally:
        hub.stop()


def test_sse_first_frame_is_an_event_snapshot() -> None:
    """``curl -N .../api/market/stream/quotes?preset=index`` 的首帧形状。"""
    from fastapi.testclient import TestClient

    upstream = FakeUpstream()
    hub = make_hub(upstream, autostart=True, codes_period=0.05)
    try:
        with TestClient(build_stream_app(hub)) as client:
            response = client.get("/api/market/stream/quotes?preset=index&events=1")
        assert "id: 1" in response.text
        name, payload = _events(response.text)[1]
        assert name == "snapshot"
        assert payload["seq"] == 1
        assert payload["preset"] == "index"
        assert payload["count"] == len(payload["rows"]) == 3
        assert payload["session"]["live_allowed"] is True
        # 契约的另一半：前端只认 phase / live 这两个键（sessionCopy.PHASE_LABELS）。
        assert payload["session"]["phase"] == "morning"
        assert payload["session"]["live"] is True
        assert payload["as_of"]
    finally:
        hub.stop()


def test_sse_signals_frame_is_marked_provisional() -> None:
    from fastapi.testclient import TestClient

    upstream = FakeUpstream()
    hub = make_hub(upstream, autostart=True, codes_period=0.05)
    try:
        with TestClient(build_stream_app(hub)) as client:
            response = client.get("/api/market/stream/signals?preset=index&events=1")
        name, payload = _events(response.text)[1]
        assert name == "signals"
        assert payload["provisional"] is True
        assert payload["count"] == 3
    finally:
        hub.stop()


def test_stats_endpoint_is_plain_json_and_unknown_preset_is_422() -> None:
    from fastapi.testclient import TestClient

    upstream = FakeUpstream()
    hub = make_hub(upstream)
    with TestClient(build_stream_app(hub)) as client:
        stats = client.get("/api/market/stream/stats")
        assert stats.status_code == 200
        body = stats.json()
        assert body["budget"]["codes_seconds"] == 3.0
        assert body["signals"]["adjust"] == "none"
        assert "index" in body["presets"]
        assert client.get("/api/market/stream/quotes?preset=moon").status_code == 422


def test_snapshot_session_carries_phase_and_live_for_the_board() -> None:
    """**契约回归钉**：SSE 的 session 块必须有 phase / live。

    少了这两个键，前端 ``session?.phase ?? "closed"`` 会把每一帧都读成「已收盘」——
    大屏在连续竞价里挂着「已收盘·展示最近快照」，实时看门狗也永远不触发。
    """
    upstream = FakeUpstream()
    hub = make_hub(upstream, phase_provider=lambda: "noon_break")
    with hub.subscribe("index") as sub:
        hub.tick_once()
        snapshot = sub.wait(0.0)
    assert snapshot is not None
    assert snapshot.session["phase"] == "noon_break"
    # 午休：闸门还开着（in_live_clock 到 15:00），但没在撮合 → 不是 live。
    assert snapshot.session["live"] is False
    assert snapshot.session["live_allowed"] is True


def test_index_basket_is_fetched_on_top_of_the_cross_section() -> None:
    """指数不在东财截面表里：不补这一次，大屏指数带就永远停在首屏 REST 快照。"""
    upstream = FakeUpstream(kind="ranked")

    def resolve(preset, codes=None, *, top_n=50):
        base = upstream.resolve(preset, codes, top_n=top_n)
        return Resolution(
            preset=base.preset, kind=base.kind, codes=base.codes, source=base.source,
            instrument_types=base.instrument_types, rows=base.rows,
            index_codes=["000001", "399001"],
        )

    hub = make_hub(upstream, resolve=resolve)
    with hub.subscribe("all") as sub:
        hub.tick_once()
        snapshot = sub.wait(0.0)
    assert snapshot is not None
    codes = [row["code"] for row in snapshot.rows]
    assert codes[:2] == ["000001", "399001"]  # 指数在前，一眼能读到
    assert len(codes) == 2 + upstream.rows


def test_index_fetch_failure_still_ships_the_stock_rows() -> None:
    """补指数失败只该少一条带，不该整帧不发。"""
    upstream = FakeUpstream(kind="ranked")

    def resolve(preset, codes=None, *, top_n=50):
        base = upstream.resolve(preset, codes, top_n=top_n)
        return Resolution(
            preset=base.preset, kind=base.kind, codes=base.codes, source=base.source,
            instrument_types=base.instrument_types, rows=base.rows, index_codes=["000001"],
        )

    def boom(codes, instrument_types=None):
        raise RuntimeError("指数线路 403")

    hub = make_hub(upstream, resolve=resolve, fetch_quotes=boom)
    with hub.subscribe("all") as sub:
        hub.tick_once()
        snapshot = sub.wait(0.0)
        assert snapshot is not None and len(snapshot.rows) == upstream.rows
        assert hub.stats()["feeds"][0]["errors"] == 0


def test_cross_section_outage_falls_back_to_per_code_quotes() -> None:
    """东财整表挂掉时改走逐票线路。

    生产日志里 ``实时推流 feed all 取数失败`` 一刷几小时，那几小时里大屏每个
    数字都停在早上——退化成另一条线路，好过整屏假装自己是实时。
    """
    upstream = FakeUpstream(kind="ranked")
    state = {"boom": False}

    def resolve(preset, codes=None, *, top_n=50):
        if state["boom"]:
            raise RuntimeError("东财全市场截面失败：RemoteDisconnected")
        return upstream.resolve(preset, codes, top_n=top_n)

    hub = make_hub(upstream, resolve=resolve)
    with hub.subscribe("all") as sub:
        hub.tick_once()
        assert sub.wait(0.0) is not None
        state["boom"] = True
        hub.tick_once()
        degraded = sub.wait(0.0)
    assert degraded is not None, "主源挂了也必须继续发帧"
    assert degraded.source == "fallback_live_quotes"
    assert len(degraded.rows) == upstream.rows


def test_feed_status_tells_the_truth_when_the_source_is_down() -> None:
    """没有它，前端只能靠「收没收到帧」猜：链路 200、心跳照发、屏幕全是冻住的数字。"""
    upstream = FakeUpstream(boom=True)
    hub = make_hub(upstream)
    with hub.subscribe("index"):
        hub.tick_once()
        status = hub.feed_status("index")
    assert status["rows"] == 0
    assert status["errors"] == 1
    assert status["source_error"].startswith("RuntimeError")
    assert status["stale_ms"] == -1  # 从未成功过，和「3 秒前刚到」不是一回事
    assert status["session"]["phase"] == "morning"
