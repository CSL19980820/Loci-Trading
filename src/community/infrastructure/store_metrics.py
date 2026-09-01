"""community.db：绩效切片与榜单快照。

两张表都是**可重算的派生数据**：清空后 ``rebuild_leaderboard`` 能整表重建。
落库的理由只有一个——「当天榜首是谁」要能回看，而榜单依赖的绩效会随时间变。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from src.community.domain.models import ValidationError
from src.community.domain.scoring import compute_score
from src.community.infrastructure.store_helpers import (
    MAX_BOARD_SIZE,
    dumps,
    json_columns,
    loads,
    row_to_dict,
)


class CommunityMetricsMixin:
    def _metrics_row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = row_to_dict(row)
        return json_columns(data, {"metrics_json": ("metrics", dict())})

    def upsert_metrics(self, publish_id: str, *, as_of_date: str, **values: Any) -> dict[str, Any]:
        """写入某天的绩效切片。

        ``score`` **一律由 ``compute_score`` 现算**，不接受调用方传进来的分数——
        否则「榜单分数」就有了第二个来源，改口径时会有一半的行还是老公式算的。
        """
        if not publish_id or not as_of_date:
            raise ValidationError("绩效切片需要 publish_id 与 as_of_date")
        extra = values.get("metrics") or dict()
        row = {
            "publish_id": publish_id,
            "as_of_date": as_of_date,
            "sharpe_1y": float(values.get("sharpe_1y") or 0.0),
            "annual_return": float(values.get("annual_return") or 0.0),
            "max_drawdown": float(values.get("max_drawdown") or 0.0),
            "win_rate": float(values.get("win_rate") or 0.0),
            "profit_factor": float(values.get("profit_factor") or 0.0),
            "trades": int(values.get("trades") or 0),
            "live_days": int(values.get("live_days") or 0),
            "oos_return": float(values.get("oos_return") or 0.0),
            "metrics_json": dumps(dict(extra)),
            "updated_at": self._now(),
        }
        row["score"] = compute_score(row["sharpe_1y"], row["live_days"])
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO strategy_metrics(
                    publish_id, as_of_date, sharpe_1y, annual_return, max_drawdown, win_rate,
                    profit_factor, trades, live_days, oos_return, score, metrics_json, updated_at
                ) VALUES (
                    :publish_id, :as_of_date, :sharpe_1y, :annual_return, :max_drawdown, :win_rate,
                    :profit_factor, :trades, :live_days, :oos_return, :score, :metrics_json, :updated_at
                )
                ON CONFLICT(publish_id, as_of_date) DO UPDATE SET
                    sharpe_1y=excluded.sharpe_1y,
                    annual_return=excluded.annual_return,
                    max_drawdown=excluded.max_drawdown,
                    win_rate=excluded.win_rate,
                    profit_factor=excluded.profit_factor,
                    trades=excluded.trades,
                    live_days=excluded.live_days,
                    oos_return=excluded.oos_return,
                    score=excluded.score,
                    metrics_json=excluded.metrics_json,
                    updated_at=excluded.updated_at
                """,
                row,
            )
        return self.get_metrics(publish_id, as_of_date) or dict()

    def get_metrics(self, publish_id: str, as_of_date: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM strategy_metrics WHERE publish_id = ? AND as_of_date = ?",
            (publish_id, as_of_date),
        ).fetchone()
        return self._metrics_row(row)

    def latest_metrics(self, publish_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM strategy_metrics WHERE publish_id = ? ORDER BY as_of_date DESC LIMIT 1",
            (publish_id,),
        ).fetchone()
        return self._metrics_row(row)

    def list_metrics_as_of(
        self, as_of_date: str, *, listed_only: bool = True
    ) -> list[dict[str, Any]]:
        """取某天全部切片（榜单输入）。

        ``as_of_date`` 那天没有切片的发布物**不会**被顺延用旧数据顶上：榜单宁可少一行，
        也不能把上个月的夏普当今天的。
        """
        sql = "SELECT m.* FROM strategy_metrics m"
        params: list[Any] = [as_of_date]
        if listed_only:
            sql += (
                " JOIN published_strategies p ON p.publish_id = m.publish_id"
                " WHERE m.as_of_date = ? AND p.status = 'listed' AND p.visibility = 'public'"
            )
        else:
            sql += " WHERE m.as_of_date = ?"
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [item for item in (self._metrics_row(row) for row in rows) if item]

    def latest_metrics_date(self) -> str:
        row = self.conn.execute("SELECT MAX(as_of_date) AS d FROM strategy_metrics").fetchone()
        return str(row["d"] or "") if row else ""

    def replace_leaderboard(
        self, *, board: str, as_of_date: str, entries: Iterable[Mapping[str, Any]]
    ) -> int:
        """整段替换一张榜（同 board + 同日）。

        先删后插在一个事务里：榜单不允许出现「一半新一半旧」的中间态，
        否则前端刷到的那一瞬间会看到重复名次。
        """
        rows = list(entries)[:MAX_BOARD_SIZE]
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "DELETE FROM leaderboard_snapshots WHERE board = ? AND as_of_date = ?",
                (board, as_of_date),
            )
            for entry in rows:
                # sort_value = 本榜排序键值（``rank_entries`` 的 "value"）：主榜等于 score，
                # 副榜是 sharpe / annual_return。不落库的话，副榜名次前端只能从 metrics 反推。
                score = float(entry.get("score") or 0.0)
                cursor.execute(
                    """
                    INSERT INTO leaderboard_snapshots(
                        board, as_of_date, rank, publish_id, score, sort_value, metrics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        board,
                        as_of_date,
                        int(entry.get("rank") or 0),
                        str(entry.get("publish_id") or ""),
                        score,
                        float(entry.get("value", score) or 0.0),
                        dumps(entry.get("metrics") or dict()),
                    ),
                )
        return len(rows)

    def read_leaderboard(
        self, *, board: str, as_of_date: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        """读某张榜。``as_of_date`` 为空取该榜最新一期。"""
        target = as_of_date or self.latest_board_date(board)
        if not target:
            return []
        rows = self.conn.execute(
            """
            SELECT b.*, p.title, p.owner_user_id, p.owner_name, p.slug, p.kind, p.stars
            FROM leaderboard_snapshots b
            LEFT JOIN published_strategies p ON p.publish_id = b.publish_id
            WHERE b.board = ? AND b.as_of_date = ?
            ORDER BY b.rank ASC LIMIT ?
            """,
            (board, target, int(limit)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_dict(row)
            item["metrics"] = loads(item.pop("metrics_json", ""), dict())
            out.append(item)
        return out

    def latest_board_date(self, board: str) -> str:
        row = self.conn.execute(
            "SELECT MAX(as_of_date) AS d FROM leaderboard_snapshots WHERE board = ?", (board,)
        ).fetchone()
        return str(row["d"] or "") if row else ""

    def board_history(
        self, publish_id: str, *, board: str = "", limit: int = 30
    ) -> list[dict[str, Any]]:
        """某个发布物的历史名次（「掉榜了吗」这个问题的答案）。"""
        sql = "SELECT * FROM leaderboard_snapshots WHERE publish_id = ?"
        params: list[Any] = [publish_id]
        if board:
            sql += " AND board = ?"
            params.append(board)
        sql += " ORDER BY as_of_date DESC LIMIT ?"
        params.append(int(limit))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_dict(row)
            item["metrics"] = loads(item.pop("metrics_json", ""), dict())
            out.append(item)
        return out
