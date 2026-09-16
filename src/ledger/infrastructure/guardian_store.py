"""守护模拟仓：每租户 palace.db；轮次、成交和退出名单原子保存。"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable

from src.shared.paths import palace_db
from src.ledger.domain.guardian_account import new_guardian_account, check_guardian_account
from src.ledger.infrastructure.guardian_reports import GuardianReportsMixin, REPORT_SCHEMA
from src.ledger.infrastructure.guardian_consults import GuardianConsultMixin, CONSULT_SCHEMA
from src.ledger.infrastructure.guardian_notices import GuardianNoticesMixin, NOTICE_SCHEMA


class GuardianStore(GuardianReportsMixin, GuardianConsultMixin, GuardianNoticesMixin):
    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path or palace_db())
        self.db_path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(REPORT_SCHEMA)
        self.conn.executescript(CONSULT_SCHEMA)
        self.conn.executescript(NOTICE_SCHEMA)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS guardian_portfolio (
                id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guardian_cycles (
                slot TEXT PRIMARY KEY, started REAL NOT NULL, status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS guardian_legacy_accounts (
                id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL, archived_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guardian_trades (
                id TEXT PRIMARY KEY, slot TEXT NOT NULL, code TEXT NOT NULL,
                occurred_at TEXT NOT NULL, detail_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_guardian_trades_time ON guardian_trades(occurred_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS ix_guardian_cycles_started ON guardian_cycles(started DESC);
        """)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT state_json FROM guardian_portfolio WHERE id=1").fetchone()
            old = json.loads(row[0]) if row else None
            if old and old.get("account_version") not in (None, 1, 2):
                raise ValueError("无法降级未知版本的守护账户")
            if old is None or old.get("account_version") != 2:
                if old is not None:
                    self.conn.execute("INSERT OR IGNORE INTO guardian_legacy_accounts VALUES(1,?,datetime('now'))", (row[0],))
                self.conn.execute("INSERT INTO guardian_portfolio VALUES(1,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
                                  (json.dumps(new_guardian_account()),))

    def __enter__(self) -> GuardianStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.conn.close()

    def state(self) -> dict[str, Any]:
        row = self.conn.execute("SELECT state_json FROM guardian_portfolio WHERE id=1").fetchone()
        return json.loads(row[0])

    def trades(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        rows = self.conn.execute("SELECT id,slot,detail_json FROM guardian_trades ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?",
                                 (limit, offset)).fetchall()
        return {"items": [{**json.loads(r["detail_json"]), "id": r["id"], "slot": r["slot"]} for r in rows],
                "total": self.conn.execute("SELECT count(*) FROM guardian_trades").fetchone()[0]}

    def performance(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("""SELECT code,
            max(json_extract(detail_json,'$.name')) AS name,
            sum(CASE WHEN json_extract(detail_json,'$.side')='buy' THEN json_extract(detail_json,'$.quantity') ELSE 0 END) AS bought_quantity,
            sum(CASE WHEN json_extract(detail_json,'$.side')='sell' THEN json_extract(detail_json,'$.quantity') ELSE 0 END) AS sold_quantity,
            sum(json_extract(detail_json,'$.realized_pnl_cents')) AS realized_pnl_cents,
            sum(json_extract(detail_json,'$.fees_cents')) AS fees_cents,
            count(*) AS trade_count FROM guardian_trades GROUP BY code ORDER BY code""").fetchall()
        return [dict(row) for row in rows]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM guardian_cycles ORDER BY started DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{**dict(row), "result": json.loads(row["result_json"])} for row in rows]

    def running_cycles(self) -> list[dict[str, Any]]:
        return [{'slot': r['slot'], 'result': json.loads(r['result_json'])} for r in self.conn.execute("SELECT slot,result_json FROM guardian_cycles WHERE status='running'")]

    def claim(self, slot: str, *, run_id: str = '') -> bool:
        # 跨进程互斥；过期 worker 不能提交，完整一轮只能落一次账。
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "UPDATE guardian_cycles SET status='expired' WHERE status='running' AND started<?",
                (time.time() - 1800,),
            )
            if self.conn.execute("SELECT 1 FROM guardian_cycles WHERE status='running'").fetchone():
                return False
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO guardian_cycles(slot,started,status,result_json) VALUES(?,?,'running',?)",
                (slot, time.time(), json.dumps({'owner_run_id': run_id}) if run_id else '{}'),
            )
            return cursor.rowcount == 1

    def finish(self, slot: str, result: dict[str, Any], state: dict[str, Any] | None = None, *,
               run_id: str | None = None, before_commit: Callable[[], None] | None = None,
               notice: dict[str, str] | None = None) -> None:
        if state is not None:
            check_guardian_account(state)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT status,result_json FROM guardian_cycles WHERE slot=?", (slot,)).fetchone()
            if row is None or row["status"] != "running":
                raise RuntimeError("守护轮次已过期或完成，拒绝重复记账")
            owner = json.loads(row["result_json"]).get("owner_run_id", "")
            if owner and owner != run_id:
                raise RuntimeError("交易员运行所有权不匹配，拒绝旧运行提交")
            if before_commit:
                before_commit()
            saved = self.conn.execute("SELECT result_json FROM guardian_cycles WHERE slot=?", (slot,)).fetchone()
            context = json.loads(saved[0]).get("decision_context") if saved else None
            if context is not None:
                result = {**result, "decision_context": context}
            cursor = self.conn.execute(
                "UPDATE guardian_cycles SET status=?,result_json=? WHERE slot=? AND status='running'",
                (result.get("status", "success"), json.dumps(result, ensure_ascii=False), slot),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("守护轮次已过期或完成，拒绝重复记账")
            if state is not None:
                previous = self.state()
                fills = result.get("fills", [])
                cash_delta = sum((f["gross_cents"] if f["side"] == "sell" else -f["gross_cents"]) - f["fees_cents"] for f in fills)
                if (state["cash_cents"] != previous["cash_cents"] + cash_delta
                        or state["realized_pnl_cents"] != previous["realized_pnl_cents"] + sum(f["realized_pnl_cents"] for f in fills)
                        or state["fees_cents"] != previous["fees_cents"] + sum(f["fees_cents"] for f in fills)):
                    raise ValueError("成交流水与账户资金变化不一致")
                quantities = {p["code"]: p["quantity"] for p in previous["positions"]}
                for fill in fills:
                    quantities[fill["code"]] = quantities.get(fill["code"], 0) + (fill["quantity"] if fill["side"] == "buy" else -fill["quantity"])
                if {code: q for code, q in quantities.items() if q} != {p["code"]: p["quantity"] for p in state["positions"]}:
                    raise ValueError("成交流水与持仓股数变化不一致")
                for index, fill in enumerate(result.get("fills", [])):
                    self.conn.execute("INSERT INTO guardian_trades VALUES(?,?,?,?,?)",
                                      (f"{slot}:{index:04d}", slot, fill["code"], fill["occurred_at"], json.dumps(fill, ensure_ascii=False)))
                self.conn.execute(
                    "INSERT INTO guardian_portfolio VALUES(1,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
                    (json.dumps(state, ensure_ascii=False),),
                )

            if notice:
                self.queue_notice(slot, notice["title"], notice["body"])
            if before_commit:
                before_commit()

    def notification(self, slot: str, receipt: dict[str, Any]) -> None:
        self.annotate(slot, {"notify": receipt})

    def annotate(self, slot: str, fields: dict[str, Any]) -> None:
        with self.conn:
            row = self.conn.execute("SELECT result_json FROM guardian_cycles WHERE slot=?", (slot,)).fetchone()
            payload = json.loads(row[0])
            payload.update(fields)
            self.conn.execute("UPDATE guardian_cycles SET result_json=? WHERE slot=?", (json.dumps(payload, ensure_ascii=False), slot))
