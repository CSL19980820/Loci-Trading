"""任务执行器：定时任务真正干活的地方。

四类任务：

- ``sync``      同步行情（盘后增量）
- ``screen``    跑一次选股，结果落执行记录
- ``backtest``  跑一次回测
- ``skill``     用配置的 LLM 执行一个技能包定义的"模式"

统一约定：执行器是纯函数，吃 config 吐可 JSON 化的结果。所有状态记录、
异常捕获、耗时统计由 ``run_job`` 统一处理——散在每个执行器里迟早会出现
"某一类任务失败了但没记录"的黑洞。

实现按 kind 拆到同包各模块；本文件只做兼容 re-export。
新 kind：在对应模块写 ``execute_*``，再注册到 ``registry.EXECUTORS``。
"""
from __future__ import annotations

from src.ops.application.jobs.backtest import execute_backtest
from src.ops.application.jobs.compare import execute_compare
from src.ops.application.jobs.context import (
    DEFAULT_PALACE_DB,
    Executor,
    JobContext,
    JobError,
    SKILL_SYSTEM_PREFIX,
    SKILL_SYSTEM_PREFIX_TRADING,
    skill_system_prefix,
)
from src.ops.application.jobs.notify import execute_notify
from src.ops.application.jobs.optimize import execute_optimize
from src.ops.application.jobs.outcome import execute_outcome
from src.ops.application.jobs.prune import execute_prune
from src.ops.application.jobs.registry import EXECUTORS, run_job
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs.skill import (
    _compose_prompt,
    _gather_context,
    execute_skill,
)
from src.ops.application.jobs.sync import execute_sync

__all__ = [
    "DEFAULT_PALACE_DB",
    "EXECUTORS",
    "Executor",
    "JobContext",
    "JobError",
    "SKILL_SYSTEM_PREFIX",
    "SKILL_SYSTEM_PREFIX_TRADING",
    "_compose_prompt",
    "_gather_context",
    "execute_backtest",
    "execute_compare",
    "execute_notify",
    "execute_optimize",
    "execute_outcome",
    "execute_prune",
    "execute_screen",
    "execute_skill",
    "execute_sync",
    "run_job",
    "skill_system_prefix",
]
