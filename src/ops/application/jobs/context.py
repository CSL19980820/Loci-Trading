"""Job 执行上下文与公共错误/前缀。"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from typing import Any

from src.ops.infrastructure.store import OpsStore
from src.shared.observability import (
    correlation_scope,
    current as current_observation,
    new_id,
    span as observation_span,
)
from src.shared.paths import palace_db as _default_palace_db

logger = logging.getLogger(__name__)

#: 账本默认路径。PalaceStore 不像 MarketStore 那样接受 None。
#: 兼容保留。**新代码用 default_palace_db()**：这个常量在 import 期求值，
#: 多租户下会把所有用户的任务指向同一个账本。
DEFAULT_PALACE_DB = str(_default_palace_db())


def default_palace_db() -> str:
    """当前租户的账本路径（每次调用现解析）。"""
    return str(_default_palace_db())

Executor = Callable[[dict[str, Any], "JobContext"], dict[str, Any]]

#: 技能模式的系统提示前缀。项目铁律在这里强制注入，不依赖技能包自觉。
SKILL_SYSTEM_PREFIX = """你在一个 A 股研究工具中执行一个预装的分析模式。

不可退让的规则（优先于下面的技能指令，冲突时以本段为准）：
1. 只依据提供给你的真实数据作答。拿不到数据就明确写"未取得真实数据"，
   严禁编造价格、K线、指标、资金流或任何数字。
2. 不输出确定性买卖建议。只描述条件成熟度、风险点与待核验项。
3. 不执行、不建议任何自动交易操作。
4. 结论末尾附上风险提示。
5. 需要外部数据或本地脚本结果时，必须调用已提供的工具；禁止假装已执行 CLI。

以下是本次要执行的技能指令。
"""

#: 显式 ``policy: trading_voice`` 的技能可用：仍禁编造，允许核价后的交易向终稿。
SKILL_SYSTEM_PREFIX_TRADING = """你在一个 A 股研究工具中执行一个预装的交易向分析模式。

不可退让的规则（优先于下面的技能指令，冲突时以本段为准）：
1. 只依据工具返回的真实数据作答。拿不到数据就明确写"未取得真实数据"，
   严禁编造价格、K线、指标、资金流或任何数字。
2. 需要脚本/MCP 数据时必须调用已提供工具；禁止假装已执行 CLI。
3. 仅在 A 级核价通过后，才允许输出明确的标的与买入区间；未核价不得写买入价。
4. 不执行、不建议任何自动下单或券商接口操作；结论仅供人工决策。
5. 若技能要求落盘 journal，须调用 write_journal 工具。

