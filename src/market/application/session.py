"""A 股交易时段与行情新鲜度判定（供 API / 前端轮询闸门）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _weekday_fallback_is_trading(d: date) -> bool:
    return d.weekday() < 5


def _backfill_window(
    *,
    last_date: str | None,
    expected: str | None,
    days: list[str],
    empty: bool,
    needs_backfill: bool,
) -> tuple[str | None, str | None]:
    """给出将补区间 [from, to]（含端点交易日）；空库则 from 为空、to 为目标日。"""
    if not needs_backfill or not expected:
        return None, None
    if empty or not last_date:
        return None, expected
    if last_date >= expected:
        return None, None
    if days:
        missing = [d for d in days if last_date < d <= expected]
        if missing:
            return missing[0], missing[-1]
    # 日历过期或不含缺口：用库日次日 → 目标日
    try:
        nxt = date.fromisoformat(last_date).toordinal() + 1
        return date.fromordinal(nxt).isoformat(), expected
    except ValueError:
        return None, expected


def _prev_closed_trading_day(
    *,
    today: str,
    days: list[str],
    now_date: date,
) -> str | None:
    """上一已收盘交易日（严格早于 today）。收盘前日 K 只要求覆盖到这一天。"""
    if days:
        prior = [d for d in days if d < today]
        if prior:
            return prior[-1]
    d = now_date
    for _ in range(10):
        d = date.fromordinal(d.toordinal() - 1)
        if _weekday_fallback_is_trading(d):
            return d.isoformat()
    return None


def _resolve_trading_day(
    *,
    today: str,
    days: list[str],
    now_date: date,
) -> tuple[bool, str | None]:
    """判定今日是否交易日，并给出「截至今天」的最近交易日（含今日若今日交易）。

    交易日历来自行情库重建：若日历最大日落后于「今天」，说明日历过期，
    此时不能把「今天不在日历里」当成休市——否则工作日会被误标「非交易日」。
    """
    if not days:
        is_trading = _weekday_fallback_is_trading(now_date)
        last_trading_day = today if is_trading else None
        if not is_trading:
            d = now_date
            for _ in range(10):
                d = date.fromordinal(d.toordinal() - 1)
                if _weekday_fallback_is_trading(d):
                    last_trading_day = d.isoformat()
                    break
        return is_trading, last_trading_day

    day_set = set(days)
    max_cal = max(days)
    if today in day_set:
        is_trading = True
    elif today > max_cal:
        # 日历未覆盖到今天：按工作日粗判，避免误报休市
        is_trading = _weekday_fallback_is_trading(now_date)
    else:
        # 日历已覆盖今天及之后，但今天不在其中 → 真节假日/休市
        is_trading = False

    prior = [d for d in days if d <= today]
    if is_trading and today > max_cal:
        last_trading_day = today
    elif prior:
        last_trading_day = prior[-1]
    elif is_trading:
        last_trading_day = today
    else:
        last_trading_day = days[-1]
    return is_trading, last_trading_day


def build_session_status(
    *,
    coverage: dict[str, Any] | None,
    trading_days: list[str] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """统一会话状态。

    - 非交易日：不自动拉实时
    - 交易日 15:00 前：日 K 只要求覆盖到上一已收盘交易日（不催补「今日」未定稿日线）
    - 交易日 15:00 后：若库内 last_date 已是今日，停实时轮询；否则可补今日
    - last_date 落后于应覆盖日：needs_backfill（周末打开等场景）
    """
    now = now or datetime.now()
    today = now.date().isoformat()
    mins = now.hour * 60 + now.minute
    after_close = mins >= 15 * 60
    in_live_clock = (9 * 60 + 15) <= mins < (15 * 60)  # [09:15, 15:00)

    days = list(trading_days or [])
    cov = coverage or {}
    rows = int(cov.get("rows") or 0)
    last_date = str(cov.get("last_date") or "") or None
    first_date = str(cov.get("first_date") or "") or None

    is_trading, last_trading_day = _resolve_trading_day(
        today=today,
        days=days,
        now_date=now.date(),
    )

    # 日 K 应覆盖日：收盘前不含今日（今日日线尚未定稿，盘中靠实时）
    if is_trading and after_close:
        expected = today
    elif is_trading:
        expected = _prev_closed_trading_day(
            today=today, days=days, now_date=now.date()
        )
    else:
        expected = last_trading_day
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
            elif i_exp < 0 and expected > max(days):
                # 日历过期：用自然日差粗估落后
                try:
                    lag_trading_days = max(
                        1,
                        (date.fromisoformat(expected) - date.fromisoformat(last_date)).days,
                    )
                except ValueError:
                    lag_trading_days = 1
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
    backfill_from, backfill_to = _backfill_window(
        last_date=last_date,
        expected=expected,
        days=days,
        empty=empty,
        needs_backfill=needs_backfill,
    )

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
        "backfill_from": backfill_from,
        "backfill_to": backfill_to,
        "live_allowed": live_allowed,
        "live_reason": live_reason,
        "in_live_clock": in_live_clock,
    }
