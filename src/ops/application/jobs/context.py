"""Job 执行上下文与公共错误/前缀。"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event
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

#: 账本默认路径。PalaceStore 不像 MarketStore 那样接受 None。
DEFAULT_PALACE_DB = str(_default_palace_db())

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
