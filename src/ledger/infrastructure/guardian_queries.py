"""Bounded UI read models. Agent/audit methods retain their complete history."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any


_RUN_FIELDS = (
    "body", "analysis", "analysis_only", "outcome", "deferred", "decisions", "fills",
    "rejects", "error", "model", "observed", "as_of",
)


def _receipt(value: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value[key] for key in ("success", "skipped") if value and key in value}


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


class GuardianQueriesMixin:
    def activity_feed(self, limit: int = 16) -> dict[str, Any]:
        """Latest research across all stages, ordered by generation time, not report date.

        Select the bounded metadata first; never deserialize decision contexts or
        return report lease/share tokens to the home page.
        """
        if not 1 <= limit <= 50:
            raise ValueError("研判条数须在1至50之间")
        rows = self.conn.execute("""
            WITH latest AS (
                SELECT * FROM (
                    SELECT 'run' AS kind, slot AS item_key, started FROM guardian_cycles
                    UNION ALL
                    SELECT 'report', report_key, started FROM guardian_reports
                ) ORDER BY started DESC, kind, item_key DESC LIMIT ?
            ), selected AS (
                SELECT f.*, COALESCE(c.status,r.status) AS status, r.period,r.trade_date,
                    CASE WHEN f.kind='run' THEN c.result_json ELSE r.result_json END AS payload
                FROM latest f
                LEFT JOIN guardian_cycles c ON f.kind='run' AND c.slot=f.item_key
                LEFT JOIN guardian_reports r ON f.kind='report' AND r.report_key=f.item_key
            ), safe AS (
                SELECT *, CASE WHEN json_valid(payload) THEN payload ELSE '{}' END AS doc
                FROM selected
            )
            SELECT kind,item_key,started,status,period,trade_date,
                substr(COALESCE(
                    NULLIF(json_extract(doc,'$.analysis.summary'),''),
                    CASE WHEN json_type(doc,'$.analysis')='text'
                         THEN NULLIF(json_extract(doc,'$.analysis'),'') END,
                    NULLIF(json_extract(doc,'$.summary'),''),
                    json_extract(doc,'$.body'),''),1,12000) AS summary,
                substr(json_extract(doc,'$.error'),1,2000) AS error,
                json_extract(doc,'$.created_at') AS created_at,
                json_extract(doc,'$.as_of') AS as_of
            FROM safe ORDER BY started DESC,kind,item_key DESC
        """, (limit,)).fetchall()
        runs, reports = [], []
        for row in rows:
            if row['kind'] == 'run':
                runs.append({'slot': row['item_key'], 'started': row['started'],
                             'status': row['status'], 'result': {
                                 'analysis': row['summary'], 'error': row['error'],
                                 'as_of': row['as_of']}})
            else:
                reports.append({'report_key': row['item_key'], 'started': row['started'],
                                'period': row['period'], 'trade_date': row['trade_date'],
                                'status': row['status'], 'summary': row['summary'],
                                'error': row['error'], 'created_at': row['created_at']})
        return {'runs': runs, 'reports': reports, 'limit': limit}

    def latest_cycle_summary(self) -> list[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT slot,status FROM guardian_cycles ORDER BY started DESC LIMIT 1"
        ).fetchone()
        return [{**dict(row), "result": {}}] if row else []

    def cycle_page(self, *, start: str, end: str, limit: int, offset: int) -> dict[str, Any]:
        # Page BEFORE projecting JSON; never deserialize the historical decision context.
        bounds = (start, _next_day(end))
        rows = self.conn.execute("""
            SELECT slot,status,started,
                json_extract(result_json,'$.outcome') AS outcome,
                json_extract(result_json,'$.notify.success') AS notify_success,
                json_extract(result_json,'$.notify.skipped') AS notify_skipped
            FROM (SELECT slot,status,started,result_json FROM guardian_cycles
                  WHERE slot>=? AND slot<? ORDER BY slot DESC LIMIT ? OFFSET ?)
            ORDER BY slot DESC
        """, (*bounds, limit, offset)).fetchall()
        items = [{"slot": r["slot"], "status": r["status"], "started": r["started"],
                  "result": {"outcome": r["outcome"], "notify": {
                      "success": r["notify_success"], "skipped": r["notify_skipped"]}}}
                 for r in rows]
        total = self.conn.execute(
            "SELECT count(*) FROM guardian_cycles WHERE slot>=? AND slot<?", bounds
        ).fetchone()[0]
        return {"items": items, "total": total}

    def cycle_detail(self, slot: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT slot,status,result_json FROM guardian_cycles WHERE slot=?", (slot,)
        ).fetchone()
        if row is None:
            return None
        original = json.loads(row["result_json"])
        result = {key: original[key] for key in _RUN_FIELDS if key in original}
        before = (original.get('decision_context') or {}).get('account_before') or {}
        result['stock_names'] = {
            item['code']: item['name']
            for item in [*(original.get('candidates') or []), *(original.get('fills') or []),
                         *(before.get('watchlist') or []), *(before.get('positions') or [])]
            if item.get('code') and item.get('name') and item['name'] != item['code']
        }
        if "notify" in original:
            result["notify"] = _receipt(original["notify"])
        return {"slot": row["slot"], "status": row["status"], "result": result}

    def report_page(self, *, start: str, end: str, limit: int, offset: int) -> dict[str, Any]:
        rows = self.conn.execute("""
            SELECT report_key,period,trade_date,status,started,
                json_extract(result_json,'$.analysis.summary') AS summary,
                json_extract(result_json,'$.error') AS error,
                json_extract(result_json,'$.created_at') AS created_at,
                json_extract(result_json,'$.notify.success') AS notify_success,
                json_extract(result_json,'$.notify.skipped') AS notify_skipped
            FROM (SELECT report_key,period,trade_date,status,started,result_json
                  FROM guardian_reports WHERE trade_date BETWEEN ? AND ?
                  ORDER BY trade_date DESC,started DESC,report_key DESC LIMIT ? OFFSET ?)
            ORDER BY trade_date DESC,started DESC,report_key DESC
        """, (start, end, limit, offset)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["notify"] = {"success": item.pop("notify_success"), "skipped": item.pop("notify_skipped")}
            items.append(item)
        total = self.conn.execute(
            "SELECT count(*) FROM guardian_reports WHERE trade_date BETWEEN ? AND ?", (start, end)
        ).fetchone()[0]
        return {"items": items, "total": total}

    def trade_page(self, *, start: str, end: str, limit: int, offset: int, keyword: str = "") -> dict[str, Any]:
        # Count and page share a literal substring filter; user input is never SQL.
        where = "occurred_at>=? AND occurred_at<?"
        params: list[Any] = [start, _next_day(end)]
        term = keyword.strip()
        if term:
            where += " AND (instr(lower(code),lower(?))>0 OR instr(lower(coalesce(json_extract(detail_json,'$.name'),'')),lower(?))>0)"
            params.extend((term, term))
        rows = self.conn.execute(f"""
            SELECT id,slot,detail_json FROM guardian_trades
            WHERE {where}
            ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?
        """, (*params, limit, offset)).fetchall()
        total = self.conn.execute(
            f"SELECT count(*) FROM guardian_trades WHERE {where}", params
        ).fetchone()[0]
        return {"items": [{**json.loads(r["detail_json"]), "id": r["id"], "slot": r["slot"]} for r in rows],
                "total": total}

    def performance_page(self, *, limit: int, offset: int) -> dict[str, Any]:
        # Cumulative P&L must still aggregate the complete ledger, only when this tab is opened.
        rows = self.conn.execute("""SELECT code,
            max(json_extract(detail_json,'$.name')) AS name,
            sum(CASE WHEN json_extract(detail_json,'$.side')='buy' THEN json_extract(detail_json,'$.quantity') ELSE 0 END) AS bought_quantity,
            sum(CASE WHEN json_extract(detail_json,'$.side')='sell' THEN json_extract(detail_json,'$.quantity') ELSE 0 END) AS sold_quantity,
            sum(json_extract(detail_json,'$.realized_pnl_cents')) AS realized_pnl_cents,
            sum(json_extract(detail_json,'$.fees_cents')) AS fees_cents,
            count(*) AS trade_count FROM guardian_trades GROUP BY code ORDER BY code LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        total = self.conn.execute("SELECT count(DISTINCT code) FROM guardian_trades").fetchone()[0]
        return {"items": [dict(row) for row in rows], "total": total}
