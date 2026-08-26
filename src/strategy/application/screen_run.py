"""即时选股进度快照（内存；仿 bootstrap，供前端轮询）。

支持单日与区间（≤31 自然日）：按交易日逐日调用通用 ``screen`` +
``persist_screen_candidates``，入库结构不变（同日同池覆盖）。
"""
from __future__ import annotations

from contextlib import ExitStack
import threading
from datetime import date
from typing import Any, Callable

from src.strategy.application.screen_dates import (
    ScreenDateError,
    resolve_from_opts,
    window_label,
)

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "status": "idle",
    "phase": "",
    "percent": 0.0,
    "message": "",
    "strategy": "",
    "trade_date": "",
    "log": [],
    "result": None,
    "error": "",
}


def screen_run_snapshot() -> dict[str, Any]:
    with _LOCK:
        snap = dict(_STATE)
        snap["log"] = list(_STATE.get("log") or [])
        return snap


def screen_run_update(**kwargs: Any) -> None:
    with _LOCK:
        if "log_line" in kwargs:
            line = str(kwargs.pop("log_line") or "").strip()
            if line:
                log = list(_STATE.get("log") or [])
                log.append(line)
                _STATE["log"] = log[-120:]
        _STATE.update(kwargs)
        if _STATE.get("status") == "done":
            _STATE["percent"] = 100.0


def _strategy_display_name(slug: str) -> str:
    """用户可见战法名；解析失败时退回 slug（库内/路由仍用 slug）。"""
    text = str(slug or "").strip()
    if not text:
        return ""
    try:
        from src.strategy.application.catalog import get

        name = str(getattr(get(text), "name", "") or "").strip()
        return name or text
    except Exception:
        return text


def screen_run_try_begin(*, strategy: str, trade_date: str) -> dict[str, Any] | None:
    """若已在 running 返回快照；否则置 running 并返回 None。"""
    display = _strategy_display_name(strategy)
    with _LOCK:
        if _STATE.get("status") == "running":
            return dict(_STATE)
        _STATE.update(
            {
                "status": "running",
                "phase": "start",
                "percent": 2.0,
                "message": "准备选股…",
                "strategy": strategy,
                "trade_date": trade_date or "",
                "log": [
                    f"▶ 开始选股 {display}"
                    + (f" · {trade_date}" if trade_date else "")
                ],
                "result": None,
                "error": "",
            }
        )
    return None


def _result_body(result: Any, recorded: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "strategy": result.strategy_slug,
        "strategy_revision": result.strategy_revision,
        "trade_date": result.trade_date,
        "entry_timing": result.entry_timing,
        "universe_size": result.universe_size,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "params": result.params,
        "effective_params": result.effective_params,
        "picks": result.picks,
        "watch_picks": list(getattr(result, "watch_picks", None) or []),
        "health": result.health,
        "universe": result.universe,
        "universe_funnel": result.universe_funnel,
        "data_snapshot": result.data_snapshot,
        "recorded": recorded,
    }


