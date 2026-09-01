"""进程是否还活着（跨平台）。仓内「按 pid 探活」的**唯一**实现。

两个消费者，同一个问题的两种形态：

1. ``ops`` 的任务占槽（``store_runs``）：进程崩溃时 ``finish_run`` 不会执行，
   ``running`` 记录会永久占槽。靠时间窗兜底太慢——盘后同步挂死会卡死整晚的选股。
2. ``market`` 的跨进程写锁（``write_lock``）：崩溃留下的锁文件会把**别的**进程
   硬挡满 ``_LOCK_STALE_SEC``（30 分钟）。一次崩溃换来半小时行情库全面瘫痪。

两处以前各自为政（ops 有实现，market 只会看锁文件的 mtime），于是同一个「多久
算挂了」在仓里有两套答案。合到这里之后 ``ops`` / ``market`` 都从这一份取。

**保守方向是刻意的**：探不出来一律当「还活着」。误判活着只是多等一会儿（有时间
窗兜底）；误判已死会把一个正在写库的进程踢掉，那才是真损失。

**Windows 上绝对不能用 ``os.kill(pid, 0)``**：CPython 在 Windows 上把
``os.kill`` 映射到 ``TerminateProcess``，signal 0 也照杀——探活会变成杀活。
"""
from __future__ import annotations

import os
import sys


def current_pid() -> int:
    return int(os.getpid())


def pid_alive(pid: int) -> bool:
    """``pid<=0`` 视为未知（旧数据/无进程号），不当成已死，留给时间窗回收。"""
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
