"""交易员报告与带租约的幂等生成；报告不产生买卖。"""
import json
import time
import uuid
from datetime import datetime
from typing import Any

REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_reports (
    report_key TEXT PRIMARY KEY, period TEXT NOT NULL, trade_date TEXT NOT NULL,
    status TEXT NOT NULL, token TEXT NOT NULL, started REAL NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_guardian_reports_date ON guardian_reports(trade_date DESC, period);
CREATE TABLE IF NOT EXISTS guardian_report_revisions (
    report_key TEXT NOT NULL, revision INTEGER NOT NULL, reason TEXT NOT NULL,
    archived_at REAL NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(report_key,revision)
);
"""


class GuardianReportsMixin:
    def reopen_report(self, period: str, day: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("更正报告必须说明原因")
        key = f"{period}:{day}"
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT status,result_json FROM guardian_reports WHERE report_key=?", (key,)).fetchone()
            if not row or row["status"] != "success":
                raise ValueError("只能更正已完成报告")
            old = json.loads(row["result_json"])
            revision = int(old.get("revision", 1))
            self.conn.execute("INSERT INTO guardian_report_revisions VALUES(?,?,?,?,?)", (key, revision, reason, time.time(), row["result_json"]))
            pending = {"status": "failed", "error": "等待更正生成", "correction_reason": reason, "next_revision": revision + 1}
            self.conn.execute("UPDATE guardian_reports SET status='failed',token='',started=0,result_json=? WHERE report_key=?", (json.dumps(pending, ensure_ascii=False), key))

    def report(self, period: str, day: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM guardian_reports WHERE report_key=?", (f"{period}:{day}",)).fetchone()
        return self._report_row(row) if row else None

    @staticmethod
    def _report_row(row: Any) -> dict[str, Any]:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json"))
        data.pop("token", None)
        return data

    def reports(self, limit: int = 30) -> list[dict[str, Any]]:
        return [self._report_row(r) for r in self.conn.execute(
            "SELECT * FROM guardian_reports ORDER BY trade_date DESC,started DESC LIMIT ?", (limit,))]

    def claim_report(self, period: str, day: str) -> str | None:
        key = f"{period}:{day}"
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            old = self.conn.execute("SELECT status,started FROM guardian_reports WHERE report_key=?", (key,)).fetchone()
            if old and (old["status"] == "success" or (old["status"] == "running" and old["started"] > time.time() - 1800)):
                return None
            token = uuid.uuid4().hex
            self.conn.execute("INSERT INTO guardian_reports VALUES(?,?,?,?,?,?,?) ON CONFLICT(report_key) DO UPDATE SET status=excluded.status,token=excluded.token,started=excluded.started",
                              (key, period, day, "running", token, time.time(), "{}"))
            return token

    def finish_report(self, period: str, day: str, token: str, result: dict[str, Any]) -> None:
        with self.conn:
            cursor = self.conn.execute("UPDATE guardian_reports SET status=?,result_json=? WHERE report_key=? AND token=? AND status='running'",
                (result["status"], json.dumps(result, ensure_ascii=False), f"{period}:{day}", token))
            if cursor.rowcount != 1:
                raise RuntimeError("报告租约已过期，拒绝覆盖或重复完成")

    def report_notification(self, period: str, day: str, receipt: dict[str, Any], *, pending: bool = False) -> None:
        with self.conn:
            row = self.conn.execute("SELECT result_json FROM guardian_reports WHERE report_key=?", (f"{period}:{day}",)).fetchone()
            result = json.loads(row[0])
            result["notify"] = receipt
            if pending:
                result['_notify_started'] = time.time()
            else:
                result.pop("_notify_started", None)
            self.conn.execute("UPDATE guardian_reports SET result_json=? WHERE report_key=?", (json.dumps(result, ensure_ascii=False), f"{period}:{day}"))

    def claim_report_notification(self, period: str, day: str) -> bool:
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT status,result_json FROM guardian_reports WHERE report_key=?", (f"{period}:{day}",)).fetchone()
            if not row or row["status"] != "success":
                return False
            result = json.loads(row["result_json"])
            if (result.get("notify") or {}).get("success") or result.get("_notify_started", 0) > time.time() - 300:
                return False
            result["_notify_started"] = time.time()
            self.conn.execute("UPDATE guardian_reports SET result_json=? WHERE report_key=?", (json.dumps(result, ensure_ascii=False), f"{period}:{day}"))
            return True

    def apply_close_valuation(self, snapshot: dict[str, Any], day: str) -> bool:
        from src.ledger.domain.guardian_account import mark_guardian_account
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.state()
            if self.conn.execute("SELECT 1 FROM guardian_trades WHERE substr(occurred_at,1,10)>? LIMIT 1", (day,)).fetchone():
                return False
            if current["cash_cents"] != snapshot["cash_cents"] or {
                p["code"]: (p["quantity"], p["cost_cents"]) for p in current["positions"]
            } != {p["code"]: (p["quantity"], p["cost_cents"]) for p in snapshot["positions"]}:
                return False
            quotes = {p["code"]: {"price": p["mark_price_cents"] / 100, "trade_date": day, "trade_time": "15:00:00", "source": p["mark_source"]} for p in snapshot["positions"]}
            marked = mark_guardian_account(current, quotes, datetime.fromisoformat(snapshot["valuation_at"]))
            marked.update(valuation_kind="official_close", valuation_date=day)
            marked["closing_sources"] = snapshot.get("closing_sources", [])
            self.conn.execute("UPDATE guardian_portfolio SET state_json=? WHERE id=1", (json.dumps(marked, ensure_ascii=False),))
            return True

    def all_trades(self, end: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT id,detail_json FROM guardian_trades WHERE substr(occurred_at,1,10)<=? ORDER BY occurred_at,id", (end,)).fetchall()
        return [{**json.loads(r["detail_json"]), "id": r["id"]} for r in rows]

    def cycles_between(self, start: str, end: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT slot,status,result_json FROM guardian_cycles WHERE substr(slot,1,10) BETWEEN ? AND ? ORDER BY started", (start, end)).fetchall()
        return [{"slot": r["slot"], "status": r["status"], "result": json.loads(r["result_json"])} for r in rows]
