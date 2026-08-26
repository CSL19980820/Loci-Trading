"""ops.db 龙头角色留痕：只追加的角色观测事实。

为什么单开一张表：`market.db.intel_snapshots` 是按 ``(交易日, 工具)`` 覆盖写的
缓存，同一天盘中反复扫描只会留下最后一次，角色演进（谁从龙头掉成走弱）会被
静默抹掉。这里一次扫描追加一批，永不覆盖；整表可删可重建。

这里**只存事实**。存活天数、转移矩阵、预警提前量都能从事实推出来，
按仓规不入库——推导在 `application/skill_watch/role_stats.py` 即时算。
"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import dumps, loads, new_id


class OpsWatchMixin:
    def record_leader_roles(
        self,
        slug: str,
        *,
        trade_date: str,
        observed_at: str,
        gate_state: str,
        entries: list[dict[str, Any]],
    ) -> int:
        """追加一批角色观测；返回写入行数。"""
        rows = [row for row in entries if isinstance(row, dict) and row.get("code")]
        if not rows:
            return 0
        now = self._now()  # type: ignore[attr-defined]
        payload = [
            (
                new_id("LRS"),
                slug,
                trade_date,
                observed_at,
                str(row.get("code")),
                str(row.get("name") or ""),
                str(row.get("role") or ""),
                str(row.get("role_basis") or ""),
                str(row.get("theme_code") or ""),
                str(row.get("theme_name") or ""),
                gate_state,
                dumps(
                    {
                        key: row.get(key)
                        for key in (
                            "ladder_level",
                            "gain_20_pct",
                            "drawdown_pct",
                            "pullback_depth_pct",
                            "pullback_days",
                            "pullback_days_recent",
                            "pullback_drawdown_pct",
                            "close",
                            "ma10",
                            "ma20",
                            "strong_days",
                            "today_pct",
                            "vol_ratio",
                            "vol_shrink",
                        )
                        if row.get(key) is not None
                    }
                ),
                now,
            )
            for row in rows
        ]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.executemany(
                """
                INSERT INTO leader_role_snapshots(
                    id, slug, trade_date, observed_at, code, name, role, role_basis,
                    theme_code, theme_name, gate_state, metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        return len(payload)

    def list_leader_roles(
        self,
        slug: str,
        *,
        code: str = "",
        trade_date: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM leader_role_snapshots WHERE slug = ?"
        params: list[Any] = [slug]
        if code:
            sql += " AND code = ?"
            params.append(code)
        if trade_date:
            sql += " AND trade_date = ?"
            params.append(trade_date)
        sql += " ORDER BY observed_at DESC, code LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        rows = self.conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
        return [self._leader_role_row(row) for row in rows]

    def record_second_wave_signals(
        self,
        *,
        trade_date: str,
        observed_at: str,
        breadth_pct: float | None,
        gate_pass: bool,
        min_strength: int,
        rows: list[dict[str, Any]],
        slug: str = "",
    ) -> int:
        """只追加写入二波触发留痕。

        **未达强度线、未过宽度闸的触发也要写**：观察期要回答「强度高的后续是不是
        真的更好」，只留最终提醒等于把反例扔掉，那个问题就永远验不了。
        `alerted` 标记它当时有没有真的推给用户。
        """
        if not rows:
            return 0
        now = observed_at
        payload = [
            (
                new_id("sw"),
                slug,
                trade_date,
                observed_at,
                str(row.get("code") or ""),
                str(row.get("name") or ""),
                int(row.get("strength") or 0),
                1 if (gate_pass and int(row.get("strength") or 0) >= min_strength) else 0,
                breadth_pct,
                1 if gate_pass else 0,
                row.get("price"),
                row.get("day_low"),
                row.get("ma_now"),
                int(row.get("ma_window") or 0),
                row.get("days_since_peak"),
                row.get("drawdown_pct"),
                row.get("pct20_now"),
                row.get("chip_width_pct"),
                str(row.get("entry_day") or ""),
                dumps(list(row.get("tags") or [])),
                now,
            )
            for row in rows
            if row.get("code")
        ]
        if not payload:
            return 0
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.executemany(
                """
                INSERT INTO second_wave_signals(
                    id, slug, trade_date, observed_at, code, name, strength, alerted,
                    breadth_pct, gate_pass, price, day_low, ma_now, ma_window,
                    days_since_peak, drawdown_pct, pct20_now, chip_width_pct,
                    entry_day, tags_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        return len(payload)

    def list_second_wave_signals(
        self, *, trade_date: str = "", code: str = "", limit: int = 200
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM second_wave_signals WHERE 1=1"
        params: list[Any] = []
        if trade_date:
            sql += " AND trade_date = ?"
            params.append(trade_date)
        if code:
            sql += " AND code = ?"
            params.append(code)
        sql += " ORDER BY observed_at DESC, strength DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        rows = self.conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["tags"] = loads(item.pop("tags_json", "[]") or "[]")
            item["alerted"] = bool(item.get("alerted"))
            item["gate_pass"] = bool(item.get("gate_pass"))
            out.append(item)
        return out

    def prune_second_wave(self, *, before_date: str) -> int:
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "DELETE FROM second_wave_signals WHERE trade_date < ?", (before_date,)
            )
            return int(cursor.rowcount or 0)

    def prune_leader_roles(self, *, before_date: str) -> int:
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "DELETE FROM leader_role_snapshots WHERE trade_date < ?", (before_date,)
            )
            return int(cursor.rowcount or 0)

    @staticmethod
    def _leader_role_row(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "trade_date": row["trade_date"],
            "observed_at": row["observed_at"],
            "code": row["code"],
            "name": row["name"],
            "role": row["role"],
            "role_basis": row["role_basis"],
            "theme_code": row["theme_code"],
            "theme_name": row["theme_name"],
            "gate_state": row["gate_state"],
            "metrics": loads(row["metrics_json"]) or {},
            "created_at": row["created_at"],
        }
