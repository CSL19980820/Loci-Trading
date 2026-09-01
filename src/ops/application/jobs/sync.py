"""sync 任务执行器：行情同步。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
import logging
from typing import Any

from src.ops.application.jobs.context import JobContext, JobError, JobSkipped
from src.ops.application.jobs.market_gate import (
    market_heavy_slot,
    skip_reason_for_intraday_sync,
)

logger = logging.getLogger(__name__)

# 整批现价挂掉时的统一人话（不按 5000+ 代码刷屏）
_SPOT_BATCH_SKIP = "当日现价暂时拉不到（源忙或断网），已跳过，不影响已有历史日K"


def _is_batch_spot_outage(error: str) -> bool:
    """整批现价路由失败：源互抢/断网/全空，不是单票停牌。"""
    text = str(error or "")
    markers = (
        "现价全部失败",
        "当日现价暂时拉不到",
        "请求进行中",
        "等待来源空闲超时",
        "ConnectionError",
        "RemoteDisconnected",
        "Connection aborted",
        "实时行情返回空",
        "实时行情日期落后",
        "实时行情失败",
        "spot 入库失败",
        "没有启用的 spot_batch",
    )
    return any(marker in text for marker in markers)


def _is_soft_spot_gap(error: str) -> bool:
    """单票现价缺口：停牌/退市等；一律不计入硬 failed、不刷企微。"""
    text = str(error or "")
    if _is_batch_spot_outage(text):
        return True
    soft_markers = (
        "行情源没返回这只票",
        "当日现价无效",
        "只有旧日期 ",
        # 兼容旧回执文案
        "spot 响应未返回该代码",
        "spot OHLC 校验拒绝",
        "spot 响应返回 ",
    )
    return any(marker in text for marker in soft_markers)


def _merge_spot_receipts(
    report_payload: dict[str, Any], receipts: list[dict[str, Any]]
) -> None:
    """把 spot 终态并入作业输出。

    现价失败**永不**累加硬 ``failed``（避免 5000+ 条刷企微）；
    整批挂掉只留一条 ``spot_skip_reason``，单票缺口进 ``spot_gaps``。
    """
    if not receipts:
        return
    evidence = report_payload["source_evidence"]
    evidence_receipts = evidence["receipts"]
    selected_sources = evidence["selected_sources"]
    unresolved_codes = evidence["unresolved_codes"]
    known_unresolved = {str(code) for code in unresolved_codes}
    gap_codes: set[str] = set()
    spot_gaps = report_payload.setdefault("spot_gaps", [])
    if not isinstance(spot_gaps, list):
        spot_gaps = []
        report_payload["spot_gaps"] = spot_gaps
    batch_outage = False
    soft_gap_count = int(report_payload.get("spot_gap_count") or 0)

    for receipt in receipts:
        evidence_receipts.append(dict(receipt))
        code = str(receipt.get("code") or "")
        unresolved = bool(receipt.get("unresolved"))
        state = str(receipt.get("state") or "")
        selected_source = str(receipt.get("selected_source") or "")
        error = str(receipt.get("error") or "spot 同步失败")
        if selected_source and state == "selected" and not unresolved:
            selected_sources[selected_source] = int(selected_sources.get(selected_source, 0)) + 1
        if not (unresolved or state == "failed") or not code:
            continue
        if code not in known_unresolved:
            unresolved_codes.append(code)
            known_unresolved.add(code)
        if _is_batch_spot_outage(error):
            batch_outage = True
            continue
        # 单票缺口：软跳过，绝不进 failures/failed
        soft_gap_count += 1
        if code in gap_codes:
            continue
        gap_codes.add(code)
        if len(spot_gaps) < 20:
            if not _is_soft_spot_gap(error):
                error = "行情源没返回这只票（常见于停牌/退市）"
            spot_gaps.append((code, error))

    report_payload["spot_gap_count"] = soft_gap_count
    if batch_outage:
        report_payload["spot_skip_reason"] = _SPOT_BATCH_SKIP


#: 作业结果里只留失败样本。逐票回执的权威副本在 market.db.source_route_receipts，
#: 把全市场 5000+ 条连同 attempts/coverage 一起塞进 ops.db 的 result_json，单条运行
#: 记录会涨到几百 MB（实测 257 MB/条），运维库随之被撑到 GB 级。
_EVIDENCE_RECEIPT_LIMIT = 50


def _compact_source_evidence(payload: dict[str, Any]) -> None:
    """把逐票回执压成「失败样本 + 计数」，避免运维库重复存一份权威证据。"""
    evidence = payload.get("source_evidence")
    if not isinstance(evidence, dict):
        return
    receipts = evidence.get("receipts")
    if not isinstance(receipts, list):
        return
    failed = [
        item
        for item in receipts
        if isinstance(item, dict)
        and (item.get("unresolved") or str(item.get("state") or "") == "failed")
    ]
    evidence["receipts"] = failed[:_EVIDENCE_RECEIPT_LIMIT]
    evidence["receipts_total"] = len(receipts)
    evidence["receipts_failed"] = len(failed)
    evidence["receipts_source"] = "market.db:source_route_receipts"


def _spot_runner_failure_receipts(codes: list[str], error: str) -> list[dict[str, Any]]:
    """仅在 spot 调用尚未来得及返回自身回执时保留作业级失败事实。"""
    # 整批挂掉只留一条摘要回执，避免 5000+ 条同文案淹没证据库
    human = _SPOT_BATCH_SKIP if _is_batch_spot_outage(error) else str(error)
    sample = codes[:1] or [""]
    return [
        {
            "code": sample[0] or "*",
            "lane": "spot_batch",
            "attempts": [{"source_id": "spot_runner", "state": "failed", "error": human}],
            "unresolved": True,
            "state": "failed",
            "error": human,
            "batch_size": len(codes),
        }
    ]


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
    - ``today_refresh``：盘后重刷当日——复权因子 + 当日 spot + **权威源定稿**
      （近窗 20 根，不重拉全市场历史）。定稿必须排在 spot 之后，理由见
      ``_finalize_today_with_authoritative``。
    """
    from src.market import (
        MarketWriteBusy,
        market_write_lock,
        sync_instruments,
    )

    mode = str(config.get("mode") or "full").strip() or "full"
    with_factors = bool(config.get("with_factors", True))
    with context.market() as store:
        market_db_path = getattr(store, "db_path", None) or context.market_db

    # 闸门放在这里而不是只放在 run_job：HTTP /api/market/sync、首启 bootstrap
    # 回填、CLI 都直接调 execute_sync，绕开 run_job 就等于绕开闸门——2026-08-24
    # 的 bootstrap 同步正是这样在闸门视野之外占着写锁，把 15:30 三只选股拖死。
    def _yield_for_tail() -> None:
        reason = skip_reason_for_intraday_sync("sync", {"config": config})
        if reason:
            raise JobSkipped(reason)
        context.check_cancelled()

    try:
        _yield_for_tail()
        with market_heavy_slot("sync", f"sync:{mode}"), market_write_lock(
            market_db_path, label=f"sync:{mode}"
        ):
            _yield_for_tail()
            instrument_refresh: dict[str, Any] = {"status": "disabled"}
            with context.market() as store:
                force_refresh = bool(config.get("refresh_instruments"))
                daily_refresh = bool(config.get("refresh_instruments_daily"))
                snapshot_date = (
                    store.instrument_snapshot_date()
                    if daily_refresh and not force_refresh
                    else ""
                )
                refresh_due = force_refresh or (
                    daily_refresh and snapshot_date != date.today().isoformat()
                )
                if refresh_due:
                    try:
                        refreshed = sync_instruments(store)
                        instrument_refresh = {
                            "status": "refreshed",
                            "rows": int(refreshed),
                        }
                    except Exception as exc:
                        if force_refresh:
                            raise
                        instrument_refresh = {
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        }
                        logger.warning(
                            "每日证券目录刷新失败，继续使用本地目录：%s", exc
                        )
                elif daily_refresh:
                    instrument_refresh = {
                        "status": "current",
                        "snapshot_date": snapshot_date,
                    }
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

            # 单只请求完成前，bootstrap 也能先显示真实总数。
            if progress:
                progress(0, len(codes), "")

            result = _execute_sync_locked(
                config,
                context,
                mode=mode,
                with_factors=with_factors,
                codes=codes,
                types=types,
                explicit=bool(explicit),
                progress=progress,
            )
            return {**result, "instrument_refresh": instrument_refresh}
    except MarketWriteBusy as exc:
        raise JobError(str(exc)) from exc


