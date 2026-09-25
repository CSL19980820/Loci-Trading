"""交易员报告与带租约的幂等生成；报告不产生买卖。"""
import json
import secrets
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

    def report_share_token(self, period: str, day: str, created_at: str) -> str:
        """随机地址只绑定当前报告版本；更正后的新结果自然获得新地址。"""
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT status,result_json FROM guardian_reports WHERE report_key=?", (f"{period}:{day}",)).fetchone()
            if not row or row["status"] != "success":
                raise ValueError("只有已完成的报告可以分享")
            result = json.loads(row["result_json"])
            if result.get("created_at", "") != created_at:
                raise ValueError("报告已更新，请重新读取后分享")
            token = result.get("share_token")
            if not token:
                token = secrets.token_urlsafe(32)
                result["share_token"] = token
                self.conn.execute("UPDATE guardian_reports SET result_json=? WHERE report_key=?", (json.dumps(result, ensure_ascii=False), f"{period}:{day}"))
            return token

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

    def save_report_checkpoint(self, period: str, day: str, token: str, checkpoint: dict) -> None:
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.conn.execute("SELECT result_json FROM guardian_reports WHERE report_key=? AND token=? AND status='running'",
                                    (f'{period}:{day}', token)).fetchone()
            if row is None:
                raise RuntimeError('报告租约已过期，拒绝保存研究阶段')
            result = json.loads(row[0])
            result['_research_checkpoint'] = checkpoint
            self.conn.execute('UPDATE guardian_reports SET result_json=? WHERE report_key=? AND token=?',
                              (json.dumps(result, ensure_ascii=False), f'{period}:{day}', token))

    def finish_report(self, period: str, day: str, token: str, result: dict[str, Any]) -> None:
        with self.conn:
            if result['status'] == 'success' and int(result.get('revision', 1)) > 1:
                key = f'{period}:{day}'
                pending = self.conn.execute(
                    "SELECT result_json FROM guardian_reports WHERE report_key=? AND token=? AND status='running'",
                    (key, token)).fetchone()
                saved = json.loads(pending[0]) if pending else {}
                revision = int(result['revision'])
                archived = self.conn.execute(
                    'SELECT 1 FROM guardian_report_revisions WHERE report_key=? AND revision=?',
                    (key, revision - 1)).fetchone()
                reason = result.get('facts', {}).get('correction_reason')
                if (not archived or saved.get('next_revision') != revision
                        or not reason or reason != saved.get('correction_reason')):
                    raise ValueError('更正报告缺少已归档前版或更正租约，拒绝跳过观察动作')
            if result['status'] != 'success':
                row = self.conn.execute('SELECT result_json FROM guardian_reports WHERE report_key=? AND token=?',
                                        (f'{period}:{day}', token)).fetchone()
                saved = json.loads(row[0]) if row else {}
                if '_research_checkpoint' in saved:
                    result = {**result, '_research_checkpoint': saved['_research_checkpoint']}
            cursor = self.conn.execute("UPDATE guardian_reports SET status=?,result_json=? WHERE report_key=? AND token=? AND status='running'",
                (result["status"], json.dumps(result, ensure_ascii=False), f"{period}:{day}", token))
            if cursor.rowcount != 1:
                raise RuntimeError("报告租约已过期，拒绝覆盖或重复完成")
            if result['status'] == 'success':
                updates = (result.get('analysis') or {}).get('watchlist_updates', [])
                if len({u['code'] for u in updates}) != len(updates):
                    raise ValueError('同一股票只能有一个观察名单决定')
                # A correction revises the historical document and experience; it must not
                # replay old watch/unwatch decisions against today's live watchlist.
                if updates and int(result.get('revision', 1)) == 1:
                    state = self.state()
                    from src.ledger.domain.guardian_watchlist import update_watchlist
                    names = result.get('facts', {}).get('stock_names', {})
                    for update in updates:
                        update_watchlist(state, update, result['created_at'], name=names.get(update['code'], ''),
                                         source=f'{period}:{day}')
                    self.conn.execute('UPDATE guardian_portfolio SET state_json=? WHERE id=1',
                                      (json.dumps(state, ensure_ascii=False),))
            items = (result.get('analysis') or {}).get('experience')
            if result['status'] == 'success' and period in {'daily', 'weekly'} and items is not None:
                self._save_experience(items, source_report=f'{period}:{day}',
                    source_revision=result.get('revision', 1), day=day,
                    expected_revision=result['facts']['experience']['revision'])

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
