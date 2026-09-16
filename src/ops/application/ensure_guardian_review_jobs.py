"""交易员报告任务，仅为已配置交易员的租户挂载，保留用户开关和cron。"""
from typing import Any

MANAGED_GUARDIAN_PREMARKET = "自主交易员 · 盘前计划"
MANAGED_GUARDIAN_DAILY = "自主交易员 · 日复盘"
MANAGED_GUARDIAN_WEEKLY = "自主交易员 · 周复盘"
MANAGED_EXCHANGE_CALENDAR = "交易所休市日历更新"


def ensure_exchange_calendar_job(store: Any) -> None:
    if store.get_job_by_name(MANAGED_EXCHANGE_CALENDAR) is None:
        store.create_job(name=MANAGED_EXCHANGE_CALENDAR, kind="exchange_calendar", cron="30 6,7,18 * * *", config={}, enabled=True)
REVIEW_JOBS = {
    "premarket": (MANAGED_GUARDIAN_PREMARKET, "*/10 8-9 * * mon-fri"),
    "daily": (MANAGED_GUARDIAN_DAILY, "45 15-18 * * mon-fri"),
    "weekly": (MANAGED_GUARDIAN_WEEKLY, "55 15-18 * * mon-fri"),
}


def ensure_guardian_review_jobs(store: Any) -> dict[str, list[str]]:
    from src.ops.application.guardian_config import get_job
    owner = get_job(store)
    if owner is None or not owner["enabled"]:
        return {"created": []}
    created = []
    for period, (name, cron) in REVIEW_JOBS.items():
        existing = store.get_job_by_name(name)
        if existing is None:
            store.create_job(name=name, kind="guardian_review", cron=cron,
                             config={"period": period}, enabled=owner["enabled"])
            created.append(name)
        elif existing["kind"] != "guardian_review":
            raise ValueError(f"报告任务名已被其他类型占用：{name}")
    return {"created": created}
