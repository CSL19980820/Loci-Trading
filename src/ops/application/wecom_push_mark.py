"""企微选股推送防重标记：按触发时点、战法及选股内容指纹精确防重。"""
from __future__ import annotations

import hashlib
import json
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


def compute_push_fingerprint(
    *,
    day: str,
    job_id: str = "",
    strategy: str = "",
    time_slot: str = "",
    picks: list[dict[str, Any]] | None = None,
) -> str:
    """根据日期、战法/任务、触发时点（小时:分）、选股内容计算防重摘要。"""
    norm_day = str(day or "").strip()[:10]
    norm_strat = str(strategy or job_id or "").strip()
    norm_slot = str(time_slot or "").strip()
    norm_picks = []
    if isinstance(picks, list):
        for p in picks:
            if isinstance(p, dict):
                norm_picks.append({
                    "code": str(p.get("code") or "").strip(),
                    "name": str(p.get("name") or "").strip(),
                    "close": round(float(p.get("close") or 0.0), 3) if p.get("close") is not None else None,
                    "pct_chg": round(float(p.get("pct_chg") or 0.0), 2) if p.get("pct_chg") is not None else None,
                })
            else:
                norm_picks.append(str(p))
    norm_picks.sort(key=lambda x: str(x.get("code")) if isinstance(x, dict) else str(x))
    payload = {
        "day": norm_day,
        "strat": norm_strat,
        "slot": norm_slot,
        "picks": norm_picks,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(encoded.encode("utf-8")).hexdigest()[:12]


def push_mark_key(job_id: str, day: str, fingerprint: str = "") -> str:
    base = f"{str(job_id).strip()}:{str(day).strip()[:10]}"
    if fingerprint:
        return f"{base}:{str(fingerprint).strip()}"
    return base


def load_push_marks(store: Any) -> dict[str, Any]:
    raw = store.get_setting(_SETTING_KEY, {}) or {}
    return raw if isinstance(raw, dict) else {}


def is_screen_pushed(
    store: Any,
    *,
    job_id: str,
    day: str,
    fingerprint: str = "",
) -> bool:
    day = str(day or "").strip()[:10]
    job_id = str(job_id or "").strip()
    if not job_id or not day:
        return False
    marks = load_push_marks(store)
    if fingerprint:
        return push_mark_key(job_id, day, fingerprint) in marks
    return push_mark_key(job_id, day) in marks
def mark_screen_pushed(
    store: Any,
    *,
    job_id: str,
    day: str,
    fingerprint: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    day = str(day or "").strip()[:10]
    job_id = str(job_id or "").strip()
    if not job_id or not day:
        return
    marks = dict(load_push_marks(store))
    key = push_mark_key(job_id, day, fingerprint)
    marks[key] = {
        "at": datetime.now(_TZ).isoformat(timespec="seconds"),
        "fingerprint": fingerprint,
        **(meta or {}),
    }
    cutoff = datetime.now(_TZ).date().toordinal() - _KEEP_DAYS
    pruned: dict[str, Any] = {}
    for k, value in marks.items():
        parts = str(k).split(":")
        # parts could be [job_id, YYYY-MM-DD] or [job_id, YYYY-MM-DD, fingerprint]
        day_part = parts[1][:10] if len(parts) >= 2 else parts[-1][:10]
        try:
            ordinal = datetime.strptime(day_part, "%Y-%m-%d").date().toordinal()
        except ValueError:
            continue
        if ordinal >= cutoff:
            pruned[k] = value
    store.set_setting(_SETTING_KEY, pruned)


def resolve_push_day(result: dict[str, Any] | None) -> str:
    if isinstance(result, dict):
        for key in ("trade_date", "as_of", "date"):
            day = str(result.get(key) or "").strip()[:10]
            if len(day) == 10 and day[4] == "-" and day[7] == "-":
                return day
    return shanghai_today()


def adopt_push_mark_from_runs(
    store: Any,
    *,
    job_id: str,
    day: str,
    fingerprint: str = "",
) -> bool:
    """若历史成功 run 已推过同日/同指纹，补写标记并返回 True。"""
    if is_screen_pushed(store, job_id=job_id, day=day, fingerprint=fingerprint):
        return True
    runs = store.list_runs(job_id=job_id, status="success", limit=40)
    for run in runs:
        result = run.get("result")
        if not isinstance(result, dict):
            continue
        trade_day = resolve_push_day(result)
        if trade_day != day:
            continue
        run_fp = str(result.get("push_fingerprint") or "")
        if fingerprint and run_fp and run_fp != fingerprint:
            continue
        if result.get("pushed") or result.get("reason") == "already_pushed":
            mark_screen_pushed(
                store,
                job_id=job_id,
                day=day,
                fingerprint=fingerprint or run_fp,
                meta={"adopted_from": str(run.get("id") or ""), "title": str(result.get("strategy") or "")},
            )
            return True
    return False
