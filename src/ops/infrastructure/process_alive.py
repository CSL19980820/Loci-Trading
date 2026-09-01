"""判断任务占槽进程是否还活着。

进程崩溃时 finish_run 不会执行，running 记录会永久占槽。
靠「超时 2 小时」太慢——盘后同步挂死后会卡死整晚的选股。
有 owner_pid 时：进程已死 → 立刻回收。

**实现已收拢到 ``src.shared.process_alive``**：`market` 的跨进程写锁要问同一个
问题（崩溃留下的锁文件该不该接管），两边各写一份就会让「多久算挂了」在仓里出现
两套答案。这里只保留 ops 侧的名字（``pid_is_alive``，`store_runs` 在用），语义与
保守方向都由那一份负责，勿在此处另加分支。
"""
from __future__ import annotations

from src.shared.process_alive import current_pid, pid_alive

__all__ = ["current_pid", "pid_is_alive"]


def pid_is_alive(pid: int) -> bool:
    """pid<=0 视为未知（旧数据），不当成已死，留给时间窗回收。"""
    return pid_alive(pid)
