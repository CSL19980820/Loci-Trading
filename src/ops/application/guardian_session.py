"""交易员研判窗口独立于可成交窗口；开闭市边界也保留研判。"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

GUARDIAN_CRON = '25-55/5 9 * * mon-fri; */5 10,13-14 * * mon-fri; 0-30/5 11 * * mon-fri; 0 15 * * mon-fri'
CADENCE_MINUTES = 5


def is_opening_review(now: datetime) -> bool:
    value = now.astimezone(ZoneInfo('Asia/Shanghai'))
    return value.weekday() < 5 and time(9, 25) <= value.time().replace(tzinfo=None) < time(9, 30)


def in_review_window(now: datetime) -> bool:
    value = now.astimezone(ZoneInfo('Asia/Shanghai'))
    clock = value.time().replace(second=0, microsecond=0)
    return value.weekday() < 5 and (time(9,25) <= clock <= time(11,30) or time(13) <= clock <= time(15))


def review_slot(now: datetime) -> str:
    return now.replace(minute=now.minute // CADENCE_MINUTES * CADENCE_MINUTES, second=0, microsecond=0).isoformat()


def recover_finished_runs(ledger, store) -> None:
    """只回收已有终态运行回执的占位，不把等待或心跳延迟当成进程死亡。"""
    for cycle in ledger.running_cycles():
        owner = cycle['result'].get('owner_run_id')
        run = store.get_run(owner) if owner else None
        if run and run['status'] in {'success', 'failed', 'cancelled', 'skipped', 'expired', 'timed_out'}:
            try:
                ledger.finish(cycle['slot'], {'status':'expired','error':f'关联任务{owner}已结束，回收未完成研判占位；下一轮重新核验。','owner_run_id':owner}, run_id=owner)
            except RuntimeError:
                pass  # 另一个进程已先完成/回收；claim 的事务仍防止重复执行。
