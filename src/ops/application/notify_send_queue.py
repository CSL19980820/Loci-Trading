"""出站发送队列：同一时刻只发一条，失败最多 3 次后再处理下一条。

15:30 多路选股会同时打企微 Webhook；并发 POST 会互相抢连接、15s 超时。
选股计算仍可并行，HTTP 出站必须串行。
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

T = TypeVar("T")


@dataclass
class _SendItem:
    fn: Callable[[], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    attempts: int = 0


_queue: queue.Queue[_SendItem] = queue.Queue()
_start_lock = threading.Lock()
_worker_started = False
_worker_ident: int | None = None


def run_serialized(fn: Callable[[], T]) -> T:
    """把 ``fn`` 排进出站队列并等待结果；已在工人线程内则直接执行，避免重入死锁。"""
    if threading.get_ident() == _worker_ident:
        return fn()
    _ensure_worker()
    item = _SendItem(fn=fn)
    _queue.put(item)
    item.done.wait()
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
        try:
            item.result = item.fn()
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
