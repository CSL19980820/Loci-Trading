"""community.db：广场检索（排序 / 筛选 / 分页）与「我收藏的」。

排序表达式写死在白名单里，绝不把用户输入拼进 ORDER BY——那是 SQL 注入的经典入口。
"""

from __future__ import annotations

from typing import Any

from src.community.domain.models import ValidationError
from src.community.infrastructure.store_helpers import clamp_page

#: 热度公式。收藏 > 克隆 > 评论 > 浏览：越费劲的动作权重越高，
#: 浏览量只给 0.1 权重，否则刷阅读就能上热榜。
_HOT_EXPR = "(p.stars * 3.0 + p.clones * 2.0 + p.comments_count * 1.0 + p.views * 0.1)"

#: 排序白名单：排序键 -> ORDER BY 片段。都带稳定次级键，保证分页不跳行。
_ORDER_BY: dict[str, str] = {
    "hot": f"{_HOT_EXPR} DESC, p.updated_at DESC, p.publish_id ASC",
    "new": "p.published_at DESC, p.created_at DESC, p.publish_id ASC",
    "score": "COALESCE(m.score, -999) DESC, p.stars DESC, p.publish_id ASC",
    "stars": "p.stars DESC, p.updated_at DESC, p.publish_id ASC",
}

#: 最新一期的绩效切片。相关子查询取 ``MAX(as_of_date)``。
#:
#: **为什么在 SQL 里 JOIN，而不是在应用层逐条 ``latest_metrics()``**：一页 20 条就是
#: 20 次额外往返（N+1）；而前端为了在卡片上显示「年化 / 夏普 / 最大回撤 / 胜率」，
#: 过去只能另外拉两次 ``/leaderboard``（overall + rookie 各 200 条）回来自己拼，
#: 没进榜的策略还只能显示「—」。绩效跟着列表一次带回来，这两笔开销一起消失。
#:
#: **索引**：``strategy_metrics`` 的主键就是 ``(publish_id, as_of_date)``（见
#: ``schema.py``），子查询是「主键前缀等值 + 后缀取最大」，SQLite 在索引上一次
#: seek 就能拿到，不会退化成全表扫。改这段 SQL 前先确认那个 PK 还在。
_LATEST_METRICS = """
LEFT JOIN strategy_metrics m
                ON m.publish_id = p.publish_id
            AND m.as_of_date = (
                SELECT MAX(as_of_date) FROM strategy_metrics x WHERE x.publish_id = p.publish_id
            )
"""

#: 卡片要展示的绩效列。别名带 ``mx_`` 前缀是为了不和 ``p.*`` 撞名——``sqlite3.Row``
#: 遇到重名列只会给你其中一个，撞上了排查起来非常费劲。
#: ``latest_score`` / ``metrics_date`` 是**既有字段，前端已在用，不许改名**。
_METRICS_SELECT = (
    "COALESCE(m.score, 0) AS latest_score,"
    " COALESCE(m.as_of_date, '') AS metrics_date,"
    " m.as_of_date AS mx_as_of_date,"
    " m.sharpe_1y AS mx_sharpe_1y,"
    " m.annual_return AS mx_annual_return,"
    " m.max_drawdown AS mx_max_drawdown,"
    " m.win_rate AS mx_win_rate,"
    " m.profit_factor AS mx_profit_factor,"
    " m.trades AS mx_trades,"
    " m.live_days AS mx_live_days,"
    " m.score AS mx_score"
)


