"""托管任务的 cron 错峰：把每个租户散到不同的分钟上。

为什么需要
----------
托管任务的时点是写死的常量：盘后选股 ``15:30``、情报盘后 ``15:40``、候选 T+N
跟踪 ``15:45``。它们对**单机单用户**是对的，多租户之后就变成「50 个用户在同一
分钟做同一件事」：租户线程池只有两条，第 3 个租户开始就得排队，而且所有人同时
去读同一个热库、同时打同一个上游。错开几分钟不解决总量，但能把尖峰摊平。

怎么散
------
``crc32(tenant_id) % span``：确定性（同一个租户每次都落在同一分钟，用户看到的
「下次触发」不会每次重启就变）、无需存状态、可测。**主租户恒为偏移 0**——
存量单机用户的 15:30 一分钟都不许动，否则就是拿别人的既有行为做实验。

用在哪一步
----------
**只在首次创建时**。托管合并语义是 ``{**DEFAULT, **prev}``：只补缺失键，不覆盖
用户改过的 cron。错峰是个默认值，不是纪律。
"""
from __future__ import annotations

import zlib

#: 错峰窗口宽度（分钟）。15 分钟够摊平 50 个租户，又不会把盘后任务拖到收市
#: 太久之后——选股要赶在日终同步之前跑完。
DEFAULT_STAGGER_SPAN_MINUTES = 15


def tenant_minute_offset(
    span: int = DEFAULT_STAGGER_SPAN_MINUTES, tenant_id: str | None = None
) -> int:
    """该租户的分钟偏移，落在 ``[0, span)``。主租户恒为 0。

    ``tenant_id`` 省略时取 ``current_tenant()``——托管确保都在 ``tenant_scope``
    里跑，调用方不用自己传。
    """
    from src.shared.tenancy import current_tenant, is_primary_tenant

    tenant = tenant_id if tenant_id is not None else current_tenant()
    if is_primary_tenant(tenant):
        return 0
    width = int(span or 0)
    if width <= 1:
        return 0
    return int(zlib.crc32(str(tenant).encode("utf-8")) % width)


def staggered_minute(
    base_minute: int,
    *,
    span: int = DEFAULT_STAGGER_SPAN_MINUTES,
    tenant_id: str | None = None,
) -> int:
    """``base_minute`` 加上本租户偏移；越过整点就退回原值。

    越过整点不进位：``16:02`` 与 ``15:xx`` 是两件事（盘后选股必须在日终同步前），
    与其偷偷改小时，不如让这个租户回到基准分钟——最坏情况是它没被错开。
    """
    base = int(base_minute)
    minute = base + tenant_minute_offset(span, tenant_id)
    return minute if 0 <= minute <= 59 else base


def staggered_cron(
    cron: str,
    *,
    span: int = DEFAULT_STAGGER_SPAN_MINUTES,
    tenant_id: str | None = None,
) -> str:
    """把 ``"40 15 * * mon-fri"`` 这种**定点** cron 的分钟字段错峰。

    只处理分钟字段是纯数字的定点 cron；``*/15`` 这类区间表达式原样返回——
    区间任务本来就分散在整个窗口里，没有尖峰可削。
    """
    fields = str(cron or "").split()
    if len(fields) != 5 or not fields[0].isdigit():
        return str(cron or "")
    fields[0] = str(staggered_minute(int(fields[0]), span=span, tenant_id=tenant_id))
    return " ".join(fields)


__all__ = [
    "DEFAULT_STAGGER_SPAN_MINUTES",
    "staggered_cron",
    "staggered_minute",
    "tenant_minute_offset",
]
