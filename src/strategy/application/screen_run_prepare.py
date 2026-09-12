"""选股任务的数据准备；区间复用只在当前连接和任务内生效。"""
from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from datetime import date
from collections.abc import Sequence
from typing import Any

from src.market import MarketStore, panel_read_window
from src.strategy.application.screen_run_state import screen_run_update
from src.strategy.domain.base import signal_history_bars


def ensure_screen_quotes(full: Any, days: list[str], refresh_spot: bool) -> bool:
    """沿用即时选股的当日行情准备与失败关闭行为。"""
    if not refresh_spot or date.today().isoformat() not in days:
        return True
    from src.market.application.screen_spot import (
        ScreenSpotError,
        ensure_today_quotes_for_screen,
    )

    instruments = full.list_instruments()
    codes = [item["code"] for item in instruments]
    types = {item["code"]: item["instrument_type"] for item in instruments}
    screen_run_update(
        phase="spot", percent=5, message="检查当日行情…",
        log_line=f"↻ 准备当日行情（{len(codes)} 只）",
    )
    try:
        ensured = ensure_today_quotes_for_screen(full, codes, instrument_types=types or None)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ScreenSpotError) else f"选股前准备当日行情失败，已阻断选股：{exc}"
        screen_run_update(
            status="error", phase="error", message=message, error=message,
            log_line=f"✗ {message}",
        )
        return False
    screen_run_update(
        log_line=f"✓ {ensured.get('message') or '当日行情就绪'}",
        message=str(ensured.get("message") or "当日行情就绪"), percent=7,
    )
    return True


def range_read_scope(
    store: Any, engine: Any, days: list[str], params: dict[str, Any] | None,
    *, codes: Sequence[str] | None = None, universe: dict[str, Any] | None = None,
) -> AbstractContextManager[None]:
    """只预读首日预热至区间末日；每日筛选、复权、审计仍使用原入口。"""
    if len(days) < 2 or engine is None or not isinstance(store, MarketStore):
        return nullcontext()
    requested = codes or (universe or getattr(engine, "default_universe", None) or {}).get("codes_include")
    if requested and len(set(requested)) * 4 < len(store.list_instruments(status="")):
        # 小股票池的定向 SQL 比预读全市场更省，避免单票调试反而变慢。
        return nullcontext()
    calendar = store.trading_days(end=days[0])
    if not calendar:
        return nullcontext()
    if getattr(engine, "requires_full_history", False):
        start = calendar[0]
    else:
        bars = signal_history_bars(engine, params=params)
        start = calendar[-min(bars, len(calendar))]
    return panel_read_window(store, start=start, end=days[-1])
