"""Settings and scheduled maintenance read the same retention policy."""
from __future__ import annotations

from typing import Any

from src.ops.domain.retention_policy import RETENTION_KEY, RetentionPolicy
from src.ops.infrastructure.store_helpers import MANAGED_PRUNE, MANAGED_PRUNE_TENANT
from src.shared.tenancy import PRIMARY_TENANT, current_tenant


def saved_policy(store: Any) -> RetentionPolicy | None:
    raw = store.get_setting(RETENTION_KEY)
    if raw is None:
        return None
    # Invalid stored policy must stop cleanup rather than revert to more aggressive
    # defaults. Pydantic validation errors are visible in the job history/settings.
    return RetentionPolicy.model_validate(raw["policy"])


def retention_snapshot(store: Any) -> dict[str, Any]:
    raw = store.get_setting(RETENTION_KEY)
    private = store.get_job_by_name(MANAGED_PRUNE_TENANT)
    system = store.get_job_by_name(MANAGED_PRUNE) if current_tenant() == PRIMARY_TENANT else None
    if raw is not None:
        policy = RetentionPolicy.model_validate(raw["policy"])
    else:
        previous = (private or {}).get("config") or {}
        global_previous = (system or {}).get("config") or {}
        days = int(previous.get("keep_days", 15))
        policy = RetentionPolicy.model_validate({
            **{field: days for field in ("job_days", "monitor_days", "alert_days", "decision_days", "leader_days", "quota_days", "ai_event_days", "ai_grant_days", "skill_days", "research_days")},
            "job_keep_min": int(previous.get("run_keep_min", 5)),
            "job_keep_max": int(previous.get("run_keep_max", 200)),
            "ai_session_keep": int(previous.get("ai_session_keep", 500)),
            "intraday_days": int(global_previous.get("intraday_keep_days", 60)),
            "community_days": int(global_previous.get("community_keep_days", 15)),
        })
    return {
        "policy": policy.model_dump(),
        "revision": int((raw or {}).get("revision", 0)),
        "global_scope": current_tenant() == PRIMARY_TENANT,
        "jobs": [{"id": job["id"], "name": job["name"], "cron": job["cron"], "enabled": job["enabled"]} for job in (private, system) if job],
    }


def save_retention(store: Any, policy: RetentionPolicy, *, expected_revision: int) -> dict[str, Any]:
    if current_tenant() != PRIMARY_TENANT:
        previous = retention_snapshot(store)["policy"]
        for field in ("login_days", "audit_days", "intraday_days", "community_days", "notification_days", "usage_days"):
            if getattr(policy, field) != previous[field]:
                raise PermissionError("全局日志保留期仅可在主工作区调整")
    store.set_versioned_setting(RETENTION_KEY, {"policy": policy.model_dump()}, expected_revision=expected_revision)
    return retention_snapshot(store)
