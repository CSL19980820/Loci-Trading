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

    def trade_page(self, *, start: str, end: str, limit: int, offset: int) -> dict[str, Any]:
        bounds = (start, _next_day(end))
        rows = self.conn.execute("""
            SELECT id,slot,detail_json FROM guardian_trades
            WHERE occurred_at>=? AND occurred_at<?
            ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?
        """, (*bounds, limit, offset)).fetchall()
        total = self.conn.execute(
            "SELECT count(*) FROM guardian_trades WHERE occurred_at>=? AND occurred_at<?", bounds
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
