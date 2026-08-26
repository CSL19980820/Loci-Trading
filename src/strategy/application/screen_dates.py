"""选股交易日窗口：单日与区间（跨度 ≤ 一个月）解析。"""
from __future__ import annotations

from datetime import date
from typing import Any

MAX_INCLUSIVE_DAYS = 31


class ScreenDateError(ValueError):
    """交易日窗口不合法。"""


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ScreenDateError(f"日期格式无效：{value}") from exc


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


def resolve_from_opts(opts: dict[str, Any]) -> tuple[str | None, str | None]:
    return resolve_screen_window(
        date=opts.get("date"),
        start=opts.get("start"),
        end=opts.get("end"),
    )
