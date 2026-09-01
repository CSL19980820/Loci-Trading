"""即时选股的**进度槽状态机**（内存，按「租户 × 战法」双重分片）。

只负责「谁跑到哪了」这一件事：槽的建立与 LRU 淘汰、快照读、增量写、running
互斥（``screen_run_try_begin``），以及协作式取消的立旗
（``screen_run_request_cancel``）与检查点查询（``screen_run_cancel_requested``）。

**不含选股执行体**：那段按交易日循环的计算在同目录 ``screen_run.py``，它是本
模块唯一的写入大户。依赖方向是单向的——本模块不 import ``screen_run``，因此
路由与测试可以只拿进度状态，而不拖起整条选股链路。为兼容既有导入，
``screen_run.py`` 仍 re-export 这里的全部符号；其中 ``_STATES`` 必须是**同一个
对象**（测试会直接 ``clear()`` 它），所以那边只能 import 名字，不能拷贝。

槽的粒度：为什么是「租户 × 战法」而不是「租户」
----------------------------------------------

底层早就允许多战法并行选股：``ops/application/jobs/market_gate.py`` 里 sync 是
写者独占、screen 是**共享读**，行情库（``market.db`` / ``market_hot.db``）多路
并发读不冲突，选股前的当日 spot 刷新在 ``market/infrastructure/sync_spot.py``
里本来就是单飞合并。真正把用户挡在门外的是这里：进度槽曾经**按租户只有一
个**，于是「潜龙出海在跑」会让同一个人连三源、杨氏都点不动，前端还得挂一句
「引擎是后端全局单槽」的告示。

现在一个槽 = 一个 ``(租户, 战法)``：

- 同一战法重复点击仍然防重（``busy_reason='same_strategy'``）——要防的是重复
  入库，不是「不许同时干两件事」。
- 不同战法并行开跑，各有独立的 status / percent / log / result / 取消旗。
- 并发数仍有上限（``MAX_CONCURRENT_RUNS``）：选股主体是同步 pandas 面板计算，
  无节制并行只会把单容器的 CPU 拖成集体变慢。到顶时返回
  ``busy_reason='tenant_limit'``，让前端说清「是排队，不是坏了」。

进度落到哪个槽，按这个顺序解析（见 ``_slot_locked``）：

1. 调用方显式 ``strategy=``（路由点名查询、``start_screen_run_thread`` 的错误
   回填都走这条）；
2. 线程绑定 ``screen_run_slot_scope``——执行体里那二十来处
   ``screen_run_update(...)`` 一个字都不用改，靠 ContextVar 认领自己的槽；
3. 「当前这一个」：最近开跑的 running 槽，否则最近碰过的槽。老调用方与老测试
   的无参 ``screen_run_snapshot()`` / ``screen_run_update()`` 落在这里。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import os
import threading
import time
from typing import Any

from src.shared.tenancy import current_tenant

_LOCK = threading.Lock()

#: 同时保留进度槽的租户上限（LRU）。一条进度里带着完整的 ``result.picks``，
#: 几十个租户各留一份并不小；有任何战法在跑的租户永远不淘汰。
MAX_TENANT_STATES = 64

#: 单租户最多保留几个战法槽（LRU）。跑完的槽要留着给前端回看 picks，所以不能
#: 一结束就丢；但也不能无限留——一个人手动点过十几个战法之后，最早那几条的
#: ``result`` 已经没人看了。淘汰只挑**已结束**的槽。
MAX_RUNS_PER_TENANT = 6

#: 全进程槽数上限。**两个上限相乘不等于有界**：64 租户 × 6 战法 = 384 个槽，
#: 每个槽里躺着一份完整的 ``result.picks``，那是几十上百 MB——服务器只有
#: 1.1 GB（ADR-016：「没有上限的分片是内存泄漏换了个名字」）。所以这里再压一道
#: 总闸，量级与改造前的「64 个租户各一个槽」持平。
MAX_TOTAL_RUN_SLOTS = 96


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    """读环境变量里的整数；缺失/非法/越界一律回落，不让配置把闸门变成 0。"""
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


#: 同一租户允许**同时在跑**的选股数上限，``LOCI_SCREEN_MAX_CONCURRENT_RUNS``
#: 可覆盖。默认 3 = 潜龙 / 三源 / 杨氏 这种「一次把当日战法都点一遍」的实际
#: 用法；再往上加只是让每一个都变慢，收益为负。
MAX_CONCURRENT_RUNS = _env_int(
    "LOCI_SCREEN_MAX_CONCURRENT_RUNS", 3, minimum=1, maximum=16
)

#: 选股进度：``_STATES[tenant][strategy_slug] -> 槽``。
#: 外层按租户分片（跨用户不可见、互不阻塞），内层按战法分片（同一个用户的多个
#: 战法各跑各的）。两层都是 ``OrderedDict``，末尾 = 最近碰过，供 LRU 淘汰。
_STATES: "OrderedDict[str, OrderedDict[str, dict[str, Any]]]" = OrderedDict()

#: 「没绑过」的哨兵。不能用空串——空串是**合法**的槽键（strategy 缺失时的兜底
#: 槽），拿它当默认值会让「线程忘了绑槽」和「绑到了兜底槽」长得一模一样。
_UNBOUND_SLOT = "\x00unbound"

#: 当前上下文正在写哪个战法的槽。``spawn_tenant_thread`` 用 ``copy_context()``
#: 起线程，因此每条选股线程各有一份，互不串写。
_RUN_SLOT: ContextVar[str] = ContextVar("loci_screen_run_slot", default=_UNBOUND_SLOT)


def _slug(strategy: str | None) -> str:
    return str(strategy or "").strip()


@contextmanager
def screen_run_slot_scope(strategy: str) -> Iterator[str]:
    """把「本上下文的进度写进哪个战法槽」钉住。

    执行体（``execute_screen_run``）进来时绑一次，里面所有无参
    ``screen_run_update(...)`` 就自动落到自己的槽——否则多战法并跑时，
    「当前这一个」的解析会让三条线程互相盖进度。
    """
    key = _slug(strategy)
    token = _RUN_SLOT.set(key)
    try:
        yield key
    finally:
        _RUN_SLOT.reset(token)


def _bound_slot() -> str | None:
    """线程绑定的槽键；``None`` = 没绑过（不是「绑到了空串」）。"""
    value = _RUN_SLOT.get()
    return None if value == _UNBOUND_SLOT else value


def _blank_state(strategy: str = "") -> dict[str, Any]:
    return {
        "status": "idle",
        "phase": "",
        "percent": 0.0,
        "message": "",
        "strategy": strategy,
        "trade_date": "",
        "log": [],
        "result": None,
        "error": "",
        # 取消是**协作式**的：这里只立一面旗，真正的退出发生在 execute_screen_run
        # 的检查点上。没有别的办法——选股主体是一段同步的 pandas 面板计算，
        # 线程既不能被安全地杀掉，也没有可打断的 IO 等待点。
        "cancel_requested": False,
        # 后端权威起点 / 心跳（epoch 秒）。前端此前只能记「我什么时候开始看见它」，
        # 刷新页面后耗时只能写「已跟踪」；有了这个就能算出真实「已跑」。
        "started_at": 0.0,
        "updated_at": 0.0,
    }


def _has_running(slots: "OrderedDict[str, dict[str, Any]]") -> bool:
    return any(slot.get("status") == "running" for slot in slots.values())


def _evict_locked() -> None:
    """租户级 LRU：整租户一起丢；有战法在跑的租户不许丢，否则进度凭空消失。"""
    while len(_STATES) > MAX_TENANT_STATES:
        victim = next(
            (name for name, slots in _STATES.items() if not _has_running(slots)),
            None,
        )
        if victim is None:
            return
        _STATES.pop(victim, None)


def _evict_slots_locked(slots: "OrderedDict[str, dict[str, Any]]") -> None:
    """战法级 LRU（单租户内）：只丢最久没碰过的**已结束**槽。"""
    while len(slots) > MAX_RUNS_PER_TENANT:
        victim = next(
            (key for key, slot in slots.items() if slot.get("status") != "running"),
            None,
        )
        if victim is None:
            return
        slots.pop(victim, None)


def _total_slots_locked() -> int:
    return sum(len(slots) for slots in _STATES.values())


def _evict_total_locked(keep: tuple[str, str] | None = None) -> None:
    """全进程总槽数上限：先丢最久没碰过的租户里最久没碰过的**已结束**槽。

    ``keep`` 是刚刚建/刚刚占的那个槽（租户, 槽键）——它绝不能被这一轮淘汰掉：
    调用方手里正握着那个 dict 往里写进度，被摘出表就成了写进真空，进度凭空消失。
    """
    while _total_slots_locked() > MAX_TOTAL_RUN_SLOTS:
        victim: tuple[str, str] | None = None
        for tenant, slots in _STATES.items():
            for key, slot in slots.items():
                if slot.get("status") == "running":
                    continue
                if keep is not None and (tenant, key) == keep:
                    continue
                victim = (tenant, key)
                break
            if victim is not None:
                break
        if victim is None:
            return
        tenant, key = victim
        slots = _STATES.get(tenant)
        if slots is None:
            return
        slots.pop(key, None)
        if not slots:
            _STATES.pop(tenant, None)


def _tenant_slots_locked() -> "OrderedDict[str, dict[str, Any]]":
    """当前租户的战法槽表。调用方必须持有 ``_LOCK``。"""
    tenant = current_tenant()
    slots = _STATES.get(tenant)
    if slots is None:
        slots = OrderedDict()
        _STATES[tenant] = slots
        _evict_locked()
    else:
        _STATES.move_to_end(tenant)
    return slots


def _primary_key_locked(slots: "OrderedDict[str, dict[str, Any]]") -> str | None:
    """「当前这一个」槽键：最近开跑的 running 槽 > 最近碰过的槽 > 没有。

    多战法并跑时「当前这一个」本身就是个含糊概念，所以它只用于兼容老调用方与
    聚合响应的顶层字段；新代码一律点名 ``strategy=``。
    """
    running = [key for key, slot in slots.items() if slot.get("status") == "running"]
    if running:
        return running[-1]
    if slots:
        return next(reversed(slots))
    return None


def _slot_locked(strategy: str | None = None, *, create: bool = True) -> dict[str, Any]:
    """解析出该读/该写的那个槽。调用方必须持有 ``_LOCK``。

    ``create=False`` 时槽不存在就返回一份**游离**的空白态（不入表）：轮询
    ``?strategy=`` 一个从没跑过的战法，不该在内存里给它建槽。
    """
    slots = _tenant_slots_locked()
    key = _slug(strategy) if strategy is not None else _bound_slot()
    if key is None:
        primary = _primary_key_locked(slots)
        key = primary if primary is not None else ""
    slot = slots.get(key)
    if slot is None:
        if not create:
            return _blank_state(key)
        slot = _blank_state(key)
        slots[key] = slot
        _evict_slots_locked(slots)
        _evict_total_locked(keep=(current_tenant(), key))
    else:
        slots.move_to_end(key)
    return slot


def _state_locked() -> dict[str, Any]:
    """兼容旧名：「当前这一个」槽。调用方必须持有 ``_LOCK``。"""
    return _slot_locked()


def _snapshot_of(slot: dict[str, Any]) -> dict[str, Any]:
    snap = dict(slot)
    snap["log"] = list(slot.get("log") or [])
    return snap


def screen_run_snapshot(strategy: str | None = None) -> dict[str, Any]:
    """单个战法槽的快照。

    ``strategy`` 省略时给「当前这一个」（最近开跑 > 最近碰过），保持无参调用方
    与历史测试的语义；点名查询时槽不存在返回 idle 空白态，且不建槽。
    """
    with _LOCK:
        return _snapshot_of(_slot_locked(strategy, create=strategy is None))


def screen_run_snapshot_all() -> dict[str, Any]:
    """聚合快照：顶层兼容单槽形状，``runs`` 是本租户全部战法槽。

    顶层平铺「当前这一个」是为了**滚动升级**：老前端（以及任何直接读 ``status``
    / ``percent`` 的客户端）在后端已经多槽之后仍然读得到一个自洽的快照；新前端
    只看 ``runs`` 与 ``running_strategies``。
    """
    with _LOCK:
        slots = _tenant_slots_locked()
        runs = {key: _snapshot_of(slot) for key, slot in slots.items()}
        primary_key = _primary_key_locked(slots)
        primary = (
            _snapshot_of(slots[primary_key]) if primary_key is not None else _blank_state()
        )
        running = [
            key for key, slot in slots.items() if key and slot.get("status") == "running"
        ]
    return {
        **primary,
        "runs": runs,
        "running_strategies": running,
        "max_concurrent_runs": MAX_CONCURRENT_RUNS,
    }


def screen_run_running_strategies() -> list[str]:
    """本租户正在跑的战法 slug（按开跑先后）。"""
    with _LOCK:
        slots = _tenant_slots_locked()
        return [
            key for key, slot in slots.items() if key and slot.get("status") == "running"
        ]


def screen_run_update(**kwargs: Any) -> None:
    """增量写进度。落到哪个槽见模块 docstring 的三级解析。

    ``strategy=`` 既是**路由键**也是槽内字段：老调用方
    ``screen_run_update(strategy="demo", status="error", ...)`` 因此自动落进 demo
    自己的槽，不会盖到别的战法。
    """
    with _LOCK:
        state = _slot_locked(kwargs.get("strategy"))
        if "log_line" in kwargs:
            line = str(kwargs.pop("log_line") or "").strip()
            if line:
                log = list(state.get("log") or [])
                log.append(line)
                state["log"] = log[-120:]
        state.update(kwargs)
        state["updated_at"] = time.time()
        if state.get("status") == "done":
            state["percent"] = 100.0


def _strategy_display_name(slug: str) -> str:
    """用户可见战法名；解析失败时退回 slug（库内/路由仍用 slug）。"""
    text = str(slug or "").strip()
    if not text:
        return ""
    try:
        from src.strategy.application.catalog import get

        name = str(getattr(get(text), "name", "") or "").strip()
        return name or text
    except Exception:
        return text


def screen_run_try_begin(*, strategy: str, trade_date: str) -> dict[str, Any] | None:
    """占住**这个战法**的槽：成功返回 None，占不到返回占用者快照。

    两种「占不到」的前端文案完全不同，所以必须能区分，快照里带 ``busy_reason``：

    - ``same_strategy``：这个战法自己还在跑（重复点击 / 放弃跟踪后又点了一次）。
    返回的就是它自己的快照，前端应当把界面接回去继续看进度。
    - ``tenant_limit``：并发到顶了。返回最早开跑的那一个，附 ``running_strategies``
    与 ``max_concurrent_runs``，前端要说「先停一个或等一个跑完」，而不是含糊
    的「引擎忙」。

    互斥粒度是「租户 × 战法」：别人在跑不影响我，我跑潜龙也不阻塞我自己跑三源。
    """
    display = _strategy_display_name(strategy)
    key = _slug(strategy)
    now = time.time()
    with _LOCK:
        slots = _tenant_slots_locked()
        state = slots.get(key)
        if state is not None and state.get("status") == "running":
            busy = _snapshot_of(state)
            busy["busy_reason"] = "same_strategy"
            return busy
        running = [k for k, slot in slots.items() if slot.get("status") == "running"]
        if len(running) >= MAX_CONCURRENT_RUNS:
            oldest = min(running, key=lambda k: float(slots[k].get("started_at") or 0.0))
            busy = _snapshot_of(slots[oldest])
            busy["busy_reason"] = "tenant_limit"
            busy["running_strategies"] = list(running)
            busy["max_concurrent_runs"] = MAX_CONCURRENT_RUNS
            return busy
        if state is None:
            state = _blank_state(key)
            slots[key] = state
        state.update(
            {
                "status": "running",
                "phase": "start",
                "percent": 2.0,
                "message": "准备选股…",
                "strategy": strategy,
                "trade_date": trade_date or "",
                "log": [
                    "▶ 开始选股 " + display + (f" · {trade_date}" if trade_date else "")
                ],
                "result": None,
                "error": "",
                # 上一轮如果是被取消结束的，旗子必须落下，否则新一轮开跑即自尽。
                "cancel_requested": False,
                "started_at": now,
                "updated_at": now,
            }
        )
        slots.move_to_end(key)
        _evict_slots_locked(slots)
        _evict_total_locked(keep=(current_tenant(), key))
    return None


def screen_run_request_cancel(strategy: str | None = None) -> dict[str, Any]:
    """请求中止本租户的选股：点名一个战法，或省略时停掉**全部**在跑的。

    返回 ``{cancelled, status, strategy, percent, cancelled_strategies}``。
    ``cancelled=False`` 表示没有可停的任务——这不是错误，是幂等：用户连点两次
    停止，第二次什么都不该发生，而不该报错。

    省略 ``strategy`` 是给老客户端（与将来的「全停」入口）的：那时一个租户最多
    只有一个在跑，语义与「停全部」一致。**新前端一律点名**，否则用户在 A 的进度
    条上点停止会把 B、C 一起停掉。

    **不保证立即停**。检查点之间最长是一个交易日的选股耗时；调用方拿到
    ``cancelled=True`` 只意味着「已经排上了」，真正的终态要等轮询看到
    ``status='cancelled'``。前端文案不能写「已取消」，要写「正在停止」。
    """
    named = _slug(strategy) if strategy is not None else ""
    with _LOCK:
        slots = _tenant_slots_locked()
        if named:
            target = slots.get(named) or {}
            targets = [named] if target.get("status") == "running" else []
        else:
            targets = [k for k, slot in slots.items() if slot.get("status") == "running"]

        if not targets:
            fallback_key = named if named else _primary_key_locked(slots)
            fallback = slots.get(fallback_key) if fallback_key is not None else None
            state = fallback if fallback is not None else _blank_state(named)
            return {
                "cancelled": False,
                "status": str(state.get("status") or "idle"),
                "strategy": str(state.get("strategy") or ""),
                "percent": float(state.get("percent") or 0.0),
                "cancelled_strategies": [],
            }

        now = time.time()
        for key in targets:
            slot = slots[key]
            slot["cancel_requested"] = True
            log = list(slot.get("log") or [])
            log.append("· 收到停止请求，将在当前交易日跑完后停下")
            slot["log"] = log[-120:]
            slot["message"] = "正在停止…"
            slot["updated_at"] = now
        first = slots[targets[0]]
        return {
            "cancelled": True,
            "status": "running",
            "strategy": str(first.get("strategy") or targets[0]),
            "percent": float(first.get("percent") or 0.0),
            "cancelled_strategies": list(targets),
        }


def screen_run_cancel_requested(strategy: str | None = None) -> bool:
    """检查点用。读一个 bool 不值得让调用方自己去碰 ``_LOCK``。

    执行体不传参：靠 ``screen_run_slot_scope`` 绑定的槽键找到自己那面旗——多战法
    并跑时，A 的停止请求绝不能让 B 在下一个检查点自尽。
    """
    with _LOCK:
        return bool(_slot_locked(strategy, create=False).get("cancel_requested"))
