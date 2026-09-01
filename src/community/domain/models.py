"""社区域模型：发布物、版本、绩效、评论、订阅、动态。

只用标准库：本层不认识 FastAPI / sqlite3 / pandas。所有 dataclass 都是
**只读快照**（``frozen=True``），由 infrastructure 的行字典喂进来，由 api 层
``to_dict()`` 出去，中间不许有人偷偷改字段再写回库。

词汇表（``KINDS`` / ``VISIBILITIES`` / ``STATUSES`` / ``BOARDS`` / ``SORTS``）
是本上下文的**唯一真相**：infrastructure 的 CHECK 约束与 api 的取值校验都从这里
取，避免出现「库里能存、api 不认」的三处漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

# 净值曲线契约：值对象与归一函数实现在 ``equity_curve``（本文件已贴着 600 行上限），
# 但它仍是域模型的一部分，在这里 re-export——调用方照常 ``from ...models import EquityPoint``。
from src.community.domain.equity_curve import (  # noqa: F401
    EQUITY_CURVE_ALIASES,
    EQUITY_CURVE_KEY,
    MAX_EQUITY_POINTS,
    EquityPoint,
    normalize_equity_curve,
)

#: 发布物类型。screen=选股战法，timing=择时，portfolio=组合，factor=因子。
StrategyKind = Literal["screen", "timing", "portfolio", "factor", "other"]
KINDS: tuple[str, ...] = ("screen", "timing", "portfolio", "factor", "other")

#: 可见性。unlisted = 有链接可看但不进广场（草稿发给朋友的场景）。
Visibility = Literal["public", "unlisted", "private"]
VISIBILITIES: tuple[str, ...] = ("public", "unlisted", "private")

#: 生命周期。**没有 deleted**：上架过的东西只能下架，不能装作没发生过。
Status = Literal["listed", "delisted"]
STATUSES: tuple[str, ...] = ("listed", "delisted")

#: 榜单分区。规则在 ``scoring.BOARD_RULES``。
Board = Literal["overall", "sharpe", "return", "rookie"]
BOARDS: tuple[str, ...] = ("overall", "sharpe", "return", "rookie")

#: 广场排序键。
SortKey = Literal["hot", "new", "score", "stars"]
SORTS: tuple[str, ...] = ("hot", "new", "score", "stars")

#: 订阅模式。**只有一种**，且永远只有一种，见 ``Subscription`` 的合规说明。
SUBSCRIPTION_MODES: tuple[str, ...] = ("signal_only",)

#: 动态流动词。写死枚举，免得前端为无穷动词写 if-else。
FEED_VERBS: tuple[str, ...] = (
    "published",
    "released",
    "delisted",
    "starred",
    "cloned",
    "commented",
    "followed",
)


class CommunityError(RuntimeError):
    """社区域的可预期错误；api 层统一映射成 4xx，不要变成 500。"""

    code = "community_error"
    http_status = 400


class ValidationError(CommunityError):
    code = "validation_error"
    http_status = 422


class PublishRuleError(ValidationError):
    """上架检查未通过。``violations`` 原样带给前端，逐条显示给作者。"""

    code = "publish_rules_failed"

    def __init__(self, message: str, violations: list[Any] | None = None) -> None:
        super().__init__(message)
        self.violations = list(violations or [])


class NotFoundError(CommunityError):
    code = "not_found"
    http_status = 404


class PermissionDeniedError(CommunityError):
    code = "forbidden"
    http_status = 403


class ConflictError(CommunityError):
    code = "conflict"
    http_status = 409


class FrozenVersionError(ConflictError):
    """已发布版本不可改不可删——改要发新版。"""

    code = "version_frozen"


def now_iso() -> str:
    """社区库统一时钟：本地时区 + 偏移 + 微秒的 ISO8601。

    与 ``ops`` / ``ledger`` 同口径：带偏移可与历史 UTC 行落在同一条时间轴上比较，
    微秒保证同一秒内多次写入仍能稳定排序（批量补动态时一秒能写十几条）。
    """
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def today_iso() -> str:
    """交易日 / 快照日的默认值：本地日期（``YYYY-MM-DD``）。"""
    return datetime.now().astimezone().date().isoformat()


def parse_iso(raw: str | None) -> datetime | None:
    """宽松解析 ISO 时间；解析不出来返回 None，绝不抛。"""
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if result != result:  # NaN 不参与排序，按缺失处理
        return fallback
    return result


def as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


@dataclass(frozen=True, slots=True)
class Actor:
    """一次操作的发起人。

    社区**不自己存账号**：``user_id`` 来自组合根注入的 ``auth_dependency``
    （identity 上下文）。这里只留够做鉴权判断的三个字段，多一个都不要。
    社区库里冗余存 ``owner_name`` / ``actor_name`` 是为了「作者改名不改写历史动态」
    的快照语义，不是第二份用户表。
    """

    user_id: str
    display_name: str = ""
    is_admin: bool = False

    def __post_init__(self) -> None:
        if not str(self.user_id).strip():
            raise ValidationError("缺少发起人 user_id")

    @property
    def name(self) -> str:
        return self.display_name or self.user_id

    def owns(self, owner_user_id: str) -> bool:
        return self.is_admin or self.user_id == owner_user_id

    def require_owner(self, owner_user_id: str, *, what: str = "该发布物") -> None:
        if not self.owns(owner_user_id):
            raise PermissionDeniedError(f"只能操作自己的{what}")


@dataclass(frozen=True, slots=True)
class PublishedStrategy:
    """策略广场上的一个发布物（多版本的容器）。"""

    publish_id: str
    owner_user_id: str
    owner_name: str = ""
    slug: str = ""
    title: str = ""
    summary: str = ""
    kind: str = "screen"
    entry_timing: str = ""
    visibility: str = "public"
    status: str = "listed"
    current_version: int = 1
    tags: tuple[str, ...] = ()
    stars: int = 0
    clones: int = 0
    views: int = 0
    comments_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    published_at: str = ""
    delisted_at: str = ""

    @property
    def listed(self) -> bool:
        return self.status == "listed"

    @property
    def in_square(self) -> bool:
        """是否该出现在广场列表：私有 / 未列出 / 已下架都不进。"""
        return self.listed and self.visibility == "public"

    def visible_to(self, actor: Actor | None) -> bool:
        """详情页可见性。作者与 admin 永远可见（下架后自己还得能看）。"""
        if actor is not None and actor.owns(self.owner_user_id):
            return True
        if self.visibility == "private":
            return False
        return self.listed

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PublishedStrategy:
        return cls(
            publish_id=as_str(row.get("publish_id")),
            owner_user_id=as_str(row.get("owner_user_id")),
            owner_name=as_str(row.get("owner_name")),
            slug=as_str(row.get("slug")),
            title=as_str(row.get("title")),
            summary=as_str(row.get("summary")),
            kind=as_str(row.get("kind")) or "screen",
            entry_timing=as_str(row.get("entry_timing")),
            visibility=as_str(row.get("visibility")) or "public",
            status=as_str(row.get("status")) or "listed",
            current_version=as_int(row.get("current_version"), 1),
            tags=_tuple(row.get("tags")),
            stars=as_int(row.get("stars")),
            clones=as_int(row.get("clones")),
            views=as_int(row.get("views")),
            comments_count=as_int(row.get("comments_count")),
            created_at=as_str(row.get("created_at")),
            updated_at=as_str(row.get("updated_at")),
            published_at=as_str(row.get("published_at")),
            delisted_at=as_str(row.get("delisted_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_id": self.publish_id,
            "owner_user_id": self.owner_user_id,
            "owner_name": self.owner_name,
            "slug": self.slug,
            "title": self.title,
            "summary": self.summary,
            "kind": self.kind,
            "entry_timing": self.entry_timing,
            "visibility": self.visibility,
            "status": self.status,
            "current_version": self.current_version,
            "tags": list(self.tags),
            "stars": self.stars,
            "clones": self.clones,
            "views": self.views,
            "comments_count": self.comments_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "published_at": self.published_at,
            "delisted_at": self.delisted_at,
        }


@dataclass(frozen=True, slots=True)
class PublishedVersion:
    """一个**冻结**的版本快照。

    上架即冻结：库里有 BEFORE UPDATE / BEFORE DELETE 触发器把改写打回，应用层再想
    改也改不动。要改就发新版，旧版留着给已克隆的人对账——否则「我抄的时候明明不是
    这个逻辑」永远说不清。
    """

    id: str
    publish_id: str
    version: int
    source_text: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    release_notes: str = ""
    content_sha256: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PublishedVersion:
        return cls(
            id=as_str(row.get("id")),
            publish_id=as_str(row.get("publish_id")),
            version=as_int(row.get("version"), 1),
            source_text=as_str(row.get("source_text")),
            params=_mapping(row.get("params")),
            manifest=_mapping(row.get("manifest")),
            release_notes=as_str(row.get("release_notes")),
            content_sha256=as_str(row.get("content_sha256")),
            created_at=as_str(row.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "publish_id": self.publish_id,
            "version": self.version,
            "source_text": self.source_text,
            "params": dict(self.params),
            "manifest": dict(self.manifest),
            "release_notes": self.release_notes,
            "content_sha256": self.content_sha256,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    """某个发布物在某一天的绩效切片（榜单的输入）。

    ``score`` 是派生值，但仍落库：榜单快照要能解释「当天为什么这么排」。重算所需的
    ``sharpe_1y`` / ``live_days`` 就在同一行，``scoring.compute_score`` 随时能校验
    一致性，所以这不构成第二真相。
    """

    publish_id: str
    as_of_date: str
    sharpe_1y: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    trades: int = 0
    live_days: int = 0
    oos_return: float = 0.0
    score: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> StrategyMetrics:
        return cls(
            publish_id=as_str(row.get("publish_id")),
            as_of_date=as_str(row.get("as_of_date")),
            sharpe_1y=as_float(row.get("sharpe_1y")),
            annual_return=as_float(row.get("annual_return")),
            max_drawdown=as_float(row.get("max_drawdown")),
            win_rate=as_float(row.get("win_rate")),
            profit_factor=as_float(row.get("profit_factor")),
            trades=as_int(row.get("trades")),
            live_days=as_int(row.get("live_days")),
            oos_return=as_float(row.get("oos_return")),
            score=as_float(row.get("score")),
            metrics=_mapping(row.get("metrics")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_id": self.publish_id,
            "as_of_date": self.as_of_date,
            "sharpe_1y": self.sharpe_1y,
            "annual_return": self.annual_return,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "trades": self.trades,
            "live_days": self.live_days,
            "oos_return": self.oos_return,
            "score": self.score,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class Comment:
    """一条评论。删除是**软删**：留占位行，保住楼层与父子关系。"""

    id: str
    publish_id: str
    user_id: str
    user_name: str = ""
    body: str = ""
    parent_id: str = ""
    created_at: str = ""
    deleted_at: str = ""

    @property
    def deleted(self) -> bool:
        return bool(self.deleted_at)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Comment:
        return cls(
            id=as_str(row.get("id")),
            publish_id=as_str(row.get("publish_id")),
            user_id=as_str(row.get("user_id")),
            user_name=as_str(row.get("user_name")),
            body=as_str(row.get("body")),
            parent_id=as_str(row.get("parent_id")),
            created_at=as_str(row.get("created_at")),
            deleted_at=as_str(row.get("deleted_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        """软删的行只回占位：正文与作者一并抹掉，楼层与时间保留。"""
        deleted = self.deleted
        return {
            "id": self.id,
            "publish_id": self.publish_id,
            "user_id": "" if deleted else self.user_id,
            "user_name": "" if deleted else self.user_name,
            "body": "" if deleted else self.body,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "deleted": deleted,
        }


@dataclass(frozen=True, slots=True)
class Subscription:
    """一条跟单订阅。

    **合规红线：只推信号，不自动下单。** ``mode`` 只有 ``signal_only`` 一个取值，
    库里有 CHECK 约束兜底。代客理财 / 全权委托在境内需牌照，本仓是个人工具，永远
    不做「订阅后自动在别人账户成交」这件事：订阅者只能拉到作者当日的信号快照
    （``signal_broadcasts``），下不下单由他自己对着自己的账本决定。

    想加 ``auto_trade`` 模式的人先读这段——这不是没做完的 TODO，是刻意不做。
    """

    publish_id: str
    user_id: str
    mode: str = "signal_only"
    notify_channels: tuple[str, ...] = ()
    created_at: str = ""
    paused_at: str = ""

    @property
    def active(self) -> bool:
        return not self.paused_at

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Subscription:
        return cls(
            publish_id=as_str(row.get("publish_id")),
            user_id=as_str(row.get("user_id")),
            mode=as_str(row.get("mode")) or "signal_only",
            notify_channels=_tuple(row.get("notify_channels")),
            created_at=as_str(row.get("created_at")),
            paused_at=as_str(row.get("paused_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_id": self.publish_id,
            "user_id": self.user_id,
            "mode": self.mode,
            "notify_channels": list(self.notify_channels),
            "created_at": self.created_at,
            "paused_at": self.paused_at,
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class FeedItem:
    """动态流的一条。``object_title`` 是**写入时的快照**，标题后改不回填。"""

    id: str
    actor_id: str
    actor_name: str = ""
    verb: str = ""
    object_type: str = ""
    object_id: str = ""
    object_title: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> FeedItem:
        return cls(
            id=as_str(row.get("id")),
            actor_id=as_str(row.get("actor_id")),
            actor_name=as_str(row.get("actor_name")),
            verb=as_str(row.get("verb")),
            object_type=as_str(row.get("object_type")),
            object_id=as_str(row.get("object_id")),
            object_title=as_str(row.get("object_title")),
            created_at=as_str(row.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "verb": self.verb,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "object_title": self.object_title,
            "created_at": self.created_at,
        }
