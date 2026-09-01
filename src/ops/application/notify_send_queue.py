"""出站发送队列：同一时刻只发一条，失败最多 3 次后再处理下一条。

15:30 多路选股会同时打企微 Webhook；并发 POST 会互相抢连接、15s 超时。
选股计算仍可并行，HTTP 出站必须串行。

本模块管三件事，都是「与租户无关、与官方口径对齐」的出站纪律：

1. **串行**（老本行）：一条发完再发下一条。
2. **令牌桶**：企业微信群机器人官方限额是**每个 webhook key 20 条/分钟**，
超了回 ``errcode=45009``。桶按 key 记账，超限的消息**排队等**，不丢。
为什么在这一层：key 才是被限的对象，它既不属于某个租户，也不属于某条业务
消息；放在通道层或业务层都会漏掉另一条腿。
3. **等待有上限**：``run_serialized`` 的调用方（很可能是调度线程）最多等
``SEND_WAIT_TIMEOUT_SEC``。工人线程因不可捕获错误退出时 ``finally`` 会把
``_worker_started`` 置回 False（下次调用能重启工人），**但已经在队列里等的
item 永远等不到 ``done.set()``**——无超时的 ``wait()`` 会把调用线程永久挂死。
这是真实存在的挂死路径，不是理论风险。
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

#: 单条消息最多尝试次数（含首次）。
SEND_MAX_ATTEMPTS = 3
#: 两次尝试之间的间隔；超时类失败立刻连打只会再次堵死。
SEND_RETRY_PAUSE_SEC = 1.0
#: 调用线程等结果的上限。宁可当失败，也不许把调度线程挂死。
SEND_WAIT_TIMEOUT_SEC = 90.0
#: 企微官方限额：每个 webhook key 每分钟 20 条。
RATE_LIMIT_PER_MINUTE = 20
#: 令牌桶的补充窗口。
RATE_LIMIT_WINDOW_SEC = 60.0

T = TypeVar("T")

__all__ = [
    "NonRetryableSendError",
    "RATE_LIMIT_PER_MINUTE",
    "RATE_LIMIT_WINDOW_SEC",
    "SEND_MAX_ATTEMPTS",
    "SEND_RETRY_PAUSE_SEC",
    "SEND_WAIT_TIMEOUT_SEC",
    "SendQueueTimeout",
    "reset_rate_limits",
    "run_serialized",
]


class NonRetryableSendError(Exception):
    """标记异常：这次失败重试无意义，甚至有害。

    队列见到它立刻收手，不再走 ``SEND_MAX_ATTEMPTS`` 的重试。典型是企微的
    45009（调用超频）：把它当普通失败再打两次，只会把限额挖得更深。

    具体的业务异常类**多重继承**它（见 ``notify.NotifyNotRetryable``），
    这样本模块不必反向 import notify（那是循环依赖），也不必用错误码字符串
    去猜——判定权留在懂协议的那一层。
    """


class SendQueueTimeout(RuntimeError):
    """排队等结果超时。调用方按「这条没发出去」处理。"""


@dataclass
class _TokenBucket:
    """标准令牌桶。``reserve`` 允许透支，返回该等多久——**不循环轮询**。

    为什么不写成 ``while not allowed: sleep(...)``：那种写法在 ``time.sleep``
    被测试替换成 no-op 时会变成死循环。这里一次算清等待时长、只睡一次，
    sleep 被 mock 掉最多只是「没真的等」，不会转不出来。
    """

    capacity: float
    window: float
    tokens: float = 0.0
    updated: float = 0.0

    def reserve(self, *, now: float) -> float:
        """占用一个令牌；返回它真正可用之前还需等待的秒数。"""
        rate = self.capacity / self.window
        self.tokens = min(self.capacity, self.tokens + max(0.0, now - self.updated) * rate)
        self.updated = now
        self.tokens -= 1.0
        return 0.0 if self.tokens >= 0 else (-self.tokens) / rate


@dataclass
class _SendItem:
    fn: Callable[[], Any]
    rate_key: str | None = None
    #: 单调时钟上的弃单时刻。调用方已经不等了，工人再发出去就是「几分钟前的
    #: 告警此刻才响」，比不发更让人困惑。
    deadline: float = 0.0
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    attempts: int = 0


_queue: queue.Queue[_SendItem] = queue.Queue()
_start_lock = threading.Lock()
_worker_started = False
_worker_ident: int | None = None

#: webhook key -> 令牌桶。key 是凭据，日志里一律打码。
_buckets: dict[str, _TokenBucket] = {}
_bucket_lock = threading.Lock()


def reset_rate_limits() -> None:
    """清空所有令牌桶。测试与运维手动重置用；生产路径不调。"""
    with _bucket_lock:
        _buckets.clear()


def _mask(rate_key: str) -> str:
    return "…" + rate_key[-6:] if len(rate_key) > 6 else "*" * len(rate_key)


def _wait_for_slot(rate_key: str | None) -> float:
    """按 key 取一个发送位，必要时**在工人线程里**等。返回等了多久。

    在工人线程里睡是刻意的：出站本来就串行，睡在这里等于把整条出站队列按
    20 条/分钟节流，而不是让某一条消息被丢掉。
    """
    if not rate_key:
        return 0.0
    with _bucket_lock:
        bucket = _buckets.get(rate_key)
        if bucket is None:
            bucket = _TokenBucket(
                capacity=float(RATE_LIMIT_PER_MINUTE),
                window=RATE_LIMIT_WINDOW_SEC,
                tokens=float(RATE_LIMIT_PER_MINUTE),
                updated=time.monotonic(),
            )
            _buckets[rate_key] = bucket
        delay = bucket.reserve(now=time.monotonic())
        if len(_buckets) > 64:
            #: 长跑进程换过很多 webhook 的话，别让桶表变成内存泄漏。
            stale = [
                key
                for key, item in _buckets.items()
                if key != rate_key and time.monotonic() - item.updated > RATE_LIMIT_WINDOW_SEC
            ]
            for key in stale:
                _buckets.pop(key, None)
    if delay > 0:
        logger.warning(
            "webhook %s 触及 %s 条/分钟上限，本条排队 %.1fs（不丢）",
            _mask(rate_key),
            RATE_LIMIT_PER_MINUTE,
            delay,
        )
        time.sleep(delay)
    return delay


def run_serialized(fn: Callable[[], T], *, rate_key: str | None = None) -> T:
    """把 ``fn`` 排进出站队列并等待结果；已在工人线程内则直接执行，避免重入死锁。

    ``rate_key`` 是被官方限额约束的那个标识（企微就是 webhook 的 key 段）。
    不传则不过令牌桶。

    **等待有超时**：``SEND_WAIT_TIMEOUT_SEC`` 内拿不到结果就抛
    ``SendQueueTimeout``。调用方（``jobs`` 调度线程、HTTP 请求线程）宁可看到一条
    「这次没发出去」的 WARNING，也不能被一条推送永久挂住。
    """
    if threading.get_ident() == _worker_ident:
        _wait_for_slot(rate_key)
        return fn()
    _ensure_worker()
    item = _SendItem(
        fn=fn,
        rate_key=rate_key,
        deadline=time.monotonic() + SEND_WAIT_TIMEOUT_SEC,
    )
    _queue.put(item)
    if not item.done.wait(SEND_WAIT_TIMEOUT_SEC):
        logger.warning(
            "出站排队超过 %.0fs 仍无结果，按失败处理（工人线程可能已退出）",
            SEND_WAIT_TIMEOUT_SEC,
        )
        raise SendQueueTimeout(f"出站发送排队超过 {SEND_WAIT_TIMEOUT_SEC:.0f}s 未完成")
    if item.error is not None:
        raise item.error
    return item.result  # type: ignore[no-any-return]


def _ensure_worker() -> None:
    global _worker_started, _worker_ident
    with _start_lock:
        if _worker_started:
            return
        thread = threading.Thread(
            target=_worker_loop, name="loci-notify-send", daemon=True
        )
        thread.start()
        _worker_started = True
        _worker_ident = thread.ident


def _worker_loop() -> None:
    global _worker_started, _worker_ident
    try:
        while True:
            item = _queue.get()
            try:
                if item.deadline and time.monotonic() > item.deadline:
                    #: 调用方早就不等了。此刻再发，用户会在毫无上下文的时间点收到一条
                    #: 过期告警；照实丢掉并记账。
                    logger.warning("出站队列丢弃一条已超时的消息（调用方已放弃等待）")
                    item.error = SendQueueTimeout("排队超时，已放弃")
                else:
                    _run_item(item)
            except Exception as exc:  # noqa: BLE001 — 工人不能死，否则整条出站队列卡死
                logger.exception("出站队列工人异常")
                if item.error is None:
                    item.error = exc
            finally:
                item.done.set()
                _queue.task_done()
    finally:
        with _start_lock:
            _worker_started = False
            _worker_ident = None


def _run_item(item: _SendItem) -> None:
    last_error: BaseException | None = None
    for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
        item.attempts = attempt
        #: 每次尝试都算一条出站——重试同样占官方的 20 条/分钟额度。
        _wait_for_slot(item.rate_key)
        try:
            item.result = item.fn()
            return
        except NonRetryableSendError as exc:
            #: 对端明确说「别再打了」（企微 45009 超频、93000 webhook 非法……）。
            #: 此前这里一视同仁再打 2 次，是在超频的伤口上撒盐。
            logger.warning("出站发送被对端拒绝且不可重试，放弃：%s", exc)
            item.error = exc
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "出站发送第 %s/%s 次失败：%s",
                attempt,
                SEND_MAX_ATTEMPTS,
                exc,
            )
            if attempt < SEND_MAX_ATTEMPTS:
                time.sleep(SEND_RETRY_PAUSE_SEC)
    item.error = last_error or RuntimeError("出站发送失败")
