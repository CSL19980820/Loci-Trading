"""Editable retention thresholds. Zero always means keep indefinitely, not erase all."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
    login_days: int = Field(default=30, ge=0, le=3650)
    audit_days: int = Field(default=90, ge=0, le=3650)
    job_days: int = Field(default=15, ge=0, le=3650)
    job_keep_min: int = Field(default=5, ge=1, le=100000)
    job_keep_max: int = Field(default=200, ge=1, le=100000)
    monitor_days: int = Field(default=15, ge=0, le=3650)
    alert_days: int = Field(default=15, ge=0, le=3650)
    decision_days: int = Field(default=15, ge=0, le=3650)
    leader_days: int = Field(default=15, ge=0, le=3650)
    quota_days: int = Field(default=15, ge=0, le=3650)
    ai_event_days: int = Field(default=15, ge=0, le=3650)
    ai_grant_days: int = Field(default=15, ge=0, le=3650)
    ai_session_keep: int = Field(default=500, ge=0, le=100000)
    skill_days: int = Field(default=15, ge=0, le=3650)
    research_days: int = Field(default=15, ge=0, le=3650)
    intraday_days: int = Field(default=60, ge=0, le=3650)
    community_days: int = Field(default=15, ge=0, le=3650)
    notification_days: int = Field(default=15, ge=0, le=3650)
    usage_days: int = Field(default=15, ge=0, le=3650)

    @model_validator(mode="after")
    def validate_window(self):
        if self.job_keep_max < self.job_keep_min:
            raise ValueError("任务历史上限不能小于保底条数")
        return self


RETENTION_KEY = "retention.policy.v1"
