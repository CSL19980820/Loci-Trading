"""单一后台采集器 + 多订阅者广播（实时行情推流的心脏）。

**为什么必须「一个进程一个采集线程」**：改造前每个客户端 tick 各自触发一次上游
取数，而 ``(spot_batch, sina/tencent)`` 的在途名额门闩默认只有 **1**
（``infrastructure/adapters/router_live.py:25 DEFAULT_ADAPTER_CONCURRENCY``）。
多客户端大屏会把同一条 lane 排成长队，上游看到的却是同一个 IP 的高频重复整表
下载——直接被打成 403 / 截断。所以：**N 个订阅者共享同一份快照**。

**周期预算**（不是拍脑袋，是被上游缓存卡死的物理上限）：指数 / 自选 ≤400 只 →
**3s**（``live_tape.py:28 _CACHE_TTL`` 就是 3s，更快只会拿到同一份 payload）；
全市场截面（东财整表）→ **6s**（``eastmoney_adapter.py:44 _SPOT_RAW_TTL_SEC``
是 4s，整表归一还要百毫秒级，6s 给解析留余量又不影响手感）；非交易时段 →
**60s**，只刷一份收盘快照。

**订阅者归零就自动停表**，不留常驻空转线程。
**铁律：纯读路径**——采集器不写 ``market.db``、不调 ``apply_today_spot``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import threading
import time
from typing import Any, Callable

from src.market.application.session import LIVE_PHASES as BOARD_LIVE_PHASES
from src.market.application.session import board_phase, board_session
from src.market.application.watchlist import DEFAULT_TOP_N, RANKED_PRESETS, Resolution, resolve_preset
from src.shared.observability import metric as observation_metric
from src.shared.observability import span as observation_span

logger = logging.getLogger(__name__)

#: 逐票 preset（指数 / 自选，≤400 只）的 tick 周期，见模块 docstring。
CODES_TICK_SECONDS = 3.0
#: 全市场截面（东财整表）的 tick 周期。
CROSS_SECTION_TICK_SECONDS = 6.0
#: 非交易时段的降频周期。
IDLE_TICK_SECONDS = 60.0
#: 单条 feed 连续失败时的指数退避上限。
MAX_BACKOFF_SECONDS = 30.0
#: 闸门缓存：coverage + 日历是 SQLite 读，没必要每 tick 开一次库。
SESSION_TTL_SECONDS = 30.0
#: 全速档相位。**词表只有一份**（application/session.py）：采集周期、SSE 的
#: ``session.live`` 与前端文案共用它，避免再出一次「后端说 regular、前端认
#: morning，于是全天显示已收盘」的契约事故。
LIVE_PHASES = BOARD_LIVE_PHASES

_METRIC_LABELS = {"component": "market", "operation": "stream"}


@dataclass(frozen=True)
class Snapshot:
    """一次采集结果。``seq`` 在同一条 feed 内单调递增，供 Last-Event-ID 续传。"""

    seq: int
    as_of: str
    source: str
    rows: list[dict[str, Any]]
    session: dict[str, Any]


@dataclass
class _Feed:
    """一条被共享的采集流；``subscribers`` 归零后即从注册表摘除。"""

    key: str
    preset: str
    codes: list[str]
    top_n: int
    subscribers: int = 0
    seq: int = 0
    latest: Snapshot | None = None
    next_due: float = 0.0
    ticks: int = 0
    errors: int = 0
    backoff: float = 0.0
    last_error: str = ""
    last_elapsed_ms: int = 0
    period: float = CODES_TICK_SECONDS
    #: 最近一次**成功**采集的单调时钟；推流层据此报「数据有多旧」。
    last_ok: float = 0.0
    #: 上一轮解析成功的代码表。东财整表挂掉时拿它走 sina/tencent 兜底，
    #: 别让一条上游把整块大屏带走。
    fallback_codes: list[str] = field(default_factory=list)
    fallback_types: dict[str, str] = field(default_factory=dict)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _feed_key(preset: str, codes: list[str] | None) -> tuple[str, list[str]]:
    clean = [str(code).strip() for code in (codes or []) if str(code).strip()]
    return (f"{preset}:{','.join(sorted(clean))}" if clean else str(preset)), clean


def default_session_status() -> dict[str, Any]:
    """热库 coverage + 日历 → 闸门；失败降级为「不许实时」而不是抛异常。"""
    try:
        from src.market.application.session import build_session_status
        from src.market.infrastructure.store_hot import open_market_hot
        
        with open_market_hot() as store:
            coverage, days = store.coverage(), _trading_days(store)
        return build_session_status(coverage=coverage, trading_days=days)
    except Exception as exc:  # pragma: no cover - 库不可用不该带死采集线程
        logger.warning("会话闸门读取失败，按不可实时降级：%s", exc)
        return {"live_allowed": False, "live_reason": "session_unavailable"}


def _trading_days(store: Any) -> list[str]:
    try:
        return list(store.trading_days())
    except Exception:  # pragma: no cover - 日历缺失按空日历降级
        return []


def default_phase() -> str:
    """大屏时段相位（``application/session.board_phase``）。

    **它判午休**：只看闸门（``in_live_clock`` 是 [09:15, 15:00)）会在 11:30–13:00
    空转打上游；也只有它能把 12:00 说成「午间休市」而不是「已收盘」。
    """
    return board_phase()


def default_fetch_quotes(codes: list[str], instrument_types: dict[str, str] | None = None) -> list[dict[str, Any]]:
    from src.market.application.live import fetch_live_quotes

    return fetch_live_quotes(codes, instrument_types=instrument_types)


class Subscription:
    """一个订阅者的视角：只记「我看到过哪个 seq」，不持有任何取数能力。

    上下文管理器：``with hub.subscribe("index", None) as sub:``；退出即退订。
    """

    def __init__(self, hub: "LiveHub", feed: _Feed, *, after: int = 0) -> None:
        self._hub, self._feed, self._seen, self._closed = hub, feed, int(after), False

    @property
    def preset(self) -> str: return self._feed.preset

    @property
    def key(self) -> str: return self._feed.key

    def __enter__(self) -> "Subscription": return self

    def __exit__(self, *_exc: Any) -> None: self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._hub._release(self._feed)

    def wait(self, timeout: float) -> Snapshot | None:
        """等一份比已见 seq 更新的快照；超时 None。Condition 唤醒，订阅侧零 CPU。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._hub._cond:
            while True:
                snapshot = self._feed.latest
                if snapshot is not None and snapshot.seq > self._seen:
                    self._seen = snapshot.seq
                    return snapshot
                remain = deadline - time.monotonic()
                if remain <= 0 or self._closed:
                    return None
                self._hub._cond.wait(remain)


