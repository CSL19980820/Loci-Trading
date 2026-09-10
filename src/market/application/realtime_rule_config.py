"""实时规则阈值的库内覆盖：读取、进程缓存、对外形状。

**库里只存被改过的键**——默认值的唯一真相源是 ``realtime_rules.RULES``。
反过来做（首启把默认值灌进库）会把默认值钉死在旧版本上：以后改代码里的默认
值、给规则加新参数，老用户全都吃不到。

从 ``realtime_signals`` 拆出来是因为它既不属于规则判定也不属于引擎调度：
它是「配置怎么进内存」这一件事，被 API 路由与引擎两边共用。
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Callable, Mapping

from src.market.application.realtime_rules import RULES, RULES_BY_ID, Rule

logger = logging.getLogger(__name__)


#: 规则配置缓存的存活秒数。``evaluate()`` 是每 tick 跑的热路径，每次开一次
#: ops.db 连接去读 6 行配置是不可接受的开销。
#:
#: 为什么有了 PUT 主动失效还要 TTL：失效只对**本进程**有效。桌面端与服务端
#: 可能是两个进程（甚至两台机器共享一份库），别的进程改了配置，这里只能靠
#: TTL 兜底。30 秒是折中：调一次阈值最多等半分钟生效，而热路径上每租户每
#: 30 秒才多一次 6 行的查询。
RULE_CONFIG_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class RuleSetting:
    """ops.db 里**被改过的**那一行。``params`` 只含覆盖键，不含默认值。"""

    rule_id: str
    enabled: bool
    params: dict[str, float]
    updated_at: str = ""


_CONFIG_LOCK = threading.Lock()
#: tenant -> (取到的时刻, 该租户的覆盖表)。
_CONFIG_CACHE: dict[str, tuple[float, dict[str, RuleSetting]]] = {}


def load_rule_settings(tenant: str) -> dict[str, RuleSetting]:
    """从 ops.db 读本租户的规则覆盖。**没有行 = 全部用代码里的默认值**。"""
    from src.ops import OpsStore

    with OpsStore() as store:
        rows = store.list_signal_rule_config(tenant=tenant)
    out: dict[str, RuleSetting] = dict()
    for row in rows:
        rule_id = str(row.get("rule_id") or "")
        if rule_id not in RULES_BY_ID:
            # 规则已从注册表里删掉，配置行留着不管：它不影响任何现存规则，而
            # 主动删除会让「回滚一个版本」丢掉用户改过的阈值。
            continue
        raw = row.get("params")
        out[rule_id] = RuleSetting(
            rule_id=rule_id,
            enabled=bool(row.get("enabled", True)),
            params=dict(raw) if isinstance(raw, dict) else {},
            updated_at=str(row.get("updated_at") or ""),
        )
    return out


def rule_settings(
    tenant: str,
    *,
    loader: Callable[[str], dict[str, RuleSetting]] | None = None,
    now: float | None = None,
) -> dict[str, RuleSetting]:
    """带缓存的配置读取。热路径（每 tick）走这里，别直接 ``load_rule_settings``。"""
    stamp = time.monotonic() if now is None else float(now)
    with _CONFIG_LOCK:
        cached = _CONFIG_CACHE.get(tenant)
        if cached is not None and (stamp - cached[0]) < RULE_CONFIG_TTL_SECONDS:
            return cached[1]
    fetch = loader or load_rule_settings
    try:
        settings = fetch(tenant)
    except Exception as exc:
        # 读不到配置时**沿用上一份已知good**，而不是回落「全部默认」：后者会让
        # 用户刚停用的规则在库抖一下之后又开始推送，比少刷新一次糟得多。
        previous = cached[1] if cached is not None else dict()
        logger.warning("实时信号规则配置读取失败，沿用上一份（%d 条）：%s", len(previous), exc)
        settings = previous
    with _CONFIG_LOCK:
        _CONFIG_CACHE[tenant] = (stamp, settings)
    return settings


def invalidate_rule_settings(tenant: str | None = None) -> None:
    """PUT 之后必须调它，否则改完阈值最多要等一个 TTL 才生效。

    不传租户 = 全清（测试、换库、以及「不确定改的是谁」时的安全选择）。
    """
    with _CONFIG_LOCK:
        if tenant is None:
            _CONFIG_CACHE.clear()
        else:
            _CONFIG_CACHE.pop(tenant, None)


def rule_view(rule: Rule, setting: RuleSetting | None) -> dict[str, Any]:
    """一条规则的对外形状：默认值、当前生效值、被改过的键，三者都给。

    只给「当前生效值」是不够的——前端要能显示「这个值是你改的，点这里恢复默认」，
    就必须同时看到 ``defaults`` 与 ``overrides``。
    """
    overrides = dict(setting.params) if setting is not None else {}
    resolved = rule.resolve(overrides)
    return {
        "rule_id": rule.id,
        "label": rule.label,
        "description": rule.description,
        "enabled": bool(setting.enabled) if setting is not None else True,
        "repeatable": rule.repeatable,
        "direction": rule.direction,
        "strength": rule.strength,
        "min_bars": rule.bars_needed(resolved),
        "params": resolved,
        "defaults": rule.defaults,
        "overrides": overrides,
        "param_specs": [spec.to_dict() for spec in rule.params],
        "updated_at": setting.updated_at if setting is not None else "",
        "customized": setting is not None,
    }


def rule_catalog(settings: Mapping[str, RuleSetting] | None = None) -> list[dict[str, Any]]:
    """整张规则表的对外形状，顺序 = 注册表顺序（前端不必自己排）。"""
    table = dict(settings or {})
    return [rule_view(rule, table.get(rule.id)) for rule in RULES]

def cached_tenant_count() -> int:
    """当前进程缓存了几个租户的覆盖表。只给运维面板看，不参与判定。"""
    with _CONFIG_LOCK:
        return len(_CONFIG_CACHE)
