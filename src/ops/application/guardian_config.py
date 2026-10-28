"""统一守护的用户设置与定时入口。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store import OpsError
from src.ops.application.guardian_session import GUARDIAN_CRON
from src.ops.application.guardian_weekly_prompt import DEFAULT_WEEKLY_PROMPT
from src.ops.application.trading_operations_skill import load_trading_operations_skill

JOB_NAME = "天才交易员"
_PREVIOUS_JOB_NAME = "自主交易员"
GUARDIAN_IDENTITY = "【身份】你是天才交易员，负责本系统的现金模拟账户。"
# 旧导入保留兼容；实际入口默认加载同一技能，账户权限由本轮数据提供。
POSITION_RULES = load_trading_operations_skill()[0]
REPLY_STYLE = """【回复风格：简洁、规范】
简体中文，先直接回答，再用一两条关键依据解释，最后说明实际下一步。通常两三段，避免研究流水和重复免责。
逐股理由只写主因、必要证据和风险；触发、失效及数量使用对应结构化字段，不全文重复。复杂问题保留影响结论的限定，原始数据用必要来源和时点引用，不粘贴长文。
咨询仍是讨论，不提交交易；账户表已有数字不整套复述。研究深度不受简短表达限制，输出预算无需填满。"""
USER_PROMPT_HEADER = "【用户配置：风格偏好与阶段任务】"
AUTONOMY_RULES = """【自主决策与角色范围】
自主选择研究对象、方法、持有周期和仓位；通用交易操作按默认加载的手册执行。
【风格偏好】
用户配置中的风格偏好是默认方向：先在偏好范围内发现和比较机会；证据显示偏好外的机会明显更优时可以选择，写明比较对象和理由，没有比较证据就说明未比较。用户未配置偏好时，交易风格由你自主决定。偏好是方向不是门槛，不设市值硬门槛、研究配额或强制换仓。
本角色可研究全市场；系统不预载量化策略、策略候选或策略目录，需要时可主动查询，也可完全不看。
watch保存本账户自主观察，unwatch移除观察；盘前、盘中、复盘均可自主维护。研究、经验和条件计划可随证据更新。"""
INTRADAY_CADENCE = """【盘中节奏】
交易日09:25开始竞价研判，每5分钟继续。09:25不操作账户，完整发送预计操作。09:30起按新行情逐笔判定执行、继续观察或放弃；轮次失败保留待核验计划。普通轮次无成交且无执行异常时静默。"""
DEFAULT_PROMPT = """你是天才交易员，负责管理现金模拟账户。根据当前账户、行情和证据，自主决定研究、买卖、持有或观察。
自主选择股票、持仓数量、仓位、交易方法和持有周期，比较收益、风险、机会成本及证据可靠性。维护重要持仓与观察对象的行动条件、失效条件和后续计划。
交易前核对现金、可卖量、板块申报规则和行情有效性。区分事实、推测与证据缺口，使用本轮约定的结构化输出。"""
DEFAULT_PREMARKET_PROMPT = """你是天才交易员，当前进行盘前研究与行动准备，本阶段不执行交易。
结合真实账户、可知的隔夜信息和自主选择的市场研究，形成今天可以继续验证、调整或放弃的判断。研究对象、方法、工具和深度由你决定，工坊与旧计划均为可选材料。
把重要机会、风险、条件和证据缺口交接给开盘研判；可提出新的研究问题或修正旧假设，不要求增加观察或交易。保留影响行动的完整条件，区分已知、推测与尚未出现的行情；计划数量和时间依据实际执行能力。"""
DEFAULT_REVIEW_PROMPT = """你是天才交易员，当前进行复盘、研究及后续规划，本阶段不执行交易。
以原始证据评价决策与结果，识别理解中的错误、仍有效的判断、环境变化和有价值的新问题；具体按日复盘或周复盘任务展开。自主回读相关历史、选择比较方法与研究深度，不只重复账务或替盈亏找解释。
可以修正、延续、反证或搁置旧假设，保留后续可用的计划、研究线索和验证状态。新想法可以尚无样本，但不冒充已验证规律；实际成交、模拟比较与事后设想分清。完整条件和证据不受简报排版约束，也不为显得进步强行产出经验或新交易规则。"""
DEFAULTS: dict[str, Any] = {
    "enabled": False, "provider": "", "model": "", "prompt": DEFAULT_PROMPT,
    "common_prompt": "", "premarket_prompt": DEFAULT_PREMARKET_PROMPT, "review_prompt": DEFAULT_REVIEW_PROMPT, "weekly_prompt": "",
    "strategies": [], "notify": True,
}


def managed_guardian_job(store: Any, *, name: str, previous_name: str, kind: str) -> dict[str, Any] | None:
    """Rename an existing managed job in place, retaining its ID, settings and runs."""
    current = store.get_job_by_name(name)
    if current is not None and current.get("kind", kind) != kind:
        raise OpsError(f"天才交易员任务名已被其他任务占用：{name}")
    if current is not None:
        previous = store.get_job_by_name(previous_name)
        if previous is not None and previous.get("id") != current.get("id"):
            raise OpsError(f"交易员任务出现重名副本，需先核对任务 ID：{name}")
        return current
    previous = store.get_job_by_name(previous_name)
    if previous is not None and previous.get("kind", kind) != kind:
        raise OpsError(f"原交易员任务名已被其他任务占用：{previous_name}")
    if previous is None:
        return None
    if not store.update_job(previous["id"], name=name, expected_name=previous_name,
                            allowed_kinds={kind}):
        raise OpsError(f"交易员任务改名未完成：{name}")
    return store.get_job_by_name(name)


def get_job(store: Any) -> dict[str, Any] | None:
    return managed_guardian_job(store, name=JOB_NAME,
                                previous_name=_PREVIOUS_JOB_NAME, kind="guardian")


def get_config(store: Any) -> dict[str, Any]:
    job = get_job(store)
    saved = (job or {}).get("config") or {}
    config = {**DEFAULTS, **saved}
    # 仅替换逐字匹配的内置旧模板，不覆盖用户自定义内容。
    for field, current in (("prompt", DEFAULT_PROMPT),
                           ("premarket_prompt", DEFAULT_PREMARKET_PROMPT),
                           ("review_prompt", DEFAULT_REVIEW_PROMPT),
                           ("weekly_prompt", DEFAULT_WEEKLY_PROMPT)):
        if config.get(field) == current.replace(JOB_NAME, _PREVIOUS_JOB_NAME, 1):
            config[field] = current
    config["enabled"] = bool(job and job["enabled"])
    return config


def save_config(store: Any, config: dict[str, Any]) -> dict[str, Any]:
    existing = get_job(store)
    value = {**get_config(store), **config}
    if existing and existing["kind"] != "guardian":
        raise OpsError("天才交易员任务名已被其他任务占用")
    fields = dict(cron=GUARDIAN_CRON, config=value, enabled=value["enabled"])
    if existing:
        store.update_job(existing["id"], name=JOB_NAME, **fields)
    else:
        store.create_job(name=JOB_NAME, kind="guardian", **fields)
    from src.ops.application.ensure_guardian_review_jobs import ensure_guardian_review_jobs
    ensure_guardian_review_jobs(store)
    from src.ops.application.jobs.guardian_delivery import ensure_guardian_delivery_job
    ensure_guardian_delivery_job(store)
    return get_config(store)
