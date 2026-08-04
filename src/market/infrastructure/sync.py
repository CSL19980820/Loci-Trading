"""同步编排：全量回填与每日增量。

三个必须做对的地方：

1. **断点续跑。** 全市场回填是分钟级到小时级的长任务，中途断网、被限流、
   进程被杀都是常态。每只票写完就更新 watermark，重跑时默认跳过已成功的。
2. **限速。** akshare 底层是爬公开网页接口，无节制并发就是在申请被封 IP。
   默认并发很小、且每次请求之间有间隔，宁可慢也不要把唯一的出口 IP 打死。
3. **失败不阻断整体。** 单票失败记进 watermark 的 status，继续跑下一只；
   跑完给一份报告，失败的可以单独重试，而不是整批推倒重来。

实测吞吐（新浪源，2026-07-26）：0.47s/票，全市场 5400 票串行约 43 分钟，
4 并发约 11 分钟。首次回填是一次性成本，之后每日增量只动最后几根。

历史日 K 接口（新浪 hisdata_klc2）盘中/盘后早期**不含当日那根**；
同步末尾必须用实时行情把当日 OHLC 补上，否则"最新交易日"会永远停在昨天。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from src.market.infrastructure.sources import QuoteSource, SourceError, fetch_with_fallback
from src.market.infrastructure.store import MarketStore, normalize_code

logger = logging.getLogger(__name__)

#: 复盘要与基准比，这三个是默认跟踪的宽基指数。
DEFAULT_BENCHMARKS = ("000300", "000905", "000852")


@dataclass
class _SpotRefreshFlight:
    """同一行情库、同一批标的的 spot 刷新单飞状态。"""

    event: threading.Event = field(default_factory=threading.Event)
    result: int = 0
    error: Exception | None = None
    completed_at: float = 0.0


# 盘后多个选股任务会同时请求同一批全市场 spot。短 TTL 只用于复用同一轮
# 刷新结果，不把实时行情变成长缓存；失败也要让等待者看到同一个失败结果。
_SPOT_REFRESH_TTL_SECONDS = 30.0
_SPOT_REFRESH_CONDITION = threading.Condition()
_SPOT_REFRESH_FLIGHTS: dict[tuple[str, str, int, tuple[tuple[str, str], ...]], _SpotRefreshFlight] = {}


@dataclass
class SyncReport:
    """一次同步的结果。失败明细要能直接拿去重试，不能只给个计数。"""

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    rows_written: int = 0
    spot_rows: int = 0
    elapsed_seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        rate = f"{self.elapsed_seconds / self.succeeded:.2f}s/票" if self.succeeded else "—"
        spot = f"，当日实时 {self.spot_rows} 行" if self.spot_rows else ""
        return (
            f"同步完成：成功 {self.succeeded} / 跳过 {self.skipped} / 失败 {self.failed}"
            f"（共 {self.total}），写入 {self.rows_written} 行{spot}，"
            f"耗时 {self.elapsed_seconds:.1f}s，{rate}"
        )


class _RateLimiter:
    """全局最小请求间隔。并发线程共用，避免并发数一高就变相取消了限速。"""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + self.min_interval
        if sleep_for > 0:
            time.sleep(sleep_for)


def _fetch_daily_for_sync(
    code: str,
    *,
    instrument_type: str,
    sources: Sequence[QuoteSource] | None,
) -> tuple[pd.DataFrame, str]:
    """日线：显式 ``sources`` 走旧降级链（单测）；默认走适配器粘性竞速。"""
    if sources is not None:
        return fetch_with_fallback(list(sources), code, instrument_type=instrument_type)
    from src.market.infrastructure.adapters import AdapterError, fetch_daily_routed

    try:
        return fetch_daily_routed(code, instrument_type=instrument_type)
    except AdapterError as exc:
        raise SourceError(str(exc)) from exc


#: 单票复权因子超过该天数未刷新则在 watermark 跳过路径上强制重拉
_FACTOR_STALE_DAYS = 3


def _factor_fetched_at(store: MarketStore, code: str) -> str:
    row = store.conn.execute(
        "SELECT MAX(fetched_at) FROM adjust_factors WHERE code = ?",
        (normalize_code(code),),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _refresh_factors_if_stale(
    store: MarketStore,
    code: str,
    *,
    sources: Sequence[QuoteSource] | None,
    limiter: _RateLimiter,
    stale_days: int = _FACTOR_STALE_DAYS,
) -> bool:
    """因子缺失或 fetched_at 过旧则重拉；成功返回 True。"""
    latest = _factor_fetched_at(store, code)
    if latest:
        try:
            fetched = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            if fetched.tzinfo is not None:
                fetched = fetched.astimezone(timezone.utc).replace(tzinfo=None)
            age = (datetime.now(timezone.utc).replace(tzinfo=None) - fetched).total_seconds()
            if age <= stale_days * 86400:
                return False
        except ValueError:
            pass
    got = _fetch_factors_for_sync(code, sources=sources, limiter=limiter)
    if got is None:
        return False
    factors, factor_src = got
    store.upsert_adjust_factors(code, factors, source=factor_src)
    return True


def refresh_adjust_factors(
    store_factory: Callable[[], MarketStore],
    codes: Sequence[str],
    *,
    sources: Sequence[QuoteSource] | None = None,
    instrument_types: dict[str, str] | None = None,
    workers: int = 4,
    min_interval: float = 0.15,
    stale_days: int = _FACTOR_STALE_DAYS,
    progress: Callable[[int, int, str], None] | None = None,
) -> int:
    """只刷新复权因子（日终 today_refresh 用），不重拉历史日 K。"""
    types = instrument_types or {}
    limiter = _RateLimiter(min_interval)
    refreshed = 0
    lock = threading.Lock()
    total = len(codes)

    def worker(index_and_code: tuple[int, str]) -> None:
        nonlocal refreshed
        index, raw_code = index_and_code
        code = normalize_code(raw_code)
        if types.get(code, "STOCK") != "STOCK":
            return
        store = store_factory()
        try:
            if _refresh_factors_if_stale(
                store, code, sources=sources, limiter=limiter, stale_days=stale_days
            ):
                with lock:
                    refreshed += 1
        except Exception as exc:
            logger.debug("刷新 %s 复权因子失败：%s", code, exc)
        finally:
            store.close()
            if progress:
                with lock:
                    progress(index + 1, total, code)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(worker, item) for item in enumerate(codes)]
        for future in as_completed(futures):
            future.result()
    return refreshed


def _fetch_factors_for_sync(
    code: str,
    *,
    sources: Sequence[QuoteSource] | None,
    limiter: _RateLimiter,
) -> tuple[pd.DataFrame, str] | None:
    """复权因子：有则返回 (frame, source_id)，全失败返回 None。"""
    if sources is not None:
        for source in sources:
            try:
                limiter.wait()
                factors = source.fetch_adjust_factors(code)
                if factors is not None and not factors.empty:
                    return factors, source.name
            except Exception as exc:
                logger.debug("取 %s 复权因子失败（%s）：%s", code, source.name, exc)
        return None

    from src.market.infrastructure.adapters import AdapterError, fetch_adjust_factors_routed

    try:
        limiter.wait()
        return fetch_adjust_factors_routed(code)
    except AdapterError as exc:
        logger.debug("取 %s 复权因子失败：%s", code, exc)
        return None


def sync_instruments(
    store: MarketStore, *, sources: Sequence[QuoteSource] | None = None
) -> int:
    """刷新证券列表。含基准指数，它们和个股走同一张表。"""
    if sources is not None:
        frame = pd.DataFrame()
        for source in list(sources):
            try:
                frame = source.fetch_instruments()
                if not frame.empty:
                    break
            except SourceError as exc:
                logger.warning("取证券列表失败（%s）：%s", source.name, exc)
        if frame.empty:
            raise SourceError("所有数据源都取不到证券列表")
    else:
        from src.market.infrastructure.adapters import AdapterError, fetch_instruments_routed

        try:
            frame, _aid = fetch_instruments_routed()
        except AdapterError as exc:
            raise SourceError(str(exc)) from exc

    records = frame.to_dict("records")
    rows = [
        {
            "code": str(record.get("code", "")).zfill(6),
            "name": str(record.get("name", "")),
            "board": str(record.get("board", "")),
            "industry": str(record.get("industry", "") or ""),
            "list_date": str(record.get("list_date", "") or ""),
            "instrument_type": "STOCK",
        }
        for record in records
        if str(record.get("code", "")).strip().isdigit()
    ]
    rows.extend(
        {"code": code, "name": f"基准指数{code}", "instrument_type": "INDEX"}
        for code in DEFAULT_BENCHMARKS
    )
    return store.upsert_instruments(rows)


def sync_quotes(
    store_factory: Callable[[], MarketStore],
    codes: Sequence[str],
    *,
    sources: Sequence[QuoteSource] | None = None,
    instrument_types: dict[str, str] | None = None,
    workers: int = 4,
    min_interval: float = 0.15,
    force: bool = False,
    stale_after_days: int = 0,
    with_factors: bool = True,
    with_today_spot: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> SyncReport:
    """同步一批证券的日线。

    store_factory 而不是 store：SQLite 连接不能跨线程共享，每个 worker
    自己开一条连接。调用方通常传 ``lambda: MarketStore(path)``。

    force=False 时，watermark 显示**今天**已同步过的票直接跳过——重复触发
    （比如手动点了"补数"又赶上定时任务）不会重复打接口。

    ``stale_after_days`` 必须默认 0，即"只跳过今天同步过的"。曾经默认 1，
    结果是昨天同步过的票今天也被跳过——盘后同步任务每天都报
    "跳过 5500 / 成功 0"，看起来一切正常，实际一条新数据都不取。
    这是最难发现的那类失败：没有报错、没有异常，只是什么都没做。

    ``with_today_spot`` 默认开：历史日 K 不含当日，末尾用实时行情补当日
    OHLC。即使历史被 watermark 跳过，当日补数仍然会跑。

    ``sources`` 为 None 时走适配器粘性竞速（尊重 ``lane_providers`` 开关）；
    传入显式源列表则仍用旧串行降级链（单测 / 特殊注入）。
    """
    types = instrument_types or {}
    limiter = _RateLimiter(min_interval)
    report = SyncReport(total=len(codes))
    started = time.monotonic()
    lock = threading.Lock()
    fresh_threshold = (date.today() - timedelta(days=max(0, stale_after_days))).isoformat()

    def worker(index_and_code: tuple[int, str]) -> None:
        index, raw_code = index_and_code
        code = normalize_code(raw_code)
        store = store_factory()
        try:
            instrument_type = types.get(code, "STOCK")
            if not force:
                mark = store.watermark(code)
                if mark and mark["status"] == "ok" and str(mark["last_synced_at"])[:10] >= fresh_threshold:
                    # 日 K 可跳过，但复权因子仍要按票刷新——否则 watermark
                    # 跳过后除权事件永远进不了 adjust_factors。
                    if with_factors and instrument_type == "STOCK":
                        _refresh_factors_if_stale(
                            store, code, sources=sources, limiter=limiter
                        )
                    with lock:
                        report.skipped += 1
                    return

            limiter.wait()
            frame, source_name = _fetch_daily_for_sync(
                code, instrument_type=instrument_type, sources=sources
            )
            written = store.upsert_quotes(code, frame, source=source_name)

            if with_factors and instrument_type == "STOCK":
                got = _fetch_factors_for_sync(code, sources=sources, limiter=limiter)
                if got is not None:
                    factors, factor_src = got
                    store.upsert_adjust_factors(code, factors, source=factor_src)

            last_date = ""
            # 兼容返回 trade_date 列名的源，避免静默写空 watermark
            date_col = "date" if "date" in frame.columns else "trade_date"
            if date_col in frame.columns:
                last_date = str(pd.to_datetime(frame[date_col]).max().date())
            store.set_watermark(code, last_trade_date=last_date, status="ok", source=source_name)
            with lock:
                report.succeeded += 1
                report.rows_written += written
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            try:
                store.set_watermark(code, status="failed", message=message)
            except Exception:  # pragma: no cover - watermark 写失败不应掩盖原始错误
                logger.exception("写 %s 的失败 watermark 时又出错", code)
            with lock:
                report.failed += 1
                report.failures.append((code, message))
            logger.warning("同步 %s 失败：%s", code, message)
        finally:
            store.close()
            if progress:
                with lock:
                    done = report.succeeded + report.skipped + report.failed
                progress(done, report.total, code)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(worker, item) for item in enumerate(codes)]
        for future in as_completed(futures):
            future.result()

    if with_today_spot and codes:
        store = store_factory()
        try:
            report.spot_rows = apply_today_spot(
                store, codes, instrument_types=types or None
            )
            report.rows_written += report.spot_rows
        except Exception as exc:
            # 当日补数失败不该把整次同步打成失败——历史段已经落库了。
            logger.warning("补当日实时日 K 失败：%s", exc)
        finally:
            store.close()

    report.elapsed_seconds = time.monotonic() - started
    return report


def _live_quotes_to_spot_frame(
    quotes: Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    """把已取到的富行情转换为 ``apply_today_spot`` 的最小字段集。"""
    rows: list[dict[str, Any]] = []
    for quote in quotes:
        try:
            close = float(quote["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if close <= 0:
            continue

        def number(name: str, fallback: float) -> float:
            try:
                value = float(quote.get(name, fallback))
            except (TypeError, ValueError):
                return fallback
            return value if pd.notna(value) else fallback

        rows.append(
            {
                "code": str(quote.get("code") or ""),
                "date": str(
                    quote.get("trade_date")
                    or quote.get("date")
                    or date.today().isoformat()
                )[:10],
                "open": number("open", close),
                "high": number("high", close),
                "low": number("low", close),
                "close": close,
                "volume": number("volume", 0.0),
                "amount": number("amount", 0.0),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "code",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ],
    )


def apply_today_spot(
    store: MarketStore,
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    live_quotes: Sequence[Mapping[str, Any]] | None = None,
    raise_on_failure: bool = False,
) -> int:
    """用 spot_batch 线路把当日日 K 写入仓库。

    历史接口不含当日；盘中选股/面板要的就是这根未定型（或刚收盘）的 bar。
    同一进程里多个任务请求同一批标的时只执行一轮刷新，等待者复用结果。
    ``raise_on_failure`` 给需要「刷新失败就不能选股」的调用方使用；兼容旧的
    同步任务时，默认仍返回 0 并记录告警。
    """
    from src.market.infrastructure.adapters import AdapterError

    types = instrument_types or {}
    normalized = [normalize_code(code) for code in codes]
    if not normalized or not _is_current_trading_day(store):
        return 0

    if live_quotes is not None:
        try:
            return _apply_today_spot_once(
                store,
                normalized,
                types,
                batch_size=batch_size,
                live_quotes=live_quotes,
            )
        except AdapterError as exc:
            logger.warning("实时行情失败：%s", exc)
            if raise_on_failure:
                raise
            return 0

    key = _spot_refresh_key(store, normalized, types, batch_size)
    flight, owner = _claim_spot_refresh(key)
    if not owner:
        if flight.error is not None and raise_on_failure:
            raise flight.error
        return flight.result

    try:
        written = _apply_today_spot_once(
            store,
            normalized,
            types,
            batch_size=batch_size,
            live_quotes=None,
        )
    except Exception as exc:
        _complete_spot_refresh(flight, result=0, error=exc)
        if isinstance(exc, AdapterError):
            logger.warning("实时行情失败：%s", exc)
            if not raise_on_failure:
                return 0
        raise
    _complete_spot_refresh(flight, result=written, error=None)
    return written


def _is_current_trading_day(store: MarketStore) -> bool:
    """交易日历未同步到今天时，工作日按日历末日之后的规则粗判。"""
    today = date.today().isoformat()
    days = store.trading_days()
    if today in days:
        return True
    if not days:
        return date.today().weekday() < 5
    return today > max(days) and date.today().weekday() < 5


def _spot_refresh_key(
    store: MarketStore,
    codes: Sequence[str],
    instrument_types: Mapping[str, str],
    batch_size: int,
) -> tuple[str, str, int, tuple[tuple[str, str], ...]]:
    pairs = tuple(sorted((code, str(instrument_types.get(code, ""))) for code in codes))
    return (str(store.db_path.resolve()), date.today().isoformat(), batch_size, pairs)


def _claim_spot_refresh(
    key: tuple[str, str, int, tuple[tuple[str, str], ...]],
) -> tuple[_SpotRefreshFlight, bool]:
    with _SPOT_REFRESH_CONDITION:
        current = _SPOT_REFRESH_FLIGHTS.get(key)
        now = time.monotonic()
        if current is not None and current.event.is_set():
            if now - current.completed_at < _SPOT_REFRESH_TTL_SECONDS:
                return current, False
            current = None
        if current is None:
            current = _SpotRefreshFlight()
            _SPOT_REFRESH_FLIGHTS[key] = current
            return current, True
    current.event.wait()
    return current, False


def _complete_spot_refresh(
    flight: _SpotRefreshFlight,
    *,
    result: int,
    error: Exception | None,
) -> None:
    with _SPOT_REFRESH_CONDITION:
        flight.result = result
        flight.error = error
        flight.completed_at = time.monotonic()
        flight.event.set()
        _SPOT_REFRESH_CONDITION.notify_all()


def _apply_today_spot_once(
    store: MarketStore,
    normalized: Sequence[str],
    instrument_types: Mapping[str, str],
    *,
    batch_size: int,
    live_quotes: Sequence[Mapping[str, Any]] | None,
) -> int:
    """执行一轮真实 spot 拉取；异常由外层按兼容/严格模式处理。"""
    from src.market.infrastructure.adapters import AdapterError, fetch_spot_routed
    from src.market.infrastructure.turnover_repair import (
        backfill_missing_turnover,
        load_shares_asof,
    )

    if live_quotes is None:
        spot, adapter_id = fetch_spot_routed(
            normalized,
            instrument_types=instrument_types or None,
            batch_size=batch_size,
        )
    else:
        spot = _live_quotes_to_spot_frame(live_quotes)
        adapter_id = "live"

    if spot is None or spot.empty:
        raise AdapterError("实时行情返回空数据")

    trade_dates = sorted(
        {str(pd.Timestamp(value).date()) for value in spot["date"].tolist()}
    )
    today = date.today().isoformat()
    if today not in trade_dates:
        raise AdapterError(f"实时行情日期落后，未返回 {today}")

    shares_by_date = {d: load_shares_asof(store, d) for d in trade_dates}
    source_tag = f"{adapter_id}_spot"
    bars: list[dict[str, Any]] = []
    latest_by_code: dict[str, str] = {}

    for row in spot.itertuples(index=False):
        code = normalize_code(str(row.code))
        trade_date = str(pd.Timestamp(row.date).date())
        shares = shares_by_date.get(trade_date, {}).get(code)
        volume = float(row.volume)
        turnover = (volume / shares) if shares and shares > 0 else None
        # 股本若误用手单位反推会小 100 倍，换手率可破 100%；宁可不写也不入库脏值。
        if turnover is not None and turnover > 1.0:
            shares = None
            turnover = None
        bars.append(
            {
                "code": code,
                "date": trade_date,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": volume,
                "amount": float(row.amount),
                "outstanding_share": shares,
                "turnover": turnover,
            }
        )
        latest_by_code[code] = trade_date

    written = store.upsert_quote_bars(bars, source=source_tag) if bars else 0
    if latest_by_code:
        store.set_watermarks(latest_by_code.items(), status="ok", source=source_tag)

    # 安全带：仍缺换手的当日行再 as-of 回填一次（跳过中间空股本日）。
    if trade_dates:
        backfill_missing_turnover(store, trade_dates=trade_dates)
    return written
