"""Windows 桌面单实例：二次启动则前置已有窗口并退出。"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any

ERROR_ALREADY_EXISTS = 183
STILL_ACTIVE = 259
SW_RESTORE = 9
SW_SHOW = 5

_mutex_handle: Any = None


def mutex_name_for(writable_root: Path) -> str:
    """按安装根目录区分互斥量，避免开发态 loci.py 与打包 Loci.exe 互挡。"""
    digest = hashlib.sha1(
        str(writable_root.resolve()).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"Local\\LociDesktopSingleInstance_{digest}"


# 兼容旧测试 / 外部引用：默认名仅作文档占位，真实抢锁用 mutex_name_for
MUTEX_NAME = "Local\\LociDesktopSingleInstance"


def _kernel32() -> Any:
    return ctypes.windll.kernel32


def _user32() -> Any:
    return ctypes.windll.user32


def lock_path(writable_root: Path) -> Path:
    return writable_root / "data" / "loci.instance.lock"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = _kernel32().OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not _kernel32().GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == STILL_ACTIVE
    finally:
        _kernel32().CloseHandle(handle)


def read_instance(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def write_instance(path: Path, *, pid: int, port: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": int(pid), "port": port}
    path.write_text(json.dumps(payload), encoding="utf-8")


def clear_instance(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def acquire_mutex(name: str | None = None) -> bool:
    """拿到互斥量返回 True（本进程为首实例）；已被占用返回 False。"""
    global _mutex_handle
    mutex = str(name or MUTEX_NAME)
    handle = _kernel32().CreateMutexW(None, False, mutex)
    if not handle:
        return True  # 拿不到互斥也不要挡启动
    _mutex_handle = handle
    return int(_kernel32().GetLastError()) != ERROR_ALREADY_EXISTS


def release_mutex() -> None:
    global _mutex_handle
    if _mutex_handle:
        try:
            _kernel32().ReleaseMutex(_mutex_handle)
            _kernel32().CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None


def focus_pid_windows(pid: int) -> bool:
    """把目标进程的顶层窗口还原并前置。"""
    if not pid_alive(pid):
        return False

    user32 = _user32()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) != pid:
            return True
        # 只要有标题的顶层窗（含被 hide 的主窗）
        if user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        found.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not found:
        return False

    hwnd = found[0]
    foreground = user32.GetForegroundWindow()
    fore_tid = user32.GetWindowThreadProcessId(foreground, None)
    cur_tid = _kernel32().GetCurrentThreadId()
    attached = False
    if fore_tid and cur_tid and fore_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(fore_tid, cur_tid, True))
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fore_tid, cur_tid, False)
    return True


def claim_or_focus(writable_root: Path) -> bool:
    """
    首实例：写入锁并返回 True（继续启动）。
    已有实例：尝试前置其窗口并返回 False（调用方应退出）。
    """
    path = lock_path(writable_root)
    first = acquire_mutex(mutex_name_for(writable_root))
    if first:
        write_instance(path, pid=os.getpid())
        return True

    existing = read_instance(path)
    pid = int(existing.get("pid") or 0) if existing else 0
    if pid and pid != os.getpid() and pid_alive(pid):
        focus_pid_windows(pid)
        return False

    # 互斥被占但锁文件 PID 已死：清陈旧锁，仍返回 False（本轮退出，用户再点一次）
    if pid and pid != os.getpid():
        clear_instance(path)
    return False


def update_port(writable_root: Path, port: int) -> None:
    path = lock_path(writable_root)
    current = read_instance(path) or {}
    write_instance(path, pid=int(current.get("pid") or os.getpid()), port=port)
