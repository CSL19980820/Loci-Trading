"""行情重任务进程内互斥：sync 独占写；screen 可并行读。

APScheduler / HTTP 同进程内，盘中同步若 SSL 重试拖很久，尾盘选股再开
第二条连接扫 market.db，容易把 WAL 读路径顶成 disk I/O error。
跨进程互斥不在此范围（单 worker 部署是本仓约定）。

设计：
- sync = 写者独占（与任何 screen/sync 互斥）
- screen = 共享读（多路选股可并行；spot 单飞已在 market 层合并）
这样不会出现「潜龙等三源选股 90s」这种假互斥。
- 14:35–15:00 盘中增量（mode=full）在占锁前直接跳过，避免与杨氏/三源
  14:50 同分钟抢锁；日终 today_refresh 不跳过（15:30 选股要吃定稿 spot）。
- **排队 ≠ 故障**。等不到锁时先看持锁者健不健康：还在租期内（sync 未超
  MARKET_SYNC_STUCK_SEC、screen 未超 MARKET_SCREEN_HOLD_LEASE_SEC）一律按
  JobSkipped 收场——本轮不插入、下一轮再跑，不刷红运维页也不推企微；
  只有持锁者真的超过租期（疑似卡死）才判 JobError。
- 等锁上限可配：``LOCI_MARKET_GATE_SYNC_WAIT_SEC`` /
  ``LOCI_MARKET_GATE_SCREEN_WAIT_SEC``。旧的 sync 90s 与 45 分钟的选股租期
  严重失配——正常排队必然超时，于是每天稳定造一次假故障。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobError, JobSkipped
from src.shared.observability import event, record_lock_wait

logger = logging.getLogger(__name__)

#: 会重压 market.db 的任务类型
MARKET_HEAVY_KINDS = frozenset({"sync", "screen"})


def _env_seconds(name: str, default: float, *, minimum: float = 1.0) -> float:
    """读环境变量里的秒数；缺失/非法/过小一律回落，绝不让配置把闸门变成 0 秒。"""
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是数字，改用默认 %s 秒", name, raw, default)
        return float(default)
    if value < minimum:
        logger.warning("环境变量 %s=%s 太小，抬到 %s 秒", name, value, minimum)
        return float(minimum)
    return value


#: 同步等锁上限（秒），``LOCI_MARKET_GATE_SYNC_WAIT_SEC`` 可覆盖。
#: 旧值 90s 与 45 分钟的选股租期完全失配：只要前面有人在正常跑，排队就必然超时，
#: 于是「等锁超时」天天被当成故障上报。现在默认 20 分钟——与租期同数量级；
#: 而且到点了也只是 JobSkipped（下轮再跑），真正的卡死另有判据。
MARKET_LOCK_WAIT_SEC = _env_seconds(
    "LOCI_MARKET_GATE_SYNC_WAIT_SEC", 20 * 60.0, minimum=10.0
)
#: 选股等锁上限（秒），``LOCI_MARKET_GATE_SCREEN_WAIT_SEC`` 可覆盖。
#: 选股多等一会儿：14:50 / 15:30 可能碰上上一档还没放锁的增量/日终。
MARKET_SCREEN_LOCK_WAIT_SEC = _env_seconds(
    "LOCI_MARKET_GATE_SCREEN_WAIT_SEC", 360.0, minimum=10.0
)
#: 同步持锁多久算「疑似卡死」。全市场同步跑几分钟很正常，此前一律判 failed，
#: 于是「日终重刷排在盘后同步后面」这种正常排队每天报一次假故障。
#: 与 ops.db 的 sync stale 回收窗（store_runs.STALE_RUN_SECONDS_BY_KIND）同口径，
#: 避免仓里出现两套「多久算挂了」。
MARKET_SYNC_STUCK_SEC = 45 * 60.0
#: 选股占读槽的上限。选股本身可能真跑十几分钟（2026-08-21 三源尾盘 984s），
#: 所以这里跟 ops.db 的 screen stale 回收窗（store_runs.STALE_RUN_SECONDS_BY_KIND）
#: 取同一口径：到点仍不放槽的，ops.db 那条 run 也已被判 failed，闸门不该继续替
#: 一个已经判死的任务挡住同步。
MARKET_SCREEN_HOLD_LEASE_SEC = 45 * 60.0

_TZ = ZoneInfo("Asia/Shanghai")
#: 14:35 起不再新开盘中增量，给 14:50 尾盘选股让路。
_TAIL_PROTECT_START_MIN = 14 * 60 + 35
_TAIL_PROTECT_END_MIN = 15 * 60

_COND = threading.Condition()
_WRITER: str | None = None
#: 写者占锁的起点（monotonic），用来区分「正在跑」和「疑似卡死」。
_WRITER_SINCE: float = 0.0
_READERS: dict[str, int] = {}
#: 每个读者标签最早占槽的时刻（monotonic），用来识别赖着不走的选股。
_READER_SINCE: dict[str, float] = {}
#: 正在排队的写者数。>0 时不再放新读者进来：读者可以并行，
#: 但不能一波接一波地插队，否则同步永远等不到空窗（写者饥饿）。
_WRITERS_WAITING: int = 0
#: 同一线程已持槽位：``{kind: 槽位标签}``。run_job 已为 sync/screen 占好槽，
#: 执行器内部再调一次 market_heavy_slot（execute_sync 现在自己也占槽，好让
#: HTTP / bootstrap / CLI 这些不走 run_job 的入口同样受闸门管辖）时必须直接
#: 放行，否则自锁。**判据是同 kind，不是「持有任意 kind」**——理由见
#: ``market_heavy_slot``。记到标签一级是因为 screen→sync 的跨 kind 升级要能
#: 找回自己那把读槽并临时让位。
_LOCAL = threading.local()


def in_tail_screen_protect_window(now: datetime | None = None) -> bool:
    """工作日 14:35–15:00：尾盘选股窗口，盘中增量不应再占行情库。"""
    if now is None:
        current = datetime.now(_TZ)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=_TZ)
    else:
        current = now.astimezone(_TZ)
    if current.weekday() >= 5:
        return False
    minutes = current.hour * 60 + current.minute
    return _TAIL_PROTECT_START_MIN <= minutes < _TAIL_PROTECT_END_MIN


def skip_reason_for_intraday_sync(
    kind: str,
    job: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """14:50 尾盘选股优先：盘中增量（非日终 today_refresh）在保护窗内不占锁。"""
    if str(kind or "") != "sync":
        return None
    config = job.get("config") if isinstance(job, dict) else {}
    if not isinstance(config, dict):
        config = {}
    if str(config.get("mode") or "full").strip() == "today_refresh":
        return None
    if not in_tail_screen_protect_window(now):
        return None
    return "14:35–15:00 让路给尾盘选股，本轮盘中增量跳过"


def _held_slots() -> dict[str, str]:
    """本线程已持有的行情重任务槽位：``kind -> 槽位标签``。"""
    slots = getattr(_LOCAL, "slots", None)
    if slots is None:
        slots = {}
        _LOCAL.slots = slots
    return slots


def _wait_seconds(exclusive: bool) -> float:
    return float(MARKET_LOCK_WAIT_SEC if exclusive else MARKET_SCREEN_LOCK_WAIT_SEC)


def _slot_label(kind: str, job_name: str) -> str:
    """人话标签；避免 screen:screen:xxx 重复前缀。"""
    name = str(job_name or "").strip() or "未命名"
    kind = str(kind or "").strip() or "?"
    if name == kind or name.startswith(f"{kind}:"):
        return name
    return f"{kind}:{name}"


def _describe_hold(label: str, since: float) -> str:
    minutes = int(max(0.0, time.monotonic() - since) // 60)
    return f"{label}·已{minutes}分钟" if minutes >= 1 else label


def _holder_text() -> str:
    if _WRITER:
        return f"同步任务「{_describe_hold(_WRITER, _WRITER_SINCE)}」"
    if _READERS:
        names = "、".join(
            _describe_hold(name, _READER_SINCE.get(name, time.monotonic()))
            for name in list(_READERS)[:3]
        )
        extra = len(_READERS) - 3
        if extra > 0:
            names = f"{names} 等 {len(_READERS)} 个"
        return f"选股任务（{names}）"
    return "未知任务"


def _evict_expired_readers() -> list[str]:
    """踢掉超过租约还没放槽的读者。

    选股卡在补 spot 或 LLM 上时，进程内的读槽就成了永久占用：ops.db 里那条
    run 早被 stale 回收判 failed，闸门却还以为有人在读，于是此后每一次同步都
    在这里等满超时。租约到期即视为已废弃——它真跑完时 ``_release_reader``
    找不到自己的键，也不会把别人的计数减坏。
    """
    now = time.monotonic()
    expired = [
        name
        for name, since in _READER_SINCE.items()
        if now - since >= MARKET_SCREEN_HOLD_LEASE_SEC
    ]
    for name in expired:
        _READERS.pop(name, None)
        _READER_SINCE.pop(name, None)
        logger.error(
            "选股「%s」占用行情库超过 %d 分钟仍未收工，按已废弃处理并放行同步；"
            "请到运维「执行历史」确认该选股是否卡死",
            name,
            int(MARKET_SCREEN_HOLD_LEASE_SEC // 60),
        )
    return expired


def _writer_timeout(label: str, waited_sec: float) -> JobError:
    """同步等不到锁的收场。

    判据只有一条：**持锁者还在租期内吗**。

    - 在租期内（同步 < MARKET_SYNC_STUCK_SEC、选股 < MARKET_SCREEN_HOLD_LEASE_SEC）
      → 这是一次正常排队，返回 JobSkipped：本轮不插入、下一轮再跑，
      不刷红运维页也不推企微。
    - 超过租期 → 持锁者疑似卡死，返回 JobError，明确要人来看。
    - 谁都没持锁却还是等不到 → 闸门状态异常，同样是 JobError。
    """
    now = time.monotonic()
    waited = int(max(0.0, waited_sec))
    if _WRITER:
        held_sec = max(0.0, now - _WRITER_SINCE)
        if held_sec >= MARKET_SYNC_STUCK_SEC:
            return JobError(
                f"同步任务「{_WRITER}」已占用行情库 {int(held_sec / 60)} 分钟，"
                f"超过 {int(MARKET_SYNC_STUCK_SEC // 60)} 分钟租期（疑似卡死）；"
                f"同步「{label}」等待 {waited} 秒仍未轮到，"
                "请到运维「执行历史」停掉它，或稍后再试"
            )
        return JobSkipped(
            f"行情库正被同步任务「{_WRITER}」写入（已 {int(held_sec / 60)} 分钟），"
            f"同步「{label}」等待 {waited} 秒未轮到；"
            "两者写的是同一批当日行情，本轮跳过，无需处理"
        )
    if _READERS:
        oldest = min(_READER_SINCE.values(), default=now)
        held_sec = max(0.0, now - oldest)
        if held_sec >= MARKET_SCREEN_HOLD_LEASE_SEC:
            return JobError(
                f"行情库正被占用（{_holder_text()}），且已超过 "
                f"{int(MARKET_SCREEN_HOLD_LEASE_SEC // 60)} 分钟租期仍不放槽（疑似卡死）；"
                f"同步「{label}」等待 {waited} 秒仍未轮到，"
                "请到运维「执行历史」确认那条选股"
            )
        # 选股确实在正常跑，同步只是这一轮没排上——这不是错误，是排队。
        return JobSkipped(
            f"行情库正被占用（{_holder_text()}），同步「{label}」等待 "
            f"{waited} 秒未轮到；选股仍在正常执行，本轮同步排队未插入，"
            "下一轮再跑，无需处理"
        )
    return JobError(
        f"同步「{label}」等待 {waited} 秒仍拿不到行情库写槽，"
        "但闸门里查不到任何持有者；这属于闸门状态异常，请重启应用后重试"
    )


def _acquire_writer(label: str, deadline: float, wait_sec: float) -> None:
    global _WRITER, _WRITER_SINCE, _WRITERS_WAITING
    started = deadline - wait_sec
    _WRITERS_WAITING += 1
    try:
        while True:
            _evict_expired_readers()
            if _WRITER is None and not _READERS:
                _WRITER = label
                _WRITER_SINCE = time.monotonic()
                return
            now = time.monotonic()
            # 持锁的同步已经超租期 = 真卡死。别再陪它耗到自己的 deadline：
            # 等满再报只会让「真故障」晚十几分钟才被看见。
            if _WRITER and now - _WRITER_SINCE >= MARKET_SYNC_STUCK_SEC:
                raise _writer_timeout(label, now - started)
            remaining = deadline - now
            if remaining <= 0:
                raise _writer_timeout(label, wait_sec)
            # 该醒的时点取最早的一个：自己的 deadline / 读者租约到期 / 写者被判卡死。
            if _READERS:
                oldest = min(_READER_SINCE.values(), default=now)
                lease_left = MARKET_SCREEN_HOLD_LEASE_SEC - (now - oldest)
                remaining = min(remaining, max(0.05, lease_left))
            if _WRITER:
                stuck_left = MARKET_SYNC_STUCK_SEC - (now - _WRITER_SINCE)
                remaining = min(remaining, max(0.05, stuck_left))
            _COND.wait(timeout=remaining)
    finally:
        _WRITERS_WAITING -= 1
        _COND.notify_all()


def _release_writer(label: str) -> None:
    global _WRITER, _WRITER_SINCE
    if _WRITER == label:
        _WRITER = None
        _WRITER_SINCE = 0.0
    _COND.notify_all()


def _acquire_reader(label: str, deadline: float, wait_sec: float) -> None:
    while True:
        # 已经持槽的同名读者直接重入；否则等写者排空（写者优先，防饥饿）。
        held = label in _READERS
        if _WRITER is None and (held or not _WRITERS_WAITING):
            _READERS[label] = _READERS.get(label, 0) + 1
            _READER_SINCE.setdefault(label, time.monotonic())
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JobError(
                f"行情库正被占用（{_holder_text()}），选股「{label}」等待 "
                f"{int(wait_sec)} 秒仍未轮到；"
                "请先停掉卡住的同步，或稍后再试"
            )
        _COND.wait(timeout=remaining)


def _restore_reader(label: str, since: float | None) -> None:
    """把跨 kind 升级时临时让出的自家读槽原样塞回去（调用方须持 _COND）。

    不走 ``_acquire_reader``：本线程从没真正放弃外层 screen 的所有权，只是为了
    让内层 sync 拿到独占写槽而暂时让位。再去排一次队会被后到的写者挡住（写者
    优先），甚至在 finally 里抛超时，把内层同步已经做完的事盖成一次假故障。
    ``since`` 沿用原值，免得升级一趟就把读槽的租约时钟洗白。
    """
    _READERS[label] = _READERS.get(label, 0) + 1
    _READER_SINCE.setdefault(label, time.monotonic() if since is None else since)


def _release_reader(label: str) -> None:
    count = _READERS.get(label, 0) - 1
    if count <= 0:
        _READERS.pop(label, None)
        _READER_SINCE.pop(label, None)
    else:
        _READERS[label] = count
    if not _READERS:
        _COND.notify_all()


@contextmanager
def market_heavy_slot(kind: str, job_name: str) -> Iterator[None]:
    """sync 独占；screen 共享；其它 kind 直接放行。

    重入判据是**同 kind**，不是「本线程持有任意 kind」：

    - 同 kind（run_job 外层 sync + execute_sync 内层 sync）要的是同一把槽、
      同一批写入，再抢一次只会自锁 —— 直接放行。
    - sync 写槽里再要 screen 读槽：独占写槽本来就涵盖读权限，此刻整个
      market.db 只有本线程能碰，也按重入放行；真去排队反而是在等自己。
    - **screen 读槽里再要 sync 写槽**：这是跨 kind，两者要的根本不是同一把槽。
      一边扫 market.db、一边写 WAL，正是本模块开头讲的 disk I/O error 组合。
      旧判据（``if held:``）把它一并静默放行，等于闸门对最危险的那种嵌套失效
      —— 只要有人在 screen executor 里加一次 execute_sync 就会被激活。
      现在它会真去抢独占写槽；为了不撞上「_acquire_writer 要等 _READERS 排空，
      而其中一份读槽正攥在自己手里」的自锁，先把自家读槽临时交回去，写完再在
      同一个临界区里降级取回（见 ``_restore_reader``）。
    """
    if kind not in MARKET_HEAVY_KINDS:
        yield
        return

    held = _held_slots()
    if kind in held or (kind == "screen" and "sync" in held):
        yield
        return

    label = _slot_label(kind, job_name)
    exclusive = kind == "sync"
    wait_sec = _wait_seconds(exclusive)
    deadline = time.monotonic() + wait_sec
    started = time.monotonic()
    outcome = "ok"
    #: 跨 kind 升级时临时让出的自家读槽（标签 + 原租约起点），完事要原样还回。
    ceded_reader: str | None = None
    ceded_since: float | None = None
    try:
        with _COND:
            if exclusive and "screen" in held:
                ceded_reader = held["screen"]
                ceded_since = _READER_SINCE.get(ceded_reader)
                _release_reader(ceded_reader)
            if exclusive:
                _acquire_writer(label, deadline, wait_sec)
            else:
                _acquire_reader(label, deadline, wait_sec)
    except JobError as exc:
        if ceded_reader is not None:
            # 没抢到写槽就把外层选股的读槽还回去，
            # 否则这一趟失败的等锁会顺手把人家的槽吞掉。
            with _COND:
                _restore_reader(ceded_reader, ceded_since)
        benign = isinstance(exc, JobSkipped)
        outcome = "skipped" if benign else "timeout"
        wait_ms = max(0, int((time.monotonic() - started) * 1000))
        record_lock_wait(
            component="market_gate",
            kind=kind,
            wait_ms=wait_ms,
            outcome=outcome,
            reason="peer_sync" if benign else "deadline",
        )
        event(
            logger,
            logging.INFO if benign else logging.WARNING,
            "market_gate_lock_timeout",
            fields={"kind": kind, "wait_ms": wait_ms, "outcome": outcome},
        )
        raise
    wait_ms = max(0, int((time.monotonic() - started) * 1000))
    record_lock_wait(
        component="market_gate",
        kind=kind,
        wait_ms=wait_ms,
        outcome=outcome,
    )
    logger.info("行情重任务占锁：%s（%s）", label, "独占" if exclusive else "共享")
    held[kind] = label
    try:
        yield
    finally:
        held.pop(kind, None)
        with _COND:
            if exclusive:
                _release_writer(label)
            else:
                _release_reader(label)
            if ceded_reader is not None:
                # 与放写锁同一临界区内取回：中间一放开就可能让第二个写者插进来，
                # 变成「别人在写 + 自己在读」同时成立。
                _restore_reader(ceded_reader, ceded_since)
        logger.info("行情重任务放锁：%s", label)
