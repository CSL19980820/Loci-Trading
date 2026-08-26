"""判断任务占槽进程是否还活着（跨平台）。

进程崩溃时 finish_run 不会执行，running 记录会永久占槽。
靠「超时 2 小时」太慢——盘后同步挂死后会卡死整晚的选股。
有 owner_pid 时：进程已死 → 立刻回收。
"""
from __future__ import annotations

import os
import sys


def current_pid() -> int:
    return int(os.getpid())


def pid_is_alive(pid: int) -> bool:
    """pid<=0 视为未知（旧数据），不当成已死，留给时间窗回收。"""
    if pid <= 0:
        return True
    if pid == current_pid():
        return True
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 无权限探活 ≠ 已死
        return True
    except OSError:
        return False
    return True


def _win_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    # PROCESS_QUERY_LIMITED_INFORMATION
    access = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(access, False, int(pid))
    if not handle:
        # 拒绝访问时进程多半还在
        err = int(ctypes.windll.kernel32.GetLastError())
        return err == 5  # ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        # 259 = STILL_ACTIVE；其它值表示该 PID 对应进程已退出（或偶发复用前残留）
        return int(code.value) == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
