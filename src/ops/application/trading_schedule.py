"""交易日选股调度：结构化配置 ↔ cron，并预览下次运行时刻。

不依赖第三方 cron UI。仅覆盖工作日（周一至周五）：
- once：每个交易日定点 HH:MM
- interval：交易时段内每隔 N 分钟（小时粒度写入 cron，分钟预览用结构化窗口）
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

ScheduleMode = Literal["off", "once", "interval"]

ALLOWED_INTERVALS = frozenset({5, 10, 15, 30, 60})


class TradingScheduleError(ValueError):
    """调度参数非法。"""


def compose_trading_cron(
    mode: ScheduleMode,
    *,
    run_hour: int = 15,
    run_minute: int = 30,
    interval_minutes: int = 10,
    window_start_hour: int = 9,
    window_start_minute: int = 30,
    window_end_hour: int = 14,
    window_end_minute: int = 50,
) -> str:
    """把结构化调度收成 APScheduler 可用的 5 段 cron。off → 空串。"""
    if mode == "off":
        return ""
    if mode == "once":
        _check_hour_minute(run_hour, run_minute)
        # mon-fri：APScheduler 0=周一；勿写 Unix 习惯的 1-5（会被当成周二–周六）
        return f"{int(run_minute)} {int(run_hour)} * * mon-fri"
    if mode == "interval":
        interval = _interval_value(interval_minutes)
        start_h = int(window_start_hour)
        end_h = int(window_end_hour)
        _interval_window_bounds(
            start_h,
            window_start_minute,
            end_h,
            window_end_minute,
        )
        return f"*/{interval} {start_h}-{end_h} * * mon-fri"
    raise TradingScheduleError(f"未知调度方式：{mode}")


def preview_trading_runs(
    mode: ScheduleMode,
    *,
    now: datetime | None = None,
    run_hour: int = 15,
    run_minute: int = 30,
    interval_minutes: int = 10,
    window_start_hour: int = 9,
    window_start_minute: int = 30,
    window_end_hour: int = 14,
    window_end_minute: int = 50,
    sessions: Sequence[Mapping[str, Any]] | None = None,
    limit: int = 5,
) -> list[str]:
    """预览下次运行（完整 ``YYYY-MM-DD HH:MM``）。定点 1 条，间隔最多 limit 条。"""
    if mode == "off":
        return []
    cursor = now or datetime.now()
    if mode == "once":
        _check_hour_minute(run_hour, run_minute)
        target = _next_weekday_at(cursor, int(run_hour), int(run_minute))
        return [_fmt(target)]

    interval = _interval_value(interval_minutes)
    start_h, start_m = int(window_start_hour), int(window_start_minute)
    end_h, end_m = int(window_end_hour), int(window_end_minute)
    start_min, end_min = _interval_window_bounds(start_h, start_m, end_h, end_m)
    session_bounds = _session_window_bounds(sessions)

    out: list[str] = []
    day = cursor.date()
    # 最多向前看 14 个自然日，保证能凑满 limit 个工作日槽位
    for _ in range(14):
        if day.weekday() < 5:
            day_slots: list[str] = []
            for minute_of_day in range(start_min, end_min + 1):
                if minute_of_day % interval:
                    continue
                if session_bounds is not None and not any(
                    session_start <= minute_of_day <= session_end
                    for session_start, session_end in session_bounds
                ):
                    continue
                slot = datetime(
                    day.year,
                    day.month,
                    day.day,
                    minute_of_day // 60,
                    minute_of_day % 60,
                )
                if slot >= cursor:
                    day_slots.append(_fmt(slot))
            if day_slots:
                # 同一天：先塞开头，最后强制带上末档（如 14:50），避免只看见 14:00
                if len(day_slots) <= max(1, limit - len(out)):
                    out.extend(day_slots)
                else:
                    remain = max(1, limit - len(out))
                    head_n = max(1, remain - 1)
                    chunk = day_slots[:head_n]
                    last = day_slots[-1]
                    if last not in chunk:
                        chunk.append(last)
                    out.extend(chunk[:remain])
                if len(out) >= limit:
                    return out[:limit]
        day = day + timedelta(days=1)
    return out[:limit]


def is_interval_run_allowed(
    schedule: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> bool:
    """判断结构化 interval 调度是否处于精确时分窗口内。

    cron 只能粗略限定到小时，起止分钟由这里在真正执行前收口；裸 cron 和
    ``once`` 调度仍完全由 cron 决定。
    """
    if not isinstance(schedule, Mapping) or str(schedule.get("mode") or "") != "interval":
        return True
    try:
        _interval_value(schedule.get("interval_minutes", 10))
        start_min, end_min = _interval_window_bounds(
            int(schedule.get("window_start_hour", 9)),
            int(schedule.get("window_start_minute", 30)),
            int(schedule.get("window_end_hour", 14)),
            int(schedule.get("window_end_minute", 50)),
        )
        session_bounds = _session_window_bounds(schedule.get("sessions"))
    except (TypeError, ValueError, TradingScheduleError):
        return False
    current_min = now.hour * 60 + now.minute
    if not start_min <= current_min <= end_min:
        return False
    return session_bounds is None or any(
        session_start <= current_min <= session_end
        for session_start, session_end in session_bounds
    )


def schedule_dict_from_payload(payload: Any) -> dict[str, Any]:
    """从 StrategyJobConfig（或同形对象）抽出可落库的 schedule 字典。"""
    mode = getattr(payload, "schedule_mode", None) or "off"
    return {
        "mode": mode,
        "run_hour": int(getattr(payload, "run_hour", 15)),
        "run_minute": int(getattr(payload, "run_minute", 30)),
        "interval_minutes": int(getattr(payload, "interval_minutes", 10)),
        "window_start_hour": int(getattr(payload, "window_start_hour", 9)),
        "window_start_minute": int(getattr(payload, "window_start_minute", 30)),
        "window_end_hour": int(getattr(payload, "window_end_hour", 14)),
        "window_end_minute": int(getattr(payload, "window_end_minute", 50)),
    }


def _check_hour_minute(hour: int, minute: int) -> None:
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise TradingScheduleError("时分非法")


def _interval_value(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise TradingScheduleError("间隔必须是整数分钟") from exc
    if interval not in ALLOWED_INTERVALS:
        raise TradingScheduleError(
            f"间隔仅支持 {sorted(ALLOWED_INTERVALS)} 分钟，收到 {interval}"
        )
    return interval


def _interval_window_bounds(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> tuple[int, int]:
    _check_hour_minute(start_hour, start_minute)
    _check_hour_minute(end_hour, end_minute)
    start_min = int(start_hour) * 60 + int(start_minute)
    end_min = int(end_hour) * 60 + int(end_minute)
    if start_min > end_min:
        raise TradingScheduleError("时段起点不能晚于终点")
    return start_min, end_min


def _session_window_bounds(
    sessions: Any,
) -> list[tuple[int, int]] | None:
    if sessions is None:
        return None
    if not isinstance(sessions, Sequence) or isinstance(sessions, (str, bytes)) or not sessions:
        raise TradingScheduleError("分段时段必须是非空列表")
    bounds: list[tuple[int, int]] = []
    for session in sessions:
        if not isinstance(session, Mapping):
            raise TradingScheduleError("分段时段格式非法")
        bounds.append(
            _interval_window_bounds(
                int(session.get("start_hour", -1)),
                int(session.get("start_minute", -1)),
                int(session.get("end_hour", -1)),
                int(session.get("end_minute", -1)),
            )
        )
    return bounds


def _next_weekday_at(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < now or candidate.weekday() >= 5:
        candidate = candidate + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate = candidate + timedelta(days=1)
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate


def _fmt(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M")
