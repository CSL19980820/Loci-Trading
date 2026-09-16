"""Durable tenant-local notification outbox; never re-executes a decision."""
from __future__ import annotations

import json
import time
from typing import Any

NOTICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS guardian_notices (
    slot TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    lease_until REAL NOT NULL DEFAULT 0, receipt_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_guardian_notices_status ON guardian_notices(status,lease_until);
"""


class GuardianNoticesMixin:
    def queue_notice(self, slot: str, title: str, body: str) -> None:
        # Called inside finish() so the outbox and ledger commit together.
        self.conn.execute("INSERT OR IGNORE INTO guardian_notices(slot,title,body) VALUES(?,?,?)",
                          (slot, title, body))

    def claim_notices(self, limit: int = 3) -> list[dict[str, Any]]:
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            rows = self.conn.execute(
                "SELECT * FROM guardian_notices WHERE status='pending' OR (status='sending' AND lease_until<=?) ORDER BY attempts,slot LIMIT ?",
                (time.time(), max(1, min(limit, 10)))).fetchall()
            claimed = []
            for row in rows:
                attempt = row["attempts"] + 1
                self.conn.execute("UPDATE guardian_notices SET status='sending',lease_until=?,attempts=? WHERE slot=?",
                                  (time.time() + 300, attempt, row["slot"]))
                claimed.append({**dict(row), "attempts": attempt})
            return claimed

    def record_notice_progress(self, slot: str, attempt: int, receipt: dict[str, Any]) -> bool:
        """Keep successful channel receipts durable without releasing the active lease."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE guardian_notices SET receipt_json=?,lease_until=? "
                "WHERE slot=? AND status='sending' AND attempts=? AND lease_until>?",
                (json.dumps(receipt, ensure_ascii=False), time.time() + 300, slot, attempt, time.time()))
            return cursor.rowcount == 1

    def finish_notice(self, slot: str, attempt: int, receipt: dict[str, Any]) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE guardian_notices SET status=?,lease_until=0,receipt_json=? "
                "WHERE slot=? AND status='sending' AND attempts=? AND lease_until>?",
                ("sent" if receipt.get("success") else "pending",
                 json.dumps(receipt, ensure_ascii=False), slot, attempt, time.time()))
            if cursor.rowcount != 1:
                return False
            row = self.conn.execute("SELECT result_json FROM guardian_cycles WHERE slot=?", (slot,)).fetchone()
            if row:
                result = json.loads(row[0])
                result["notify"] = receipt
                self.conn.execute("UPDATE guardian_cycles SET result_json=? WHERE slot=?",
                                  (json.dumps(result, ensure_ascii=False), slot))
            return True

    def notice_backlog(self) -> dict[str, Any]:
        rows = self.conn.execute("SELECT status,count(*) AS n,min(slot) AS oldest FROM guardian_notices "
                                 "WHERE status != 'sent' GROUP BY status").fetchall()
        counts = {row["status"]: row["n"] for row in rows}
        return {"pending": counts.get("pending", 0), "sending": counts.get("sending", 0),
                "total": sum(counts.values()), "oldest_slot": min((row["oldest"] for row in rows), default=None)}
