"""用例：排行榜计算与快照落库。

榜单是**派生数据**：``rebuild_leaderboard`` 随时能从 ``strategy_metrics`` 整表重建，
清空 ``leaderboard_snapshots`` 只丢「当天视角」的回看能力，不丢任何事实。

口径全部在 ``domain/scoring``（``compute_score`` / ``BOARD_RULES`` / ``rank_entries``）：
本模块只负责取数、调用纯函数、把结果写回去，**不在这里写任何公式**。
"""

from __future__ import annotations

from typing import Any, Mapping

from src.community.domain.models import (
    BOARDS,
    EQUITY_CURVE_ALIASES,
    EQUITY_CURVE_KEY,
    Actor,
    ValidationError,
    normalize_equity_curve,
    today_iso,
)
from src.community.domain.scoring import (
    BOARD_RULES,
    compute_score,
    describe_boards,
    rank_entries,
)
from src.community.infrastructure.store import CommunityStore
from src.community.infrastructure.store_helpers import MAX_BOARD_SIZE


def rebuild_leaderboard(
    store: CommunityStore,
    *,
    as_of: str | None = None,
    board: str = "overall",
    limit: int = 100,
    write_feed: bool = False,
) -> dict[str, Any]:
    """重算一张榜并落快照。

    ``as_of`` 缺省用**库里最新一期绩效日**（而不是「今天」）：盘后任务可能凌晨才跑，
    用今天会算出一张空榜然后把昨天的快照挤掉。库里一条绩效都没有时才退回今天。
    """
    if board not in BOARDS:
        raise ValidationError(f"未知榜单：{board}（可选 {', '.join(BOARDS)}）")
    as_of_date = (as_of or "").strip() or store.latest_metrics_date() or today_iso()
    rows = store.list_metrics_as_of(as_of_date)
    entries = rank_entries(rows, board=board, limit=min(int(limit), MAX_BOARD_SIZE))
    written = store.replace_leaderboard(board=board, as_of_date=as_of_date, entries=entries)
    if write_feed and entries:
        top = entries[0]
        record = store.get_publish(str(top["publish_id"]))
        store.add_feed_item(
            actor_id="system",
            actor_name="榜单",
            verb="ranked",
            object_type="strategy",
            object_id=str(top["publish_id"]),
            object_title=f"{(record or dict()).get('title', '')} 登顶 {board} 榜",
        )
    return {
        "board": board,
        "as_of_date": as_of_date,
        "candidates": len(rows),
        "written": written,
        "entries": entries,
        "rule": _rule_dict(board),
    }


def rebuild_all(
    store: CommunityStore, *, as_of: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """重算全部分区（盘后任务一次调这个）。"""
    return [rebuild_leaderboard(store, as_of=as_of, board=name, limit=limit) for name in BOARDS]


def read_board(
    store: CommunityStore, *, board: str = "overall", as_of: str = "", limit: int = 50
) -> dict[str, Any]:
    """读榜。**不现算**：读接口拿到的必须是快照，否则每次刷新名次都在跳。"""
    if board not in BOARDS:
        raise ValidationError(f"未知榜单：{board}（可选 {', '.join(BOARDS)}）")
    rows = store.read_leaderboard(board=board, as_of_date=as_of, limit=limit)
    return {
        "board": board,
        "as_of_date": rows[0]["as_of_date"] if rows else (as_of or store.latest_board_date(board)),
        "entries": rows,
        "rule": _rule_dict(board),
    }


def record_metrics(
    store: CommunityStore,
    publish_id: str,
    *,
    actor: Actor | None = None,
    as_of: str | None = None,
    **values: Any,
) -> dict[str, Any]:
    """写入一期绩效切片（``score`` 由 store 按统一公式现算，调用方传不进来）。

    ``actor`` 给 HTTP 入口用：只有作者本人 / admin 能改自己策略的绩效。
    盘后任务在进程内直接调时可以不传（那时没有「当前用户」这回事）。
    """
    record = store.require_publish(publish_id)
    if actor is not None:
        actor.require_owner(str(record["owner_user_id"]), what="策略绩效")
    values["metrics"] = normalize_metrics_extra(values.get("metrics"))
    return store.upsert_metrics(publish_id, as_of_date=(as_of or today_iso()), **values)


def normalize_metrics_extra(raw: Any) -> dict[str, Any]:
    """把 ``metrics_json`` 里的净值曲线收敛到契约形状。**写入口只有这一处。**

    契约：``metrics_json.equity_curve = [{"d": "YYYY-MM-DD", "v": 1.0234}, ...]``，
    ``v`` 是归一化净值（起点 1.0，不是金额），点数 <= 750（超了降采样）。

    历史别名 ``equity`` / ``nav`` / ``curve`` 读的时候仍然认（见
    ``domain.normalize_equity_curve``），但**落库只写 ``equity_curve`` 一个键**：
    留着别名就是留着四份真相，前端又要回到「四个名字挨个猜」的日子。

    曲线形状认不出来时它就是空的，其余标量照常落库——一条画不出来的线不该把整期
    绩效连坐掉。
    """
    extra = dict(raw) if isinstance(raw, Mapping) else dict()
    curve = normalize_equity_curve(extra)
    for alias in EQUITY_CURVE_ALIASES:
        if isinstance(extra.get(alias), (list, tuple)):
            extra.pop(alias)
    if curve:
        extra[EQUITY_CURVE_KEY] = [point.to_dict() for point in curve]
    return extra


def preview_score(sharpe_1y: float, live_days: int) -> dict[str, Any]:
    """给前端解释「我为什么是这个分」的小工具。"""
    return {
        "sharpe_1y": float(sharpe_1y),
        "live_days": int(live_days),
        "score": compute_score(sharpe_1y, live_days),
        "formula": "score = sharpe_1y * min(1, live_days / 365)",
    }


def board_catalog() -> list[dict[str, Any]]:
    return describe_boards()


def _rule_dict(board: str) -> dict[str, Any]:
    rule = BOARD_RULES[board]
    return {
        "description": rule.description,
        "min_trades": rule.min_trades,
        "min_live_days": rule.min_live_days,
        "max_live_days": rule.max_live_days,
    }
