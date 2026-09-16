"""分页历史、独立资金曲线与有界日记清理；成交及资金流水不参与清理。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


class StockAgentConflict(ValueError):
    """运行所有权、账户版本或配置版本已发生变化。"""


def agent_now(value: datetime | None = None) -> datetime:
    value = value or datetime.now(ZoneInfo("Asia/Shanghai"))
    if value.tzinfo is None:
        raise ValueError("智能体时钟必须带时区")
    return value.astimezone(ZoneInfo("Asia/Shanghai"))


def encode_agent_json(value: Any) -> str:
    result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(result.encode("utf-8")) > 1_048_576:
        raise ValueError("单次智能体记录超过1MB，请减少工具结果或输出长度")
    return result


class StockAgentHistoryMixin:
    conn: sqlite3.Connection

    def history(self, agent_id: str, *, kind: str = "runs", limit: int = 20,
                offset: int = 0, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        tables = {"runs": ("stock_agent_runs", "started_at"),
                  "trades": ("stock_agent_trades", "at"), "funding": ("stock_agent_funding", "at")}
        if kind not in tables:
            raise ValueError("未知的历史类型")
        table, time_column = tables[kind]
        limit, offset = max(1, min(100, int(limit))), max(0, int(offset))
        where, params = ["agent_id=?"], [agent_id]
        if start:
            where.append(f"{time_column} >= ?")
            params.append(start[:10] + "T00:00:00")
        if end:
            where.append(f"{time_column} < ?")
            params.append((datetime.fromisoformat(end[:10]) + timedelta(days=1)).date().isoformat())
        clause = " AND ".join(where)
        total = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {clause}", params).fetchone()[0]
        columns = ("id,phase,started_at,finished_at,status,summary,actions_json" if kind == "runs" else "*")
        tie = "request_id" if kind == "funding" else "id"
        rows = self.conn.execute(
            f"SELECT {columns} FROM {table} WHERE {clause} ORDER BY {time_column} DESC,{tie} DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = []
        for raw in rows:
            item = dict(raw)
            if "actions_json" in item:
                item["actions"] = json.loads(item.pop("actions_json"))
            if "detail_json" in item:
                detail = json.loads(item.pop("detail_json"))
                item.update(detail)
            items.append(item)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def run_detail(self, agent_id: str, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM stock_agent_runs WHERE agent_id=? AND id=?", (agent_id, run_id)).fetchone()
        if row is None:
            raise KeyError("日记不存在，或已按保留策略清理")
        result = dict(row)
        result["detail"] = json.loads(result.pop("detail_json") or "{}")
        result["actions"] = json.loads(result.pop("actions_json"))
        return result

    def equity(self, agent_id: str, *, limit: int = 365) -> dict[str, Any]:
        limit = max(1, min(2000, limit))
        total = self.conn.execute("SELECT COUNT(*) FROM stock_agent_equity WHERE agent_id=?", (agent_id,)).fetchone()[0]
        rows = self.conn.execute(
            "SELECT * FROM stock_agent_equity WHERE agent_id=? ORDER BY day DESC LIMIT ?", (agent_id, limit),
        ).fetchall()
        return {"items": [dict(row) for row in reversed(rows)], "total": total, "truncated": total > limit,
                "caliber": "累计盈亏=模拟净资产−累计投入；追加资金不计为利润。估值时间及陈旧标记随每日快照保留。"}

    def prune_diary(self, agent_id: str, *, now: datetime | None = None,
                    force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        current = agent_now(now)
        row = self.conn.execute("SELECT config_json,cleanup_at FROM stock_agent_profiles WHERE id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError("智能体不存在")
        config = json.loads(row["config_json"]).get("retention", {})
        hours = max(1, int(config.get("cleanup_hours", 24)))
        if not force and row["cleanup_at"] and current < datetime.fromisoformat(row["cleanup_at"]) + timedelta(hours=hours):
            return {"removed": 0, "due": False}
        days, count = max(0, int(config.get("days", 30))), max(0, int(config.get("max_entries", 2000)))
        conditions, values = [], []
        if days:
            conditions.append("started_at < ?")
            values.append((current - timedelta(days=days)).isoformat())
        if count:
            conditions.append("id IN (SELECT id FROM stock_agent_runs WHERE agent_id=? ORDER BY started_at DESC,id DESC LIMIT -1 OFFSET ?)")
            values.extend([agent_id, max(20, count)])
        if not conditions:
            return {"removed": 0, "due": True, "disabled": True}
        # 当天幂等槽和最近20次推理上下文不能被清理；清理不触碰财务事实表。
        sql = """SELECT id FROM stock_agent_runs WHERE agent_id=? AND status<>'running'
            AND started_at<? AND id NOT IN (SELECT id FROM stock_agent_runs WHERE agent_id=?
            ORDER BY started_at DESC,id DESC LIMIT 20) AND (""" + " OR ".join(conditions) + ") ORDER BY started_at LIMIT 1000"
        params = [agent_id, current.date().isoformat(), agent_id, *values]
        with self._write():
            ids = [item[0] for item in self.conn.execute(sql, params)]
            if not dry_run:
                self.conn.executemany("DELETE FROM stock_agent_runs WHERE id=? AND agent_id=? AND status<>'running'", [(item, agent_id) for item in ids])
                self.conn.execute("UPDATE stock_agent_profiles SET cleaned_runs=cleaned_runs+?,cleanup_at=? WHERE id=?",
                                  (len(ids), None if len(ids) == 1000 else current.isoformat(), agent_id))
        return {"removed": 0 if dry_run else len(ids), "eligible": len(ids), "due": True,
                "more_possible": len(ids) == 1000, "protected": "最近20次、当天与运行中日记；全部成交、资金流水和资金曲线"}
