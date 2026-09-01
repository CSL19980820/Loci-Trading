"""每用户 LLM 配额与用量计费。

为什么不是「进程级环境变量单值」
--------------------------------
``LOCI_AI_MONTHLY_TOKEN_BUDGET`` 表达的是「**这台机器**的额度」。一个进程
服务多个用户时，第二个人上来就在花第一个人的预算，事后也说不清是谁烧掉的。
额度必须挂在**人**身上。

数据落在哪
----------
- **额度**在 ``identity.db`` 的 ``user_quotas``：跨租户全局唯一，管理员要横向
    比较、要能改。放进租户库就没法用一条 SQL 回答「谁这个月烧得最多」。
- **用量**在当前租户 ``ops.db`` 的 ``ai_usage_daily``：``paths.ops_db()`` 随
    ``current_tenant()`` 走，天然分库，不需要给表加 ``user_id`` 列。
    同时**尽力**回写 identity 的 ``usage_counters``，供后台跨租户盘点。

降级
----
身份库读不出来（文件缺失 / schema 未建 / 当前租户没有对应 user）时，一律退回
环境变量与内置默认值。**身份库故障不能把 AI 功能整个卡死**——配额是治理手段，
不是业务前提。

边界
----
跨上下文只走包根 ``from src.identity import IdentityStore``，禁止深路径。
"""
from __future__ import annotations

from datetime import date
import logging
import os

logger = logging.getLogger(__name__)

#: 拿不到每用户配额时的兜底月度 Token 硬顶。
DEFAULT_MONTHLY_TOKEN_BUDGET = 1_000_000

#: 兜底日调用次数上限；0 = 不限（保持存量单机行为不变）。
DEFAULT_DAILY_CALL_BUDGET = 0

ENV_MONTHLY_TOKENS = "LOCI_AI_MONTHLY_TOKEN_BUDGET"
ENV_DAILY_CALLS = "LOCI_AI_DAILY_CALL_BUDGET"

#: 配额键。与 identity ``user_quotas`` 的列名一字不差，免得两边各写一套映射。
QUOTA_KEYS = ("llm_monthly_tokens", "llm_daily_calls")

#: 对外统一用负数表达「不限」。identity 里的 0 含义是「用系统默认」，
#: 两者不能混，否则「没配过额度」会被读成「无限额度」。
UNLIMITED = -1


class QuotaExceeded(RuntimeError):
    """当前用户的 LLM 配额已用尽。"""


def _env_int(key: str, default: int) -> int:
    """读环境变量整数。写歪了记一条警告后用默认值，不抛。

    这里**故意不抛**：环境变量是运维输入，写错一个字符不该让所有用户的
    AI 功能一起挂掉，而每用户配额本身还有另一层兜底。
    """
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("%s 不是整数（%r），按默认值 %s 处理", key, raw, default)
        return default


def env_llm_quota() -> dict[str, int]:
    """旧的「进程级单值」口径。只在拿不到每用户配额时使用。"""
    return {
        "llm_monthly_tokens": _env_int(ENV_MONTHLY_TOKENS, DEFAULT_MONTHLY_TOKEN_BUDGET),
        "llm_daily_calls": _env_int(ENV_DAILY_CALLS, DEFAULT_DAILY_CALL_BUDGET),
    }


def _normalize(values: dict[str, int], fallback: dict[str, int]) -> dict[str, int]:
    """归一成本模块口径：正数是硬顶、负数是不限、绝不返回 0。"""
    out: dict[str, int] = {}
    for key in QUOTA_KEYS:
        try:
            raw = int(values.get(key, 0) or 0)
        except (TypeError, ValueError):
            raw = 0
        if raw == 0:
            # identity 语义：0 = 用系统默认，不是「一点都不给」。
            raw = int(fallback.get(key, 0) or 0)
        out[key] = raw if raw != 0 else UNLIMITED
    return out


