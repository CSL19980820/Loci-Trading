"""研究输入快照：只保存本次计算实际需要的本地事实。"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from typing import Any, Literal

import pandas as pd

from src.shared.clock import utc_now
from src.market import check_market_health, normalize_code
from src.research.domain.contract import ResearchInputSnapshot, SourceAttempt


Budget = Literal["lite", "standard", "deep"]
MAX_BARS: dict[str, int] = {"lite": 120, "standard": 320, "deep": 600}


class ResearchNotFoundError(ValueError):
    """标的在本地行情仓中不存在。"""


def _jsonable(value: Any) -> Any:
    """把 pandas / numpy 标量收敛成严格 JSON 值。"""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _records(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    if frame.empty:
        return ()
    output: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row = {str(key): _jsonable(value) for key, value in raw.items()}
        if row.get("trade_date") not in (None, ""):
            row["trade_date"] = str(row["trade_date"])[:10]
        output.append(row)
    return tuple(output)


def _latest(code: str, rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not rows:
        return {}
    latest = dict(rows[-1])
    latest["code"] = code
    previous = rows[-2] if len(rows) > 1 else {}
    close = latest.get("close")
    previous_close = previous.get("close")
    try:
        if float(previous_close or 0) > 0 and float(close or 0) > 0:
            latest["pct"] = round(
                (float(close) - float(previous_close)) / float(previous_close) * 100,
                2,
            )
    except (TypeError, ValueError):
        latest["pct"] = None
    return latest


def _requested_date(value: str | None) -> str:
    raw = str(value or "").strip()
    if raw:
        try:
            date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"研究截止日格式无效：{raw}") from exc
    return raw


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """移除采集墙钟，保留真正会改变研究结论的输入事实。"""
    market_health = dict(payload.get("market_health") or {})
    market_health.pop("checked_at", None)
    attempts = [
        {key: value for key, value in dict(item).items() if key != "checked_at"}
        for item in payload.get("source_attempts", [])
        if isinstance(item, dict)
    ]
    return {**payload, "market_health": market_health, "source_attempts": attempts}


_SOURCE_STATES = {
    "registered", "probed", "selected", "failed", "skipped", "cancelled", "not_probed", "not_observed"
}


def _source_state(value: object, *, default: str) -> str:
    state = str(value or "").strip()
    return state if state in _SOURCE_STATES else default


def _project_source_attempts(
    evidence: dict[str, Any], *, code: str, rows: tuple[dict[str, Any], ...]
) -> tuple[SourceAttempt, ...]:
    """保留 market 逐标的 receipt/attempt，绝不由本地行反推外部成功。"""
    receipts = [item for item in evidence.get("receipts", []) if isinstance(item, dict)]
    receipt_by_id = {str(item.get("receipt_id") or ""): item for item in receipts}
    row_sources = tuple(sorted({str(row.get("source") or "") for row in rows if row.get("source")}))
    row_fields = tuple(sorted({key for row in rows for key in row}))
    projected: list[SourceAttempt] = []
    for receipt in receipts:
        requested = [str(item) for item in receipt.get("requested_sources", []) if str(item)]
        source_id = str(receipt.get("selected_source") or (requested[0] if requested else "unknown"))
        coverage = receipt.get("coverage") if isinstance(receipt.get("coverage"), dict) else {}
        projected.append(
            SourceAttempt(
                source_id=source_id,
                state=_source_state(receipt.get("state"), default="failed"),
                checked_at=str(receipt.get("generated_at") or ""),
                row_sources=row_sources,
                fields=tuple(str(item) for item in coverage.get("fields", []) if str(item)),
                error=str(receipt.get("error") or ""),
                kind="route_receipt",
                receipt_id=str(receipt.get("receipt_id") or ""),
                code=str(receipt.get("code") or code),
                lane=str(receipt.get("lane") or ""),
                unresolved=bool(receipt.get("unresolved", False)),
                fallback_used=bool(receipt.get("fallback_used", False)),
            )
        )
    for attempt in (item for item in evidence.get("attempts", []) if isinstance(item, dict)):
        receipt = receipt_by_id.get(str(attempt.get("receipt_id") or ""), {})
        projected.append(
            SourceAttempt(
                source_id=str(attempt.get("source_id") or "unknown"),
                state=_source_state(attempt.get("state"), default="failed"),
                checked_at=str(attempt.get("checked_at") or ""),
                row_sources=row_sources,
                fields=tuple(str(item) for item in attempt.get("fields", []) if str(item)),
                error=str(attempt.get("error") or ""),
                kind="route_attempt",
                receipt_id=str(attempt.get("receipt_id") or ""),
                code=str(attempt.get("code") or receipt.get("code") or code),
                lane=str(receipt.get("lane") or ""),
                unresolved=bool(receipt.get("unresolved", False)),
                fallback_used=bool(receipt.get("fallback_used", False)),
            )
        )
    if evidence.get("attempts_not_observed"):
        missing_codes = [str(item) for item in evidence.get("attempts_not_observed_codes", []) if str(item)]
        for missing_code in dict.fromkeys(missing_codes or [code]):
            projected.append(
                SourceAttempt(
                    source_id=row_sources[0] if len(row_sources) == 1 else "market.db",
                    state="not_observed",
                    row_sources=row_sources,
                    fields=row_fields,
                    error="行情行没有可追溯的来源 attempts/receipt",
                    kind="legacy_row",
                    code=missing_code,
                )
            )
    if rows:
        projected.append(
            SourceAttempt(
                source_id="market.db",
                state="selected",
                row_sources=row_sources,
                fields=row_fields,
                kind="local_snapshot",
                code=code,
            )
        )
    return tuple(projected)


def capture_research_input(
    store: Any,
    code: str,
    *,
    budget: Budget = "standard",
    as_of: str | None = None,
) -> ResearchInputSnapshot:
    """截取截止日以前的本地输入，并为其生成稳定指纹。"""
    normalized = normalize_code(code)
    requested = _requested_date(as_of)
    max_bars = MAX_BARS[budget]
    days = store.trading_days(end=requested or None)
    resolved_as_of = str(days[-1]) if days else ""
    start = days[-max_bars] if len(days) > max_bars else None
    frame = store.history(
        normalized,
        start=start,
        end=resolved_as_of or requested or None,
        adjust="qfq",
    )
    instrument_rows = store.instruments_by_codes([normalized])
    instrument = (
        {str(key): _jsonable(value) for key, value in instrument_rows[0].items()}
        if instrument_rows
        else {}
    )
    rows = _records(frame)
    if not instrument and not rows:
        raise ResearchNotFoundError(f"行情仓中没有标的：{normalized}")
    if not resolved_as_of and rows:
        resolved_as_of = str(rows[-1].get("trade_date") or "")

    market_snapshot = _jsonable(
        dict(
            store.data_snapshot(
                codes=[normalized],
                start=start,
                end=resolved_as_of or requested or None,
            )
        )
    )
    market_health = _jsonable(
        check_market_health(
            store,
            trade_date=resolved_as_of or None,
            include_ok=False,
        ).to_dict()
    )
    source_evidence = dict(market_snapshot.get("source_evidence") or {})
    source_attempts = _project_source_attempts(
        source_evidence, code=normalized, rows=rows
    )
    latest = _latest(normalized, rows)
    # 审计时间戳统一走 shared.clock:此前这里写的是 `_now()`,而这个名字在本模块
    # 既没定义也没导入——凡是走到这一行的调用都会 NameError 当场炸掉。
    generated_at = utc_now()
    payload = {
        "contract_version": "research-input-v1",
        "code": normalized,
        "budget": budget,
        "requested_as_of": requested,
        "as_of": resolved_as_of,
        "adjust": "qfq",
        "market_revision": str(market_snapshot.get("market_revision") or ""),
        "market_snapshot": market_snapshot,
        "market_health": market_health,
        "instrument": instrument,
        "latest": latest,
        "history": list(rows),
        "source_attempts": [item.to_dict() for item in source_attempts],
    }
    return ResearchInputSnapshot(
        code=normalized,
        budget=budget,
        requested_as_of=requested,
        as_of=resolved_as_of,
        adjust="qfq",
        generated_at=generated_at,
        market_revision=str(market_snapshot.get("market_revision") or ""),
        market_snapshot=market_snapshot,
        market_health=market_health,
        instrument=instrument,
        latest=latest,
        history=rows,
        source_attempts=source_attempts,
        input_sha256=_canonical_hash(_fingerprint_payload(payload)),
    )
