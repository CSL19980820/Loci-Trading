"""旧交易员的展示与存储维护，不参与任何交易决策或提示词组装。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from src.ledger.infrastructure.guardian_store import GuardianStore
from src.ledger.domain.guardian_curve import curve_snapshot
from src.ledger.infrastructure.stock_agent_history import agent_now


class GuardianDiaryStore:
    """保留运行槽防止重复成交；仅压缩过期正文，财务账本与近期模型记忆保持原样。"""

    def __init__(self, path=None):
        self.ledger = GuardianStore(path)
        self.conn = self.ledger.conn
        if not getattr(self.ledger, "_use_postgres", False):
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS guardian_diary_preferences (
                    id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL, checked_at TEXT);
                CREATE TABLE IF NOT EXISTS guardian_diary_compactions (slot TEXT PRIMARY KEY, at TEXT NOT NULL);
            """)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.conn.close()

    def preferences(self) -> dict[str, Any]:
        row = self.conn.execute("SELECT config_json FROM guardian_diary_preferences WHERE id=1").fetchone()
        return json.loads(row["config_json"]) if row else {"days": 30, "max_entries": 2000, "cleanup_hours": 24}

    def save_preferences(self, config: dict[str, Any]) -> dict[str, Any]:
        with self.conn:
            self.conn.execute("""INSERT INTO guardian_diary_preferences VALUES(1,?,NULL)
                ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,checked_at=NULL""",
                (json.dumps(config, ensure_ascii=False, allow_nan=False),))
        return self.preferences()

    def stats(self) -> dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) AS count FROM guardian_cycles").fetchone()["count"]
        compacted = self.conn.execute("SELECT COUNT(*) AS count FROM guardian_diary_compactions").fetchone()["count"]
        return {"total_runs": total, "full_entries": max(0, total-compacted), "compacted_entries": compacted,
                "total_trades": self.conn.execute("SELECT COUNT(*) AS count FROM guardian_trades").fetchone()["count"],
                "total_reports": self.conn.execute("SELECT COUNT(*) AS count FROM guardian_reports").fetchone()["count"],
                "retention": self.preferences(), "protected_recent": 40}

    def latest(self) -> list[dict[str, Any]]:
        # SQL先定位一行，再投影少量字段；绝不把全量研究上下文传给列表页。
        row = self.conn.execute("""SELECT slot,status,started,
            substr(COALESCE(json_extract(result_json,'$.analysis'),json_extract(result_json,'$.body'),''),1,1000) AS analysis,
            substr(COALESCE(json_extract(result_json,'$.error'),''),1,1000) AS error,
            json_extract(result_json,'$.as_of') AS as_of
            FROM (SELECT slot,status,started,result_json FROM guardian_cycles ORDER BY started DESC LIMIT 1)""").fetchone()
        if row is None:
            return []
        fills = self.conn.execute("""SELECT json_extract(value,'$.name') AS name,
            json_extract(value,'$.code') AS code,json_extract(value,'$.action') AS action,
            json_extract(value,'$.side') AS side,json_extract(value,'$.quantity') AS quantity
            FROM guardian_cycles,json_each(guardian_cycles.result_json,'$.fills')
            WHERE guardian_cycles.slot=? LIMIT 3""", (row["slot"],)).fetchall()
        return [{"slot": row["slot"], "status": row["status"], "started": row["started"],
                 "result": {"analysis": row["analysis"], "error": row["error"], "as_of": row["as_of"],
                            "fills": [dict(fill) for fill in fills]}}]

    def compact(self, *, now: datetime | None = None, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        current = agent_now(now)
        config = self.preferences()
        previous = self.conn.execute("SELECT checked_at FROM guardian_diary_preferences WHERE id=1").fetchone()
        checked_at = previous["checked_at"] if previous and hasattr(previous, "keys") else (
            previous[0] if previous else None
        )
        if not force and checked_at and current < datetime.fromisoformat(checked_at) + timedelta(hours=config["cleanup_hours"]):
            return {"removed": 0, "eligible": 0, "due": False}
        terms, values = [], []
        if config["days"]:
            terms.append("started < ?")
            values.append((current-timedelta(days=config["days"])).timestamp())
        if config["max_entries"]:
            limit_clause = "LIMIT -1" if not getattr(self.ledger, "_use_postgres", False) else ""
            terms.append(
                "slot IN (SELECT slot FROM guardian_cycles ORDER BY started DESC "
                f"{limit_clause} OFFSET ?)"
            )
            values.append(max(40, config["max_entries"]))
        if not terms:
            return {"removed": 0, "eligible": 0, "disabled": True}
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            rows = self.conn.execute("""SELECT slot,
                COALESCE(json_extract(result_json,'$.curve_snapshot'),
                         json_extract(result_json,'$.decision_context.account_before')) AS curve_snapshot_json,
                COALESCE(json_extract(result_json,'$.curve_account'),
                         json_extract(result_json,'$.account')) AS curve_account_json,
                substr(COALESCE(json_extract(result_json,'$.analysis'),
                         json_extract(result_json,'$.body'),''),1,1000) AS compact_analysis,
                json_extract(result_json,'$.as_of') AS compact_as_of,
                json_extract(result_json,'$.outcome') AS compact_outcome,
                substr(COALESCE(json_extract(result_json,'$.error'),''),1,500) AS compact_error,
                json_extract(result_json,'$.notify') AS compact_notify
                FROM guardian_cycles WHERE status<>'running' AND slot<?
                AND slot NOT IN (SELECT slot FROM guardian_cycles ORDER BY started DESC LIMIT 40)
                AND slot NOT IN (SELECT slot FROM guardian_diary_compactions) AND (""" + " OR ".join(terms)
                + ") ORDER BY started LIMIT 200", [current.date().isoformat(), *values]).fetchall()
            if not dry_run:
                for row in rows:
                    snapshot_json = row["curve_snapshot_json"]
                    account_json = row["curve_account_json"]
                    if getattr(self.ledger, "_use_postgres", False):
                        compacted = {
                            "diary_compacted": True,
                            "analysis": row["compact_analysis"],
                            "as_of": row["compact_as_of"],
                            "outcome": row["compact_outcome"],
                            "error": row["compact_error"],
                            "notify": row["compact_notify"],
                            "curve_snapshot": curve_snapshot(json.loads(snapshot_json)) if snapshot_json else None,
                            "curve_account": curve_snapshot(json.loads(account_json)) if account_json else None,
                            "compacted_at": current.isoformat(),
                        }
                        self.conn.execute(
                            "UPDATE guardian_cycles SET result_json=? "
                            "WHERE slot=? AND status<>'running'",
                            (json.dumps(compacted, ensure_ascii=False), row["slot"]),
                        )
                    else:
                        snapshot_json = snapshot_json[0] if isinstance(snapshot_json, tuple) else snapshot_json
                        account_json = account_json[0] if isinstance(account_json, tuple) else account_json
                        self.conn.execute("""UPDATE guardian_cycles SET result_json=json_object(
                            'diary_compacted',json('true'),
                            'analysis',substr(COALESCE(json_extract(result_json,'$.analysis'),json_extract(result_json,'$.body'),''),1,1000),
                            'as_of',json_extract(result_json,'$.as_of'),
                            'outcome',json_extract(result_json,'$.outcome'),
                            'error',substr(COALESCE(json_extract(result_json,'$.error'),''),1,500),
                            'notify',json_extract(result_json,'$.notify'),
                            'curve_snapshot',json(?),'curve_account',json(?),
                            'compacted_at',?) WHERE slot=? AND status<>'running'""", (
                                json.dumps(curve_snapshot(json.loads(snapshot_json))) if snapshot_json else 'null',
                                json.dumps(curve_snapshot(json.loads(account_json))) if account_json else 'null',
                                current.isoformat(), row["slot"]))
                    self.conn.execute("INSERT OR IGNORE INTO guardian_diary_compactions VALUES(?,?)", (row["slot"], current.isoformat()))
                self.conn.execute("""INSERT INTO guardian_diary_preferences VALUES(1,?,?)
                    ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at""",
                    (json.dumps(config), None if len(rows) == 200 else current.isoformat()))
        return {"removed": 0 if dry_run else len(rows), "eligible": len(rows), "more_possible": len(rows) == 200,
                "protected": "当天、运行中和最近40次完整日记；全部成交流水、账户、报告和运行槽保留"}
