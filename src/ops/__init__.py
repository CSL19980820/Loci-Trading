"""运维层：技能包、定时任务、执行历史、LLM 供应商配置。

「装个 zip 就多一个能定时跑的模式」和「通达信公式转成能定时跑的量化脚本」
这两件事，最后都落在这里：技能包与策略都被包装成 job，由同一个调度器
按 cron 触发，由同一套执行记录留痕。
"""
from src.ops.jobs import EXECUTORS, JobContext, JobError, run_job
from src.ops.scheduler import JobScheduler, SchedulerError, validate_cron
from src.ops.skills import (
    SkillError,
    SkillPackage,
    install_skill,
    parse_manifest,
    read_skill_file,
    uninstall_skill,
)
from src.ops.store import JOB_KINDS, OpsError, OpsStore

__all__ = [
    "EXECUTORS",
    "JOB_KINDS",
    "JobContext",
    "JobError",
    "JobScheduler",
    "OpsError",
    "OpsStore",
    "SchedulerError",
    "SkillError",
    "SkillPackage",
    "install_skill",
    "parse_manifest",
    "read_skill_file",
    "run_job",
    "uninstall_skill",
    "validate_cron",
]
