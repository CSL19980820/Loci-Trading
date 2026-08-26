"""APScheduler weekday: Unix 1-5 must still mean Mon–Fri."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.ops.infrastructure.scheduler import (
    next_cron_fire_at,
    normalize_cron_weekdays,
    validate_cron,
)


def test_normalize_unix_1_5_to_mon_fri() -> None:
    assert normalize_cron_weekdays("*/10 9-14 * * 1-5") == "*/10 9-14 * * mon-fri"
    assert normalize_cron_weekdays("35 15 * * 1,2,3,4,5") == "35 15 * * mon-fri"
    assert normalize_cron_weekdays("35 15 * * mon-fri") == "35 15 * * mon-fri"
    # already APScheduler-style Mon–Fri numbering — do not rewrite
    assert normalize_cron_weekdays("*/10 9-14 * * 0-4") == "*/10 9-14 * * 0-4"


def test_monday_interval_fires_today_not_tuesday() -> None:
    """Regression: raw 1-5 skipped Monday under APScheduler (0=Mon)."""
    tz = ZoneInfo("Asia/Shanghai")
    monday = datetime(2026, 8, 10, 9, 52, tzinfo=tz)
    nxt = next_cron_fire_at("*/10 9-14 * * 1-5", now=monday)
    assert nxt is not None
    assert nxt.startswith("2026-08-10T10:00:00")
    trigger = validate_cron("*/10 9-14 * * 1-5")
    fire = trigger.get_next_fire_time(previous_fire_time=None, now=monday)
    assert fire is not None
    assert fire.date().isoformat() == "2026-08-10"
