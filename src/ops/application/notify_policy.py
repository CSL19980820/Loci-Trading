"""通知安静时段与策略。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import re
from zoneinfo import ZoneInfo

_QUIET_RE = re.compile(r"^(?P<s>\d{1,2}:\d{2})\s*-\s*(?P<e>\d{1,2}:\d{2})$")


def _parse_hhmm(text: str) -> time:
    hh, mm = text.split(":", 1)
    hour = int(hh)
    minute = int(mm)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("invalid time")
    return time(hour=hour, minute=minute)


@dataclass(frozen=True)
class NotifyPolicy:
    timezone: str = "Asia/Shanghai"
    quiet_hours: str = ""

    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    def is_quiet_now(self, now: datetime | None = None) -> bool:
        raw = (self.quiet_hours or "").strip()
        if not raw:
            return False
        match = _QUIET_RE.match(raw)
        if not match:
            return False
        start = _parse_hhmm(match.group("s"))
        end = _parse_hhmm(match.group("e"))
        tz = self.tzinfo()
        current = now.astimezone(tz) if now else datetime.now(tz)
        clock = current.time()
        if start == end:
            return True
        if start < end:
            return start <= clock < end
        return clock >= start or clock < end


def load_notify_policy(store: object) -> NotifyPolicy:
    raw = {}
    getter = getattr(store, "get_setting", None)
    if callable(getter):
        loaded = getter("notify_policy", {}) or {}
        if isinstance(loaded, dict):
            raw = loaded
    return NotifyPolicy(
        timezone=str(raw.get("timezone") or "Asia/Shanghai"),
        quiet_hours=str(raw.get("quiet_hours") or ""),
    )


def save_notify_policy(store: object, *, quiet_hours: str, timezone: str = "Asia/Shanghai") -> NotifyPolicy:
    policy = NotifyPolicy(timezone=timezone, quiet_hours=(quiet_hours or "").strip())
    if policy.quiet_hours and not _QUIET_RE.match(policy.quiet_hours):
        from src.ops.infrastructure.store import OpsError

        raise OpsError("安静时段须为 HH:MM-HH:MM，例如 23:00-07:00")
    setter = getattr(store, "set_setting", None)
    if callable(setter):
        setter(
            "notify_policy",
            {"timezone": policy.timezone, "quiet_hours": policy.quiet_hours},
        )
    return policy
