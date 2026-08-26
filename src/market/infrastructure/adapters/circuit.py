"""每源熔断：稳定失败的来源短路跳过，避免拖垮整轮同步。

为什么需要：``hist_daily`` 是**等齐所有源再合并**，且每源同时只允许一条在途
请求（``router_live`` 的门闩）。一个稳定不可达的源，会让每只票都先把
``claim_wait_sec``（默认 120s）耗满才放弃——全市场同步于是从十几分钟退化成
几小时，而且退化得毫无提示。

熔断只决定「要不要再打这个源」，不改写任何已取到的数字，也不影响多源合并的
优先序。判据只认**真失败**（异常 / 等门闩超时）；源正常应答但没有这只票的
数据（空表）不计入，否则连着几只退市票就能把一个健康的源打下线。

冷却到点后只放行一个探针请求（half-open）：探针成功即完全恢复，探针失败或
迟迟不回，都不会有第二个请求跟进。
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time

#: 连续真失败多少次后开路。
FAILURE_THRESHOLD = 5
#: 开路后的冷却秒数；到点放行一个探针。
COOLDOWN_SEC = 180.0


@dataclass
class _State:
    failures: int = 0
    open_until: float = 0.0


_lock = threading.Lock()
_states: dict[tuple[str, str], _State] = {}


def _state(lane: str, adapter_id: str) -> _State:
    return _states.setdefault((lane, adapter_id), _State())


def acquire(lane: str, adapter_id: str, *, now: float | None = None) -> bool:
    """现在能不能打这个源。

    开路且仍在冷却中 → ``False``。冷却到点 → 放行一个探针，并把冷却窗口顺延，
    因此不会有第二个请求同时挤进来。
    """
    moment = time.monotonic() if now is None else now
    with _lock:
        state = _state(lane, adapter_id)
        if state.open_until <= 0.0:
            return True
        if moment < state.open_until:
            return False
        state.open_until = moment + COOLDOWN_SEC
        return True


def record_success(lane: str, adapter_id: str) -> None:
    """成功取到数：连续失败清零并合闸。"""
    with _lock:
        _states.pop((lane, adapter_id), None)


def record_failure(lane: str, adapter_id: str, *, now: float | None = None) -> None:
    """真失败（异常 / 等门闩超时）；达到阈值即开路。"""
    moment = time.monotonic() if now is None else now
    with _lock:
        state = _state(lane, adapter_id)
        state.failures += 1
        if state.failures >= FAILURE_THRESHOLD:
            state.open_until = moment + COOLDOWN_SEC


def cooldown_remaining(lane: str, adapter_id: str, *, now: float | None = None) -> float:
    """剩余冷却秒数；未开路为 0。供错误文案与运维展示。"""
    moment = time.monotonic() if now is None else now
    with _lock:
        state = _states.get((lane, adapter_id))
        if state is None or state.open_until <= 0.0:
            return 0.0
        return max(0.0, state.open_until - moment)


def reset(lane: str | None = None) -> None:
    """测试 / 运维手动合闸；``None`` 清全部 lane。"""
    with _lock:
        if lane is None:
            _states.clear()
            return
        for key in [key for key in _states if key[0] == lane]:
            _states.pop(key, None)
