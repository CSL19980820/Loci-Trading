"""成交、账户事件、日盈亏与持仓投影。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    PalaceError,
    Position,
    _dumps,
    _now,
    normalize_code,
    normalize_date,
)


class TradeMixin:
    def _position_row(self, cursor: sqlite3.Cursor, code: str) -> sqlite3.Row | None:
        return cursor.execute("SELECT code, name, shares, cost, updated_on, note FROM holdings WHERE code = ?", (code,)).fetchone()

    def record_trade(
        self,
        *,
        action: str,
        code: str,
        shares: int,
        price: float,
        occurred_on: str | None = None,
        name: str = "",
        reason: str = "",
        source: str = "manual",
        correlation_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录开仓、买入或卖出，并按潜龙规则重算部分卖出的余票成本。"""
        code = normalize_code(code)
        action = action.upper()
        if action not in {"OPENING", "BUY", "SELL"}:
            raise PalaceError("动作必须为 OPENING、BUY 或 SELL")
        if shares <= 0:
            raise PalaceError("股数必须大于 0")
        if price < 0:
            raise PalaceError("成交价不能为负数")
        occurred_on = normalize_date(occurred_on)
        event_id = f"TX-{uuid4().hex[:12].upper()}"

        with self._transaction() as cursor:
            current = self._position_row(cursor, code)
            shares_before = int(current["shares"]) if current else 0
            cost_before = float(current["cost"]) if current else 0.0
            current_name = str(current["name"]) if current else ""
            effective_name = name.strip() or current_name or code
            self._upsert_stock(cursor, code, effective_name)

            realized_pnl = 0.0
            if action in {"OPENING", "BUY"}:
                if action == "OPENING" and current is not None:
                    raise PalaceError(f"{code} 已有仓位，不能重复导入开仓快照")
                shares_after = shares_before + shares
                cost_after = ((cost_before * shares_before) + (price * shares)) / shares_after
            else:
                if current is None or shares_before <= 0:
                    raise PalaceError(f"{code} 没有可卖出的仓位")
                if shares > shares_before:
                    raise PalaceError(f"卖出 {shares} 股超过当前持仓 {shares_before} 股")
                shares_after = shares_before - shares
                realized_pnl = (price - cost_before) * shares
                # 用户长期规则：部分卖出后，将已实现盈亏摊入余票成本。
                cost_after = ((cost_before * shares_before) - (price * shares)) / shares_after if shares_after else 0.0

            cost_after = round(cost_after, 6)
            realized_pnl = round(realized_pnl, 2)
            cursor.execute(
                """
                INSERT INTO position_events(
                    id, occurred_on, code, name, action, shares, price, shares_before, shares_after,
                    cost_before, cost_after, realized_pnl, reason, source, correlation_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, occurred_on, code, effective_name, action, shares, price, shares_before, shares_after,
                    cost_before, cost_after, realized_pnl, reason.strip(), source.strip() or "manual",
                    correlation_id.strip(), _dumps(metadata), _now(),
                ),
            )
            if shares_after:
                cursor.execute(
                    """
                    INSERT INTO holdings(code, name, shares, cost, updated_on, note) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET name = excluded.name, shares = excluded.shares,
                    cost = excluded.cost, updated_on = excluded.updated_on, note = excluded.note
                    """,
                    (code, effective_name, shares_after, cost_after, occurred_on, reason.strip()),
                )
            else:
                cursor.execute("DELETE FROM holdings WHERE code = ?", (code,))

        return {
            "id": event_id,
            "code": code,
            "name": effective_name,
            "action": action,
            "date": occurred_on,
            "shares_before": shares_before,
            "shares_after": shares_after,
            "cost_before": round(cost_before, 6),
            "cost_after": cost_after,
            "realized_pnl": realized_pnl,
        }

    def record_account_event(
        self,
        *,
        kind: str,
        amount: float,
        occurred_on: str | None = None,
        note: str = "",
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        kind = kind.upper()
        if kind not in {"CASHFLOW", "REALIZED_PNL_IMPORT"}:
            raise PalaceError("账户事件类型必须为 CASHFLOW 或 REALIZED_PNL_IMPORT")
        event_id = f"AC-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO account_events(id, occurred_on, kind, amount, note, source, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, normalize_date(occurred_on), kind, amount, note.strip(), source.strip() or "manual", _dumps(metadata), _now()),
            )
        return event_id

    def record_daily_pnl(
        self,
        *,
        broker_pnl: float,
        occurred_on: str | None = None,
        market_pnl: float | None = None,
        source: str = "market",
        note: str = "",
        legs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """写入/覆盖一日券商市值法当日盈亏（与 position_events 已实现分列）。

        口径：今日市值 + 今日卖出 − 昨日市值 − 今日买入；软件数优先入 broker_pnl。
        """
        day = normalize_date(occurred_on)
        market = float(market_pnl) if market_pnl is not None else float(broker_pnl)
        broker = float(broker_pnl)
        gap = round(broker - market, 4)
        now = _now()
        with self._transaction() as cursor:
            existing = cursor.execute(
                "SELECT created_at FROM daily_pnl_ledger WHERE occurred_on = ?",
                (day,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            cursor.execute(
                """
                INSERT INTO daily_pnl_ledger(
                    occurred_on, broker_pnl, market_pnl, gap, source, note,
                    legs_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurred_on) DO UPDATE SET
                    broker_pnl = excluded.broker_pnl,
                    market_pnl = excluded.market_pnl,
                    gap = excluded.gap,
                    source = excluded.source,
                    note = excluded.note,
                    legs_json = excluded.legs_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    day,
                    broker,
                    market,
                    gap,
                    (source or "market").strip() or "market",
                    note.strip(),
                    _dumps(legs or []),
                    _dumps(metadata or {}),
                    created_at,
                    now,
                ),
            )
        return {
            "date": day,
            "broker_pnl": broker,
            "market_pnl": market,
            "gap": gap,
            "source": (source or "market").strip() or "market",
            "note": note.strip(),
        }

    def list_daily_pnl(self, *, limit: int = 365) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 3650))
        rows = self.conn.execute(
            """
            SELECT occurred_on, broker_pnl, market_pnl, gap, source, note, legs_json, metadata_json, updated_at
            FROM daily_pnl_ledger
            ORDER BY occurred_on DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            legs = json.loads(str(row["legs_json"] or "[]"))
            meta = json.loads(str(row["metadata_json"] or "{}"))
            out.append(
                {
                    "date": str(row["occurred_on"]),
                    "broker_pnl": float(row["broker_pnl"]),
                    "market_pnl": None if row["market_pnl"] is None else float(row["market_pnl"]),
                    "gap": None if row["gap"] is None else float(row["gap"]),
                    "source": str(row["source"]),
                    "note": str(row["note"]),
                    "legs": legs if isinstance(legs, list) else [],
                    "metadata": meta if isinstance(meta, dict) else {},
                    "updated_at": str(row["updated_at"]),
                }
            )
        return out

    def daily_pnl_summary(self) -> dict[str, Any]:
        rows = self.list_daily_pnl(limit=3650)
        cumulative = round(sum(r["broker_pnl"] for r in rows), 4)
        latest = rows[0] if rows else None
        return {
            "cumulative_broker_pnl": cumulative,
            "days": len(rows),
            "latest": latest,
            "series": list(reversed(rows)),
        }

    def record_snapshot(
        self,
        *,
        total_assets: float,
        occurred_on: str | None = None,
        cash: float | None = None,
        note: str = "",
        source: str = "manual",
    ) -> str:
        if total_assets < 0:
            raise PalaceError("总资产不能为负数")
        if cash is not None and cash < 0:
            raise PalaceError("现金不能为负数")
        snapshot_id = f"AS-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO account_snapshots(id, occurred_on, total_assets, cash, note, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, normalize_date(occurred_on), total_assets, cash, note.strip(), source.strip() or "manual", _now()),
            )
        return snapshot_id

    def list_positions(self) -> list[Position]:
        rows = self.conn.execute("SELECT code, name, shares, cost, updated_on, note FROM holdings ORDER BY cost * shares DESC, code").fetchall()
        return [
            Position(str(row["code"]), str(row["name"]), int(row["shares"]), float(row["cost"]), str(row["updated_on"]), str(row["note"]))
            for row in rows
        ]

    def positions_payload(self) -> list[dict[str, Any]]:
        """返回前端消费的当前仓位投影；附带 T+1 可卖、今买与当前轮持仓天数。"""
        from datetime import date

        today = date.today().isoformat()
        out: list[dict[str, Any]] = []
        for position in self.list_positions():
            today_buy = int(
                self.conn.execute(
                    """
                    SELECT COALESCE(SUM(shares), 0) AS value FROM position_events
                    WHERE code = ? AND action IN ('BUY', 'OPENING') AND occurred_on = ?
                    """,
                    (position.code, today),
                ).fetchone()["value"]
                or 0
            )
            # 当前这轮持仓起点：清仓（shares_after=0）之后的首笔买入；从未清仓则取历史首买
            last_flat = self.conn.execute(
                """
                SELECT MAX(occurred_on) AS value FROM position_events
                WHERE code = ? AND shares_after = 0
                """,
                (position.code,),
            ).fetchone()["value"]
            if last_flat:
                first_open = self.conn.execute(
                    """
                    SELECT MIN(occurred_on) AS value FROM position_events
                    WHERE code = ? AND action IN ('BUY', 'OPENING') AND occurred_on > ?
                    """,
                    (position.code, str(last_flat)),
                ).fetchone()["value"]
            else:
                first_open = self.conn.execute(
                    """
                    SELECT MIN(occurred_on) AS value FROM position_events
                    WHERE code = ? AND action IN ('BUY', 'OPENING')
                    """,
                    (position.code,),
                ).fetchone()["value"]
            holding_days = 0
            if first_open:
                try:
                    holding_days = max(
                        0, (date.fromisoformat(today) - date.fromisoformat(str(first_open))).days
                    )
                except ValueError:
                    holding_days = 0
            available = max(0, int(position.shares) - today_buy)
            out.append(
                {
                    "code": position.code,
                    "name": position.name,
                    "shares": position.shares,
                    "available_shares": available,
                    "today_buy_shares": today_buy,
                    "cost": position.cost,
                    "cost_value": position.cost_value,
                    "updated_on": position.updated_on,
                    "opened_on": str(first_open) if first_open else position.updated_on,
                    "holding_days": holding_days,
                    "note": position.note,
                }
            )
        return out

    def realized_pnl(self, occurred_on: str | None = None, *, include_historical_baseline: bool = True) -> float:
        """汇总已实现盈亏；历史累计基线不得伪装成某一天的成交明细。"""
        params: list[str] = []
        where = ""
        if occurred_on:
            where = " WHERE occurred_on = ?"
            params.append(normalize_date(occurred_on))
        position_value = self.conn.execute(
            f"SELECT COALESCE(SUM(realized_pnl), 0) AS value FROM position_events{where}", params
        ).fetchone()["value"]
        account_where = " WHERE kind = 'REALIZED_PNL_IMPORT'"
        account_params = list(params)
        if not include_historical_baseline:
            account_where += " AND source <> 'qianlong-skill-memory'"
        if occurred_on:
            account_where += " AND occurred_on = ?"
        account_value = self.conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS value FROM account_events{account_where}", account_params
        ).fetchone()["value"]
        return round(float(position_value) + float(account_value), 2)

    def trades_payload(self, code: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """交割单视图：按时间倒序输出加减持与已实现盈亏。"""
        if limit <= 0 or limit > 10_000:
            raise PalaceError("limit 必须在 1-10000 之间")
        clauses: list[str] = []
        params: list[Any] = []
        if code:
            clauses.append("code = ?")
            params.append(normalize_code(code))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, created_at, code, name, action, shares, price,
                   shares_before, shares_after, cost_before, cost_after, realized_pnl,
                   reason, source, correlation_id
            FROM position_events
            {where}
            ORDER BY occurred_on DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "created_at": str(row["created_at"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "action": str(row["action"]),
                "shares": int(row["shares"]),
                "price": float(row["price"]),
                "amount": round(int(row["shares"]) * float(row["price"]), 2),
                "shares_before": int(row["shares_before"]),
                "shares_after": int(row["shares_after"]),
                "cost_before": float(row["cost_before"]),
                "cost_after": float(row["cost_after"]),
                "realized_pnl": float(row["realized_pnl"]),
                "reason": str(row["reason"]),
                "source": str(row["source"]),
                "correlation_id": str(row["correlation_id"]),
            }
            for row in rows
        ]
