"""历史日 K、复权因子与证券列表同步编排。"""
from __future__ import annotations

from src.shared.clock import utc_now

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Callable, Sequence

import pandas as pd

from src.market.infrastructure.sources import QuoteSource, SourceError, fetch_with_fallback
from src.market.infrastructure.store import MarketError, MarketStore, normalize_code
from src.market.infrastructure.store_quote_payload import partition_valid_ohlc_rows
from src.market.infrastructure import sync_engine
from src.market.infrastructure.sync_engine import RateLimiter as _RateLimiter
from src.market.infrastructure.sync_prefetch import SyncPrefetch, load_sync_prefetch
from src.market.infrastructure.sync_spot import (
    _apply_today_spot_once,
    apply_today_spot,
    fallback_used as _fallback_used,
)
from src.market.infrastructure.sync_factors import (
    _FACTOR_STALE_DAYS,
    _factor_fetched_at,
    _factor_is_fresh,
    _fetch_factors_for_sync,
    _refresh_factors_if_stale,
    refresh_adjust_factors,
)

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARKS = ("000300", "000905", "000852")
_HISTORICAL_REQUEST_START = "1990-01-01"

#: 历史日 K 同步默认并发。主源是通达信二进制协议（单票 p50 约 28ms），
#: 实测 8~16 路才吃得满；旧默认 4 是为逐票 HTTP 源留的，早已不是瓶颈所在。
DEFAULT_SYNC_WORKERS = 12
#: 每个 worker 槽位的最小请求间隔。聚合速率 = workers / interval，
#: 12 路 × 0.02s ≈ 600 次/秒上限，实际由各源在途名额门闩先卡住。
DEFAULT_SYNC_INTERVAL = 0.02


@dataclass
class SyncReport:
    """一次同步的结果。失败明细可直接拿去重试。"""

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    rows_written: int = 0
    spot_rows: int = 0
    elapsed_seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)
    source_receipts: list[dict[str, Any]] = field(default_factory=list)
    selected_sources: dict[str, int] = field(default_factory=dict)
    unresolved_codes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        rate = f"{self.elapsed_seconds / self.succeeded:.2f}s/票" if self.succeeded else "-"
        spot = f"，当日实时 {self.spot_rows} 行" if self.spot_rows else ""
        return (
            f"同步完成：成功 {self.succeeded} / 跳过 {self.skipped} / 失败 {self.failed}"
            f"（共 {self.total}），写入 {self.rows_written} 行{spot}，"
            f"耗时 {self.elapsed_seconds:.1f}s，{rate}"
        )




def _fetch_daily_for_sync(
    code: str,
    *,
    instrument_type: str,
    sources: Sequence[QuoteSource] | None,
    receipt: list[dict[str, Any]] | None = None,
    recent_bars: int | None = None,
) -> tuple[pd.DataFrame, str]:
    """显式 source 走串行降级链（不支持近窗），默认走适配器粘性竞速。"""
    if sources is not None:
        return fetch_with_fallback(list(sources), code, instrument_type=instrument_type, receipt=receipt)
    from src.market.infrastructure.adapters import AdapterError, fetch_daily_routed

    try:
        return fetch_daily_routed(
            code,
            instrument_type=instrument_type,
            receipt=receipt,
            recent_bars=recent_bars,
        )
    except AdapterError as exc:
        raise SourceError(str(exc)) from exc


#: 已有历史时的最小近窗；顺带重写最近几天，订正盘中 spot 落下的临时行。
_INCREMENTAL_MIN_BARS = 20
#: 断档超过这么多自然日就别拼近窗了，直接回全量补齐。
_INCREMENTAL_MAX_GAP_DAYS = 180
#: spot 来源标记后缀（``{adapter}_spot``）。盘中快照既不是当日定稿日 K，
#: 也不代表历史已经补齐，任何「同步进度」判据都必须把它排除在外。
_SPOT_SOURCE_SUFFIX = "_spot"


def _window_start(bars: int, *, today: date) -> str:
    from src.market.infrastructure.adapters import window_start_date

    return window_start_date(bars, today=today).isoformat()


def _is_spot_watermark(mark: Any) -> bool:
    """水位是否由盘中 spot 推进（而不是历史日 K 线路）。"""
    if mark is None:
        return False
    try:
        source = str(mark["source"] or "")
    except (IndexError, KeyError, TypeError):
        return False
    return source.endswith(_SPOT_SOURCE_SUFFIX)


