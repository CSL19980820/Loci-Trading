"""盘口情报 provider 契约。

provider 只负责一条 lane 的取数与归一化；路由、失败冷却和来源回执由
``router.py`` 统一处理。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from src.market.domain.tape import TapeRequest, TapeResult


class TapeProviderError(RuntimeError):
    """provider 无法返回当前请求时使用的可识别异常。"""


@runtime_checkable
class TapeProvider(Protocol):
    """可注册的盘口情报 provider。"""

    provider_id: str
    lanes: Sequence[str]

    def fetch(self, request: TapeRequest) -> TapeResult:
        """取一份结果；临时不可用也可返回 degraded 的 TapeResult。"""


def provider_id_of(provider: Any) -> str:
    """兼容 ``provider_id`` 与已有 adapter ``meta.id`` 命名。"""
    direct = str(getattr(provider, "provider_id", "") or "").strip()
    if direct:
        return direct
    meta = getattr(provider, "meta", None)
    return str(getattr(meta, "id", "") or "").strip()


def provider_lanes(provider: Any) -> tuple[str, ...]:
    """读取 provider 支持的 lane，不要求 provider 继承具体基类。"""
    lanes = getattr(provider, "lanes", None)
    if lanes is None:
        meta = getattr(provider, "meta", None)
        lanes = getattr(meta, "lanes", ())
    if isinstance(lanes, str):
        return (lanes,)
    try:
        return tuple(str(lane) for lane in lanes)
    except TypeError:
        return ()


def supports_lane(provider: Any, lane: str) -> bool:
    """优先尊重显式 ``supports``，否则按 lanes 元数据判断。"""
    supports = getattr(provider, "supports", None)
    if callable(supports):
        try:
            return bool(supports(lane))
        except Exception:
            return False
    return lane in provider_lanes(provider)


__all__ = [
    "TapeProvider",
    "TapeProviderError",
    "TapeRequest",
    "TapeResult",
    "provider_id_of",
    "provider_lanes",
    "supports_lane",
]