def _finalize_today_with_authoritative(
    config: dict[str, Any],
    context: JobContext,
    *,
    codes: list[str],
    types: dict[str, str],
    progress: Callable[[int, int, str], None] | None,
) -> dict[str, Any]:
    """日终定稿：用 hist_daily 权威源把当日重写成正式日 K。**必须排在 spot 之后。**

    **为什么缺了这一步**：``quotes_daily`` 的 upsert 是 ``source=excluded.source``
    （后写覆盖先写，见 ``store_rw._write_quote_payload``），而 ``apply_today_spot``
    在**每一种** mode 里都是最后一个写库的，它写进去的 source 恒带 ``_spot``
    后缀。于是只要 spot 这一趟成功，当日行在任何同步跑完之后都还是**临时行**；
    正式日 K 要等第二天早上增量近窗（``sync._INCREMENTAL_MIN_BARS=20``）回头重写
    才落。当天的 15:30 选股、当日回测与复盘读到的全是临时行：没有 source
    receipt（``strict_pit`` 直接拒收），回退源的 ``amount`` 还是 ``close×volume``
    合成的假值。

    **证据**（开发机 2026-08-25 16:10 热库重建快照，``market_hot.db``）：当日
    5542 行**全部**是 ``tencent_spot``，权威源 0 行。``market.db`` 现在能看到
    4400 行 ``tencent``，是当晚 19:12 手工补跑一次 ``mode=full`` 才写进去的，
    不是流水线的产出——``data_quality`` 把那个事后状态记成了「日终之后残留
    20.6%」，实际的流水线终态是 100%。

    代价：通达信本地二进制近窗 20 根，全市场约 2 分钟（ADR-013 实测增量
    43.1 票/秒）。排在 spot 之后，不影响 15:30 选股吃当日快照。

    失败只记录不抛：spot 行还在库里，有临时行比当天没有数据强，不该把整条
    日终任务刷红。体检的 ``last_day_authoritative`` 会在 16 点之后把它报出来。
    """
    from src.market import MarketStore, sync_quotes

    try:
        report = sync_quotes(
            lambda: MarketStore(context.market_db),
            codes,
            instrument_types=types or None,
            workers=int(config.get("workers", 4)),
            min_interval=float(config.get("interval", 0.15)),
            # 复权因子上面已单独刷过；当日 spot 也已写过。这一趟只补正式日 K。
            with_factors=False,
            with_today_spot=False,
            progress=progress,
        )
    except Exception as exc:
        logger.warning("日终定稿（权威源重写当日）失败：%s", exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
    return {
        "status": "ok",
        "succeeded": report.succeeded,
        "skipped": report.skipped,
        "failed": report.failed,
        "rows_written": report.rows_written,
        "elapsed_seconds": round(report.elapsed_seconds, 2),
    }


def _execute_sync_locked(
    config: dict[str, Any],
    context: JobContext,
    *,
    mode: str,
    with_factors: bool,
    codes: list[str],
    types: dict[str, str],
    explicit: bool,
    progress: Callable[[int, int, str], None] | None,
) -> dict[str, Any]:
    from src.market import (
        MarketStore,
        apply_today_spot,
        refresh_adjust_factors,
        sync_quotes,
    )

    report_payload = {
        "total": len(codes),
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
        "rows_written": 0,
        "failures": [],
        "spot_gaps": [],
        "spot_gap_count": 0,
        "spot_skip_reason": "",
        "source_evidence": {
            "receipts": [],
            "selected_sources": {},
            "unresolved_codes": [],
        },
        "elapsed_seconds": 0.0,
    }
    factors_refreshed = 0
    factors_error = ""

    reason = skip_reason_for_intraday_sync("sync", {"config": config})
    if reason:
        raise JobSkipped(reason)
    context.check_cancelled()

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
            "spot_gaps": [],
            "spot_gap_count": 0,
            "spot_skip_reason": "",
            "source_evidence": {
                "receipts": report.source_receipts,
                "selected_sources": report.selected_sources,
                "unresolved_codes": report.unresolved_codes,
            },
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
            # 只记日志等于静默失败：除权后 qfq 会长期失真，运维页必须看得见。
            factors_error = f"{type(exc).__name__}: {exc}"
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
        spot_receipts: list[dict[str, Any]] = []
        with context.market() as store:
            try:
                spot_rows = apply_today_spot(
                    store,
                    spot_codes,
                    instrument_types=spot_types or None,
                    source_receipts=spot_receipts,
                )
            except Exception as exc:
                logger.warning("补当日实时日 K 失败：%s", exc)
                if not spot_receipts:
                    spot_receipts = _spot_runner_failure_receipts(
                        spot_codes, f"{type(exc).__name__}: {exc}"
                    )
            _merge_spot_receipts(report_payload, spot_receipts)
            try:
                from datetime import date, timedelta

                from src.market import backfill_missing_turnover

                # 同步后只扫近三周，避免每次全历史扫 16M 行；深度回填走 repair API。
                since = (date.today() - timedelta(days=21)).isoformat()
                turnover_repair = backfill_missing_turnover(store, since=since)
            except Exception as exc:
                turnover_repair = {"error": f"{type(exc).__name__}: {exc}"}
                logger.warning("回填换手率失败：%s", exc)

    # 日终定稿必须排在 spot 之后：upsert 后写覆盖先写，反过来就会被 spot
    # 重新盖成临时行——那正是这一步要修的形态。
    finalize: dict[str, Any] = {}
    if mode == "today_refresh":
        finalize = _finalize_today_with_authoritative(
            config, context, codes=codes, types=types, progress=progress
        )

    # 全量库写事务全部结束后，把最近交易日增量镜像到滚动热读库。
    # 热库是派生缓存：镜像失败只记 warning + payload 字段，绝不把同步标记 failed。
    from src.market import mirror_recent_to_hot

    hot_mirror: dict[str, Any] = {}
    try:
        with context.market() as full, context.market_hot() as hot:
            mirror = mirror_recent_to_hot(full, hot)
        hot_mirror = {key: mirror[key] for key in ("mode", "quotes", "end")}
    except Exception as exc:
        logger.warning("镜像热库失败（热库为派生缓存，不影响同步结果）：%s", exc)
        hot_mirror = {"error": str(exc)}

    _compact_source_evidence(report_payload)
    return {
        **report_payload,
        "rows_written": int(report_payload.get("rows_written") or 0)
        + spot_rows
        + int(finalize.get("rows_written") or 0),
        "spot_rows": spot_rows,
        "factors_refreshed": factors_refreshed,
        "factors_error": factors_error,
        "turnover_repair": turnover_repair,
        "finalize": finalize,
        "hot_mirror": hot_mirror,
        "mode": mode,
    }
