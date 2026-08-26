"""胜率查询与 review 只读缓存指纹。

持仓/成交下线后本文件只剩两类东西：读 ``reviews`` 表的胜率聚合，以及
``review_read_fingerprint``（原在已删除的 ``tracking.py``）。
"""
from __future__ import annotations

import hashlib
from typing import Any

#: review 端点只读这几张表；每条 SQL 的口径必须覆盖「这张表被 review 读到的列」。
#: 只增不改的表（plans / reviews）用 条数 + 最大 rowid + 最大 created_at 就够；
#: candidate_reviews 的改判是不刷新任何时间戳的原地 UPDATE，只能逐行摘要。
_REVIEW_FINGERPRINT_SQL = (
    "SELECT COUNT(*), MAX(rowid), MAX(created_at) FROM plans",
    "SELECT COUNT(*), MAX(rowid), MAX(created_at) FROM reviews",
    (
        "SELECT COUNT(*), MAX(rowid), MAX(created_at), GROUP_CONCAT("
        "  rowid || '|' || IFNULL(name, '') || '|' || IFNULL(score, '') || '|' ||"
        "  decision || '|' || tier || '|' || strategy_slug || '|' ||"
        "  rule_version || '|' || source, char(10))"
        " FROM candidate_reviews"
    ),
)


class QueryMixin:
    def winrate_trend(
        self,
        *,
        strategy_tags: list[str] | None = None,
        granularity: str = "month",
    ) -> list[dict[str, Any]]:
        """按时间粒度统计各战法的胜率趋势。

        数据源：reviews 表的 return_pct 字段（有复盘记录时才有值）。
        granularity: 'month'(YYYY-MM) 或 'week'(YYYY-Www)。
        返回 [{period, strategy_tag, total, wins, win_rate}]，按 period+tag 升序。
        """
        if granularity == "week":
            # 用本周周一日期作为 period key（YYYY-MM-DD），避免 strftime('%W') 的
            # W00 边界问题（年初第一个周一之前的天数会落到 W00）。
            period_expr = "date(reviewed_on, 'weekday 0', '-6 days')"
        else:
            period_expr = "strftime('%Y-%m', reviewed_on)"

        params: list[Any] = []
        where = "return_pct IS NOT NULL"
        if strategy_tags:
            placeholders = ",".join("?" * len(strategy_tags))
            where += f" AND strategy_tag IN ({placeholders})"
            params.extend(strategy_tags)

        rows = self.conn.execute(
            f"""
            SELECT {period_expr} AS period,
                   strategy_tag,
                   COUNT(*) AS total,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS wins
            FROM reviews
            WHERE {where}
            GROUP BY period, strategy_tag
            ORDER BY period ASC, strategy_tag ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "period": str(row["period"]),
                "strategy_tag": str(row["strategy_tag"]),
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]) * 100, 1) if row["total"] else None,
            }
            for row in rows
        ]

    def strategy_winrates(self) -> list[dict[str, Any]]:
        """各战法综合胜率（全时段汇总）。用于首页滚动展示。"""
        rows = self.conn.execute(
            """
            SELECT strategy_tag,
                   COUNT(*) AS total,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS wins,
                   AVG(return_pct) AS avg_return,
                   MAX(reviewed_on) AS last_reviewed
            FROM reviews
            WHERE return_pct IS NOT NULL
            GROUP BY strategy_tag
            ORDER BY total DESC
            """
        ).fetchall()
        return [
            {
                "strategy_tag": str(row["strategy_tag"]),
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]) * 100, 1) if row["total"] else None,
                "avg_return": round(float(row["avg_return"]), 2) if row["avg_return"] is not None else None,
                "last_reviewed": str(row["last_reviewed"]) if row["last_reviewed"] else "",
            }
            for row in rows
        ]

    def review_read_fingerprint(self) -> str:
        """review 只读缓存的失效键：账本里任何影响复盘结果的写入都会改变它。

        原先住在 ``tracking.py``；持仓下线后搬到这里，口径同步收窄到仍然存在的三张表
        （candidate_reviews / plans / reviews）。函数名与返回类型不变，``src/review``
        侧的缓存键一个字都不用改。

        为什么不是 ``PRAGMA data_version``：它只在**同一条连接**上前后比较才有意义，
        而 review 每个请求都新开一条连接（跨连接读到的是同一个常数）；要让它有意义
        就得常驻一条探针连接，Windows 上会一直占住 palace.db 的句柄，临时库删不掉。

        为什么 candidate_reviews 要逐行摘要：改判走 record_candidate 的原地 UPDATE，
        不刷新 created_at、不改 rowid、不改条数——只看 COUNT/MAX(rowid)/MAX(created_at)
        的话「精选→落选」这种**等长改判**查不出来，缓存就会喂出陈数据。plans / reviews
        在全仓内只有 INSERT，条数 + 最大 rowid + 时间戳足够。

        成本是每张表一次索引扫描（实测 720 条候选约 1ms），相对被缓存的端点
        （200~700ms）可以忽略。
        """
        parts: list[str] = []
        for sql in _REVIEW_FINGERPRINT_SQL:
            row = self.conn.execute(sql).fetchone()
            parts.append("|".join("" if value is None else str(value) for value in tuple(row)))
        digest = hashlib.blake2b("\n".join(parts).encode("utf-8"), digest_size=16)
        return digest.hexdigest()
