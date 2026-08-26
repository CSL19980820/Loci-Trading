"""盘口情报 tape 的稳定领域 DTO。

这些类型只描述「一份信息是什么」和「它从哪里来」，不负责调用 MCP、
访问 SQLite 或猜测缺失指标。数据源是否可用由 market infrastructure 决定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


Row = Mapping[str, Any]
Rows = tuple[Row, ...] | None


@dataclass(frozen=True, slots=True)
class TapeAttempt:
    """一次 provider 尝试；不会把多个 provider 的数据合并成一份事实。"""

    provider_id: str | None = None
    lane: str | None = None
    ok: bool = False
    status: str = "failed"
    error: str | None = None
    elapsed_ms: float | None = None

    @property
    def success(self) -> bool:
        return self.ok


@dataclass(frozen=True, slots=True)
class TapeProvenance:
    """结果的来源与时效标记。

    ``provider_id`` 只有一个赢家；其它 provider 只出现在 ``attempts``，
    防止下游误以为不同来源已经完成可审计的合并。
    """

    provider_id: str | None = None
    lane: str | None = None
    requested_date: str | None = None
    as_of_date: str | None = None
    #: 这份数据实际取回的时刻（ISO）。``as_of_date`` 只到「日」，盘中判断
    #: 「这是不是早盘的旧快照」必须靠它。
    fetched_at: str | None = None
    degraded: bool = False
    stale: bool = False
    from_cache: bool = False
    attempts: tuple[TapeAttempt, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def requested_trade_date(self) -> str | None:
        return self.requested_date

    @property
    def as_of_trade_date(self) -> str | None:
        return self.as_of_date


@dataclass(frozen=True, slots=True)
class TapeRequest:
    """provider 无关的 tape 请求。

    ``arguments`` 保留工具参数的透明承载位；``params`` 是骨架阶段对旧调用方
    的兼容别名，provider 应优先读取 ``params``（若存在）。
    """

    lane: str
    requested_date: str | None = None
    as_of_date: str | None = None
    tool: str | None = None
    codes: tuple[str, ...] = ()
    limit: int | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    params: Mapping[str, Any] | None = None
    context: Mapping[str, Any] | None = None
    cache: bool = True
    cache_max_age_minutes: int | None = None

    @property
    def trade_date(self) -> str | None:
        return self.requested_date

    @property
    def requested_trade_date(self) -> str | None:
        return self.requested_date

    @property
    def as_of_trade_date(self) -> str | None:
        return self.as_of_date

    @property
    def effective_arguments(self) -> Mapping[str, Any]:
        return self.params if self.params is not None else self.arguments


@dataclass(frozen=True, slots=True)
class TapeResult:
    """provider/router 的统一结果；失败也返回对象而不是抛业务异常。"""

    data: Any | None = None
    provenance: TapeProvenance = field(default_factory=TapeProvenance)
    error: str | None = None

    @property
    def payload(self) -> Any | None:
        return self.data

    @property
    def value(self) -> Any | None:
        return self.data

    @property
    def healthy(self) -> bool:
        return self.data is not None and not self.provenance.degraded


@dataclass(frozen=True, slots=True)
class MarketEmotion:
    trade_date: str | None = None
    temperature: float | None = None
    breadth: float | None = None
    promotion_rate: float | None = None
    broken_rate: float | None = None
    limit_up_count: float | None = None
    limit_down_count: float | None = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class LimitUpLadder:
    trade_date: str | None = None
    height: float | None = None
    rows: Rows = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class BrokenLimitUp:
    trade_date: str | None = None
    rows: Rows = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class ThemeRank:
    theme_code: str | None = None
    theme_name: str | None = None
    strength: float | None = None
    pct_chg: float | None = None
    main_net_amount: float | None = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class ThemeBoard:
    trade_date: str | None = None
    theme_code: str | None = None
    theme_name: str | None = None
    strength: float | None = None
    ranks: tuple[ThemeRank, ...] | None = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class ThemeMembers:
    trade_date: str | None = None
    theme_code: str | None = None
    theme_name: str | None = None
    members: Rows = None
    payload: Row | None = None


@dataclass(frozen=True, slots=True)
class AuctionSnapshot:
    trade_date: str | None = None
    active: bool | None = None
    rows: Rows = None
    payload: Row | None = None


TapeValue = (
    MarketEmotion
    | LimitUpLadder
    | BrokenLimitUp
    | ThemeRank
    | ThemeBoard
    | ThemeMembers
    | AuctionSnapshot
    | Row
)


__all__ = [
    "AuctionSnapshot",
    "BrokenLimitUp",
    "LimitUpLadder",
    "MarketEmotion",
    "Row",
    "Rows",
    "TapeAttempt",
    "TapeProvenance",
    "TapeRequest",
    "TapeResult",
    "TapeValue",
    "ThemeBoard",
    "ThemeMembers",
    "ThemeRank",
]
