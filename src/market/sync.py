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
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
import logging
import threading
import time
from typing import Callable, Sequence

import pandas as pd

from src.market.sources import QuoteSource, SourceError, default_sources, fetch_with_fallback
from src.market.store import MarketStore, normalize_code

logger = logging.getLogger(__name__)

#: 复盘要与基准比，这三个是默认跟踪的宽基指数。
DEFAULT_BENCHMARKS = ("000300", "000905", "000852")


@dataclass
class SyncReport:
    """一次同步的结果。失败明细要能直接拿去重试，不能只给个计数。"""

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    rows_written: int = 0
    elapsed_seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        rate = f"{self.elapsed_seconds / self.succeeded:.2f}s/票" if self.succeeded else "—"
        return (
            f"同步完成：成功 {self.succeeded} / 跳过 {self.skipped} / 失败 {self.failed}"
            f"（共 {self.total}），写入 {self.rows_written} 行，"
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


def sync_instruments(
    store: MarketStore, *, sources: Sequence[QuoteSource] | None = None
) -> int:
    """刷新证券列表。含基准指数，它们和个股走同一张表。"""
    chain = list(sources or default_sources())
    frame = pd.DataFrame()
    for source in chain:
        try:
            frame = source.fetch_instruments()
            if not frame.empty:
                break
        except SourceError as exc:
            logger.warning("取证券列表失败（%s）：%s", source.name, exc)
    if frame.empty:
        raise SourceError("所有数据源都取不到证券列表")

    records = frame.to_dict("records")
    rows = [
        {
            "code": str(record.get("code", "")).zfill(6),
            "name": str(record.get("name", "")),
            "board": str(record.get("board", "")),
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
    stale_after_days: int = 1,
    with_factors: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> SyncReport:
    """同步一批证券的日线。

    store_factory 而不是 store：SQLite 连接不能跨线程共享，每个 worker
    自己开一条连接。调用方通常传 ``lambda: MarketStore(path)``。

    force=False 时，watermark 显示今天已同步过的票直接跳过——每日增量
    重复触发（比如手动点了"补数"又赶上定时任务）不会重复打接口。
    """
    chain = list(sources or default_sources())
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
            if not force:
                mark = store.watermark(code)
                if mark and mark["status"] == "ok" and str(mark["last_synced_at"])[:10] >= fresh_threshold:
                    with lock:
                        report.skipped += 1
                    return

            limiter.wait()
            instrument_type = types.get(code, "STOCK")
            frame, source_name = fetch_with_fallback(
                chain, code, instrument_type=instrument_type
            )
            written = store.upsert_quotes(code, frame, source=source_name)

            if with_factors and instrument_type == "STOCK":
                for source in chain:
                    try:
                        limiter.wait()
                        factors = source.fetch_adjust_factors(code)
                        if factors is not None and not factors.empty:
                            store.upsert_adjust_factors(code, factors, source=source.name)
                            break
                    except Exception as exc:  # 因子拿不到不该拖垮行情本身
                        logger.debug("取 %s 复权因子失败（%s）：%s", code, source.name, exc)

            last_date = ""
            if "date" in frame.columns:
                last_date = str(pd.to_datetime(frame["date"]).max().date())
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

    report.elapsed_seconds = time.monotonic() - started
    return report
