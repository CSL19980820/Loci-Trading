"""盘口情报缓存薄封装。

只读写已经存在的 ``market.db.intel_snapshots``；不在 tape 层新增表或第二套
缓存协议。缓存是可重建的，写入失败由调用方按 provider 不可用处理。
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from src.market.domain.tape import TapeProvenance, TapeRequest, TapeResult

_UTC = timezone.utc


def _trade_date(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(value or "").strip()[:10]


def _declared_trade_date(payload: Mapping[str, Any]) -> str:
    """读取缓存载荷声明的交易日；无声明时交给表 key 约束。"""
    candidates: list[Mapping[str, Any]] = [payload]
    for mapping in tuple(candidates):
        for key in ("structured", "structuredContent", "data", "result", "meta"):
            nested = mapping.get(key)
            if isinstance(nested, Mapping):
                candidates.append(nested)
                for child_key in ("data", "structured", "structuredContent", "meta"):
                    child = nested.get(child_key)
                    if isinstance(child, Mapping):
                        candidates.append(child)
    for mapping in candidates:
        for key in ("actualTradeDate", "actual_trade_date", "tradeDate", "trade_date"):
            value = _trade_date(mapping.get(key))
            if value:
                return value
    return ""


def _args_hash(tool: str, arguments: dict[str, Any] | None) -> str:
    payload = json.dumps(
        {"tool": tool, "arguments": arguments or {}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _ensure_table(store: Any) -> None:
    """调用现有 Store API；不在此处 CREATE TABLE。"""
    ensure = getattr(store, "ensure_intel_snapshots_schema", None)
    if callable(ensure):
        ensure()


def read_tape_cache(
    store: Any,
    request: TapeRequest,
    *,
    tool: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    max_age_minutes: int | None = None,
) -> TapeResult | None:
    """读取与 intel_snapshots 相同 key 规则的缓存。

    ``arguments`` 用于按写入方的真实参数取 key（例如悟道 lane 会补
    ``format`` / ``detailLevel``）；缺省仍用请求原参数，不同参数不共用行。
    """
    if store is None or not request.requested_date:
        return None
    _ensure_table(store)
    selected_tool = str(tool or request.tool or request.lane)
    key_arguments = dict(
        arguments if arguments is not None else request.effective_arguments
    )
    digest = _args_hash(selected_tool, key_arguments)
    row = store.conn.execute(
        """
        SELECT payload_json, fetched_at, server
        FROM intel_snapshots
        WHERE trade_date = ? AND tool = ? AND args_hash = ?
        """,
        (request.requested_date, selected_tool, digest),
    ).fetchone()
    if row is None:
        return None
    fetched_at = str(row["fetched_at"] or "")
    if max_age_minutes is not None and max_age_minutes > 0:
        if not fetched_at:
            return None
        try:
            stamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age = (datetime.now(stamp.tzinfo or _UTC) - stamp).total_seconds() / 60.0
        except (TypeError, ValueError):
            # 旧库里存的是不带时区的 fetched_at，相减会抛 TypeError；
            # 必须在这里收口，否则会顺着盘口取数一路炸到调用方。
            return None
        if age > max_age_minutes:
            return None
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    declared_date = _declared_trade_date(payload)
    requested_date = _trade_date(request.requested_date)
    if declared_date and requested_date and declared_date != requested_date:
        return None
    return TapeResult(
        data=payload,
        provenance=TapeProvenance(
            provider_id=str(row["server"] or "") or None,
            lane=request.lane,
            requested_date=request.requested_date,
            as_of_date=declared_date or request.requested_date,
            fetched_at=fetched_at or None,
            from_cache=True,
        ),
    )


def write_tape_cache(
    store: Any,
    request: TapeRequest,
    payload: dict[str, Any],
    *,
    tool: str | None = None,
    server: str = "",
) -> None:
    """写入既有 intel_snapshots 表；payload 仍是可清理的缓存。"""
    if store is None or not request.requested_date:
        return
    _ensure_table(store)
    selected_tool = str(tool or request.tool or request.lane)
    arguments = dict(request.effective_arguments)
    digest = _args_hash(selected_tool, arguments)
    now = datetime.now(_UTC).isoformat(timespec="seconds")
    store.conn.execute(
        """
        INSERT INTO intel_snapshots(
            trade_date, tool, args_hash, server, payload_json, fetched_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, tool, args_hash) DO UPDATE SET
            server = excluded.server,
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (
            request.requested_date,
            selected_tool,
            digest,
            server,
            json.dumps(payload, ensure_ascii=False, default=str),
            now,
        ),
    )
    store.conn.commit()


__all__ = ["read_tape_cache", "write_tape_cache"]
