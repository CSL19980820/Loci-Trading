"""选股进程级容量许可：全进程同时执行的选股数上限（内存闸门）。

为什么在 shared 而不是 ops：这道闸门要同时管住三类入口——Job 执行器
（`src.ops`）、HTTP 异步选股（`src.strategy`）、AI 助手选股工具（`src.ai`）。
放进 ops 会让 strategy/ai 为了一道信号量反向依赖 ops；shared 是唯一可以被
所有上下文依赖的落点。本模块因此**不导入任何限界上下文**。

容量默认 1 的依据（实测事故，原记在 `market_gate` 的常量注释里，随实现搬来）：
每档选股加载 4400 只 × 60 日的多字段面板；三档 15:30 并发的峰值在 3.7G 机器上
会触发 memcg OOM 把整个容器打掉，串行后峰值只有一档。OOM 不是选股失败，是整个
进程被杀——正在跑的 Job、调度器、其他租户的会话一起没。调大
`LOCI_SCREEN_JOB_CONCURRENCY` 前先确认机器内存。

为什么不是 `BoundedSemaphore`：CPython 的信号量按 notify 的唤醒顺序放行，不保证
到达顺序。一次选股要跑几十秒到十几分钟，倒霉的等待者可能被后到者反复插队直到撞上
排队上限，然后以「前面那档卡住了」的假故障收场。这里用 `Condition` + 递增票号做
FIFO：只有队头才有资格拿许可。

许可是**进程级**的，不按租户分桶：它守的是这台机器的物理内存，多租户下每个租户
各来一档同样会把容器打死。租户信息由调用方写进 `label`，只用于诊断。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import count
from typing import Any

logger = logging.getLogger(__name__)

#: 同一进程内同时执行的选股数默认值。
DEFAULT_SCREEN_PROCESS_CONCURRENCY = 1
#: 排队等前面选股放行的默认上限（秒）。与行情同步等锁同数量级；等满仍没轮到，
#: 说明前面那档已远超正常耗时（实测最慢单条 984s），按故障处理。
DEFAULT_SCREEN_PERMIT_WAIT_SEC = 20 * 60.0
#: `cancelled` 回调的轮询间隔（秒）：排队中的选股点「停止」要能尽快退出排队，
#: 而不是干等到排队上限。
_CANCEL_POLL_SEC = 0.5

#: 已经抱怨过的环境变量写法；排队循环里会反复读配置，不去重会刷屏。
_WARNED: set[str] = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(message, *args)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """读环境变量里的整数；缺失/非法/过小一律回落，绝不让配置把闸门变成 0。"""
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except ValueError:
        _warn_once(f"{name}={raw}", "环境变量 %s=%r 不是整数，改用默认 %s", name, raw, default)
        return int(default)
    if value < minimum:
        _warn_once(f"{name}={raw}", "环境变量 %s=%s 太小，抬到 %s", name, value, minimum)
        return int(minimum)
    return value


def _env_seconds(name: str, default: float, *, minimum: float = 1.0) -> float:
    """读环境变量里的秒数；缺失/非法/过小一律回落。"""
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        _warn_once(f"{name}={raw}", "环境变量 %s=%r 不是数字，改用默认 %s 秒", name, raw, default)
        return float(default)
    if value < minimum:
        _warn_once(f"{name}={raw}", "环境变量 %s=%s 太小，抬到 %s 秒", name, value, minimum)
        return float(minimum)
    return value


def screen_process_concurrency() -> int:
    """进程级选股并发上限，``LOCI_SCREEN_JOB_CONCURRENCY`` 可覆盖。

    **每次调用都重读**：import 期求值的常量会把进程钉死在启动那一刻的值上，
    测试也没法覆写（`src.ops.application.tenant_jobs` 已经踩过同一个坑）。
    """
    return _env_int("LOCI_SCREEN_JOB_CONCURRENCY", DEFAULT_SCREEN_PROCESS_CONCURRENCY)


def screen_permit_wait_sec() -> float:
    """排队上限（秒），``LOCI_SCREEN_QUEUE_WAIT_SEC`` 可覆盖。同样每次重读。"""
    return _env_seconds(
        "LOCI_SCREEN_QUEUE_WAIT_SEC", DEFAULT_SCREEN_PERMIT_WAIT_SEC, minimum=10.0
    )


class ScreenCapacityBusy(RuntimeError):
    """拿不到许可：容量已满且不等 / 等满 / 被取消。

    `reason` 取 ``no_wait`` / ``deadline`` / ``cancelled``——三者对调用方是不同的
    收场（立刻回「站内排队中」/ 判故障 / 静默结束），别让它们共用一条分支。
    """

    def __init__(self, message: str, *, waited_sec: float, reason: str) -> None:
        super().__init__(message)
        self.waited_sec = float(waited_sec)
        self.reason = str(reason)


_COND = threading.Condition()
_TICKETS = count(1)
#: 票号 -> label。用 `OrderedDict` 而不是 set：队头判定要的就是到达顺序。
_HOLDERS: "OrderedDict[int, str]" = OrderedDict()
_WAITING: "OrderedDict[int, str]" = OrderedDict()
#: 同线程重入深度。执行器内部再要一次许可时必须直接放行，否则自锁。
_LOCAL = threading.local()


def _try_grant_locked(ticket: int) -> bool:
    """队头 + 有空位才放行（调用方须持 `_COND`）。"""
    if len(_HOLDERS) >= screen_process_concurrency():
        return False
    for head in _WAITING:
        if head != ticket:
            return False
        break
    label = _WAITING.pop(ticket, None)
    if label is None:
        return False
    _HOLDERS[ticket] = label
    return True


def _busy(label: str, started: float, reason: str) -> ScreenCapacityBusy:
    waited = max(0.0, time.monotonic() - started)
    status = screen_capacity_status()
    if reason == "cancelled":
        message = f"选股「{label}」排队 {int(waited)} 秒后被取消"
    elif reason == "no_wait":
        message = (
            f"选股容量已满（{status['in_use']}/{status['limit']}，"
            # 自己此刻还在队列里，报「另有」要把自己减掉。
            f"另有 {max(0, status['waiting'] - 1)} 个在排队），「{label}」不排队直接放弃"
        )
    else:
        holders = "、".join(status["holders"]) or "无"
        message = (
            f"排队 {int(waited)} 秒仍未轮到（容量 {status['limit']}，"
            f"当前 {holders}），选股「{label}」放弃等待"
        )
    return ScreenCapacityBusy(message, waited_sec=waited, reason=reason)


def _acquire(
    label: str, wait_sec: float | None, cancelled: Callable[[], bool] | None
) -> tuple[int, float]:
    started = time.monotonic()
    with _COND:
        ticket = next(_TICKETS)
        _WAITING[ticket] = label
        granted = _try_grant_locked(ticket)
    if granted:
        return ticket, 0.0
    deadline = None if wait_sec is None else started + max(0.0, float(wait_sec))
    try:
        while True:
            if deadline is None:
                raise _busy(label, started, "no_wait")
            # 取消回调是调用方代码（可能自己拿着别的锁），一律在 `_COND` 之外调用，
            # 免得把外部的锁序拖进本模块。
            if cancelled is not None and cancelled():
                raise _busy(label, started, "cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _busy(label, started, "deadline")
            with _COND:
                if _try_grant_locked(ticket):
                    break
                _COND.wait(timeout=min(_CANCEL_POLL_SEC, remaining))
                if _try_grant_locked(ticket):
                    break
    except BaseException:
        with _COND:
            _WAITING.pop(ticket, None)
            # 自己退出队列也可能让后面那位变成队头，必须唤醒。
            _COND.notify_all()
        raise
    waited = max(0.0, time.monotonic() - started)
    if waited >= 1.0:
        logger.info("选股「%s」排队 %d 秒后开始", label, int(waited))
    return ticket, waited


def _release(ticket: int) -> None:
    with _COND:
        _HOLDERS.pop(ticket, None)
        _COND.notify_all()


@contextmanager
def screen_capacity_permit(
    *,
    label: str,
    wait_sec: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """占一个进程级选股许可；拿不到抛 `ScreenCapacityBusy`。

    - `label`：诊断用的人话标签，建议带上入口与租户，如 ``http:[tenant] 潜龙``。
    - `wait_sec=None`：不排队，没空位立刻抛；`wait_sec=N`：最多等 N 秒。
    - `cancelled`：每 0.5 秒问一次「还要不要等」，返回 True 则放弃排队。
    - 同线程重入直接放行：外层已经持有许可，再排一次必然自锁。
    """
    depth = int(getattr(_LOCAL, "depth", 0))
    if depth:
        _LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL.depth = depth
        return
    ticket, _waited = _acquire(str(label), wait_sec, cancelled)
    _LOCAL.depth = 1
    try:
        yield
    finally:
        _LOCAL.depth = 0
        _release(ticket)


def screen_capacity_status() -> dict[str, Any]:
    """当前容量占用快照，供运维面板与「忙」文案读。

    `holders` / `waiters` 是 label 列表，按占位 / 到达顺序；`waiters[0]` 就是下一个
    会被放行的那位。
    """
    with _COND:
        return {
            "limit": screen_process_concurrency(),
            "in_use": len(_HOLDERS),
            "waiting": len(_WAITING),
            "holders": list(_HOLDERS.values()),
            "waiters": list(_WAITING.values()),
        }
