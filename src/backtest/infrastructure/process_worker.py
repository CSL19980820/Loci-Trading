"""受控的回测进程边界。

回测面板会同时占用较大的 Python 堆和 NumPy 缓冲区。把它放在请求线程或
普通后台线程里，异常退出时内存不会及时回收，还会拖住同一进程里的 API。
本模块只负责进程生命周期与受限 IPC；业务计算仍复用
``backtest.application.batch``，所以不会出现第二套成交规则。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from threading import BoundedSemaphore
import time
from typing import Any

from src.shared.tenancy import normalize_tenant, tenant_scope

MAX_IPC_BYTES = 16 * 1024 * 1024
DEFAULT_PROCESS_SLOTS = 1
_SLOTS_ENV = "LOCI_BACKTEST_PROCESS_SLOTS"


def _read_slot_limit() -> int:
    raw = str(os.environ.get(_SLOTS_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_PROCESS_SLOTS
    return max(1, min(value, 4))


_PROCESS_SLOTS = BoundedSemaphore(_read_slot_limit())


class ProcessWorkerError(RuntimeError):
    """子进程返回了可读但失败的执行结果。"""


class ProcessWorkerBusy(ProcessWorkerError):
    """重任务进程槽已占用。"""


class ProcessWorkerStartError(ProcessWorkerError):
    """子进程无法启动。"""


class ProcessWorkerCancelled(ProcessWorkerError):
    """父任务收到取消请求并已终止子进程。"""


class ProcessWorkerTimedOut(ProcessWorkerError):
    """子进程超过父任务的墙钟预算。"""


def process_slot_limit() -> int:
    """返回本进程当前声明的回测 worker 槽数（默认 1，避免内存叠加）。"""
    return _read_slot_limit()


def run_isolated_job(
    operation: str,
    config: Mapping[str, Any],
    *,
    market_db: str,
    tenant_id: str,
    timeout_seconds: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """在 ``spawn`` 子进程中执行一次回测批处理。

    ``market_db`` 是全局共享行情库的显式路径；租户只用于加载自己的 Screen
    Skill。父进程持有 ops.db 的取消与心跳，子进程只读行情，不写任何租户库。
    """
    if operation not in {"backtest", "compare", "optimize"}:
        raise ProcessWorkerError(f"不支持的隔离回测操作：{operation}")
    if not str(market_db or "").strip():
        raise ProcessWorkerError("隔离回测缺少 market_db 路径")
    tenant = normalize_tenant(tenant_id)
    # 先消费父任务的剩余预算；已经过期时不要先拉起一个必然要被杀掉的子进程。
    budget = _positive_timeout(timeout_seconds)
    deadline = time.monotonic() + budget if budget is not None else None
    if not _PROCESS_SLOTS.acquire(blocking=False):
        raise ProcessWorkerBusy("回测进程容量已满，请稍后重试")

    receiver: Connection | None = None
    sender: Connection | None = None
    process: BaseProcess | None = None
    started = False
    try:
        worker_context = get_context("spawn")
        receiver, sender = worker_context.Pipe(duplex=False)
        process = worker_context.Process(
            target=_worker_entry,
            args=(sender, operation, dict(config), str(market_db), tenant),
            daemon=True,
            name=f"backtest-{operation}",
        )
        try:
            process.start()
        except Exception as exc:
            raise ProcessWorkerStartError(
                f"回测 worker 启动失败：{type(exc).__name__}: {exc}"
            ) from exc
        started = True
        sender.close()
        sender = None

        peak_rss = 0
        while True:
            if cancel_check is not None and _cancelled(cancel_check):
                _stop_process(process)
                raise ProcessWorkerCancelled("回测 worker 已按请求取消")
            if deadline is not None and time.monotonic() >= deadline:
                _stop_process(process)
                raise ProcessWorkerTimedOut(
                    f"回测 worker 超过 {budget:g}s runtime budget"
                )

            peak_rss = max(peak_rss, _process_rss(process.pid))
            wait_seconds = 0.2
            if deadline is not None:
                wait_seconds = min(wait_seconds, max(0.0, deadline - time.monotonic()))
            if receiver.poll(wait_seconds):
                message = _read_message(receiver)
                if message.get("status") == "error":
                    raise ProcessWorkerError(str(message.get("error") or "worker 执行失败"))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ProcessWorkerError("worker 返回了无效结果")
                process.join(timeout=1)
                if process.is_alive():
                    _stop_process(process)
                execution = {
                    "mode": "process",
                    "operation": operation,
                    "worker_pid": int(process.pid or 0),
                    "peak_rss_bytes": peak_rss or None,
                }
                result["execution"] = execution
                return result
            if not process.is_alive():
                # 子进程可能在父进程下一次 poll 前刚写完消息。
                if receiver.poll(0):
                    continue
                raise ProcessWorkerError("worker 未返回结果即退出")
    finally:
        if sender is not None:
            sender.close()
        if receiver is not None:
            receiver.close()
        if process is not None and started:
            if process.is_alive():
                _stop_process(process)
            process.join(timeout=0)
        _PROCESS_SLOTS.release()


def _worker_entry(
    sender: Connection,
    operation: str,
    config: dict[str, Any],
    market_db: str,
    tenant_id: str,
) -> None:
    try:
        from src.backtest.application.batch import (
            run_backtest_job,
            run_compare_job,
            run_optimize_job,
        )
        from src.market import MarketStore

        handlers = {
            "backtest": run_backtest_job,
            "compare": run_compare_job,
            "optimize": run_optimize_job,
        }
        with tenant_scope(tenant_id):
            with MarketStore(market_db) as store:
                result = handlers[operation](store, config)
        _send_message(sender, {"status": "ok", "result": result})
    except BaseException as exc:  # worker 必须把异常变成可收口的 IPC 结果
        _send_message(
            sender,
            {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:4000]},
        )
    finally:
        sender.close()


def _send_message(sender: Connection, message: dict[str, Any]) -> None:
    try:
        payload = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
        if len(payload) > MAX_IPC_BYTES:
            payload = json.dumps(
                {"status": "error", "error": "worker 结果超过 IPC 大小上限"},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        sender.send_bytes(payload)
    except (BrokenPipeError, EOFError, OSError):
        # 父进程超时/取消后会先关接收端；子进程只需退出，不能再制造 traceback。
        return


def _read_message(receiver: Connection) -> dict[str, Any]:
    try:
        payload = receiver.recv_bytes(MAX_IPC_BYTES)
    except EOFError as exc:
        raise ProcessWorkerError("worker 在 IPC 返回前退出") from exc
    try:
        message = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ProcessWorkerError("worker 返回了无效 IPC JSON") from exc
    if not isinstance(message, dict) or message.get("status") not in {"ok", "error"}:
        raise ProcessWorkerError("worker 返回了无效 IPC 消息")
    return message


def _positive_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        raise ProcessWorkerTimedOut("回测 worker 没有剩余 runtime budget")
    return seconds


def _cancelled(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except (OSError, RuntimeError):
        return False


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _process_rss(pid: int | None) -> int:
    """可选采样子进程 RSS；没有 psutil 时不改变执行语义。"""
    if not pid:
        return 0
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(pid).memory_info().rss)
    except (ImportError, OSError, ValueError):
        return 0


def _stop_process(process: BaseProcess) -> None:
    """终止并确认退出，避免超时 worker 留在后台继续吃内存。"""
    if not process.is_alive():
        process.join(timeout=0)
        return
    process.terminate()
    process.join(timeout=1)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=1)
    if process.is_alive():
        raise ProcessWorkerError("回测 worker 无法终止")


__all__ = [
    "ProcessWorkerBusy",
    "ProcessWorkerCancelled",
    "ProcessWorkerError",
    "ProcessWorkerStartError",
    "ProcessWorkerTimedOut",
    "process_slot_limit",
    "run_isolated_job",
]
