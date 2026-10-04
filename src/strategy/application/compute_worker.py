"""未知策略的可终止计算边界；只接收面板并返回数值结果，不持有数据库连接。

使用 spawn，避免继承 API 的连接/线程状态。Python 包在临时目录重建，默认应用
数据路径也指向该目录。它是资源与故障隔离，不是对任意 Python IO 的安全沙箱。
pure 引擎是否留在进程内由调用方决定，本模块不会绕过未知策略的隔离执行。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields
from io import BytesIO
import json
import math
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import os
from pathlib import Path
import pickle
import sys
import tempfile
import time
from typing import Any

import numpy as np
import pandas as pd

from src.shared.tenancy import current_tenant, tenant_scope
from src.strategy.domain.base import SignalResult, StrategyError

DEFAULT_COMPUTE_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
DEFAULT_MEMORY_HEADROOM_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
_ERROR_BYTES = 8192
_WORKER_ACTIVE: ContextVar[bool] = ContextVar("strategy_compute_worker_active", default=False)
_TIMEOUT_ENV = "LOCI_PYTHON_COMPUTE_TIMEOUT_SECONDS"
_MEMORY_ENV = "LOCI_PYTHON_COMPUTE_MEMORY_HEADROOM_MB"


class ComputeWorkerError(StrategyError):
    def __init__(self, message: str, *, code: str = "E_COMPUTE_WORKER") -> None:
        super().__init__(message)
        self.code = code


class ComputeWorkerTimedOut(ComputeWorkerError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="E_COMPUTE_TIMEOUT")


class ComputeWorkerCancelled(ComputeWorkerError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="E_COMPUTE_CANCELLED")


def compute_in_worker(
    engine: Any,
    panels: Mapping[str, Any],
    params: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    memory_headroom_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    audit: bool = False,
) -> SignalResult:
    """一次性 spawn 计算；超时、取消、错误均等待进程真正退出后再返回。

    PythonScreenEngine 通过声明字段和包文件重建（不传锁、callable 或临时目录）；
    其他引擎必须可由标准 pickle 重建，否则明确失败，不退回请求线程计算。
    墙钟预算包括启动、子进程源码导入、compute 与输出编码。运行时和输入已加载
    后、未知源码加载前硬限新增内存：默认 512 MiB，可用 memory_headroom_bytes
    或 LOCI_PYTHON_COMPUTE_MEMORY_HEADROOM_MB 调整。Linux 限虚拟空间，Windows
    限提交内存；它们不是 RSS 上限，输入加载预算仍由调用方负责。
    """
    result = _run_worker(
        engine, "screen" if audit else "compute", {"panels": dict(panels), "params": params},
        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
        memory_headroom_bytes=memory_headroom_bytes, cancel_check=cancel_check,
    )
    if not isinstance(result, SignalResult):
        raise ComputeWorkerError("计算进程返回了错误的结果类型", code="E_COMPUTE_OUTPUT")
    return result


def in_compute_worker() -> bool:
    """明确受控的隔离子进程上下文内为 True，防止适配器递归 spawn。"""
    return _WORKER_ACTIVE.get()


@contextmanager
def python_worker_scope():
    """供已有隔离子进程复用边界；调用者必须已有硬超时与取消监督。

    只应在子进程入口使用，不能在 API/普通任务线程使用。特别是 daemon 回测
    worker 不能再 spawn 子进程；它的父进程负责终止该整条计算。
    """
    token = _WORKER_ACTIVE.set(True)
    try:
        yield
    finally:
        _WORKER_ACTIVE.reset(token)


def inspect_python_in_worker(engine: Any) -> dict[str, Any]:
    """加载/校验入口并返回声明标志，不把未知 callable 交回父进程。"""
    return _run_worker(engine, "inspect", {}, max_output_bytes=_ERROR_BYTES)


def call_python_attribute_in_worker(engine: Any, attribute: str, arguments: tuple[Any, ...]) -> Any:
    if attribute not in {"history_bars", "live_candidate_codes"}:
        raise ComputeWorkerError("不支持的 Python 策略属性", code="E_COMPUTE_ATTRIBUTE")
    return _run_worker(engine, "attribute", {"name": attribute, "arguments": arguments})


def _run_worker(
    engine: Any, operation: str, arguments: dict[str, Any], *,
    timeout_seconds: float | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    memory_headroom_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Any:
    if timeout_seconds is None:
        try:
            timeout_seconds = float(os.environ.get(_TIMEOUT_ENV, str(DEFAULT_COMPUTE_TIMEOUT_SECONDS)))
        except (TypeError, ValueError):
            timeout_seconds = DEFAULT_COMPUTE_TIMEOUT_SECONDS
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ComputeWorkerTimedOut("未知策略没有有效的剩余计算时间预算")
    from src.strategy.application.compute_runtime import remaining_unknown_seconds

    remaining = remaining_unknown_seconds()
    if remaining is not None:
        timeout_seconds = min(timeout_seconds, remaining)
        if timeout_seconds <= 0:
            raise ComputeWorkerTimedOut("本次选股任务的未知策略总时间预算已耗尽")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ComputeWorkerError("计算输出大小预算必须是正整数", code="E_COMPUTE_BUDGET")
    if memory_headroom_bytes is None:
        try:
            memory_headroom_bytes = int(os.environ.get(
                _MEMORY_ENV, str(DEFAULT_MEMORY_HEADROOM_BYTES // (1024 * 1024)),
            )) * 1024 * 1024
        except (TypeError, ValueError) as exc:
            raise ComputeWorkerError("策略内存预算配置必须为正整数 MiB", code="E_COMPUTE_MEMORY") from exc
    if (isinstance(memory_headroom_bytes, bool) or not isinstance(memory_headroom_bytes, int)
            or not 0 < memory_headroom_bytes <= sys.maxsize // 2):
        raise ComputeWorkerError("策略新增内存预算必须为正整数 bytes", code="E_COMPUTE_MEMORY")
    deadline = time.monotonic() + timeout_seconds
    receiver: Connection | None = None
    sender: Connection | None = None
    process: BaseProcess | None = None
    memory_job = None
    started = False
    with tempfile.TemporaryDirectory(prefix="loci-compute-") as directory:
        try:
            specification = _engine_specification(engine, Path(directory), deadline=deadline)
            if cancel_check is not None and cancel_check():
                raise ComputeWorkerCancelled("未知策略计算已按请求取消")
            if time.monotonic() >= deadline:
                raise ComputeWorkerTimedOut("未知策略准备阶段已耗尽计算时间预算")
            context = get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            # The child cannot import strategy source until the parent assigns its
            # Windows Job Object. Runtime/imports and input unpickling precede this gate.
            memory_gate = context.Event() if os.name == "nt" else None
            process = context.Process(
                target=_worker_entry,
                args=(sender, specification, operation, arguments, current_tenant(), directory,
                      max_output_bytes, memory_headroom_bytes, memory_gate),
                daemon=True, name="loci-strategy-compute",
            )
            try:
                process.start()
            except Exception as exc:
                raise ComputeWorkerError(
                    f"未知策略计算进程启动失败：{type(exc).__name__}", code="E_COMPUTE_START",
                ) from exc
            started = True
            sender.close()
            sender = None
            while True:
                if cancel_check is not None and cancel_check():
                    raise ComputeWorkerCancelled("未知策略计算已按请求取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ComputeWorkerTimedOut(f"未知策略计算超过 {timeout_seconds:g}s 时间预算")
                if receiver.poll(min(0.1, remaining)):
                    try:
                        payload = receiver.recv_bytes(max(_ERROR_BYTES, max_output_bytes + 1))
                    except (EOFError, OSError) as exc:
                        raise ComputeWorkerError("计算进程未返回完整结果", code="E_COMPUTE_EXIT") from exc
                    if payload == b"R" and memory_gate is not None and memory_job is None:
                        memory_job = _assign_windows_memory_job(process.pid, memory_headroom_bytes)
                        memory_gate.set()
                        continue
                    result = _decode_result(payload)
                    if time.monotonic() >= deadline:
                        raise ComputeWorkerTimedOut("策略结果传输/解码已耗尽计算时间预算")
                    # Return only after cleanup, even if code left a thread alive.
                    process.join(timeout=0.2)
                    return result
                if not process.is_alive():
                    if receiver.poll(0):
                        continue
                    raise ComputeWorkerError(
                        f"计算进程未返回结果即退出（exitcode={process.exitcode}）", code="E_COMPUTE_EXIT",
                    )
        finally:
            if sender is not None:
                sender.close()
            if receiver is not None:
                receiver.close()
            if process is not None:
                try:
                    if started:
                        _stop_process(process)
                finally:
                    try:
                        process.close()
                    finally:
                        if memory_job is not None:
                            memory_job.close()


def _engine_specification(engine: Any, directory: Path, *, deadline: float) -> dict[str, Any]:
    from src.strategy.application.screen_python import PythonScreenEngine

    if type(engine) is PythonScreenEngine:
        stage = directory / "package"
        stage.mkdir()
        total = 0
        if engine.package_files is not None:
            files = ((name, content.encode("utf-8")) for name, content in engine.package_files.items())
        elif engine.install_path:
            root = Path(engine.install_path).resolve()
            files = _installed_package_files(root)
        else:
            raise ComputeWorkerError("Python 策略缺少可重建的包文件", code="E_COMPUTE_ENGINE")
        for relative, content in files:
            if time.monotonic() >= deadline:
                raise ComputeWorkerTimedOut("策略包准备已耗尽计算时间预算")
            total += len(content)
            target = (stage / relative).resolve()
            if not target.is_relative_to(stage.resolve()) or total > MAX_PACKAGE_BYTES:
                raise ComputeWorkerError("策略包路径或大小超出计算进程预算", code="E_COMPUTE_ENGINE")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        kwargs = {item.name: getattr(engine, item.name) for item in fields(engine) if item.init}
        kwargs.update(install_path=str(stage), package_files=None)
        return {"kind": "python", "kwargs": kwargs}
    try:
        payload = pickle.dumps(engine, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        raise ComputeWorkerError(
            "未知策略无法在隔离进程重建（需要可 pickle 的引擎或 Python 技能包）",
            code="E_COMPUTE_ENGINE",
        ) from exc
    return {"kind": "pickle", "payload": payload}


def _installed_package_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.relative_to(root).parts:
            continue
        if not path.resolve().is_relative_to(root) or path.stat().st_size > MAX_PACKAGE_BYTES:
            raise ComputeWorkerError("策略包文件超出可复制的路径或大小范围", code="E_COMPUTE_ENGINE")
        yield path.relative_to(root).as_posix(), path.read_bytes()


def _apply_linux_memory_limit(headroom: int) -> None:
    """Keep NumPy's existing virtual mappings; cap new mappings before unknown import."""
    if not sys.platform.startswith("linux"):
        raise ComputeWorkerError("当前平台没有可用的策略硬内存限制", code="E_COMPUTE_MEMORY")
    try:
        import resource

        baseline = int(Path("/proc/self/statm").read_text().split()[0]) * os.sysconf("SC_PAGE_SIZE")
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = baseline + headroom
        # Respect an outer job/container's existing stricter address-space budget.
        for existing in (soft, hard):
            if existing != resource.RLIM_INFINITY:
                ceiling = min(ceiling, existing)
        if ceiling <= baseline:
            raise ValueError("existing address-space budget has no available headroom")
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        if resource.getrlimit(resource.RLIMIT_AS) != (ceiling, ceiling):
            raise ValueError("address-space budget readback mismatch")
    except (OSError, ValueError, IndexError, OverflowError) as exc:
        raise ComputeWorkerError("无法应用 Linux 策略硬内存限制", code="E_COMPUTE_MEMORY") from exc


