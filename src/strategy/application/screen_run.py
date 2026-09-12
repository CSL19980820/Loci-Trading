"""即时选股的**执行体**：按交易日循环选股 + 可选入库，全程写进度快照。

支持单日与区间（≤31 自然日）：按交易日逐日调用通用 ``screen`` +
``persist_screen_candidates``，入库结构不变（同日同池覆盖）。
``start_screen_run_thread`` 负责起后台线程——必须走 ``spawn_tenant_thread``，
裸 ``threading.Thread`` 会丢掉租户 ContextVar。

进度槽本身（``_STATES[tenant][strategy]`` 双层分片、LRU、快照/更新/互斥/取消
旗）住在同目录的 ``screen_run_state.py``；本模块只是它最大的写入方，并负责在
线程入口用 ``screen_run_slot_scope`` 认领「自己这个战法的槽」——**多战法并跑就
靠这一层**，缺了它三条线程会往同一个槽里写。下面把那些符号**原样 re-export**，
让历史导入（路由、``tests/strategy/test_screen_run_*.py``、``tests/conftest.py``）
继续成立；``_STATES`` 是同一个对象而非拷贝。
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date
from typing import Any, Callable

from src.shared.screen_capacity import (
    ScreenCapacityBusy,
    screen_capacity_permit,
    screen_capacity_status,
    screen_permit_wait_sec,
)
from src.shared.tenancy import current_tenant, is_primary_tenant, spawn_tenant_thread
from src.strategy.domain.base import signal_history_bars
from src.strategy.application.screen_run_prepare import ensure_screen_quotes, range_read_scope
from src.strategy.application.screen_dates import (
    ScreenDateError,
    resolve_from_opts,
    window_label,
)
from src.strategy.application.screen_run_state import (  # noqa: F401 - 兼容 re-export
    MAX_CONCURRENT_RUNS,
    MAX_RUNS_PER_TENANT,
    MAX_TENANT_STATES,
    MAX_TOTAL_RUN_SLOTS,
    _LOCK,
    _STATES,
    _blank_state,
    _evict_locked,
    _state_locked,
    _strategy_display_name,
    screen_run_cancel_requested,
    screen_run_request_cancel,
    screen_run_running_strategies,
    screen_run_slot_scope,
    screen_run_snapshot,
    screen_run_snapshot_all,
    screen_run_try_begin,
    screen_run_update,
)




def _capacity_label(opts: dict[str, Any]) -> str:
    """许可持有者标签，进运维快照与「忙」文案。

    非主租户带租户前缀：两个租户同时跑同名战法时，光看战法名分不出是谁占着
    唯一的那个位子。口径与 ops 的 job 槽标签一致。
    """
    slug = str(opts.get("strategy") or "?")
    if is_primary_tenant():
        return f"http:{slug}"
    return f"http:[{current_tenant()}] {slug}"


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
    """后台线程入口：把进度写进**本战法自己的槽**，再跑选股。

    ``screen_run_slot_scope`` 是多战法并跑的关键：下面几十处
    ``screen_run_update(...)`` 都不带 strategy，靠这层 ContextVar 认领槽位。
    少了它，三个战法的线程会一起往「当前这一个」槽里写：进度条互相盖、日志
    串成一锅，取消旗还会跨战法生效（A 点停止把 B 一起停掉）。
    """
    with screen_run_slot_scope(str(opts.get("strategy") or "")):
        _execute_screen_run(
            opts,
            market_factory=market_factory,
            palace_db=palace_db,
            hot_db=hot_db,
        )


def _execute_screen_run(
    opts: dict[str, Any],
    *,
    market_factory: Callable[[], Any],
    palace_db: str | None,
    hot_db: str | None = None,
) -> None:
    """选股 + 可选入库的循环体：槽已由上面的入口绑好，这里只管写进度。

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
        from src.market import should_overlay_live

        refresh_spot = bool(opts.get("refresh_spot", True))
        live_today = should_overlay_live(date.today().isoformat())
        if live_today:
            refresh_spot = False

        # 策略声明 requires_full_history（如递推/长窗口公式）时必须读全量库；
        # 否则默认读滚动热库（近 700 交易日窗口），与全量写库物理隔离。
        engine = None
        try:
            from src.strategy import get as _get_strategy

            engine = _get_strategy(str(opts["strategy"]))
            needs_full = bool(getattr(engine, "requires_full_history", False))
        except Exception:
            needs_full = False

        screen_run_update(
            phase="calendar",
            percent=4,
            message=f"解析交易日 · {label}",
            trade_date=label,
            log_line=f"▸ 窗口 {label}",
        )

        # 面板内存峰值全在下面这段里（4400 只票 x 60 日面板）。进程级许可必须在
        # 打开行情库之前拿到——三档并发在 3.7G 机器上打爆过整个容器，依据见
        # src/shared/screen_capacity.py 的模块 docstring。
        capacity = screen_capacity_status()
        if int(capacity["in_use"]) >= int(capacity["limit"]):
            # 只在真要排队时才提示。空闲时也报「排队中」会让人以为系统忙。
            screen_run_update(
                phase="queued",
                percent=3,
                message="排队等前面的选股…",
                log_line=(
                    f"· 进程内已有 {capacity['in_use']} 个选股在跑"
                    f"（{'、'.join(capacity['holders']) or '?'}），排队中"
                ),
            )
        with ExitStack() as stack:
            try:
                stack.enter_context(
                    screen_capacity_permit(
                        label=_capacity_label(opts),
                        wait_sec=screen_permit_wait_sec(),
                        cancelled=screen_run_cancel_requested,
                    )
                )
            except ScreenCapacityBusy as exc:
                msg = str(exc)
                screen_run_update(
                    status="error",
                    phase="error",
                    message=msg,
                    error=msg,
                    log_line=f"✗ {msg}",
                )
                return
            full = stack.enter_context(market_factory())
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

            if not ensure_screen_quotes(full, days, refresh_spot):
                return

            # 选股读滚动热库（近 700 交易日窗口），与全量写库物理隔离；写操作
            # （apply_today_spot）只碰全量库。策略要求全历史或未配置热库时回退
            # 全量库。镜像失败不阻断：热库缺当日由哨兵/重建任务兜底。
            store = full
            if hot_db and not needs_full:
                from src.market import (
                    hot_fallback_reason,
                    mirror_recent_to_hot,
                    open_market_hot,
                )

                # 预热根数在 try 外面算：算不出来是策略契约问题，不该被下面那个
                # except 归成「镜像热库失败」，那会让人照着错方向查热库。
                warmup_bars = signal_history_bars(engine, params=opts.get("params"))
                try:
                    hot = open_market_hot(hot_db)
                    stack.enter_context(hot)
                    if not live_today:
                        screen_run_update(
                            phase="prepare", percent=6, message="同步选股热库…",
                            log_line="· 同步选股热库（行情与来源回执）…",
                        )
                        mirror_recent_to_hot(full, hot)
                    reason = hot_fallback_reason(
                        full,
                        hot,
                        trade_date=days[0],
                        end=days[-1],
                        warmup_bars=warmup_bars,
                        live_overlay=live_today,
                    )
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

            stack.enter_context(range_read_scope(
                store, engine, days, opts.get("params"), codes=opts.get("codes"), universe=uni,
            ))
            # 数据证据由 screen 在解析当日股票池与预热窗口后读取。
            # 编排层预取全库快照既扫描无关回执，也不能冻结逐日计算时的行情版本。
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
                # 检查点：一个交易日的选股是一整段同步面板计算，中途插不进来。
                # 放在日循环头 = 最坏等一天的耗时，这是不杀线程能给出的最短延迟。
                if screen_run_cancel_requested():
                    screen_run_update(
                        status="cancelled",
                        phase="cancelled",
                        message=f"已停止 · 完成 {index - 1}/{total_days} 个交易日",
                        log_line=(
                            f"■ 已按请求停止 · 已完成 {index - 1}/{total_days} 个交易日"
                            + ("，已完成的部分已入库" if record and written_total else "")
                        ),
                    )
                    return

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
                        live_overlay=should_overlay_live(day),
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
    """尝试启动；占不到槽时返回占用者快照（带 ``busy_reason``）。

    占不到只有两种情况：**这个战法自己**还在跑（``same_strategy``，防重复入库），
    或本租户并发到顶（``tenant_limit``）。**别的战法在跑不算占用**——那是老的
    「全局单槽」语义，已经废掉了。
    """
    slug = str(opts.get("strategy") or "")
    try:
        win_start, win_end = resolve_from_opts(opts)
        label = window_label(win_start, win_end)
    except ScreenDateError as exc:
        screen_run_update(
            status="error", phase="error", message=str(exc), error=str(exc),
            strategy=slug,
            log=["✗ " + str(exc)],
            result=None,
        )
        return screen_run_snapshot(slug)

    busy = screen_run_try_begin(strategy=slug, trade_date=label)
    if busy is not None:
        return busy

    try:
        # 不能裸起 threading.Thread：ContextVar 不跨线程边界，线程里
        # current_tenant() 会掉回主租户，于是 B 的选股候选被静默写进
        # 管理员的 palace.db（不报错、单机形态下 100% 观察不到）。
        spawn_tenant_thread(
            execute_screen_run,
            kwargs={
                "opts": opts,
                "market_factory": market_factory,
                "palace_db": palace_db,
                "hot_db": hot_db,
            },
            # 线程名带 slug：多战法并跑时 py-spy / 线程栈里才认得出是谁在跑。
            name=f"loci-screen-run-{slug or 'unknown'}",
        )
    except Exception as exc:
        message = f"后台选股启动失败：{type(exc).__name__}: {exc}"
        screen_run_update(
            status="error",
            phase="error",
            message=message,
            error=message,
            strategy=slug,
            log_line=f"✗ {message}",
        )
    return screen_run_snapshot(slug)
