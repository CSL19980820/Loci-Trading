"""基于 ``instruments.industry`` 与日 K 的本地题材降级计算。

这里的题材不是供应商板块，也没有盘中资金流。所有派生字段都带有明确
``local_industry_derived`` 标记，供上层闸门按降级数据 fail-closed。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from math import isfinite
from typing import Any

from src.market.domain.tape import TapeRequest

LOCAL_THEME_STRENGTH_SOURCE = "local_industry_derived"
LOCAL_THEME_WARNING = "local_industry_derived"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _argument(arguments: Mapping[str, Any], *names: str) -> Any:
    normalized = {_key(name) for name in names}
    for key, value in arguments.items():
        if _key(key) in normalized:
            return value
    return None


def _values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in re.split(r"[\s,，;；]+", value) if item]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value not in (None, ""):
        return [str(value).strip()]
    return []


def _code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else str(value or "").strip()


def _requested_codes(request: TapeRequest) -> set[str]:
    arguments = request.effective_arguments
    raw_values: list[str] = [str(item) for item in request.codes]
    for name in ("codes", "stockCodes", "stock_codes", "code"):
        raw_values.extend(_values(_argument(arguments, name)))
    return {cleaned for value in raw_values if (cleaned := _code(value))}


def _requested_themes(request: TapeRequest) -> list[str]:
    arguments = request.effective_arguments
    values: list[str] = []
    for name in (
        "themeCode",
        "theme_code",
        "themeName",
        "theme_name",
        "industry",
        "板块代码",
        "板块名称",
    ):
        values.extend(_values(_argument(arguments, name)))
    return list(dict.fromkeys(values))


def _industry_name(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    for prefix in ("local:industry:", "local_industry:", "industry:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return _industry(text)


def _industry(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"", "none", "nan", "null"} else text


def _limit(request: TapeRequest, default: int) -> int:
    raw = request.limit
    if raw is None:
        raw = _argument(request.effective_arguments, "limit", "maxRows", "max_rows")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), 500)


def _pct_chg(row: Mapping[str, Any]) -> float | None:
    direct = _number(row.get("pct_chg"))
    if direct is None:
        direct = _number(row.get("pctChg"))
    if direct is not None:
        return direct
    close = _number(row.get("close"))
    previous = _number(row.get("prev_close"))
    if close is None or previous is None or previous <= 0:
        return None
    return (close / previous - 1.0) * 100.0


def _member_row(raw: Mapping[str, Any], industry: str) -> dict[str, Any]:
    code = _code(raw.get("code"))
    name = str(raw.get("name") or code)
    pct = _pct_chg(raw)
    amount = _number(raw.get("amount"))
    row: dict[str, Any] = {
        "code": code,
        "name": name,
        "themeCode": industry,
        "themeName": industry,
        "theme_code": industry,
        "theme_name": industry,
        "industry": industry,
        "pct_chg": round(pct, 4) if pct is not None else None,
        "pctChg": round(pct, 4) if pct is not None else None,
        "amount": round(amount, 4) if amount is not None else None,
        "tradeAmount": round(amount, 4) if amount is not None else None,
        "成交额": round(amount, 4) if amount is not None else None,
    }
    for key in ("close", "prev_close", "high", "low", "volume", "turnover", "board"):
        if raw.get(key) is not None:
            row[key] = raw[key]
    for key in ("isLimitUp", "is_limit_up", "ladder_level", "level"):
        if raw.get(key) is not None:
            row[key] = raw[key]
    return row


def _weighted_pct(rows: Sequence[Mapping[str, Any]]) -> float | None:
    values = [
        (_number(row.get("pct_chg")), _number(row.get("amount")))
        for row in rows
    ]
    valid = [(pct, amount) for pct, amount in values if pct is not None]
    if not valid:
        return None
    weighted = [(pct, amount) for pct, amount in valid if amount is not None and amount > 0]
    if weighted and (total := sum(amount for _pct, amount in weighted)) > 0:
        return sum(pct * amount for pct, amount in weighted) / total
    return sum(pct for pct, _amount in valid) / len(valid)


def _sort_key(row: Mapping[str, Any]) -> tuple[float, float, str]:
    pct = _number(row.get("pct_chg"))
    amount = _number(row.get("amount"))
    return (
        -(pct if pct is not None else float("-inf")),
        -(amount if amount is not None else float("-inf")),
        str(row.get("themeName") or row.get("theme_name") or ""),
    )


def _rank_strength(rows: list[dict[str, Any]], *, basis: str) -> None:
    for index, row in enumerate(rows):
        row["strength"] = (
            100.0 if len(rows) == 1 else round(100.0 * (len(rows) - index - 1) / (len(rows) - 1), 2)
        )
        row["strength_source"] = LOCAL_THEME_STRENGTH_SOURCE
        row["strength_basis"] = basis


def _meta(day: str, *, stale: bool) -> dict[str, Any]:
    return {
        "tradeDate": day,
        "actualTradeDate": day,
        "dateStatus": "mismatch" if stale else "exact",
        "isRealtime": False,
        "dataFreshness": {"isRealtime": False},
        "source": "market_daily_cache",
        "strength_source": LOCAL_THEME_STRENGTH_SOURCE,
    }


def _instrument_rows(store: Any) -> list[dict[str, Any]]:
    try:
        rows = store.conn.execute(
            """
            SELECT code, name, industry
            FROM instruments
            WHERE COALESCE(industry, '') <> ''
              AND instrument_type = 'STOCK'
              AND status = 'normal'
            ORDER BY code
            """
        ).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _selected_industries(
    request: TapeRequest,
    instruments: Sequence[Mapping[str, Any]],
    quote_rows: Sequence[Mapping[str, Any]],
) -> set[str]:
    known = {
        _industry(row.get("industry"))
        for row in (*instruments, *quote_rows)
        if _industry(row.get("industry"))
    }
    by_key = {item.casefold(): item for item in known}
    requested = [_industry_name(item) for item in _requested_themes(request)]
    selected = {by_key[item.casefold()] for item in requested if item.casefold() in by_key}
    codes = _requested_codes(request)
    if not requested and codes:
        selected.update(
            _industry(row.get("industry"))
            for row in instruments
            if _code(row.get("code")) in codes and _industry(row.get("industry"))
        )
        selected.update(
            _industry(row.get("industry"))
            for row in quote_rows
            if _code(row.get("code")) in codes and _industry(row.get("industry"))
        )
    return selected


def local_theme_available(
    request: TapeRequest,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    if not rows:
        return False, "local_theme_quotes_unavailable"
    if not any(_industry(row.get("industry")) for row in rows):
        return False, "local_theme_industry_missing"
    return True, LOCAL_THEME_WARNING


def _apply_limit(
    rows: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """按 limit 截断并回报是否真的截断，避免「只看了前 N 条」被读成全量。"""
    return rows[:limit], len(rows) > limit


def _empty_payload(day: str, *, stale: bool) -> dict[str, Any]:
    return {**_meta(day, stale=stale), "rows": [], "row_total": 0, "truncated": False}


def build_local_theme_payload(
    store: Any,
    request: TapeRequest,
    *,
    day: str,
    stale: bool,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, tuple[str, ...], str | None]:
    """返回本地题材载荷、来源告警和可读错误。"""
    warnings: list[str] = [LOCAL_THEME_WARNING]
    instruments = _instrument_rows(store)
    if request.lane == "theme_board":
        selected = _selected_industries(request, instruments, rows)
        requested_themes = _requested_themes(request)
        if requested_themes and not selected:
            return (
                _empty_payload(day, stale=stale),
                tuple(dict.fromkeys((*warnings, "local_theme_not_found"))),
                "local_theme_not_found",
            )
        grouped: dict[str, list[dict[str, Any]]] = {}
        requested_codes = _requested_codes(request)
        for raw in rows:
            industry = _industry(raw.get("industry"))
            code = _code(raw.get("code"))
            if not industry or (selected and industry not in selected):
                continue
            if requested_codes and code not in requested_codes:
                continue
            grouped.setdefault(industry, []).append(_member_row(raw, industry))
        output: list[dict[str, Any]] = []
        for industry, members in grouped.items():
            pct = _weighted_pct(members)
            amounts = [_number(row.get("amount")) for row in members]
            valid_amounts = [amount for amount in amounts if amount is not None]
            output.append(
                {
                    "themeCode": industry,
                    "themeName": industry,
                    "theme_code": industry,
                    "theme_name": industry,
                    "pct_chg": round(pct, 4) if pct is not None else None,
                    "pctChg": round(pct, 4) if pct is not None else None,
                    "amount": round(sum(valid_amounts), 4) if valid_amounts else None,
                    "tradeAmount": round(sum(valid_amounts), 4) if valid_amounts else None,
                    "成交额": round(sum(valid_amounts), 4) if valid_amounts else None,
                    "member_count": len(members),
                }
            )
        if not output:
            return (
                _empty_payload(day, stale=stale),
                tuple(dict.fromkeys((*warnings, "local_theme_unavailable"))),
                "local_theme_unavailable",
            )
        has_pct = any(row.get("pct_chg") is not None for row in output)
        if not has_pct:
            warnings.append("local_theme_pct_missing")
        output.sort(key=_sort_key)
        basis = "pct_chg_then_amount" if has_pct else "amount_only"
        _rank_strength(output, basis=basis)
        rows, truncated = _apply_limit(output, _limit(request, 20))
        if truncated:
            warnings.append("local_theme_rows_truncated")
        payload = {
            **_meta(day, stale=stale),
            "rows": rows,
            "row_total": len(output),
            "truncated": truncated,
            "rank_basis": basis,
        }
        return payload, tuple(dict.fromkeys(warnings)), None

    if request.lane != "theme_members":
        return None, ("unsupported_tape_lane",), "unsupported_tape_lane"

    selected = _selected_industries(request, instruments, rows)
    requested_themes = _requested_themes(request)
    requested_codes = _requested_codes(request)
    if not requested_themes and not requested_codes:
        return (
            None,
            ("local_theme_members_requires_selector",),
            "local_theme_members_requires_selector",
        )
    if requested_themes and not selected:
        payload = _empty_payload(day, stale=stale)
        return (
            payload,
            tuple(dict.fromkeys((*warnings, "local_theme_members_not_found"))),
            "local_theme_members_not_found",
        )

    quote_by_code = {_code(row.get("code")): row for row in rows if _code(row.get("code"))}
    candidates = [
        row
        for row in instruments
        if (not selected or _industry(row.get("industry")) in selected)
        and (not requested_codes or _code(row.get("code")) in requested_codes)
    ]
    if not candidates:
        candidates = [
            row
            for row in rows
            if (not selected or _industry(row.get("industry")) in selected)
            and (not requested_codes or _code(row.get("code")) in requested_codes)
        ]
    output: list[dict[str, Any]] = []
    for instrument in candidates:
        code = _code(instrument.get("code"))
        industry = _industry(instrument.get("industry"))
        raw = quote_by_code.get(code)
        if raw is None:
            raw = {
                "code": code,
                "name": instrument.get("name") or code,
                "industry": industry,
            }
            warnings.append("local_theme_quote_missing")
        else:
            raw = {**dict(raw), "name": raw.get("name") or instrument.get("name") or code}
        output.append(_member_row(raw, industry))
    output.sort(
        key=lambda row: (
            _number(row.get("pct_chg")) is None,
            -(_number(row.get("pct_chg")) or 0.0),
            -(_number(row.get("amount")) or 0.0),
            str(row.get("code") or ""),
        )
    )
    if not output:
        warnings.append("local_theme_members_empty")
    rows, truncated = _apply_limit(output, _limit(request, 200))
    if truncated:
        warnings.append("local_theme_rows_truncated")
    selected_names = sorted(selected)
    payload = {
        **_meta(day, stale=stale),
        "themeCode": selected_names[0] if len(selected_names) == 1 else None,
        "themeName": selected_names[0] if len(selected_names) == 1 else None,
        "rows": rows,
        "row_total": len(output),
        "truncated": truncated,
    }
    return payload, tuple(dict.fromkeys(warnings)), None


__all__ = [
    "LOCAL_THEME_STRENGTH_SOURCE",
    "LOCAL_THEME_WARNING",
    "build_local_theme_payload",
    "local_theme_available",
]