def current_user_id() -> str:
    """当前租户对应的 identity 用户 id；查不到返回空串（调用方据此降级）。

    租户 id 由 ``src.shared.tenancy.current_tenant()`` 给出，再到 identity.db
    反查 user。主租户（单机存量用户）没建过账号时同样落到空串，走环境变量。
    """
    from src.shared.tenancy import current_tenant

    tenant = current_tenant()
    try:
        from src.identity import IdentityStore

        with IdentityStore() as store:
            row = store.conn.execute(
                "SELECT id FROM users WHERE tenant_id = ?", (tenant,)
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 — 身份库不可用绝不能卡死 AI
        logger.debug("identity 不可用，LLM 配额回退环境变量：%s", exc)
        return ""
    return str(row["id"]) if row is not None else ""


def current_llm_quota() -> dict[str, int]:
    """当前用户的 LLM 配额。

    返回 ``{"llm_monthly_tokens": int, "llm_daily_calls": int}``；
    正数是硬顶，负数是不限，**永远不会是 0**。
    """
    fallback = env_llm_quota()
    user_id = current_user_id()
    if not user_id:
        return _normalize(fallback, fallback)
    try:
        from src.identity import IdentityStore

        with IdentityStore() as store:
            quota = dict(store.get_quota(user_id))
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取用户配额失败，回退环境变量：%s", exc)
        return _normalize(fallback, fallback)
    return _normalize(quota, fallback)


def _ops_db_path(ops_db: str | None = None) -> str:
    """当前租户的 ops.db。**每次调用重新解析**，不许在模块导入期定死。"""
    if ops_db:
        return str(ops_db)
    from src.shared.paths import ops_db as resolve

    return str(resolve())


def monthly_token_usage(*, on: date | None = None, ops_db: str | None = None) -> int:
    """当前租户本自然月已计费的输入 + 输出 Token。读失败按 0 计。"""
    from src.ai.infrastructure.assistant_store import AssistantStore

    try:
        with AssistantStore(_ops_db_path(ops_db)) as store:
            return int(store.monthly_token_usage(on=on))
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取月度 Token 用量失败，按 0 计：%s", exc)
        return 0


def daily_call_count(*, on: date | None = None, ops_db: str | None = None) -> int:
    """当前租户今日 LLM 调用次数（``ai_usage_daily.calls`` 求和）。"""
    from src.ai.infrastructure.assistant_store import AssistantStore

    day = (on or date.today()).isoformat()
    try:
        with AssistantStore(_ops_db_path(ops_db)) as store:
            row = store.conn.execute(
                "SELECT COALESCE(SUM(calls), 0) AS total FROM ai_usage_daily WHERE day = ?",
                (day,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取今日 LLM 调用次数失败，按 0 计：%s", exc)
        return 0


def check_llm_quota(*, tokens_needed: int = 0, ops_db: str | None = None) -> None:
    """发起调用前的配额闸门。用尽抛 :class:`QuotaExceeded`。

    ``tokens_needed`` 是本轮预估用量（不传就只判「是不是已经超了」，与旧的
    ``used >= budget`` 语义一致）。拿不到配额时**放行**：见模块头的降级约定。
    """
    quota = current_llm_quota()

    monthly = quota["llm_monthly_tokens"]
    if monthly > 0:
        used = monthly_token_usage(ops_db=ops_db)
        if used + max(0, int(tokens_needed or 0)) >= monthly:
            raise QuotaExceeded(
                f"本月 Token 预算已用尽（{used} / {monthly}），"
                "请下月再试或联系管理员提高配额"
            )

    daily = quota["llm_daily_calls"]
    if daily > 0:
        calls = daily_call_count(ops_db=ops_db)
        if calls >= daily:
            raise QuotaExceeded(
                f"今日 LLM 调用次数已达上限（{calls} / {daily}），"
                "请明天再试或联系管理员提高配额"
            )


def record_llm_usage(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    ops_db: str | None = None,
    store: object | None = None,
) -> None:
    """记一笔 LLM 用量：租户 ``ai_usage_daily`` + identity ``usage_counters``。

    **计费失败只记日志**。审计坏了顶多丢一条用量，不能把盯盘 / 选股 / 技能这一轮
    真实业务带崩。

    - ``store``：已经开着的 ``AssistantStore``，助手主环用（省一次开库，也避免
      在同一段事务里另开连接）。
    - ``ops_db``：调用方手里已有一条明确库路径时传（任务侧 ``JobContext``），
      免得同一轮业务的用量写进另一个库。
    - 两个都不传就按 ``current_tenant()`` 惰性解析。

    0 token 也照记：它同样占掉了一次调用，日调用配额要能看见。
    """
    tokens_in = max(0, int(input_tokens or 0))
    tokens_out = max(0, int(output_tokens or 0))
    name, model_id = str(provider or "unknown"), str(model or "unknown")

    try:
        if store is not None:
            store.record_usage(
                provider=name, model=model_id, input_tokens=tokens_in, output_tokens=tokens_out
            )
        else:
            from src.ai.infrastructure.assistant_store import AssistantStore

            with AssistantStore(_ops_db_path(ops_db)) as opened:
                opened.record_usage(
                    provider=name,
                    model=model_id,
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 ai_usage_daily 失败：%s", exc)

    _bump_identity_usage(tokens_in + tokens_out)


def _bump_identity_usage(total_tokens: int) -> None:
    """把用量同步一份到 identity，供管理员跨租户盘点。失败即忽略。"""
    user_id = current_user_id()
    if not user_id:
        return
    today = date.today()
    try:
        from src.identity import IdentityStore

        with IdentityStore() as store:
            store.bump_usage(
                user_id,
                period=today.strftime("%Y-%m"),
                metric="llm_tokens",
                delta=total_tokens,
            )
            store.bump_usage(user_id, period=today.isoformat(), metric="llm_calls", delta=1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("回写 identity 用量失败（不影响本轮）：%s", exc)


__all__ = [
    "DEFAULT_DAILY_CALL_BUDGET",
    "DEFAULT_MONTHLY_TOKEN_BUDGET",
    "ENV_DAILY_CALLS",
    "ENV_MONTHLY_TOKENS",
    "QUOTA_KEYS",
    "QuotaExceeded",
    "UNLIMITED",
    "check_llm_quota",
    "current_llm_quota",
    "current_user_id",
    "daily_call_count",
    "env_llm_quota",
    "monthly_token_usage",
    "record_llm_usage",
]