def _assign_windows_memory_job(pid: int, headroom: int):
    """Parent-owned Job Object: loaded private commit plus bounded extra memory.

    The child waits at its entry until assignment succeeds. Job-wide memory also
    includes descendants; closing the parent's sole handle kills the complete job.
    Refuse execution if nested jobs or system policy prevent applying these limits.
    """
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("minimum_ws", ctypes.c_size_t),
                    ("maximum_ws", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("basic", BasicLimit), ("io", IoCounters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("page_faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak_ws", "ws", "peak_paged", "paged",
            "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private_usage")]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                wintypes.DWORD, ctypes.c_void_p]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    class JobHandle:
        def __init__(self, handle):
            self.handle = handle

        def close(self):
            if self.handle:
                kernel.CloseHandle(self.handle)
                self.handle = None

    process_handle = kernel.OpenProcess(0x0100 | 0x0001 | 0x0400 | 0x0010, False, pid)
    job = JobHandle(kernel.CreateJobObjectW(None, None))
    try:
        if not process_handle or not job.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        usage = MemoryCounters()
        usage.size = ctypes.sizeof(usage)
        if not psapi.GetProcessMemoryInfo(process_handle, ctypes.byref(usage), usage.size):
            raise ctypes.WinError(ctypes.get_last_error())
        limit = ExtendedLimit()
        # PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE.
        limit.basic.flags = 0x0100 | 0x0200 | 0x2000
        limit.process_memory = limit.job_memory = usage.private_usage + headroom
        if not kernel.SetInformationJobObject(job.handle, 9, ctypes.byref(limit), ctypes.sizeof(limit)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job.handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        observed = ExtendedLimit()
        if not kernel.QueryInformationJobObject(job.handle, 9, ctypes.byref(observed),
                                                ctypes.sizeof(observed), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if (observed.basic.flags & limit.basic.flags != limit.basic.flags
                or observed.process_memory != limit.process_memory
                or observed.job_memory != limit.job_memory):
            raise OSError("Job Object memory budget readback mismatch")
        return job
    except OSError as exc:
        job.close()
        raise ComputeWorkerError(
            "无法应用 Windows 策略 Job Object 硬内存限制", code="E_COMPUTE_MEMORY",
        ) from exc
    finally:
        if process_handle:
            kernel.CloseHandle(process_handle)


def _worker_entry(
    sender: Connection, specification: dict[str, Any], operation: str,
    arguments: dict[str, Any], tenant: str, directory: str, max_output_bytes: int,
    memory_headroom_bytes: int, memory_gate: Any,
) -> None:
    token = _WORKER_ACTIVE.set(True)
    try:
        if memory_gate is not None:
            sender.send_bytes(b"R")
            memory_gate.wait()
        else:
            _apply_linux_memory_limit(memory_headroom_bytes)
        root = Path(directory) / "data"
        root.mkdir()
        for key in list(os.environ):
            if key.startswith(("LOCI_", "PALACE_")):
                os.environ.pop(key)
        os.environ.update({
            "LOCI_DATA_DIR": str(root), "LOCI_CONFIG_JSON": str(root / "loci.config.json"),
            "PALACE_MCP_JSON": str(root / "mcp.json"), "LOCI_IDENTITY_DB": str(root / "identity.db"),
            "PALACE_ENABLE_SCHEDULER": "0", "PALACE_ENV": "local",
        })
        with tenant_scope(tenant):
            if specification["kind"] == "python":
                from src.strategy.application.screen_python import PythonScreenEngine

                engine = PythonScreenEngine(**specification["kwargs"])
            else:
                engine = pickle.loads(specification["payload"])
            if operation in {"compute", "screen"}:
                result = engine.compute(arguments["panels"], arguments["params"])
                if operation == "screen":
                    from src.strategy.application.audit import guard_strategy
                    from src.strategy.application.compute_runtime import project_result

                    guard_strategy(engine, arguments["panels"], params=arguments["params"], baseline=result)
                    result = project_result(result, list(result.signals.index[-3:]))
                payload = b"O" + _encode_result(result, max_output_bytes)
            elif operation == "inspect":
                target = engine._load_callable()
                payload = _encode_json_result({
                    "history_bars": callable(getattr(target, "history_bars", None)),
                    "live_candidate_codes": callable(getattr(target, "live_candidate_codes", None)),
                    "strict_live_ohlcv": getattr(target, "strict_live_ohlcv", False) is True,
                }, max_output_bytes)
            elif operation == "attribute":
                target = getattr(engine._load_callable(), arguments["name"], None)
                result = target(*arguments["arguments"]) if callable(target) else None
                payload = _encode_json_result(result, max_output_bytes)
            else:
                raise ComputeWorkerError("未知计算进程操作", code="E_COMPUTE_OPERATION")
            sender.send_bytes(payload)
    except BaseException as exc:
        diagnostics = getattr(exc, "diagnostics", ())
        primary_code = diagnostics[0].code if diagnostics else "E_COMPUTE_EXEC"
        cause = exc
        while cause is not None:
            if isinstance(cause, MemoryError):
                primary_code = "E_COMPUTE_MEMORY"
                break
            cause = cause.__cause__
        message = f"{type(exc).__name__}: {exc}".encode("utf-8")[:4000].decode("utf-8", errors="replace")
        error = json.dumps({
            "code": str(getattr(exc, "code", primary_code))[:128], "message": message,
        }, ensure_ascii=False).encode("utf-8")
        try:
            sender.send_bytes(b"E" + error)
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        _WORKER_ACTIVE.reset(token)
        sender.close()


def _encode_json_result(value: Any, maximum: int) -> bytes:
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputeWorkerError("策略声明/属性必须返回 JSON 数值或标量集合", code="E_COMPUTE_OUTPUT") from exc
    if len(payload) > maximum:
        raise ComputeWorkerError("策略属性输出超过大小预算", code="E_COMPUTE_OUTPUT_LIMIT")
    return b"J" + payload


class _LimitedBuffer(BytesIO):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum

    def write(self, value: bytes) -> int:
        if self.tell() + len(value) > self.maximum:
            raise ComputeWorkerError("策略输出超过大小预算", code="E_COMPUTE_OUTPUT_LIMIT")
        return super().write(value)


def _encode_result(result: SignalResult, maximum: int) -> bytes:
    if not isinstance(result, SignalResult) or not isinstance(result.factors, dict):
        raise ComputeWorkerError("策略必须返回 SignalResult", code="E_COMPUTE_OUTPUT")
    frames = [("signals", "", result.signals)]
    if result.watch_signals is not None:
        frames.append(("watch", "", result.watch_signals))
    frames.extend(("factor", name, frame) for name, frame in result.factors.items())
    descriptor = []
    arrays = {}
    estimated = 0
    for number, (role, name, frame) in enumerate(frames):
        if not isinstance(frame, pd.DataFrame):
            raise ComputeWorkerError("策略输出必须是数值 DataFrame", code="E_COMPUTE_OUTPUT")
        values = frame.to_numpy(copy=False)
        if values.dtype.kind not in "biuf":
            raise ComputeWorkerError("策略输出不能包含 Python 对象或非数值单元格", code="E_COMPUTE_OUTPUT")
        estimated += int(values.nbytes) + int(frame.index.memory_usage(deep=True))
        estimated += int(frame.columns.memory_usage(deep=True))
        if estimated > maximum:
            raise ComputeWorkerError("策略输出超过大小预算", code="E_COMPUTE_OUTPUT_LIMIT")
        arrays[f"frame{number}"] = values
        descriptor.append({
            "role": role, "name": str(name), "index": frame.index.tolist(),
            "columns": frame.columns.tolist(), "index_name": frame.index.name,
            "columns_name": frame.columns.name,
        })
    # Numeric arrays plus JSON axes prevent unpickling child-created Python objects
    # in the API process. Object axes/custom pandas indexes are unsupported.
    try:
        metadata = json.dumps(descriptor, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputeWorkerError("策略输出的轴标签必须是 JSON 标量", code="E_COMPUTE_OUTPUT") from exc
    arrays["metadata"] = np.frombuffer(metadata, dtype=np.uint8)
    # Include NPY/ZIP headers before writing, so ordinary budget failures do not
    # interrupt ZipFile cleanup halfway through its central directory.
    if sum(array.nbytes for array in arrays.values()) + 1024 * len(arrays) > maximum:
        raise ComputeWorkerError("策略输出超过大小预算", code="E_COMPUTE_OUTPUT_LIMIT")
    output = _LimitedBuffer(maximum)
    np.savez(output, **arrays)
    return output.getvalue()


def _decode_result(payload: bytes) -> Any:
    try:
        if payload[:1] == b"E":
            error = json.loads(payload[1:])
            raise ComputeWorkerError(str(error["message"]), code=str(error["code"]))
        if payload[:1] == b"J":
            return json.loads(payload[1:])
        if payload[:1] != b"O":
            raise ValueError("unknown payload")
        with np.load(BytesIO(payload[1:]), allow_pickle=False) as arrays:
            descriptor = json.loads(arrays["metadata"].tobytes())
            signals = None
            watch = None
            factors = {}
            for number, metadata in enumerate(descriptor):
                frame = pd.DataFrame(
                    arrays[f"frame{number}"], index=metadata["index"], columns=metadata["columns"],
                )
                frame.index.name = metadata["index_name"]
                frame.columns.name = metadata["columns_name"]
                if metadata["role"] == "signals":
                    signals = frame
                elif metadata["role"] == "watch":
                    watch = frame
                else:
                    factors[metadata["name"]] = frame
        if signals is None:
            raise ValueError("missing signals")
        return SignalResult(signals=signals, factors=factors, watch_signals=watch)
    except ComputeWorkerError:
        raise
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ComputeWorkerError("计算进程返回了无效数值结果", code="E_COMPUTE_OUTPUT") from exc


def _stop_process(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)
    else:
        process.join(timeout=0)
    if process.is_alive():
        raise ComputeWorkerError("无法终止策略计算进程", code="E_COMPUTE_STOP")
