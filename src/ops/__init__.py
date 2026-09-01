"""运维限界上下文：技能、任务、调度、LLM 配置索引。"""
from src.ops.application.jobs import (
    EXECUTORS,
    JobCancelled,
    JobContext,
    JobError,
    JobTimedOut,
    run_job,
)
from src.ops.infrastructure.scheduler import (
    MIN_TENANT_CRON_INTERVAL_SECONDS,
    JobScheduler,
    SchedulerError,
    cron_interval_seconds,
    next_cron_fire_at,
    preview_upcoming_jobs,
    validate_cron,
)
from src.ops.application.job_quota import (
    JobQuotaExceeded,
    check_job_quota,
    current_job_quota,
    job_quota_status,
)
from src.ops.application.ensure_managed_jobs import (
    ensure_all_managed_jobs,
    ensure_system_jobs,
    ensure_tenant_jobs,
)
from src.ops.application.ensure_prune_tenant_job import (
    DEFAULT_PRUNE_TENANT_CONFIG,
 MANAGED_PRUNE_TENANT,
    ensure_prune_tenant_job,
    prune_tenant_cron,
)
from src.ops.application.tenant_storage import tenant_storage_usage
from src.ops.application.tenant_jobs import (
    SYSTEM_JOB_KINDS,
    is_system_job_kind,
    iter_tenant_plans,
    list_active_tenants,
    run_tenant_job,
)
from src.ops.domain.notify import NotifyChannel, NotifyMessage
from src.ops.application.notify_registry import (
    NotifyChannelError,
    dispatch,
    list_channels,
    test_channel,
)
from src.ops.application.notify_subscribers import dispatch_subscription_signal
from src.ops.application import skill_runs
from src.ops.application.screen import (
    ScreenPackageError,
    ScreenPackageRecord,
    delete_screen_history,
    delete_screen_package,
    get_screen_package,
    list_screen_history,
    list_screen_packages,
    read_screen_archive,
    restore_screen_package,
    save_screen_package,
)
from src.ops.application.skills import (
    DEFAULT_SKILL_ROOT,
    SkillError,
    SkillPackage,
    discover_skills,
    install_skill,
    install_skill_dir,
    load_skill_from_disk,
    parse_manifest,
    read_skill_file,
    resolve_skill,
    set_skill_enabled,
    uninstall_skill,
)
from src.ops.infrastructure.store import JOB_KINDS, OpsError, OpsStore, new_id
from src.ops.infrastructure.store_helpers import (
    DEFAULT_DB,
    MANAGED_OUTCOME_CRON,
    MANAGED_OUTCOME_TRACK,
    MANAGED_SYNC_EOD,
    MANAGED_SYNC_INTRADAY,
)
# 实时信号日志的两道保留闸门（用户需求 5）。从包根导出，是为了让 src.market
# 的路由能拿到阈值去回声给前端，而不必深挖 src.ops.infrastructure
# （.importlinter 的 protect-ops-infra 契约禁止跨上下文深 import）。
from src.ops.infrastructure.store_signals import (
    SIGNAL_JOURNAL_MAX_ROWS,
    SIGNAL_RETENTION_DAYS,
)
from src.ops.infrastructure.model_catalog import (
    enabled_model_ids,
    ensure_default_in_catalog,
    find_model_entry,
    merge_discovered,
    normalize_models,
    present_provider_models,
)

__all__ = [
    "EXECUTORS",
    # 多租户调度：系统级任务只跑一份，用户级任务按租户各跑各的
    "SYSTEM_JOB_KINDS",
    # 保留期与垃圾回收：租户段清理（prune_tenant）与租户目录占用统计
    "DEFAULT_PRUNE_TENANT_CONFIG",
    "MANAGED_PRUNE_TENANT",
    "ensure_all_managed_jobs",
    "ensure_prune_tenant_job",
    "prune_tenant_cron",
    "tenant_storage_usage",
    "ensure_system_jobs",
    "ensure_tenant_jobs",
    "is_system_job_kind",
    "iter_tenant_plans",
    "list_active_tenants",
    "run_tenant_job",
    # 定时任务配额与 cron 频率下限（HTTP 层闸门，见 api/jobs.py）
    "JobQuotaExceeded",
    "MIN_TENANT_CRON_INTERVAL_SECONDS",
    "check_job_quota",
    "cron_interval_seconds",
    "current_job_quota",
    "job_quota_status",
    # 多通道告警：企微/钉钉/飞书/通用 Webhook/邮件/站内信，注册表可插拔
    "NotifyChannel",
    "NotifyChannelError",
    "NotifyMessage",
    "dispatch",
    "dispatch_subscription_signal",
    "list_channels",
    "test_channel",
    "DEFAULT_DB",
    "DEFAULT_SKILL_ROOT",
    "JOB_KINDS",
    "MANAGED_OUTCOME_CRON",
    "MANAGED_OUTCOME_TRACK",
    "MANAGED_SYNC_EOD",
    "MANAGED_SYNC_INTRADAY",
    "JobContext",
    "JobCancelled",
    "JobError",
    "JobTimedOut",
    "JobScheduler",
    "OpsError",
    "OpsStore",
    "SIGNAL_JOURNAL_MAX_ROWS",
    "SIGNAL_RETENTION_DAYS",
    "SchedulerError",
    "SkillError",
    "SkillPackage",
    "discover_skills",
    "enabled_model_ids",
    "ensure_default_in_catalog",
    "find_model_entry",
    "install_skill",
    "install_skill_dir",
    "load_skill_from_disk",
    "merge_discovered",
    "new_id",
    "next_cron_fire_at",
    "normalize_models",
    "parse_manifest",
    "present_provider_models",
    "preview_upcoming_jobs",
    "read_skill_file",
    "resolve_skill",
    "run_job",
    "set_skill_enabled",
    "skill_runs",
    "uninstall_skill",
    "validate_cron",
    # Screen Skill 包存储：strategy 侧编译/注册战法时经包根消费，禁止深引 application.screen
    "ScreenPackageError",
    "ScreenPackageRecord",
    "delete_screen_history",
    "delete_screen_package",
    "get_screen_package",
    "list_screen_history",
    "list_screen_packages",
    "read_screen_archive",
    "restore_screen_package",
    "save_screen_package",
]