class LiveHub:
    """进程级实时行情广播器。所有外部取数都可注入，测试永远不碰真 HTTP。"""

    def __init__(
        self,
        *,
        resolve: Callable[..., Resolution] | None = None,
        fetch_quotes: Callable[..., list[dict[str, Any]]] | None = None,
        session_provider: Callable[[], dict[str, Any]] | None = None,
        phase_provider: Callable[[], str] | None = None,
        codes_period: float = CODES_TICK_SECONDS,
        cross_period: float = CROSS_SECTION_TICK_SECONDS,
        idle_period: float = IDLE_TICK_SECONDS,
        autostart: bool = True,
    ) -> None:
        self._resolve = resolve or resolve_preset
        self._fetch = fetch_quotes or default_fetch_quotes
        self._session_provider = session_provider or default_session_status
        self._phase_provider = phase_provider or default_phase
        self._codes_period, self._cross_period = float(codes_period), float(cross_period)
        self._idle_period, self._autostart = float(idle_period), bool(autostart)
        self._cond = threading.Condition(threading.Lock())
        self._feeds: dict[str, _Feed] = {}
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._session_cache: tuple[float, dict[str, Any]] | None = None

    def subscribe(self, preset: str, codes: list[str] | None = None, *, top_n: int = DEFAULT_TOP_N, after: int = 0) -> Subscription:
        """登记订阅者并（按需）拉起采集线程。返回上下文管理器。"""
        key, clean = _feed_key(preset, codes)
        with self._cond:
            feed = self._feeds.get(key)
            if feed is None:
                feed = _Feed(key=key, preset=str(preset), codes=clean, top_n=int(top_n))
                self._feeds[key] = feed
            feed.subscribers += 1
            feed.next_due = 0.0  # 新订阅者进来立刻补一帧，不等下一个周期
            self._cond.notify_all()
        observation_metric("loci.market.stream.subscribes", labels=_METRIC_LABELS)
        self._ensure_thread()
        return Subscription(self, feed, after=after)

    def _release(self, feed: _Feed) -> None:
        with self._cond:
            feed.subscribers = max(0, feed.subscribers - 1)
            if feed.subscribers == 0:
                self._feeds.pop(feed.key, None)
            self._cond.notify_all()

    def latest(self, preset: str, codes: list[str] | None = None) -> Snapshot | None:
        with self._cond:
            feed = self._feeds.get(_feed_key(preset, codes)[0])
            return feed.latest if feed else None

    def _ensure_thread(self) -> None:
        if not self._autostart:
            return
        with self._cond:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            thread = threading.Thread(target=self._run, name="loci-live-hub", daemon=True)
            self._thread = thread
        thread.start()

    def stop(self) -> None:
        """请求停表并等线程退出（测试 / 关站用）。"""
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stopping:
                    self._thread = None
                    return
                feeds = [f for f in self._feeds.values() if f.subscribers > 0]
                if not feeds:
                    self._thread = None  # 订阅者归零：自动停表
                    return
                now = time.monotonic()
                due = [f for f in feeds if f.next_due <= now]
                if not due:
                    self._cond.wait(max(0.01, min(min(f.next_due for f in feeds) - now, 1.0)))
                    continue
            for feed in due:
                self._tick(feed)

    def tick_once(self) -> int:
        """同步跑一轮采集（``autostart=False`` 的测试入口），返回本轮 feed 数。"""
        with self._cond:
            feeds = [f for f in self._feeds.values() if f.subscribers > 0]
        for feed in feeds:
            self._tick(feed)
        return len(feeds)

    def _period_for(self, feed: _Feed, session: dict[str, Any], phase: str) -> float:
        """全速档只在「闸门放行」且「时钟真在撮合」时给；否则降到 60s。

        相位由调用方传进来：同一 tick 里周期判定与 SSE 会话块必须读同一个相位，
        各自调一次 provider 会在 11:30 / 15:00 的边界上给出自相矛盾的一帧。
        """
        if not bool(session.get("live_allowed")) or phase not in LIVE_PHASES:
            return self._idle_period
        return self._cross_period if feed.preset in RANKED_PRESETS else self._codes_period

    def _session(self) -> dict[str, Any]:
        cached, now = self._session_cache, time.monotonic()
        if cached is not None and now - cached[0] < SESSION_TTL_SECONDS:
            return cached[1]
        session = dict(self._session_provider() or {})
        self._session_cache = (now, session)
        return session

    def _session_cached(self) -> dict[str, Any]:
        """只读缓存版：**推流协程（事件循环）专用**，绝不在这里碰 SQLite。

        采集线程每 tick 都会刷新它，所以正常情况下是热的；真取不到就回空 dict，
        ``board_session`` 仍能按时钟给出相位（只是 live 保守判 False）。
        """
        cached = self._session_cache
        return dict(cached[1]) if cached else {}

    def _collect(self, feed: _Feed) -> tuple[list[dict[str, Any]], str]:
        """解析 + 取数，返回 (行, 数据源标签)。

        **东财整表挂了不等于大屏该黑屏**：解析失败时退回上一轮解析出来的代码表，
        改走 sina/tencent 的逐票批量（``fetch_quotes``）。生产日志里
        ``实时推流 feed all 取数失败`` 一刷就是几小时，而那几小时里大屏的每一个
        数字都停在早上——退化成另一条线路，总好过整屏假装自己是实时。
        """
        with observation_span("market.stream.tick", labels={**_METRIC_LABELS, "lane": "spot_batch"}):
            try:
                resolution = self._resolve(feed.preset, feed.codes or None, top_n=feed.top_n)
            except Exception as exc:
                rows = self._fallback_rows(feed, exc)
                if rows is None:
                    raise
                return rows, "fallback_live_quotes"
            # 排行榜路径：排序用的截面表本身就是报价，不再补一次取数。
            rows = list(resolution.rows) if resolution.rows else list(
                self._fetch(resolution.codes, resolution.instrument_types)
            )
            # 兜底代码表带上指数：主源挂掉时指数带不能跟着停
            feed.fallback_codes = list(resolution.index_codes) + list(resolution.codes)
            feed.fallback_types = dict(resolution.instrument_types)
            return self._with_indices(feed, resolution, rows), resolution.source

    def _fallback_rows(self, feed: _Feed, exc: BaseException) -> list[dict[str, Any]] | None:
        """上游解析失败时的兜底行；没有可用代码表就返回 None（交回去照旧报错）。"""
        codes = list(feed.fallback_codes)
        if not codes:
            return None
        try:
            rows = list(self._fetch(codes, feed.fallback_types or None))
        except Exception:
            return None
        if not rows:
            return None
        logger.warning("实时推流 feed %s 主源失败，改走逐票兜底：%s", feed.key, exc)
        return rows

    def _with_indices(
        self, feed: _Feed, resolution: Resolution, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """补一次指数报价。指数**不在东财截面表里**，不补的话大屏的指数带永远
        停在首屏那次 REST 快照上——用户看到的就是「行情在动、指数不动」。

        失败只记日志：少一条指数带，好过整帧不发。
        """
        codes = [code for code in (resolution.index_codes or []) if code]
        if not codes:
            return rows
        try:
            quotes = list(self._fetch(codes, {code: "INDEX" for code in codes}))
        except Exception as exc:
            logger.warning("实时推流 feed %s 指数补采失败（本帧只发个股）：%s", feed.key, exc)
            return rows
        return quotes + rows

    def _tick(self, feed: _Feed) -> None:
        """一次采集。**任何异常都不许带死线程**：记 errors + 指数退避。"""
        started, gate = time.perf_counter(), self._session()
        phase = str(self._phase_provider())
        try:
            rows, source = self._collect(feed)
        except Exception as exc:
            self._record_failure(feed, exc)
            return
        period = self._period_for(feed, gate, phase)
        session = board_session(gate, phase=phase)
        with self._cond:
            feed.seq, feed.ticks = feed.seq + 1, feed.ticks + 1
            feed.backoff, feed.last_error, feed.period = 0.0, "", period
            feed.last_elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            feed.next_due = time.monotonic() + period
            feed.last_ok = time.monotonic()
            feed.latest = Snapshot(
                seq=feed.seq, as_of=_now_text(), source=source, rows=rows, session=session
            )
            self._cond.notify_all()
        observation_metric("loci.market.stream.ticks", labels=_METRIC_LABELS)
        observation_metric("loci.market.stream.rows", value=len(rows), labels=_METRIC_LABELS)

    def _record_failure(self, feed: _Feed, exc: BaseException) -> None:
        with self._cond:
            feed.errors += 1
            feed.last_error = f"{type(exc).__name__}: {exc}"
            feed.backoff = min(MAX_BACKOFF_SECONDS, (feed.backoff or max(0.5, self._codes_period)) * 2)
            feed.next_due = time.monotonic() + feed.backoff
            self._cond.notify_all()
        observation_metric("loci.market.stream.errors", labels={**_METRIC_LABELS, "status": "error"})
        logger.warning("实时推流 feed %s 取数失败：%s", feed.key, feed.last_error)

    def feed_status(self, preset: str, codes: list[str] | None = None) -> dict[str, Any]:
        """这条 feed 现在到底有没有数据——**推流层用来说实话的那句**。

        没有它，前端只能靠「收没收到帧」猜：上游挂掉时 SSE 照样 200、心跳照发、
        链路显示「已连接」，而屏幕上是一片冻住的数字，没有任何一处交代原因。
        """
        key = _feed_key(preset, codes)[0]
        now = time.monotonic()
        with self._cond:
            feed = self._feeds.get(key)
            latest = feed.latest if feed else None
            errors = int(feed.errors) if feed else 0
            ticks = int(feed.ticks) if feed else 0
            last_error = str(feed.last_error) if feed else ""
            last_ok = float(feed.last_ok) if feed else 0.0
        phase = str(self._phase_provider())
        session = latest.session if latest else board_session(self._session_cached(), phase=phase)
        return {
            "preset": str(preset),
            "session": session,
            "seq": int(latest.seq) if latest else 0,
            "as_of": latest.as_of if latest else "",
            "source": latest.source if latest else "",
            "rows": len(latest.rows) if latest else 0,
            "ticks": ticks,
            "errors": errors,
            "source_error": last_error,
            # 从未成功过就报 -1：「还没拿到过数据」和「数据 3 秒前刚到」不是一回事。
            "stale_ms": int((now - last_ok) * 1000) if last_ok else -1,
        }

    def stats(self) -> dict[str, Any]:
        """给 ``/api/market/stream/stats`` 的进程内自述。"""
        with self._cond:
            running = self._thread is not None and self._thread.is_alive()
            items = [_feed_stats(feed) for feed in self._feeds.values()]
        return {
            "running": running,
            "feeds": items,
            "feed_count": len(items),
            "subscribers": sum(int(item["subscribers"]) for item in items),
            "ticks": sum(int(item["ticks"]) for item in items),
            "errors": sum(int(item["errors"]) for item in items),
            "phase": self._phase_provider(),
            "session": board_session(self._session(), phase=self._phase_provider()),
            "budget": {
                "codes_seconds": self._codes_period,
                "cross_section_seconds": self._cross_period,
                "idle_seconds": self._idle_period,
            },
        }


def _feed_stats(feed: _Feed) -> dict[str, Any]:
    return {
        "key": feed.key, "preset": feed.preset, "codes": len(feed.codes),
        "subscribers": feed.subscribers, "seq": feed.seq, "ticks": feed.ticks,
        "errors": feed.errors, "last_error": feed.last_error,
        "last_elapsed_ms": feed.last_elapsed_ms, "period_seconds": feed.period,
        "as_of": feed.latest.as_of if feed.latest else "",
        "rows": len(feed.latest.rows) if feed.latest else 0,
    }


_HUB_LOCK = threading.Lock()
_HUB: LiveHub | None = None


def get_live_hub() -> LiveHub:
    """进程级单例。整个进程只有这一个采集线程。"""
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = LiveHub()
        return _HUB


def reset_live_hub() -> None:
    """丢弃单例并停表（测试用）。"""
    global _HUB
    with _HUB_LOCK:
        hub, _HUB = _HUB, None
    if hub is not None:
        hub.stop()


__all__ = [
    "CODES_TICK_SECONDS", "CROSS_SECTION_TICK_SECONDS", "IDLE_TICK_SECONDS", "LIVE_PHASES",
    "LiveHub", "Snapshot", "Subscription", "get_live_hub", "reset_live_hub",
]
