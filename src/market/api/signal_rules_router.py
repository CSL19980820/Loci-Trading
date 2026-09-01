"""实时信号的**维护面**：规则开关 / 阈值配置 + 信号历史。

与 ``stream_router.py`` 的分工：那边是推流（SSE，纯读，不写任何库），这边是
**普通 JSON 的增删改查**，落 ops.db。分成两个文件是因为两者的并发范式完全不同
——推流那套 ``async`` 生成器 + 线程池令牌的讲究，一条 PUT 用不上，混在一起只会
让下一个人以为 PUT 也要照着 SSE 的规矩写。

三个端点：

- ``GET  /api/market/signals/rules``      规则表（默认值 / 当前值 / 口径说明）
- ``PUT  /api/market/signals/rules/{rule_id}``  改开关与阈值（**写鉴权**）
- ``GET  /api/market/signals/recent``           信号历史（服务端已压 7 天 + 80 条）

**为什么只有 PUT 要写鉴权**：两个 GET 是大屏的只读依赖，和推流一样属于纯读；
而 PUT 会改变「谁会收到什么提醒」，是一次真正的配置写入，按全仓惯例（
``quality_router`` 的 repair、``board?persist=true``）挂 ``write_dependency``。

**租户**：规则配置与信号历史都是私人事实，一律经 ``current_tenant()`` 收窄。
行情本身是全局共享的，但「我关了哪条规则」「我收到过什么」不是。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.market.application.realtime_signals import (
    RULES_BY_ID,
    RuleParamError,
    RuleSetting,
    invalidate_rule_settings,
    rule_catalog,
    rule_view,
)
from src.shared.tenancy import current_tenant

logger = logging.getLogger(__name__)


class SignalRuleUpdate(BaseModel):
    """PUT 的请求体。两个字段都可选，只给一个就只改一个。

    ``params`` 的语义是**整份覆盖集**，不是增量补丁：给 ``{"speed_pct": 5}`` 之后，
    这条规则的其它参数一律回到代码里的默认值。这样 PUT 是幂等的，前端也不必先
    GET 再合并——它本来就是把整个表单提交上来。
    """

    enabled: bool | None = Field(default=None, description="停用后该规则不再产生任何信号")
    params: dict[str, Any] | None = Field(
        default=None, description="阈值覆盖集；缺省的键回落代码默认值"
    )


def _store_settings(rows: list[dict[str, Any]]) -> dict[str, RuleSetting]:
    """ops.db 的行 → 引擎认识的覆盖表。未知 rule_id 直接忽略。"""
    out: dict[str, RuleSetting] = dict()
    for row in rows:
        rule_id = str(row.get("rule_id") or "")
        if rule_id not in RULES_BY_ID:
            continue
        raw = row.get("params")
        out[rule_id] = RuleSetting(
            rule_id=rule_id,
            enabled=bool(row.get("enabled", True)),
            params=dict(raw) if isinstance(raw, dict) else dict(),
            updated_at=str(row.get("updated_at") or ""),
        )
    return out


def _open_ops_store() -> Any:
    """默认的 ops 库句柄。

    从**包根** ``src.ops`` 取而不是深挖 ``src.ops.infrastructure``：
    ``.importlinter`` 的 protect-ops-infra 契约只允许 ops 自己深 import 自己。
    放在函数里是为了让 import 期不拉起整个 ops 上下文（推流进程可能根本不碰它）。
    """
    from src.ops import OpsStore

    return OpsStore()


def build_signal_rules_router(
    *,
    write_dependency: Callable[..., Any],
    store_factory: Callable[[], Any] | None = None,
) -> APIRouter:
    """规则维护 + 信号历史。``store_factory`` 供测试注入，不注入就开当前租户的 ops.db。"""
    router = APIRouter()
    write_guard = Depends(write_dependency)
    open_store = store_factory or _open_ops_store

    @router.get("/api/market/signals/rules", tags=["market"])
    def list_signal_rules() -> dict[str, Any]:
        """规则表。``defaults`` / ``params`` / ``overrides`` 三者都给，见 rule_view。"""
        tenant = current_tenant()
        with open_store() as store:
            rows = store.list_signal_rule_config(tenant=tenant)
        settings = _store_settings(rows)
        rules = rule_catalog(settings)
        return {
            "tenant": tenant,
            "count": len(rules),
            "enabled_count": sum(1 for item in rules if item["enabled"]),
            "rules": rules,
        }

    @router.put("/api/market/signals/rules/{rule_id}", tags=["market"])
    def update_signal_rule(
        rule_id: str = Path(..., max_length=64),
        payload: SignalRuleUpdate = Body(default=SignalRuleUpdate()),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """改一条规则的开关 / 阈值。返回改完之后的那一条（形状同 GET 的元素）。

        校验分三层，全部返回人话原因：

        - 未知 ``rule_id`` → 404（规则表是代码里的常量，拼错就是拼错）
        - 未知参数键 / 非数字 / 越界 / 跨参数冲突 → 400
        - 与默认值相同的键**不入库**：库里只存被改过的那几个，见 store_signals
        """
        rule = RULES_BY_ID.get(str(rule_id))
        if rule is None:
            known = "、".join(RULES_BY_ID)
            raise HTTPException(
                status_code=404,
                detail=f"未知规则 {rule_id!r}；现有规则：{known}",
            )
        tenant = current_tenant()
        with open_store() as store:
            current = store.get_signal_rule_config(rule.id, tenant=tenant)
            existing = dict(current.get("params") or dict()) if current else dict()
            if payload.enabled is None:
                # 没给 enabled 就保持原状；库里没这条就是「从没改过」= 启用。
                enabled = bool(current.get("enabled", True)) if current else True
            else:
                enabled = bool(payload.enabled)
            if payload.params is None:
                overrides = existing
            else:
                try:
                    validated = rule.validate(payload.params)
                except RuleParamError as exc:
                    # 人话原因原样上抛：前端会把 detail 直接显示在表单下面。
                    raise HTTPException(status_code=400, detail=str(exc)) from None
                # 与默认值相同的键不落库。这样以后改代码里的默认值，没特意调过这个
                # 键的用户会跟着走新默认值，而不是被一条「其实等于默认」的旧行钉死。
                defaults = rule.defaults
                overrides = {
                    key: value
                    for key, value in validated.items()
                    if float(value) != float(defaults[key])
                }
            saved = store.upsert_signal_rule_config(
                rule.id, tenant=tenant, enabled=enabled, params=overrides
            )
        # 缓存失效必须发生在写成功之后。放前面的话，两个并发请求里慢的那个会把
        # 旧值重新灌回缓存，症状是「改了没生效，刷新一下又生效了」。
        invalidate_rule_settings(tenant)
        setting = _store_settings([saved]).get(rule.id)
        return rule_view(rule, setting)

    @router.get("/api/market/signals/recent", tags=["market"])
    def recent_signals(
        limit: int = Query(default=80, ge=1, le=80, description="上限即保留上限，见用户需求 5"),
    ) -> dict[str, Any]:
        """信号历史，``triggered_at`` 倒序。

        **服务端就已经只返回 7 天内 + 最多 80 条**——不是靠前端自己截。两道闸门在
        ``store_signals`` 里写死成模块常量，读写两侧共用同一份。
        """
        from src.ops import SIGNAL_JOURNAL_MAX_ROWS, SIGNAL_RETENTION_DAYS

        tenant = current_tenant()
        with open_store() as store:
            rows = store.list_signal_journal(tenant=tenant, limit=limit)
        return {
            "count": len(rows),
            "limit": int(limit),
            # 最新一条的时刻。前端的 getRecentSignals 读它当 asOf，用来在首屏
            # 显示「最近一次信号是什么时候」；空列表时给空串而不是 now()，
            # 否则界面会写着「刚刚」却一条都没有。
            "as_of": rows[0]["triggered_at"] if rows else "",
            "retention_days": SIGNAL_RETENTION_DAYS,
            "max_rows": SIGNAL_JOURNAL_MAX_ROWS,
            "signals": rows,
        }

    return router


__all__ = ["SignalRuleUpdate", "build_signal_rules_router"]
