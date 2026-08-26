"""悟道 MCP 日配额表读写（ops.db · mcp_quota）。"""
from __future__ import annotations

from typing import Any


class OpsQuotaMixin:
    """mcp_quota 计数；DDL 权威在 store_schema。"""

    conn: Any

    def read_mcp_quota_counts(self, trade_date: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT pool, call_count FROM mcp_quota WHERE trade_date = ?",
            (trade_date,),
        ).fetchall()
        out = {"structured": 0, "skill": 0}
        for pool, count in rows:
            if pool in out:
                out[str(pool)] = int(count or 0)
        return out

    def increment_mcp_quota_call(
        self,
        *,
        trade_date: str,
        pool: str,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO mcp_quota(trade_date, pool, call_count, updated_at)
            VALUES(?, ?, 1, ?)
            ON CONFLICT(trade_date, pool) DO UPDATE SET
                call_count = call_count + 1,
                updated_at = excluded.updated_at
            """,
            (trade_date, pool, updated_at),
        )
        self.conn.commit()
