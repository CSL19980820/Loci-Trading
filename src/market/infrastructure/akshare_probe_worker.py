"""AkShare 受控试跑的可回收进程边界。"""
from __future__ import annotations

from collections.abc import Mapping
import json
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import time
from typing import Any

from src.market.infrastructure.akshare_probe_result import JsonValue, summarize_probe_result


MAX_CONCURRENT_PROBES = 2
MAX_IPC_BYTES = 256 * 1024


class ProbeWorkerError(RuntimeError):
    """子进程已受控退出，但上游调用本身失败。"""


class ProbeCapacityError(RuntimeError):
    """本进程的受控试跑并发槽已经用尽。"""


class ProbeWorkerStartError(RuntimeError):
    """受控试跑子进程未能启动。"""


def run_akshare_probe(
    name: str,
    params: Mapping[str, JsonValue],
    *,
    timeout_seconds: float,
    max_sample_rows: int,
    slots: Any,
) -> dict[str, JsonValue]:
    """在 ``spawn`` 子进程中执行固定 AkShare 目录项并返回受限摘要。"""
    if not slots.acquire(blocking=False):
        raise ProbeCapacityError("probe capacity is exhausted; retry later")
    receiver: Connection | None = None
    sender: Connection | None = None
    process: BaseProcess | None = None
    process_started = False
    try:
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_probe_entry,
            args=(sender, name, dict(params), max_sample_rows),
            daemon=True,
            name="akshare-probe",
        )
        try:
            process.start()
        except Exception as exc:
            raise ProbeWorkerStartError(
                f"probe worker could not start: {type(exc).__name__}: {exc}"
            ) from exc
        process_started = True
        sender.close()
        sender = None
        deadline = time.monotonic() + timeout_seconds
        try:
            message = _read_message(receiver, deadline)
        except TimeoutError as exc:
            _stop_process(process)
            raise TimeoutError(f"probe exceeded {timeout_seconds:g}s runtime budget") from exc
        process.join(timeout=max(0.0, deadline - time.monotonic()))
        if process.is_alive():
            _stop_process(process)
            raise TimeoutError(f"probe exceeded {timeout_seconds:g}s runtime budget")
        if message["status"] == "error":
            raise ProbeWorkerError(str(message["error"]))
        result = message.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("probe worker returned an invalid result")
        return result
    except TimeoutError:
        if process is not None and process_started and process.is_alive():
            _stop_process(process)
        raise
    finally:
        worker_stopped = process is None or not process_started
        try:
            if sender is not None:
                sender.close()
        finally:
            try:
                if receiver is not None:
                    receiver.close()
            finally:
                if process is not None and process_started:
                    if process.is_alive():
                        _stop_process(process)
                    process.join(timeout=0)
                    worker_stopped = not process.is_alive()
                if worker_stopped:
                    slots.release()


def _probe_entry(
    sender: Connection,
    name: str,
    params: dict[str, JsonValue],
    max_sample_rows: int,
) -> None:
    try:
        import akshare

        target = getattr(akshare, name, None)
        module = getattr(target, "__module__", "")
        if (
            not name.startswith("stock_")
            or not callable(target)
            or not isinstance(module, str)
            or not module.startswith("akshare.")
        ):
            raise ValueError(f"unknown stock capability: {name}")
        _send_message(
            sender,
            {"status": "ok", "result": summarize_probe_result(target(**params), max_sample_rows=max_sample_rows)},
        )
    except Exception as exc:
        _send_message(sender, {"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        sender.close()


def _send_message(sender: Connection, message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_IPC_BYTES:
        payload = json.dumps(
            {"status": "error", "error": "probe result exceeds IPC size limit"}, separators=(",", ":")
        ).encode("utf-8")
    sender.send_bytes(payload)


def _read_message(receiver: Connection, deadline: float) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not receiver.poll(remaining):
        raise TimeoutError("probe worker did not respond before its runtime budget")
    try:
        payload = receiver.recv_bytes(MAX_IPC_BYTES)
    except EOFError as exc:
        raise RuntimeError("probe worker exited without an IPC result") from exc
    try:
        message = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("probe worker returned invalid IPC JSON") from exc
    if not isinstance(message, dict) or message.get("status") not in {"ok", "error"}:
        raise RuntimeError("probe worker returned an invalid IPC message")
    return message


def _stop_process(process: BaseProcess) -> None:
    """超时后先终止，再兜底 kill，并在返回前确认已经退出。"""
    if not process.is_alive():
        process.join(timeout=0)
        return
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)
    if process.is_alive():
        raise RuntimeError("probe worker could not be terminated")
