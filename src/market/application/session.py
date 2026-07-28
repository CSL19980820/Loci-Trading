"""A 股交易时段与行情新鲜度判定（供 API / 前端轮询闸门）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _weekday_fallback_is_trading(d: date) -> bool:
    return d.weekday() < 5


def build_session_status(
    *,
    coverage: dict[str, Any] | None,
    trading_days: list[str] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """统一会话状态。

    - 非交易日：不自动拉实时
    - 交易日 15:00 后：若库内 last_date 已是今日（或上一交易日且今日非交易），停实时轮询，读库即可
    - last_date 落后于上一交易日：needs_backfill（周末打开等场景）
    """
    now = now or datetime.now()
    today = now.date().isoformat()
    mins = now.hour * 60 + now.minute
    in_live_clock = (9 * 60 + 15) <= mins < (15 * 60)  # [09:15, 15:00)

    days = list(trading_days or [])
    cov = coverage or {}
    rows = int(cov.get("rows") or 0)
    last_date = str(cov.get("last_date") or "") or None
    first_date = str(cov.get("first_date") or "") or None

    if days:
        is_trading = today in set(days)
        # 上一交易日：日历中 <= today 的最后一天
        prior = [d for d in days if d <= today]
        last_trading_day = prior[-1] if prior else days[-1]
    else:
        is_trading = _weekday_fallback_is_trading(now.date())
        last_trading_day = today if is_trading else None
        # 无日历时：往前找最近工作日
        if not is_trading:
            d = now.date()
            for _ in range(10):
                d = date.fromordinal(d.toordinal() - 1)
                if _weekday_fallback_is_trading(d):
                    last_trading_day = d.isoformat()
                    break

    # 库是否已覆盖到「应有的最新交易日」
    expected = today if is_trading else last_trading_day
    db_is_current = bool(last_date and expected and last_date >= expected)

    lag_trading_days = 0
    if expected and last_date and days:
        try:
            i_exp = days.index(expected) if expected in days else -1
            i_last = days.index(last_date) if last_date in days else -1
            if i_exp >= 0 and i_last >= 0:
                lag_trading_days = max(0, i_exp - i_last)
            elif i_exp >= 0 and i_last < 0:
                lag_trading_days = max(1, i_exp)  # 库日期不在日历上，至少算落后
        except ValueError:
            lag_trading_days = 0
    elif expected and not last_date:
        lag_trading_days = 99 if rows == 0 else 1
    elif expected and last_date and last_date < expected:
        # 无完整日历时用自然日差粗估
        try:
            lag_trading_days = max(
                1,
                (date.fromisoformat(expected) - date.fromisoformat(last_date)).days,
            )
        except ValueError:
            lag_trading_days = 1

    empty = rows == 0
    needs_backfill = empty or lag_trading_days >= 1

    # 实时轮询闸门
    live_allowed = False
    live_reason = "off"
    if not is_trading:
        live_reason = "non_trading_day"
    elif not in_live_clock:
        if mins >= 15 * 60:
            live_reason = "after_close"
            # 15:00 后：库已是当日最新 → 不刷实时
            if db_is_current:
                live_reason = "after_close_db_current"
            else:
                # 收盘后库还没有今日，允许一次「补今日」由 bootstrap/sync，不自动 live 轮询
                live_reason = "after_close_db_stale"
        else:
            live_reason = "before_open"
    else:
        live_allowed = True
        live_reason = "live_window"

    return {
        "today": today,
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_day": is_trading,
        "last_trading_day": last_trading_day,
        "expected_last_date": expected,
        "coverage_first_date": first_date,
        "coverage_last_date": last_date,
        "coverage_rows": rows,
        "db_is_current": db_is_current,
        "lag_trading_days": lag_trading_days,
        "needs_backfill": needs_backfill,
        "backfill_kind": "empty" if empty else ("catchup" if needs_backfill else "none"),
        "live_allowed": live_allowed,
        "live_reason": live_reason,
        "in_live_clock": in_live_clock,
    }