class CommunityDiscoveryMixin:
    def search_publishes(
        self,
        *,
        sort: str = "hot",
        kind: str = "",
        tag: str = "",
        keyword: str = "",
        owner_user_id: str = "",
        page: int = 1,
        page_size: int | None = None,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        """广场列表。返回 ``{"items": [...], "total": n, "page": p, "page_size": s}``。

        每条带最近一期绩效：``latest_score`` / ``metrics_date``（既有字段）+ ``metrics``
        对象（没有绩效时为 ``None``，不是一堆 0——0 分和「还没跑过」是两回事）。

        ``include_hidden=True`` 只给「作者看自己的」用，广场入口永远不传。
        """
        if sort not in _ORDER_BY:
            raise ValidationError(f"未知排序：{sort}（可选 {', '.join(sorted(_ORDER_BY))}）")
        current, size = clamp_page(page, page_size)
        clauses: list[str] = []
        params: list[Any] = []
        if not include_hidden:
            clauses.append("p.status = 'listed'")
            clauses.append("p.visibility = 'public'")
        if kind:
            clauses.append("p.kind = ?")
            params.append(kind)
        if owner_user_id:
            clauses.append("p.owner_user_id = ?")
            params.append(owner_user_id)
        if tag:
            # tags_json 是 JSON 数组文本；用带引号的子串匹配避免 "ma" 命中 "macd"。
            clauses.append("p.tags_json LIKE ?")
            params.append(f'%"{tag}"%')
        if keyword:
            clauses.append("(p.title LIKE ? OR p.summary LIKE ? OR p.slug LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total_row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM published_strategies p" + where, tuple(params)
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        sql = (
            "SELECT p.*, "
            + _METRICS_SELECT
            + " FROM published_strategies p"
            + _LATEST_METRICS
            + where
            + f" ORDER BY {_ORDER_BY[sort]} LIMIT ? OFFSET ?"
        )
        rows = self.conn.execute(sql, tuple(params) + (size, (current - 1) * size)).fetchall()
        items = [item for item in (self._card_row(row) for row in rows) if item]
        pages = (total + size - 1) // size if size else 0
        return {
            "items": items,
            "total": total,
            "page": current,
            "page_size": size,
            "pages": pages,
            "sort": sort,
        }

    def list_starred_publishes(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """「我收藏的」。条目与广场列表**同形状**（含 ``metrics``），前端复用同一个卡片组件。

        可见性按 ``PublishedStrategy.visible_to`` 的口径过滤：别人后来改私有 / 下架的，
        不再出现在我的收藏里（收藏关系还在库里，只是不展示）；自己的东西永远看得到。
        """
        size = max(1, min(100, int(limit)))
        start = max(0, int(offset))
        where = (
            " WHERE s.user_id = ?"
            " AND (p.owner_user_id = ?"
            " OR (p.status = 'listed' AND p.visibility <> 'private'))"
        )
        params = (user_id, user_id)
        total_row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_stars s"
            " JOIN published_strategies p ON p.publish_id = s.publish_id" + where,
            params,
        ).fetchone()
        rows = self.conn.execute(
            "SELECT p.*, s.created_at AS starred_at, "
            + _METRICS_SELECT
            + " FROM strategy_stars s"
            + " JOIN published_strategies p ON p.publish_id = s.publish_id"
            + _LATEST_METRICS
            + where
            + " ORDER BY s.created_at DESC, p.publish_id ASC LIMIT ? OFFSET ?",
            params + (size, start),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = self._card_row(row)
            if item is None:
                continue
            item["starred"] = True
            item["starred_at"] = str(row["starred_at"] or "")
            items.append(item)
        return {
            "items": items,
            "total": int(total_row["n"]) if total_row else 0,
            "limit": size,
            "offset": start,
        }

    def _card_row(self, row: Any) -> dict[str, Any] | None:
        """一行「发布物 + 最近一期绩效」→ 广场卡片。"""
        item = self._publish_row(row)
        if item is None:
            return None
        # 既有字段保持原样（前端在用），metrics 是新增的可空对象。
        item["latest_score"] = float(row["latest_score"] or 0.0)
        item["metrics_date"] = str(row["metrics_date"] or "")
        item["metrics"] = self._card_metrics(row)
        for column in _CARD_METRIC_COLUMNS:
            item.pop(column, None)
        return item

    @staticmethod
    def _card_metrics(row: Any) -> dict[str, Any] | None:
        """没跑过绩效的返回 ``None``：全 0 会被前端画成「夏普 0 / 回撤 0」的假象。"""
        if not row["mx_as_of_date"]:
            return None
        return {
            "as_of_date": str(row["mx_as_of_date"]),
            "sharpe_1y": float(row["mx_sharpe_1y"] or 0.0),
            "annual_return": float(row["mx_annual_return"] or 0.0),
            "max_drawdown": float(row["mx_max_drawdown"] or 0.0),
            "win_rate": float(row["mx_win_rate"] or 0.0),
            "profit_factor": float(row["mx_profit_factor"] or 0.0),
            "trades": int(row["mx_trades"] or 0),
            "live_days": int(row["mx_live_days"] or 0),
            "score": float(row["mx_score"] or 0.0),
        }

    def count_publishes(self, *, owner_user_id: str = "", include_hidden: bool = False) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id:
            clauses.append("owner_user_id = ?")
            params.append(owner_user_id)
        if not include_hidden:
            clauses.append("status = 'listed'")
            clauses.append("visibility = 'public'")
        sql = "SELECT COUNT(*) AS n FROM published_strategies"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return int(row["n"]) if row else 0

    def list_tags(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """标签直方图。表小（个人仓），在 Python 里数比给 tags 建反查表划算。"""
        rows = self.conn.execute(
            "SELECT tags_json FROM published_strategies"
            " WHERE status = 'listed' AND visibility = 'public'"
        ).fetchall()
        counter: dict[str, int] = dict()
        for row in rows:
            for tag in self._loads_tags(row["tags_json"]):
                counter[tag] = counter.get(tag, 0) + 1
        ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[: int(limit)]
        return [{"tag": tag, "count": count} for tag, count in ordered]

    @staticmethod
    def _loads_tags(raw: Any) -> list[str]:
        from src.community.infrastructure.store_helpers import loads

        value = loads(raw, [])
        return [str(item) for item in value] if isinstance(value, list) else []


#: ``_card_row`` 收完就删掉的中间列，别让 ``mx_*`` 泄进 API 响应。
_CARD_METRIC_COLUMNS = (
    "mx_as_of_date",
    "mx_sharpe_1y",
    "mx_annual_return",
    "mx_max_drawdown",
    "mx_win_rate",
    "mx_profit_factor",
    "mx_trades",
    "mx_live_days",
    "mx_score",
)
