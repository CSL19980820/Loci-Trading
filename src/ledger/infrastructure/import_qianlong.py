"""潜龙 state.json 导入。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ledger.infrastructure.store_types import (
    PalaceError,
    _dumps,
    normalize_code,
    normalize_date,
)


class ImportQianlongMixin:
    @staticmethod
    def _qianlong_holdings_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        holdings: list[dict[str, Any]] = []
        for item in payload.get("holdings") or []:
            if not isinstance(item, dict):
                continue
            shares = int(item.get("shares") or 0)
            cost = float(item.get("cost") or 0)
            if shares <= 0 or cost < 0:
                continue
            code = normalize_code(str(item.get("code") or ""))
            holdings.append(
                {
                    "code": code,
                    "name": str(item.get("name") or code),
                    "shares": shares,
                    "cost": cost,
                    "note": str(item.get("note") or ""),
                    "layers": item.get("layers"),
                    "buy_date": item.get("buyDate"),
                }
            )
        return holdings

    def preview_qianlong_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """预览潜龙 ``state.json`` 导入结果，不写入账本。"""
        if not isinstance(payload, dict):
            raise PalaceError("潜龙 state.json 必须是 JSON 对象")
        has_events = bool(self.conn.execute("SELECT COUNT(*) AS value FROM position_events").fetchone()["value"])
        block_reason = "账本已有仓位事件；为避免重复导入，请使用新的数据库文件" if has_events else ""
        imported_on = normalize_date(str(payload.get("updatedAt") or ""))
        holdings = self._qianlong_holdings_from_payload(payload)
        assets = payload.get("totalAssets")
        return {
            "can_import": not has_events,
            "block_reason": block_reason,
            "date": imported_on,
            "holdings_count": len(holdings),
            "holdings": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "shares": item["shares"],
                    "cost": item["cost"],
                    "note": item["note"],
                }
                for item in holdings[:50]
            ],
            "realized_pnl_baseline": float(payload.get("realizedPnlCumulative") or 0),
            "total_assets": float(assets) if assets is not None else None,
        }

    def import_qianlong_payload(
        self,
        payload: dict[str, Any],
        *,
        source: str = "qianlong-skill-memory",
        source_label: str = "qianlong-skill-memory",
    ) -> dict[str, Any]:
        """从已解析的潜龙 state 对象导入起始快照。"""
        if not isinstance(payload, dict):
            raise PalaceError("潜龙 state.json 必须是 JSON 对象")
        with self._transaction():
            if self.conn.execute("SELECT COUNT(*) AS value FROM position_events").fetchone()["value"]:
                raise PalaceError("账本已有仓位事件；为避免重复导入，请使用新的数据库文件")

            imported_on = normalize_date(str(payload.get("updatedAt") or ""))
            imported: list[str] = []
            for item in self._qianlong_holdings_from_payload(payload):
                result = self.record_trade(
                    action="OPENING",
                    code=item["code"],
                    name=item["name"],
                    shares=item["shares"],
                    price=item["cost"],
                    occurred_on=imported_on,
                    reason=item["note"] or "潜龙技能记忆导入",
                    source=source,
                    metadata={
                        "imported_from": source_label,
                        "legacy_layers": item.get("layers"),
                        "buy_date": item.get("buy_date"),
                    },
                )
                imported.append(result["id"])

            realized = float(payload.get("realizedPnlCumulative") or 0)
            if realized:
                self.record_account_event(
                    kind="REALIZED_PNL_IMPORT",
                    amount=realized,
                    occurred_on=imported_on,
                    note="从潜龙技能记忆导入的累计已实现盈亏基线",
                    source=source,
                    metadata={"imported_from": source_label},
                )
            assets = payload.get("totalAssets")
            if assets is not None:
                self.record_snapshot(
                    total_assets=float(assets),
                    occurred_on=imported_on,
                    note=str(payload.get("totalAssetsNote") or "从潜龙技能记忆导入"),
                    source=source,
                )
            self._set_meta(
                "qianlong_state_import",
                _dumps({"path": source_label, "date": imported_on, "events": imported}),
            )
            return {
                "date": imported_on,
                "position_events": imported,
                "realized_pnl_baseline": realized,
                "total_assets": assets,
            }

    def import_qianlong_state(self, state_path: Path | str, source: str = "qianlong-skill-memory") -> dict[str, Any]:
        """从潜龙技能的 ``state.json`` 导入一个可审计的起始快照。

        导入只允许在空仓位账本执行，防止把同一份记忆重复计入交易历史；历史已实现盈亏
        作为 ``REALIZED_PNL_IMPORT`` 基线，不会冒充项目内发生的卖出事件。
        """
        path = Path(state_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PalaceError(f"无法读取潜龙 state.json：{path}") from exc
        return self.import_qianlong_payload(payload, source=source, source_label=str(path))
