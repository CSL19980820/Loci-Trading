"""持仓周期跟踪。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    _now,
    normalize_code,
    normalize_date,
)


class TrackingMixin:
    def open_tracking(
        self,
        *,
        strategy_tag: str,
        pool_id: str,
        code: str,
        name: str,
        tier: str = "core",
        signal_date: str,
        entry_date: str,
        hold_days: int = 3,
        exit_by_date: str,
        entry_price: float | None = None,
    ) -> str:
        """开启一条持仓跟踪记录。"""
        code = normalize_code(code)
        tracking_id = f"PT-{uuid4().hex[:12].upper()}"
        now = _now()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO position_tracking(
                    id, strategy_tag, pool_id, code, name, tier,
                    signal_date, entry_date, hold_days, exit_by_date,
                    entry_price, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    tracking_id,
                    strategy_tag.strip(),
                    pool_id.strip(),
                    code,
                    name.strip() or code,
                    tier.strip() or "core",
                    normalize_date(signal_date),
                    normalize_date(entry_date),
                    int(hold_days),
                    normalize_date(exit_by_date),
                    entry_price,
                    now,
                    now,
                ),
            )
        return tracking_id

    def close_tracking(
        self,
        tracking_id: str,
        *,
        exit_price: float | None = None,
        actual_return: float | None = None,
        reason: str = "expired",
    ) -> None:
        """关闭一条跟踪记录（到期、止损、止盈）。"""
        closed_status = "expired" if reason == "expired" else "closed"
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE position_tracking
                SET status = ?, exit_price = ?, actual_return = ?,
                    closed_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (closed_status, exit_price, actual_return, reason.strip(), _now(), tracking_id),
            )

    def list_active_tracking(self, strategy_tag: str | None = None) -> list[dict]:
        """列出所有活跃跟踪（用于每日更新价格）。"""
        if strategy_tag:
            rows = self.conn.execute(
                "SELECT * FROM position_tracking WHERE status = 'active' AND strategy_tag = ?"
                " ORDER BY signal_date DESC",
                (strategy_tag,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM position_tracking WHERE status = 'active'"
                " ORDER BY signal_date DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def tracking_summary(self, strategy_tag: str, limit: int = 100) -> list[dict]:
        """已关闭的跟踪汇总，按 signal_date 降序。"""
        rows = self.conn.execute(
            "SELECT * FROM position_tracking"
            " WHERE strategy_tag = ? AND status != 'active'"
            " ORDER BY signal_date DESC LIMIT ?",
            (strategy_tag, limit),
        ).fetchall()
        return [dict(row) for row in rows]