def execute_screen_run(
    opts: dict[str, Any],
    *,
    market_factory: Callable[[], Any],
    palace_db: str | None,
    hot_db: str | None = None,
) -> None:
    """后台线程入口：选股 + 可选入库，全程写进度快照。

    hot_db 非空时：日历计算与 spot 刷新写全量库（market_factory），随后把
    最近交易日镜像进热库，选股只读热库（近 700 交易日窗口）；策略声明
    ``requires_full_history`` 或未配置热库时回退全量库。
    """
    try:
        from src.market import DataQualityError
        from src.strategy import screen
        from src.strategy.application.persist import persist_screen_candidates
        from src.strategy.domain.base import StrategyError

        try:
            win_start, win_end = resolve_from_opts(opts)
        except ScreenDateError as exc:
            screen_run_update(
                status="error", phase="error", message=str(exc), error=str(exc),
                log_line=f"✗ {exc}",
            )
            return

        label = window_label(win_start, win_end)
        uni = opts.get("universe")
        if uni is not None and not isinstance(uni, dict):
            uni = None
        record = bool(opts.get("record_candidates", True))
        health_check = not bool(opts.get("skip_health_check"))
        refresh_spot = bool(opts.get("refresh_spot", True))

        # 策略声明 requires_full_history（如递推/长窗口公式）时必须读全量库；
        # 否则默认读滚动热库（近 700 交易日窗口），与全量写库物理隔离。
        try:
            from src.strategy import get as _get_strategy

            needs_full = bool(
                getattr(_get_strategy(str(opts["strategy"])), "requires_full_history", False)
            )
        except Exception:
            needs_full = False

        screen_run_update(
            phase="calendar",
            percent=4,
            message=f"解析交易日 · {label}",
            trade_date=label,
            log_line=f"▸ 窗口 {label}",
        )

        with ExitStack() as stack, market_factory() as full:
            if win_start and win_end:
                days = full.trading_days(start=win_start, end=win_end)
                # 休市点「今日」会得到空窗口：回落到窗口末日之前最近交易日。
                if not days and win_start == win_end:
                    prior = full.trading_days(end=win_end)
                    if prior:
                        days = [prior[-1]]
                        screen_run_update(
                            log_line=f"· {win_end} 非交易日，改用 {days[0]}",
                            message=f"改用最近交易日 {days[0]}",
                        )
            else:
                latest = full.trading_days()
                days = [latest[-1]] if latest else []

            if not days:
                msg = f"窗口内无交易日：{label}" if win_start else "行情仓没有任何交易日数据"
                screen_run_update(
                    status="error", phase="error", message=msg, error=msg,
                    log_line=f"✗ {msg}",
                )
                return

            # 与 job:screen 对齐：窗口含今天时保证「今日日 K 可用」。
            # 覆盖已达标则跳过 spot，避免与盘后同步抢写把选股打死。
            today = date.today().isoformat()
            if refresh_spot and today in days:
                from src.market.application.screen_spot import (
                    ScreenSpotError,
                    ensure_today_quotes_for_screen,
                )

                instruments = full.list_instruments()
                spot_codes = [item["code"] for item in instruments]
                spot_types = {
                    item["code"]: item["instrument_type"] for item in instruments
                }
                screen_run_update(
                    phase="spot",
                    percent=5,
                    message="检查当日行情…",
                    log_line=f"↻ 准备当日行情（{len(spot_codes)} 只）",
                )
                try:
                    ensured = ensure_today_quotes_for_screen(
                        full,
                        spot_codes,
                        instrument_types=spot_types or None,
                    )
                except ScreenSpotError as exc:
                    msg = str(exc)
                    screen_run_update(
                        status="error",
                        phase="error",
                        message=msg,
                        error=msg,
                        log_line=f"✗ {msg}",
                    )
                    return
                except Exception as exc:
                    msg = f"选股前准备当日行情失败，已阻断选股：{exc}"
                    screen_run_update(
                        status="error",
                        phase="error",
                        message=msg,
                        error=msg,
                        log_line=f"✗ {msg}",
                    )
                    return
                screen_run_update(
                    log_line=f"✓ {ensured.get('message') or '当日行情就绪'}",
                    message=str(ensured.get("message") or "当日行情就绪"),
                    percent=7,
                )

            # 选股读滚动热库（近 700 交易日窗口），与全量写库物理隔离；写操作
            # （apply_today_spot）只碰全量库。策略要求全历史或未配置热库时回退
            # 全量库。镜像失败不阻断：热库缺当日由哨兵/重建任务兜底。
            store = full
            if hot_db and not needs_full:
                from src.market import hot_unusable_reason, mirror_recent_to_hot, open_market_hot

                try:
                    hot = open_market_hot(hot_db)
                    stack.enter_context(hot)
                    mirror_recent_to_hot(full, hot)
                    reason = hot_unusable_reason(full, hot)
                    if reason:
                        screen_run_update(log_line=f"⚠ {reason}，回退全量库")
                        store = full
                    else:
                        store = hot
                except Exception as exc:
                    screen_run_update(
                        log_line=f"⚠ 镜像热库失败，回退全量库：{exc}",
                    )
                    store = full

            # 区间内各日共享同一行情仓版本；每次 screen 都重新扫描快照会把
            # O(区间天数 × 全库) 的审计开销叠加到选股热路径。
            market_snapshot = store.data_snapshot()
            total_days = len(days)
            screen_run_update(
                log_line=f"· 共 {total_days} 个交易日待跑",
                message=f"共 {total_days} 个交易日",
                percent=8,
            )

            names = {
                item["code"]: item["name"] for item in store.list_instruments(status="")
            } if record else {}

            # 仓内最新交易日：只有跑这一天才算「真选」；更早日期一律回填源，
            # 避免区间重放覆盖 job:screen / 盘后结果污染首页昨选。
            coverage_last = str((store.coverage() or {}).get("last_date") or "")
            live_day = coverage_last or (days[-1] if days else "")

            day_rows: list[dict[str, Any]] = []
            written_total = 0
            last_body: dict[str, Any] | None = None
            elapsed_total = 0.0

            for index, day in enumerate(days, start=1):
                base = 8.0 + 84.0 * ((index - 1) / max(total_days, 1))
                span = 84.0 / max(total_days, 1)

                def on_progress(
                    phase: str,
                    percent: float,
                    message: str,
                    *,
                    _base=base,
                    _span=span,
                    _day=day,
                    _index=index,
                ) -> None:
                    mapped = _base + _span * max(0.0, min(1.0, percent / 100.0)) * 0.85
                    screen_run_update(
                        phase=phase,
                        percent=mapped,
                        message=f"[{_index}/{total_days}] {_day} · {message}",
                        trade_date=_day,
                        log_line=f"[{_index}/{total_days}] {_day} · {message}",
                    )

                screen_run_update(
                    phase="day",
                    percent=base,
                    message=f"[{index}/{total_days}] 选股 {day}",
                    trade_date=day,
                    log_line=f"▷ [{index}/{total_days}] 开始 {day}",
                )

                try:
                    result = screen(
                        store,
                        str(opts["strategy"]),
                        trade_date=day,
                        params=opts.get("params"),
                        codes=opts.get("codes"),
                        universe=uni,
                        health_check=health_check and index == 1,
                        on_progress=on_progress,
                        data_snapshot=market_snapshot,
                    )
                except DataQualityError as exc:
                    screen_run_update(
                        status="error", phase="error", message=str(exc), error=str(exc),
                        log_line=f"✗ 阻断 {day}：{exc}",
                    )
                    return
                except StrategyError as exc:
                    screen_run_update(
                        status="error", phase="error", message=str(exc), error=str(exc),
                        log_line=f"✗ 策略错误 {day}：{exc}",
                    )
                    return

                elapsed_total += float(result.elapsed_seconds or 0)
                pick_n = len(result.picks)
                watch_n = len(getattr(result, "watch_picks", None) or [])
                screen_run_update(
                    percent=base + span * 0.88,
                    message=(
                        f"[{index}/{total_days}] {day} · 正式 {pick_n} 只"
                        f" · 观察 {watch_n} 只"
                    ),
                    log_line=(
                        f"✓ [{index}/{total_days}] {day} 正式 {pick_n} 只"
                        f" · 观察 {watch_n} 只"
                        f"（宇宙 {result.universe_size}）"
                    ),
                )

                recorded = None
                if record:
                    screen_run_update(
                        phase="persist",
                        percent=base + span * 0.92,
                        message=f"[{index}/{total_days}] 入库 {day}…",
                        log_line=f"→ [{index}/{total_days}] 写入候选池 {day}",
                    )
                    from src.strategy.application.persist import BACKFILL_SOURCE

                    persist_source = (
                        "api:screen_run" if str(day) == live_day else BACKFILL_SOURCE
                    )
                    recorded = persist_screen_candidates(
                        result,
                        palace_db=palace_db,
                        names=names,
                        pool_id=opts.get("pool_id"),
                        top_n=int(opts.get("top_n") or 0),
                        source=persist_source,
                    )
                    written = int((recorded or {}).get("written") or 0)
                    written_total += written
                    strategy_label = _strategy_display_name(
                        str(getattr(result, "strategy_slug", "") or opts.get("strategy") or "")
                    )
                    screen_run_update(
                        log_line=(
                            f"✓ [{index}/{total_days}] 已入库 {written} 条"
                            f" → {strategy_label} · {day}"
                        ),
                    )

                day_rows.append(
                    {
                        "trade_date": day,
                        "picks": pick_n,
                        "watch_picks": watch_n,
                        "universe_size": result.universe_size,
                        "elapsed_seconds": round(float(result.elapsed_seconds or 0), 3),
                        "recorded": recorded,
                    }
                )
                last_body = _result_body(result, recorded)

        if last_body is None:
            screen_run_update(
                status="error", phase="error", message="未产生选股结果", error="empty",
                log_line="✗ 未产生选股结果",
            )
            return

        last_body["elapsed_seconds"] = round(elapsed_total, 3)
        last_body["range"] = {
            "start": days[0],
            "end": days[-1],
            "trading_days": total_days,
            "days": day_rows,
            "written_total": written_total,
        }
        if total_days > 1 and last_body.get("recorded") is not None:
            last_body["recorded"] = {
                **(last_body.get("recorded") or {}),
                "written_total": written_total,
                "days": total_days,
            }

        screen_run_update(
            status="done",
            phase="done",
            percent=100,
            message=(
                f"完成 · {total_days} 日 · 入库合计 {written_total} 条"
                if record
                else f"完成 · {total_days} 日"
            ),
            trade_date=window_label(days[0], days[-1]),
            result=last_body,
            log_line=(
                f"■ 选股任务结束 · {total_days} 个交易日"
                + (f" · 入库合计 {written_total} 条" if record else "")
            ),
        )
    except Exception as exc:
        screen_run_update(
            status="error",
            phase="error",
            message=str(exc),
            error=str(exc),
            log_line=f"✗ 失败：{exc}",
        )


