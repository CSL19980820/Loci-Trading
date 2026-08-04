"""选股交易日窗口：单日与区间（跨度 ≤ 一个月）解析。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

MAX_INCLUSIVE_DAYS = 31


class ScreenDateError(ValueError):
    """交易日窗口不合法。"""


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ScreenDateError(f"日期格式无效：{value}") from exc


def inclusive_day_span(start: str, end: str) -> int:
    return (_parse_day(end) - _parse_day(start)).days + 1


def assert_window_ok(start: str, end: str) -> None:
    a = _parse_day(start)
    b = _parse_day(end)
    if a > b:
        raise ScreenDateError(f"起始日不能晚于结束日：{start} → {end}")
    span = (b - a).days + 1
    if span > MAX_INCLUSIVE_DAYS:
        raise ScreenDateError(
            f"选股跨度不能超过一个月（最多 {MAX_INCLUSIVE_DAYS} 个自然日），"
            f"当前 {start} → {end} 共 {span} 天"
        )


def resolve_screen_window(
    *,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[str | None, str | None]:
    """归一化为 ``(start, end)``。

    - 都空：运行时取行情最新交易日（单日）
    - 仅 ``date``：单日
    - ``start``/``end``：区间（可相等）；若同时传 ``date`` 则忽略 ``date``
    """
    start_s = str(start or "").strip() or None
    end_s = str(end or "").strip() or None
    date_s = str(date or "").strip() or None

    if start_s or end_s:
        if not start_s or not end_s:
            raise ScreenDateError("区间选股需同时提供 start 与 end")
        assert_window_ok(start_s, end_s)
        return start_s, end_s

    if date_s:
        assert_window_ok(date_s, date_s)
        return date_s, date_s

    return None, None


def window_label(start: str | None, end: str | None) -> str:
    if not start and not end:
        return "最新交易日"
    if start and end and start != end:
        return f"{start}→{end}"
    return str(start or end or "")


def preset_range(kind: str, *, today: date | None = None) -> tuple[str, str]:
    """前端快捷泡同源算法（自然日；交易日过滤留给行情日历）。"""
    base = today or date.today()
    kind = str(kind or "").strip().lower()

    if kind in {"today", "今日"}:
        day = base.isoformat()
        return day, day

    if kind in {"this_week", "本周"}:
        monday = base - timedelta(days=base.weekday())
        return monday.isoformat(), base.isoformat()

    if kind in {"last_week", "上周"}:
        monday = base - timedelta(days=base.weekday() + 7)
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()

    if kind in {"last_30", "近一月", "near_month"}:
        start = base - timedelta(days=MAX_INCLUSIVE_DAYS - 1)
        return start.isoformat(), base.isoformat()

    if kind in {"prev_month", "上一月"}:
        first_this = base.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev.isoformat(), last_prev.isoformat()

    raise ScreenDateError(f"未知快捷区间：{kind}")


def resolve_from_opts(opts: dict[str, Any]) -> tuple[str | None, str | None]:
    return resolve_screen_window(
        date=opts.get("date"),
        start=opts.get("start"),
        end=opts.get("end"),
    )


def iso_today() -> str:
    return date.today().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).strip()[:10])
