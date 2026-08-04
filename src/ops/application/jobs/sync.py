"""sync 任务执行器：行情同步。"""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from src.ops.application.jobs.context import JobContext, JobError

logger = logging.getLogger(__name__)


def execute_sync(
    config: dict[str, Any],
    context: JobContext,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """同步行情。默认只同步证券列表里的全部标的，走 watermark 增量。

    历史日 K 不含当日；末尾用实时行情给**全市场**补当日 OHLC
    （即使 limit 只回填了部分历史，最新交易日也能跟上今天）。

    ``mode``:
    - ``full``（默认）：watermark 增量拉历史 + 当日 spot
    - ``today_refresh``：只刷当日 OHLC（盘后重刷用，避免全市场历史重拉）
    """
    from src.market import (
        MarketStore,
        apply_today_spot,
        refresh_adjust_factors,
        sync_instruments,
        sync_quotes,
    )

    mode = str(config.get("mode") or "full").strip() or "full"
    with_factors = bool(config.get("with_factors", True))
    with context.market() as store:
        if config.get("refresh_instruments"):
            sync_instruments(store)
        instruments = store.list_instruments()
        codes = [item["code"] for item in instruments]
        types = {item["code"]: item["instrument_type"] for item in instruments}

    explicit = config.get("codes")
    if explicit:
        codes = [str(code).strip() for code in explicit if str(code).strip()]
        types = {}
    if config.get("limit"):
        codes = codes[: int(config["limit"])]
    if not codes:
        raise JobError("没有可同步的标的，请先刷新证券列表")

    # 先把已知总数交给 bootstrap；单只行情请求完成前，进度条也能显示真实范围。
    if progress:
        progress(0, len(codes), "")

    report_payload = {
        "total": len(codes),
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
        "rows_written": 0,
        "failures": [],
        "elapsed_seconds": 0.0,
    }
    factors_refreshed = 0

    if mode != "today_refresh":
        report = sync_quotes(
            lambda: MarketStore(context.market_db),
            codes,
            instrument_types=types or None,
            workers=int(config.get("workers", 4)),
            min_interval=float(config.get("interval", 0.15)),
            force=bool(config.get("force", False)),
            with_factors=with_factors,
            # 下面单独做全市场当日补数，避免 limit 场景只更新 200 只。
            with_today_spot=False,
            progress=progress,
        )
        report_payload = {
            "total": report.total,
            "succeeded": report.succeeded,
            "skipped": report.skipped,
            "failed": report.failed,
            "rows_written": report.rows_written,
            "failures": report.failures[:20],
            "elapsed_seconds": round(report.elapsed_seconds, 2),
        }
    elif with_factors:
        # 日终只刷 spot 时仍要刷过期复权因子，否则除权后 qfq 选股长期失真
        try:
            factors_refreshed = refresh_adjust_factors(
                lambda: MarketStore(context.market_db),
                codes,
                instrument_types=types or None,
                workers=int(config.get("workers", 4)),
                min_interval=float(config.get("interval", 0.15)),
                progress=progress,
            )
        except Exception as exc:
            logger.warning("日终刷新复权因子失败：%s", exc)

    spot_codes = codes
    spot_types = types
    if not explicit:
        with context.market() as store:
            instruments = store.list_instruments()
            spot_codes = [item["code"] for item in instruments]
            spot_types = {
                item["code"]: item["instrument_type"] for item in instruments
            }

    spot_rows = 0
    turnover_repair: dict[str, Any] = {}
    if spot_codes:
        with context.market() as store:
            try:
                spot_rows = apply_today_spot(
                    store, spot_codes, instrument_types=spot_types or None
                )
            except Exception as exc:
                logger.warning("补当日实时日 K 失败：%s", exc)
            try:
                from datetime import date, timedelta

                from src.market import backfill_missing_turnover

                # 同步后只扫近三周，避免每次全历史扫 16M 行；深度回填走 repair API。
                since = (date.today() - timedelta(days=21)).isoformat()
                turnover_repair = backfill_missing_turnover(store, since=since)
            except Exception as exc:
                logger.warning("回填换手率失败：%s", exc)

    return {
        **report_payload,
        "rows_written": int(report_payload.get("rows_written") or 0) + spot_rows,
        "spot_rows": spot_rows,
        "factors_refreshed": factors_refreshed,
        "turnover_repair": turnover_repair,
        "mode": mode,
    }
