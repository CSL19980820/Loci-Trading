"""企微选股推送日标记：同任务同交易日只推一次。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")
_SETTING_KEY = "wecom_push_marks"
_KEEP_DAYS = 45


def shanghai_today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def shanghai_date_of_timestamp(text: str) -> str:
    """把 ops.db 时间戳（UTC naive / 带时区 / 偶发本地 naive）换成上海日历日。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10] if len(raw) >= 10 else ""
    if parsed.tzinfo is None:
        # 与 eod_catchup 一致：优先按 UTC 解释；若像盘后本地钟点则也给出上海日
        as_utc = parsed.replace(tzinfo=timezone.utc).astimezone(_TZ)
        return as_utc.strftime("%Y-%m-%d")
    return parsed.astimezone(_TZ).strftime("%Y-%m-%d")


def push_mark_key(job_id: str, day: str) -> str:
    return f"{str(job_id).strip()}:{str(day).strip()[:10]}"


def load_push_marks(store: Any) -> dict[str, Any]:
    raw = store.get_setting(_SETTING_KEY, {}) or {}
    return raw if isinstance(raw, dict) else {}


def is_screen_pushed(store: Any, *, job_id: str, day: str) -> bool:
    day = str(day or "").strip()[:10]
    job_id = str(job_id or "").strip()
    if not job_id or not day:
        return False
    marks = load_push_marks(store)
    return push_mark_key(job_id, day) in marks


def mark_screen_pushed(
    store: Any,
    *,
    job_id: str,
    day: str,
    meta: dict[str, Any] | None = None,
) -> None:
    day = str(day or "").strip()[:10]
    job_id = str(job_id or "").strip()
    if not job_id or not day:
        return
    marks = dict(load_push_marks(store))
    marks[push_mark_key(job_id, day)] = {
        "at": datetime.now(_TZ).isoformat(timespec="seconds"),
        **(meta or {}),
    }
    cutoff = datetime.now(_TZ).date().toordinal() - _KEEP_DAYS
    pruned: dict[str, Any] = {}
    for key, value in marks.items():
        day_part = str(key).split(":")[-1][:10]
        try:
            ordinal = datetime.strptime(day_part, "%Y-%m-%d").date().toordinal()
        except ValueError:
            continue
        if ordinal >= cutoff:
            pruned[key] = value
    store.set_setting(_SETTING_KEY, pruned)


def resolve_push_day(result: dict[str, Any] | None) -> str:
    if isinstance(result, dict):
        for key in ("trade_date", "as_of", "date"):
            day = str(result.get(key) or "").strip()[:10]
            if len(day) == 10 and day[4] == "-" and day[7] == "-":
                return day
    return shanghai_today()


def adopt_push_mark_from_runs(store: Any, *, job_id: str, day: str) -> bool:
    """若历史成功 run 已推过同日，补写标记并返回 True。"""
    if is_screen_pushed(store, job_id=job_id, day=day):
        return True
    runs = store.list_runs(job_id=job_id, status="success", limit=40)
    for run in runs:
        result = run.get("result")
        if not isinstance(result, dict):
            continue
        trade_day = resolve_push_day(result)
        if trade_day != day:
            continue
        if result.get("pushed") or result.get("reason") == "already_pushed":
            mark_screen_pushed(
                store,
                job_id=job_id,
                day=day,
                meta={"adopted_from": str(run.get("id") or ""), "title": str(result.get("strategy") or "")},
            )
            return True
    return False
