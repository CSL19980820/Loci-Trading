"""看板、评分卡、胜率与分析查询。"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.ledger.infrastructure.store_types import normalize_date


class QueryMixin:
    def realized_pnl_between(
        self,
        start: str,
        end: str,
        *,
        include_historical_baseline: bool = True,
    ) -> float:
        """闭区间 [start, end] 已实现盈亏；默认可排除潜龙累计基线。"""
        start_on = normalize_date(start)
        end_on = normalize_date(end)
        position_value = self.conn.execute(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS value FROM position_events
            WHERE occurred_on >= ? AND occurred_on <= ?
            """,
            (start_on, end_on),
        ).fetchone()["value"]
        account_where = (
            "kind = 'REALIZED_PNL_IMPORT' AND occurred_on >= ? AND occurred_on <= ?"
        )
        account_params: list[Any] = [start_on, end_on]
        if not include_historical_baseline:
            account_where += " AND source <> 'qianlong-skill-memory'"
        account_value = self.conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS value FROM account_events WHERE {account_where}",
            account_params,
        ).fetchone()["value"]
        return round(float(position_value) + float(account_value), 2)

    def today_sells_payload(self, as_of: str | None = None) -> list[dict[str, Any]]:
        """当日卖出明细（同花顺式：卖价对照卖出前成本）。"""
        as_of = normalize_date(as_of)
        rows = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, code, name, shares, price,
                   shares_after, cost_before, cost_after, realized_pnl,
                   reason, source, correlation_id
            FROM position_events
            WHERE action = 'SELL' AND occurred_on = ?
            ORDER BY created_at DESC, id DESC
            """,
            (as_of,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            price = float(row["price"])
            cost_before = float(row["cost_before"])
            shares = int(row["shares"])
            pnl_pct = (
                round((price / cost_before - 1) * 100, 2) if cost_before > 0 else None
            )
            out.append(
                {
                    "id": str(row["id"]),
                    "date": str(row["occurred_on"]),
                    "created_at": str(row["created_at"]),
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "shares": shares,
                    "price": price,
                    "amount": round(shares * price, 2),
                    "cost_before": cost_before,
                    "cost_after": float(row["cost_after"]),
                    "shares_after": int(row["shares_after"]),
                    "realized_pnl": float(row["realized_pnl"]),
                    "realized_pnl_pct": pnl_pct,
                    "reason": str(row["reason"]),
                    "source": str(row["source"]),
                    "correlation_id": str(row["correlation_id"]),
                }
            )
        return out

    def month_pnl_curve(
        self,
        start: str,
        end: str,
        *,
        include_historical_baseline: bool = False,
    ) -> list[dict[str, Any]]:
        """自然月内逐日累计已实现（从 0 起），供参考盈亏 sparkline。"""
        from datetime import date, timedelta

        start_on = normalize_date(start)
        end_on = normalize_date(end)
        trade_rows = self.conn.execute(
            """
            SELECT occurred_on, SUM(realized_pnl) AS day_pnl
            FROM position_events
            WHERE occurred_on >= ? AND occurred_on <= ?
            GROUP BY occurred_on
            """,
            (start_on, end_on),
        ).fetchall()
        account_where = (
            "kind = 'REALIZED_PNL_IMPORT' AND occurred_on >= ? AND occurred_on <= ?"
        )
        account_params: list[Any] = [start_on, end_on]
        if not include_historical_baseline:
            account_where += " AND source <> 'qianlong-skill-memory'"
        import_rows = self.conn.execute(
            f"""
            SELECT occurred_on, SUM(amount) AS day_pnl
            FROM account_events
            WHERE {account_where}
            GROUP BY occurred_on
            """,
            account_params,
        ).fetchall()
        day_map: dict[str, float] = {}
        for row in trade_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(
                row["day_pnl"] or 0
            )
        for row in import_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(
                row["day_pnl"] or 0
            )

        d0 = date.fromisoformat(start_on)
        d1 = date.fromisoformat(end_on)
        if d1 < d0:
            return []
        cumulative = 0.0
        curve: list[dict[str, Any]] = []
        cur = d0
        while cur <= d1:
            key = cur.isoformat()
            cumulative = round(cumulative + day_map.get(key, 0.0), 2)
            curve.append({"date": key, "cumulative_pnl": cumulative})
            cur += timedelta(days=1)
        return curve

    def dashboard_payload(self, as_of: str | None = None) -> dict[str, Any]:
        """面向工作台的结构化看板数据；展示数值均来自账本而非估算行情。"""
        as_of = normalize_date(as_of)
        snapshot = self._latest_snapshot()
        positions = self.positions_payload()
        total_cost = round(sum(float(position["cost_value"]) for position in positions), 2)
        cash_detail = self.broker_cash_detail()
        cash = cash_detail["cash"]
        # 快照里的 total_assets 只作历史锚点；有现金时前端用 现金+市值 作为券商总资产
        total_assets = float(snapshot["total_assets"]) if snapshot else None
        if cash is not None and total_assets is not None:
            # 无实时市值时，用成本占用估一个账面总资产（偏保守，不等于盯市）
            total_assets = round(cash + total_cost, 2)
        reviews_count = int(self.conn.execute("SELECT COUNT(*) AS value FROM reviews").fetchone()["value"])
        historical_baseline = self.conn.execute(
            """
            SELECT 1 FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT' AND occurred_on = ? AND source = 'qianlong-skill-memory'
            LIMIT 1
            """,
            (as_of,),
        ).fetchone()
        detailed_day_events = self.conn.execute(
            """
            SELECT COUNT(*) AS value FROM position_events
            WHERE occurred_on = ? AND realized_pnl <> 0
            """,
            (as_of,),
        ).fetchone()["value"]
        detailed_day_imports = self.conn.execute(
            """
            SELECT COUNT(*) AS value FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT' AND occurred_on = ? AND source <> 'qianlong-skill-memory'
            """,
            (as_of,),
        ).fetchone()["value"]
        today_is_baseline_only = bool(historical_baseline) and not (detailed_day_events or detailed_day_imports)
        candidates = self.candidates_payload(as_of)
        broker_day = self.conn.execute(
            "SELECT broker_pnl, source, note FROM daily_pnl_ledger WHERE occurred_on = ?",
            (as_of,),
        ).fetchone()
        broker_cum = self.conn.execute(
            "SELECT COALESCE(SUM(broker_pnl), 0) AS value FROM daily_pnl_ledger"
        ).fetchone()
        month_start = f"{as_of[:7]}-01"
        month_realized = self.realized_pnl_between(
            month_start, as_of, include_historical_baseline=False
        )
        # 同花顺式：本月已实现 / 当前账面总资产；无总资产时不编造比例
        month_pct = (
            round(month_realized / total_assets * 100, 2)
            if total_assets and total_assets > 0
            else None
        )
        month_curve = self.month_pnl_curve(month_start, as_of, include_historical_baseline=False)
        today_sells = self.today_sells_payload(as_of)
        return {
            "as_of": as_of,
            "account": {
                "realized_pnl": self.realized_pnl(),
                "today_realized_pnl": None if today_is_baseline_only else self.realized_pnl(
                    as_of, include_historical_baseline=False
                ),
                "today_realized_note": "旧账仅导入累计盈亏基线；当日明细待补录" if today_is_baseline_only else f"截至 {as_of}",
                "month_realized_pnl": month_realized,
                "month_realized_pnl_pct": month_pct,
                "month_realized_note": f"{as_of[:7]} 参考盈亏（已实现，不含潜龙累计基线）",
                "broker_daily_pnl": None if broker_day is None else float(broker_day["broker_pnl"]),
                "broker_daily_pnl_cumulative": round(float(broker_cum["value"] or 0), 4),
                "broker_daily_note": (
                    "尚无券商市值法当日盈亏入账"
                    if broker_day is None
                    else f"来源 {broker_day['source']}；{broker_day['note'] or '券商市值法当日盈亏（≠已实现）'}"
                ),
                "total_assets": total_assets,
                "snapshot_date": str(snapshot["occurred_on"]) if snapshot else None,
                "cash": cash,
                "cash_base": cash_detail["cash_base"],
                "cash_implied": cash_detail["cash_implied"],
                "cost_exposure": total_cost,
                "cost_exposure_pct": round(total_cost / total_assets * 100, 2) if total_assets else None,
            },
            "positions": positions,
            "today_sells": today_sells,
            "month_pnl_curve": month_curve,
            "candidates": candidates,
            "candidate_summary": self.candidate_day_summary(candidates),
            "plans": self.plans_payload(),
            "scorecard": self.scorecard(),
            "evolution": {
                "review_count": reviews_count,
                "gate": 5,
                "ready": reviews_count >= 5,
                "message": "样本达到门槛，可按 rule_version 进行前向验证。" if reviews_count >= 5 else "复盘样本不足 5 条，当前只记录假设，不修改规则。",
            },
        }

    def _latest_snapshot(self) -> sqlite3.Row | None:
        return self._latest_snapshot_row()

    def scorecard(self) -> dict[str, Any]:
        sells = self.conn.execute(
            "SELECT realized_pnl FROM position_events WHERE action = 'SELL' ORDER BY occurred_on, created_at"
        ).fetchall()
        values = [float(row["realized_pnl"]) for row in sells]
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        review_rows = self.conn.execute(
            "SELECT strategy_tag, return_pct FROM reviews WHERE return_pct IS NOT NULL"
        ).fetchall()
        groups: dict[str, list[float]] = {}
        for row in review_rows:
            groups.setdefault(str(row["strategy_tag"]), []).append(float(row["return_pct"]))
        return {
            "closed_trades": len(values),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(values) * 100, 2) if values else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else None,
            "average_realized": round(sum(values) / len(values), 2) if values else None,
            "realized_pnl": self.realized_pnl(),
            "review_groups": {
                tag: {"count": len(returns), "average_return_pct": round(sum(returns) / len(returns), 2)}
                for tag, returns in groups.items()
            },
        }

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

    def analytics_payload(self) -> dict[str, Any]:
        """可视化：累计盈亏曲线、日盈亏、决策分布、复盘收益。"""
        trade_rows = self.conn.execute(
            """
            SELECT occurred_on, SUM(realized_pnl) AS day_pnl
            FROM position_events
            GROUP BY occurred_on
            ORDER BY occurred_on ASC
            """
        ).fetchall()
        import_rows = self.conn.execute(
            """
            SELECT occurred_on, SUM(amount) AS day_pnl
            FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT'
            GROUP BY occurred_on
            ORDER BY occurred_on ASC
            """
        ).fetchall()
        day_map: dict[str, float] = {}
        for row in trade_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(row["day_pnl"] or 0)
        for row in import_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(row["day_pnl"] or 0)
        cumulative = 0.0
        equity_curve: list[dict[str, Any]] = []
        daily_pnl: list[dict[str, Any]] = []
        for day in sorted(day_map):
            pnl = round(day_map[day], 2)
            cumulative = round(cumulative + pnl, 2)
            daily_pnl.append({"date": day, "pnl": pnl})
            equity_curve.append({"date": day, "cumulative_pnl": cumulative})

        decision_rows = self.conn.execute(
            """
            SELECT decision, COUNT(*) AS count
            FROM (
                SELECT decision,
                       ROW_NUMBER() OVER (
                           PARTITION BY occurred_on, pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE IFNULL(source, '') NOT LIKE '%backfill%'
                  AND IFNULL(source, '') NOT LIKE '%:history'
            ) ranked
            WHERE rn = 1
            GROUP BY decision
            ORDER BY count DESC, decision ASC
            """
        ).fetchall()
        decisions = [{"decision": str(row["decision"]), "count": int(row["count"])} for row in decision_rows]

        review_rows = self.conn.execute(
            """
            SELECT reviewed_on, return_pct, strategy_tag
            FROM reviews
            WHERE return_pct IS NOT NULL
            ORDER BY reviewed_on ASC, created_at ASC
            """
        ).fetchall()
        review_returns = [
            {
                "date": str(row["reviewed_on"]),
                "return_pct": float(row["return_pct"]),
                "strategy_tag": str(row["strategy_tag"]),
            }
            for row in review_rows
        ]

        action_rows = self.conn.execute(
            """
            SELECT action, COUNT(*) AS count, COALESCE(SUM(realized_pnl), 0) AS realized
            FROM position_events
            GROUP BY action
            ORDER BY action
            """
        ).fetchall()
        actions = [
            {
                "action": str(row["action"]),
                "count": int(row["count"]),
                "realized_pnl": round(float(row["realized"]), 2),
            }
            for row in action_rows
        ]

        return {
            "equity_curve": equity_curve,
            "daily_pnl": daily_pnl,
            "decisions": decisions,
            "review_returns": review_returns,
            "actions": actions,
            "scorecard": self.scorecard(),
            "broker_daily_pnl": self.daily_pnl_summary(),
        }

    def dashboard_markdown(self, as_of: str | None = None) -> str:
        """生成只含事实、预案状态和数据质量提示的日常看板。"""
        as_of = normalize_date(as_of)
        positions = self.list_positions()
        snapshot = self._latest_snapshot()
        total_cost = round(sum(position.cost_value for position in positions), 2)
        total_assets = float(snapshot["total_assets"]) if snapshot else None
        active_plans = self.conn.execute(
            "SELECT id, code, title, entry_zone, stop_price, target_price, layers, invalidation FROM plans WHERE status = 'active' ORDER BY occurred_on DESC, created_at DESC"
        ).fetchall()
        candidates = self.conn.execute(
            """
            SELECT pool_id, COUNT(*) AS total,
                   SUM(CASE WHEN decision = '精选' THEN 1 ELSE 0 END) AS selected
            FROM candidate_reviews
            WHERE occurred_on = ?
              AND IFNULL(source, '') NOT LIKE '%backfill%'
              AND IFNULL(source, '') NOT LIKE '%:history'
            GROUP BY pool_id ORDER BY pool_id
            """,
            (as_of,),
        ).fetchall()
        scorecard = self.scorecard()
        coverage = self.conn.execute("SELECT COUNT(*) AS value FROM reviews").fetchone()["value"]

        lines = [
            "# 潜龙记忆宫殿｜日常看板",
            "",
            f"> 截至：{as_of} ｜账本：`{self.db_path}` ｜仅作研究记录与复盘，不构成投资建议。",
            "",
            "## 账户与仓位",
            "",
            f"- 已实现累计：**{self.realized_pnl():+.2f} 元**",
            f"- 当日已实现：**{self.realized_pnl(as_of):+.2f} 元**",
            f"- 最近总资产快照：**{total_assets:,.2f} 元**（{snapshot['occurred_on']}）" if snapshot else "- 最近总资产快照：未记录",
            f"- 持仓成本占用：**{total_cost:,.2f} 元**" + (f"（约 {total_cost / total_assets * 100:.1f}%）" if total_assets else ""),
            "",
            "| 代码 | 名称 | 股数 | 成本 | 成本金额 | 最后变更 | 备注 |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
        if positions:
            lines.extend(
                f"| {position.code} | {position.name} | {position.shares} | {position.cost:.3f} | {position.cost_value:,.2f} | {position.updated_on} | {position.note or '-'} |"
                for position in positions
            )
        else:
            lines.append("| - | 当前无持仓 | - | - | - | - | - |")

        lines.extend(["", "## 候选池与预案", ""])
        if candidates:
            lines.extend(["| 候选池 | 总数 | 精选 |", "|---|---:|---:|"])
            lines.extend(f"| {row['pool_id']} | {row['total']} | {row['selected']} |" for row in candidates)
        else:
            lines.append("- 当日尚未归档候选池。")
        if active_plans:
            lines.extend(["", "| 计划 ID | 标的 | 预案 | 入场区 | 止损 | 目标 | 层数 | 失效条件 |", "|---|---|---|---|---:|---:|---:|---|"])
            for plan in active_plans:
                stop = f"{float(plan['stop_price']):.3f}" if plan["stop_price"] is not None else "-"
                target = f"{float(plan['target_price']):.3f}" if plan["target_price"] is not None else "-"
                layers = f"{float(plan['layers']):.2f}" if plan["layers"] is not None else "-"
                lines.append(
                    f"| {plan['id']} | {plan['code']} | {plan['title']} | {plan['entry_zone'] or '-'} | {stop} | {target} | {layers} | {plan['invalidation'] or '-'} |"
                )
        else:
            lines.append("- 当前无 active 预案。")

        lines.extend([
            "",
            "## 量化复盘与进化门槛",
            "",
            f"- 已平仓事件：{scorecard['closed_trades']} 笔；胜率：{scorecard['win_rate'] if scorecard['win_rate'] is not None else '-'}%；盈亏比：{scorecard['profit_factor'] if scorecard['profit_factor'] is not None else '-'}。",
            f"- 已记录复盘：{coverage} 条。",
        ])
        if coverage < 5:
            lines.append("- 进化建议：样本不足 5 条，只记录假设与结果，暂不修改规则版本。")
        else:
            lines.append("- 进化建议：可按策略标签比较复盘收益、MFE/MAE 与失效原因，再以新 rule_version 做小样本前向验证。")
        if scorecard["review_groups"]:
            lines.extend(["", "| 策略标签 | 已复盘样本 | 平均收益率 |", "|---|---:|---:|"])
            lines.extend(
                f"| {tag} | {item['count']} | {item['average_return_pct']:+.2f}% |"
                for tag, item in sorted(scorecard["review_groups"].items())
            )
        return "\n".join(lines) + "\n"