def _finalized_last_date(
    store: MarketStore, code: str, prefetch: SyncPrefetch | None = None
) -> str:
    """库内最后一根非 spot 日 K。spot 行是盘中快照，不能当断档基准。

    有预热就直接查表：这条 SQL 的 ``source NOT LIKE`` 走不了索引，逐票执行
    会沿 (code, trade_date) 把该票全历史扫一遍，全市场实测 277s。
    """
    if prefetch is not None and prefetch.loaded:
        return prefetch.finalized_last.get(code, "")
    row = store.conn.execute(
        "SELECT MAX(trade_date) FROM quotes_daily"
        " WHERE code = ? AND source NOT LIKE '%\\_spot' ESCAPE '\\'",
        (code,),
    ).fetchone()
    return str(row[0] or "")[:10] if row else ""


def _earliest_date(
    store: MarketStore, code: str, prefetch: SyncPrefetch | None = None
) -> str:
    """库内最早一根日 K；预热命中就不回库。"""
    if prefetch is not None and prefetch.loaded:
        return prefetch.earliest.get(code, "")
    row = store.conn.execute(
        "SELECT MIN(trade_date) FROM quotes_daily WHERE code = ?", (code,)
    ).fetchone()
    return str(row[0] or "")[:10] if row else ""


def _incremental_bars(
    store: MarketStore,
    code: str,
    mark: Any,
    *,
    today: date,
    prefetch: SyncPrefetch | None = None,
) -> int | None:
    """库里已有足量历史且断档不久 → 只补近窗；否则返回 None 走全量。

    盘中增量若每天对全市场重拉三十年历史，既会把来源打到连接超时，
    也会白写上百万行。
    """
    last = str(mark["last_trade_date"] or "")[:10] if mark is not None else ""
    if not last:
        return None
    # spot 会把水位推到今天，可定稿历史也许还停在几十天前；按水位算断档
    # 只会补最近 20 根，中间的洞永远补不上。
    finalized = _finalized_last_date(store, code, prefetch)
    if finalized and finalized < last:
        last = finalized
    try:
        gap = (today - date.fromisoformat(last)).days
    except ValueError:
        return None
    if gap < 0 or gap > _INCREMENTAL_MAX_GAP_DAYS:
        return None
    bars = max(_INCREMENTAL_MIN_BARS, gap + 5)
    earliest = _earliest_date(store, code, prefetch)
    # 近窗只能续已有历史的尾巴。新票、首次回填必须走全量，
    # 否则库里会永远只剩最近几十根。
    if not earliest or earliest > _window_start(bars, today=today):
        return None
    return bars



def sync_instruments(store: MarketStore, *, sources: Sequence[QuoteSource] | None = None) -> int:
    """刷新证券列表，并补齐默认宽基指数。"""
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

    rows = [
        {
            "code": str(record.get("code", "")).zfill(6),
            "name": str(record.get("name", "")),
            "market": str(record.get("market", "") or ""),
            "board": str(record.get("board", "")),
            "industry": str(record.get("industry", "") or ""),
            "list_date": str(record.get("list_date", "") or ""),
            "instrument_type": "STOCK",
        }
        for record in frame.to_dict("records")
        if str(record.get("code", "")).strip().isdigit()
    ]
    active_stock_codes = [str(row["code"]) for row in rows]
    rows.extend(
        {"code": code, "name": f"基准指数{code}", "instrument_type": "INDEX"}
        for code in DEFAULT_BENCHMARKS
    )
    written = store.upsert_instruments(rows)
    complete_markets = frame.attrs.get("complete_markets", ())
    if complete_markets:
        reconciliation = store.reconcile_instrument_snapshot(
            active_stock_codes,
            complete_markets=complete_markets,
            snapshot_date=date.today().isoformat(),
        )
        if reconciliation["rejected_markets"]:
            logger.warning(
                "证券列表快照骤减，已拒绝淘汰交易所：%s",
                ", ".join(reconciliation["rejected_markets"]),
            )
    return written


def _selected_source(attempts: Sequence[dict[str, Any]]) -> str:
    for item in reversed(attempts):
        if str(item.get("state") or "") == "selected":
            return str(item.get("source_id") or "")
    return ""


def _source_url(source_name: str, sources: Sequence[QuoteSource] | None) -> str:
    """返回本次实际来源的公开入口；不把猜测的接口地址当作证据。"""
    if sources is not None:
        for source in sources:
            if str(getattr(source, "name", "")) == source_name:
                return str(getattr(source, "source_url", getattr(source, "base_url", "")) or "")
        return ""
    try:
        from src.market.infrastructure.adapters import get_adapter

        return str(get_adapter(source_name).meta.base_url or "")
    except Exception:
        return ""