def start_screen_run_thread(
    opts: dict[str, Any],
    *,
    market_factory: Callable[[], Any],
    palace_db: str | None,
    hot_db: str | None = None,
) -> dict[str, Any]:
    """尝试启动；若已在跑则返回当前快照。"""
    try:
        win_start, win_end = resolve_from_opts(opts)
        label = window_label(win_start, win_end)
    except ScreenDateError as exc:
        screen_run_update(
            status="error", phase="error", message=str(exc), error=str(exc),
            strategy=str(opts.get("strategy") or ""),
            log=["✗ " + str(exc)],
            result=None,
        )
        return screen_run_snapshot()

    busy = screen_run_try_begin(
        strategy=str(opts.get("strategy") or ""),
        trade_date=label,
    )
    if busy is not None:
        return busy

    try:
        threading.Thread(
            target=execute_screen_run,
            kwargs={
                "opts": opts,
                "market_factory": market_factory,
                "palace_db": palace_db,
                "hot_db": hot_db,
            },
            name="loci-screen-run",
            daemon=True,
        ).start()
    except Exception as exc:
        message = f"后台选股启动失败：{type(exc).__name__}: {exc}"
        screen_run_update(
            status="error",
            phase="error",
            message=message,
            error=message,
            log_line=f"✗ {message}",
        )
    return screen_run_snapshot()