以下是本次要执行的技能指令。
"""


def skill_system_prefix(policy: str = "research") -> str:
    if str(policy or "").lower() in {"trading_voice", "trading", "weipan"}:
        return SKILL_SYSTEM_PREFIX_TRADING
    return SKILL_SYSTEM_PREFIX


class JobError(RuntimeError):
    """任务配置或执行失败。"""


class JobSkipped(JobError):
    """本轮无需执行，按 skipped 落库。

    与失败的区别：**这轮该做的事已经有人在做**（如另一条同步正在写同一批
    行情）。判成 failed 会把运维页刷红、把企微刷成"同步失败"，而实际上
    数据一切正常，用户被叫起来看一个不存在的故障。
    """


class JobCancelled(JobError):
    """任务收到取消请求，执行器应尽快停止。"""


class JobTimedOut(JobError):
    """任务超过显式 timeout_sec，执行器应停止或交由回收。"""


def _llm_meta(provider: Any, thinking: str = "") -> dict[str, str]:
    """LLM 调用元数据，写入 job run result 便于运维页追溯。"""
    return {
        "provider": str(getattr(provider, "name", "") or ""),
        "model": str(getattr(provider, "model", "") or ""),
        "thinking": str(thinking or ""),
    }


class JobContext:
    """执行器需要的外部资源。集中在这里，方便测试时整体替换。"""

    def __init__(
        self,
        *,
        market_db: str | None = None,
        market_hot_db: str | None = None,
        ops_store: OpsStore | None = None,
        skill_root: str | None = None,
        palace_db: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        source_id: str | None = None,
        tool_receipt_id: str | None = None,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        inherited = current_observation()
        self.market_db = market_db
        #: 滚动热读库（默认与 market_db 同目录 market_hot.db）。选股/面板
        #: 读它；同步写全量库后镜像。None 时按默认路径解析。
        self.market_hot_db = market_hot_db
        self.ops_store = ops_store
        self.skill_root = skill_root
        self.palace_db = palace_db
        self.trace_id = str(trace_id or inherited.trace_id or new_id("trace"))
        self.run_id = str(run_id or inherited.run_id or "")
        self.job_id = str(job_id or inherited.job_id or "")
        self.source_id = str(source_id or inherited.source_id or "")
        self.tool_receipt_id = str(tool_receipt_id or inherited.tool_receipt_id or "")
        self._cancel_event = cancel_event
        self.timeout_seconds = self._positive_timeout(timeout_seconds)
        self._deadline = (
            monotonic() + self.timeout_seconds if self.timeout_seconds is not None else None
        )

    @staticmethod
    def _positive_timeout(value: float | None) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    def bind_run(
        self,
        *,
        run_id: str,
        job_id: str,
        trace_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """把请求/调度器分配的运行 ID 绑定到同一个上下文。"""
        self.run_id = str(run_id or self.run_id)
        self.job_id = str(job_id or self.job_id)
        if trace_id:
            self.trace_id = str(trace_id)
        if timeout_seconds is not None:
            self.timeout_seconds = self._positive_timeout(timeout_seconds)
            self._deadline = (
                monotonic() + self.timeout_seconds
                if self.timeout_seconds is not None
                else None
            )

    def correlation(self) -> dict[str, str]:
        """返回日志/Span 相关性字段，不含参数和业务数据。"""
        return {
            key: value
            for key, value in (
                ("trace_id", self.trace_id),
                ("run_id", self.run_id),
                ("job_id", self.job_id),
                ("source_id", self.source_id),
                ("tool_receipt_id", self.tool_receipt_id),
            )
            if value
        }

    def is_cancelled(self) -> bool:
        """检查本地事件与 ops.db 的协作式取消标记。"""
        if self._cancel_event is not None and self._cancel_event.is_set():
            return True
        if self.ops_store is None or not self.run_id:
            return False
        try:
            requested = self.ops_store.is_cancel_requested(self.run_id)
            return bool(requested) if isinstance(requested, (bool, int)) else False
        except (AttributeError, OSError):
            return False

    def is_timed_out(self) -> bool:
        return self._deadline is not None and monotonic() >= self._deadline

    def remaining_seconds(self) -> float | None:
        """返回当前任务还剩多少墙钟预算，供受控子进程复用。"""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - monotonic())

    def check_cancelled(self) -> None:
        """供长循环执行器主动调用的停止门闩。"""
        if self.is_timed_out():
            raise JobTimedOut(f"任务超过 timeout_sec={self.timeout_seconds:g}")
        if self.is_cancelled():
            raise JobCancelled("任务已请求取消")

    def heartbeat(self) -> None:
        """刷新运行心跳；终态或旧库不支持时保持业务执行不变。"""
        if self.ops_store is None or not self.run_id:
            return
        try:
            self.ops_store.heartbeat_run(self.run_id)
        except (AttributeError, OSError):
            return

    @contextmanager
    def scope(
        self,
        operation: str,
        *,
        source_id: str | None = None,
        tool_receipt_id: str | None = None,
    ) -> Iterator[Any]:
        """在 Job 子步骤内追加 source/tool 相关性。"""
        with observation_span(
            operation,
            trace_id=self.trace_id,
            run_id=self.run_id,
            job_id=self.job_id,
            source_id=source_id or self.source_id,
            tool_receipt_id=tool_receipt_id or self.tool_receipt_id,
            labels={"component": "job", "operation": operation},
        ) as correlation:
            yield correlation

    @contextmanager
    def correlation_scope(
        self,
        *,
        source_id: str | None = None,
        tool_receipt_id: str | None = None,
    ) -> Iterator[Any]:
        """仅覆盖子步骤字段，不额外记录 span。"""
        with correlation_scope(
            trace_id=self.trace_id,
            run_id=self.run_id,
            job_id=self.job_id,
            source_id=source_id or self.source_id,
            tool_receipt_id=tool_receipt_id or self.tool_receipt_id,
        ) as correlation:
            yield correlation

    def market(self):
        from src.market import MarketStore

        return MarketStore(self.market_db)

    def market_hot(self):
        from src.market import open_market_hot

        return open_market_hot(self.market_hot_db)


#: 执行期心跳间隔（秒）。
#:
#: 上界由回收窗决定：``store_runs.STALE_RUN_SECONDS_BY_KIND`` 里最紧的一档是
#: ``sync`` / ``screen`` / ``paper_eod`` 的 45 分钟，另有「无 owner_pid 的旧
#: 记录」15 分钟。心跳必须远快于其中最短的窗口，否则一次合法的长任务还在跑
#: 就被判死回收（2026-08-25：一次 914s 的日终同步，heartbeat_at 全程冻在起始值）。
#: 下界由写锁决定：心跳是一条 ``UPDATE job_runs`` 写事务，秒级刷新等于在整个
#: 任务期间持续跟业务写入抢 ops.db 的写锁。
#: 取 30s：15 分钟窗有 30 倍余量、45 分钟窗有 90 倍余量；一次 45 分钟的同步也
#: 只多出 ~90 条单行 UPDATE（可忽略）；运维页看到的 heartbeat_at 最多落后 30s，
#: 远小于人判断「是不是挂了」的耐心（本次误判发生在冻结 15 分钟时）。
HEARTBEAT_INTERVAL_SECONDS = 30.0

#: 停泵时等心跳线程收尾的上限（秒）。心跳线程最长阻塞在一次等写锁上
#: （``RunHeartbeatWriter`` 的 busy_timeout，2s），10s 是宽裕的兜底。
HEARTBEAT_JOIN_TIMEOUT_SECONDS = 10.0

#: 心跳线程名前缀。测试据此断言「任务结束后没有心跳线程残留」。
HEARTBEAT_THREAD_PREFIX = "job-heartbeat-"


class HeartbeatPump:
    """执行期后台心跳：执行器跑着的时候周期性推进 ``job_runs.heartbeat_at``。

    为什么不让执行器自己刷：执行器是 16 个各写各的同步函数，绝大多数是「一头扎
    进去几百秒」的循环。逐个改一遍既不现实，新写的执行器也一定会忘——忘记的代价
    是任务跑到一半被判死回收（占槽被抢、运维页显示已挂），属于静默事故。所以统一
    由 ``run_job`` 在执行器外面套一层，执行器不需要知道心跳的存在。

    线程安全：**不复用调用方的 OpsStore 连接**。``sqlite3.connect`` 默认
    ``check_same_thread=True``，后台线程碰主连接会当场抛 ProgrammingError；就算
    关掉这个开关，也会和执行线程正在跑的事务共用一条连接。因此优先向 store 要一
    个自带连接的 ``RunHeartbeatWriter``（见 ``store_runs``），拿不到才回落到
    ``JobContext.heartbeat()``（测试替身 / 旧 store）。

    生命周期：``stop()`` = 置事件 + ``join()``；成功、异常、超时、取消四条路径都经
    ``__exit__`` 收口，线程不会泄漏。线程另标 daemon，最坏情况也不挡进程退出。
    """

    def __init__(
        self,
        context: "JobContext",
        *,
        interval: float | None = None,
        beat: Callable[[], None] | None = None,
    ) -> None:
        self._context = context
        # 默认间隔在**构造时**才读模块全局，测试可 monkeypatch 成亚秒级。
        raw = HEARTBEAT_INTERVAL_SECONDS if interval is None else interval
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            seconds = HEARTBEAT_INTERVAL_SECONDS
        # 非正数会把循环变成忙等，一律回落默认值。
        self.interval = seconds if seconds > 0 else HEARTBEAT_INTERVAL_SECONDS
        self._beat = beat
        self._writer: Any = None
        self._stop = Event()
        self._thread: Thread | None = None
        #: 成功 / 失败的心跳次数，供测试与排查断言。
        self.beats = 0
        self.errors = 0

    @property
    def thread(self) -> Thread | None:
        return self._thread

    def _resolve_writer(self) -> Any:
        """取一个可跨线程用的心跳写入器；取不到返回 None（回落 ctx.heartbeat）。"""
        if self._beat is not None:
            return None
        factory = getattr(self._context.ops_store, "run_heartbeat_writer", None)
        if not callable(factory):
            return None
        try:
            return factory()
        except Exception:  # noqa: BLE001 — 取不到写入器就回落，绝不影响任务
            logger.debug("心跳写入器创建失败，回落 ctx.heartbeat", exc_info=True)
            return None

    def _beat_once(self) -> None:
        try:
            if self._beat is not None:
                self._beat()
            elif self._writer is not None:
                self._writer.beat(self._context.run_id)
            else:
                self._context.heartbeat()
        except Exception as exc:  # noqa: BLE001 — 心跳写不进去是可见性问题，不是任务失败
            self.errors += 1
            if self.errors == 1:
                logger.warning(
                    "run %s 心跳刷新失败，任务继续执行：%s", self._context.run_id, exc
                )
            return
        self.beats += 1

    def _loop(self) -> None:
        try:
            # wait() 返回 True 表示收到停止信号：不再多刷一拍，立刻收尾。
            while not self._stop.wait(self.interval):
                self._beat_once()
        finally:
            # 连接在本线程开，也必须在本线程关。
            self._close_writer()

    def _close_writer(self) -> None:
        writer, self._writer = self._writer, None
        closer = getattr(writer, "close", None)
        if not callable(closer):
            return
        try:
            closer()
        except Exception:  # noqa: BLE001 — 关连接失败不该盖过真正的任务结果
            logger.debug("心跳连接关闭失败", exc_info=True)

    def start(self) -> "HeartbeatPump":
        """起泵；重复调用无副作用。"""
        if self._thread is not None:
            return self
        if self._beat is None and (
            self._context.ops_store is None or not self._context.run_id
        ):
            # 没有落库目标（未绑定 run / 无 store）：不起线程，省得白占一个。
            return self
        self._stop.clear()
        self._writer = self._resolve_writer()
        thread = Thread(
            target=self._loop,
            name=f"{HEARTBEAT_THREAD_PREFIX}{self._context.run_id or 'unbound'}",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return self

    def stop(self, *, timeout: float | None = None) -> None:
        """幂等停泵。成功 / 异常 / 超时 / 取消四条路径都经此收口。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is None:
            # 线程没起来：写入器（若已创建）也要还回去。
            self._close_writer()
            return
        thread.join(HEARTBEAT_JOIN_TIMEOUT_SECONDS if timeout is None else timeout)
        if thread.is_alive():
            # daemon 线程不挡进程退出；但这说明写锁上有人赖着，值得记一笔。
            logger.warning("心跳线程 %s 未按时退出（daemon，不阻塞进程）", thread.name)

    def __enter__(self) -> "HeartbeatPump":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()