def _skip_receipt(code: str, mark: Any) -> dict[str, Any]:
    """watermark 命中、本轮没有重新请求的终态回执。"""
    scope_date = str(mark["last_trade_date"] or date.today().isoformat())[:10]
    return {
        "code": code,
        "lane": "hist_daily",
        "attempts": [
            {
                "source_id": "watermark",
                "state": "skipped",
                "checked_at": utc_now(),
                "error": "watermark 命中，未重新请求",
            }
        ],
        "selected_source": str(mark["source"] or ""),
        "fallback_used": False,
        "unresolved": False,
        "coverage_start": scope_date,
        "coverage_end": scope_date,
        "request_start": scope_date,
        "request_end": scope_date,
    }


def _watermark_is_fresh(mark: Any, fresh_threshold: str) -> bool:
    """水位是否新到可以整只跳过。

    spot 水位只说明「盘中快照写过」，不代表当日定稿日 K 已入库；认它就会让
    当晚的历史同步整只跳过，半天的快照被当成收盘价。
    """
    if not mark:
        return False
    if str(mark["status"] or "") != "ok":
        return False
    if _is_spot_watermark(mark):
        return False
    return str(mark["last_synced_at"] or "")[:10] >= fresh_threshold


def sync_quotes(
    store_factory: Callable[[], MarketStore],
    codes: Sequence[str],
    *,
    sources: Sequence[QuoteSource] | None = None,
    instrument_types: dict[str, str] | None = None,
    workers: int = DEFAULT_SYNC_WORKERS,
    min_interval: float = DEFAULT_SYNC_INTERVAL,
    force: bool = False,
    stale_after_days: int = 0,
    with_factors: bool = True,
    with_today_spot: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    chunk_size: int | None = None,
) -> SyncReport:
    """同步一批证券历史日 K；每个终态均保留逐代码来源回执。

    结构见 ``sync_engine`` 的模块注释：预热一次、取数并发扇出、落库单写批量。
    取数线程完全不碰 SQLite，因此全程只用主线程这一条连接。
    """
    types = dict(instrument_types or ())
    worker_count = max(1, int(workers))
    limiter = _RateLimiter(min_interval, slots=worker_count)
    report = SyncReport(total=len(codes))
    started = time.monotonic()
    today = date.today()
    today_iso = today.isoformat()
    fresh_threshold = (today - timedelta(days=max(0, stale_after_days))).isoformat()
    batch = sync_engine.chunk_size_for(force, chunk_size)

    store = store_factory()
    try:
        prefetch = load_sync_prefetch(store, today=today)
        logger.info(
            "同步预热完成：%d 条水位 / %d 条首末日 / %.2fs",
            len(prefetch.watermarks),
            len(prefetch.earliest),
            prefetch.elapsed_seconds,
        )

        def fetch_one(raw_code: str) -> sync_engine.Outcome:
            """只做网络与解析；不碰 SQLite，因此可以随便开线程。"""
            attempts: list[dict[str, Any]] = []
            code = str(raw_code).strip()
            coverage: dict[str, object] = {
                "source_rows": 0,
                "rows_written": 0,
                "rejected_ohlc_rows": 0,
            }
            request_start = _HISTORICAL_REQUEST_START
            try:
                try:
                    code = normalize_code(raw_code)
                except MarketError as exc:
                    attempts.append(
                        {
                            "source_id": "input",
                            "state": "failed",
                            "checked_at": utc_now(),
                            "error": str(exc),
                        }
                    )
                    raise
                instrument_type = types.get(code, "STOCK")
                mark = prefetch.watermark(code)
                wants_factor = with_factors and instrument_type == "STOCK"
                factor_stale = wants_factor and not _factor_is_fresh(
                    prefetch.factor_age.get(code, ""), _FACTOR_STALE_DAYS
                )
                factors = (
                    _fetch_factors_for_sync(code, sources=sources, limiter=limiter)
                    if factor_stale
                    else None
                )
                if not force and _watermark_is_fresh(mark, fresh_threshold):
                    return sync_engine.Outcome(
                        code=code,
                        kind="skip",
                        receipt=_skip_receipt(code, mark),
                        factors=factors,
                    )

                # force 是「我怀疑本地历史坏了」的逃生口，必须重拉全量。
                recent_bars = (
                    None
                    if force
                    else _incremental_bars(
                        None, code, mark, today=today, prefetch=prefetch
                    )
                )
                if recent_bars is not None:
                    request_start = _window_start(recent_bars, today=today)
                limiter.wait()
                frame, source_name = _fetch_daily_for_sync(
                    code,
                    instrument_type=instrument_type,
                    sources=sources,
                    receipt=attempts,
                    recent_bars=recent_bars,
                )
                if frame is None or frame.empty:
                    raise SourceError("日线源返回空数据")
                source_rows = int(len(frame))
                frame, rejected = partition_valid_ohlc_rows(frame)
                coverage = {
                    "source_rows": source_rows,
                    "rows_written": 0,
                    "rejected_ohlc_rows": int(len(rejected)),
                    "fields": [str(field) for field in frame.columns],
                }
                if frame.empty:
                    raise SourceError(f"日线 OHLC 校验拒绝全部 {source_rows} 行")
                date_col = "date" if "date" in frame.columns else "trade_date"
                if date_col not in frame.columns:
                    raise SourceError("日线数据缺少日期列")
                last_date = str(pd.to_datetime(frame[date_col]).max().date())
                return sync_engine.Outcome(
                    code=code,
                    kind="ok",
                    frame=frame,
                    source=source_name,
                    last_date=last_date,
                    factors=factors,
                    receipt={
                        "code": code,
                        "lane": "hist_daily",
                        "requested_sources": [
                            str(item.get("source_id") or "") for item in attempts
                        ],
                        "attempts": attempts,
                        "selected_source": source_name,
                        "fallback_used": _fallback_used(attempts, source_name),
                        "unresolved": False,
                        "coverage": coverage,
                        "source_url": _source_url(source_name, sources),
                        # 适配器只观测到本次拉取，证明不了供应商历史发布时间或某
                        # 交易时点可见性；严格 PIT 必须因此拒绝，不能拿抓取时刻冒充。
                        "published_at": "",
                        "publication_status": "not_observed",
                        "available_at": "",
                        "availability_status": "not_observed",
                        "request_start": request_start,
                        "request_end": today_iso,
                    },
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if not attempts:
                    attempts.append(
                        {
                            "source_id": "hist_daily_router",
                            "state": "failed",
                            "checked_at": utc_now(),
                            "error": message,
                        }
                    )
                selected = _selected_source(attempts)
                return sync_engine.Outcome(
                    code=code,
                    kind="fail",
                    source=selected,
                    message=message,
                    receipt={
                        "code": code,
                        "lane": "hist_daily",
                        "requested_sources": [
                            str(item.get("source_id") or "") for item in attempts
                        ],
                        "attempts": attempts,
                        "selected_source": selected,
                        "fallback_used": _fallback_used(attempts, selected),
                        "unresolved": True,
                        "error": message[:500],
                        "coverage": coverage,
                        "request_start": request_start,
                        "request_end": today_iso,
                    },
                )

        def on_written(
            code: str, written: int, receipt: dict[str, Any], source: str
        ) -> None:
            report.succeeded += 1
            report.rows_written += written
            report.source_receipts.append(receipt)
            report.selected_sources[source] = report.selected_sources.get(source, 0) + 1

        def on_failed(code: str, message: str, receipt: dict[str, Any]) -> None:
            report.failed += 1
            report.failures.append((code, message))
            report.unresolved_codes.append(code)
            if receipt:
                report.source_receipts.append(receipt)
            logger.warning("同步 %s 失败：%s", code, message)

        def on_skipped(code: str, receipt: dict[str, Any]) -> None:
            report.skipped += 1
            if receipt:
                report.source_receipts.append(receipt)

        writer = sync_engine.BatchWriter(
            store,
            chunk_size=batch,
            on_written=on_written,
            on_failed=on_failed,
            on_skipped=on_skipped,
        )
        outcomes = sync_engine.make_queue(batch)
        pool = sync_engine.fan_out(
            list(codes), fetch_one, outcomes, workers=worker_count
        )
        try:
            sync_engine.drain(
                outcomes,
                writer,
                len(codes),
                progress=(
                    (lambda done, code: progress(done, report.total, code))
                    if progress
                    else None
                ),
            )
        finally:
            pool.shutdown(wait=True)

        if with_today_spot and codes:
            try:
                report.spot_rows = apply_today_spot(
                    store, codes, instrument_types=types or None
                )
                report.rows_written += report.spot_rows
            except Exception as exc:
                logger.warning("补当日实时日 K 失败：%s", exc)
    finally:
        store.close()
    report.elapsed_seconds = time.monotonic() - started
    return report
