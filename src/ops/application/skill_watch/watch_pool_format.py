"""统一监察池推送行格式化。"""
from __future__ import annotations

import re
from typing import Any


_ACTION_PRIORITY = {
    "holding": 0,
    "buy": 1,
    "rebalance": 2,
    "sell": 3,
    "observe": 5,
}


def _action_of(item: dict[str, Any]) -> str:
    action = str(item.get("action") or item.get("intent") or "observe").strip().lower()
    return action if action in _ACTION_PRIORITY else "observe"


def _score_text(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "暂无分"
    return f"{score:g}分"


def _layers_text(item: dict[str, Any], *, holding: bool) -> str:
    value = item.get("layers")
    if value is None or not holding:
        value = item.get("planned_layers")
    if value is None:
        value = item.get("planned_layers_max")
    try:
        layers = float(value)
    except (TypeError, ValueError):
        return ""
    label = "持仓" if holding else "计划"
    return f"{label}{layers:g}层" if layers > 0 else ""


def _cost_text(item: dict[str, Any]) -> str:
    try:
        cost = float(item.get("mark_cost") or 0)
    except (TypeError, ValueError):
        return ""
    return f"成本{cost:g}" if cost > 0 else ""


def _position_market_parts(item: dict[str, Any]) -> list[str]:
    try:
        cost = float(item.get("mark_cost") or 0)
        price = float(
            item.get("current_price")
            or item.get("live_price")
            or item.get("price")
            or item.get("close")
            or item.get("mark_price")
            or 0
        )
    except (TypeError, ValueError):
        return []
    if cost <= 0 or price <= 0:
        return []
    pnl_pct = (price / cost - 1.0) * 100.0
    if abs(pnl_pct) < 0.05:
        pnl_pct = 0.0
    return [f"现价{price:g}", f"{pnl_pct:+.1f}%"]


def _identity(item: dict[str, Any]) -> str:
    code = str(item.get("code") or "").strip()
    name = str(item.get("name") or code).strip()
    return f"{name} {code}".strip()


def _brief_reason(value: Any) -> str:
    text = str(value or "").strip(" ，。；;·")
    if not text:
        return ""
    boilerplate = {
        "龙头身份合格",
        "龙空龙空仓",
        "龙回头尚未回撤",
        "新入池",
    }
    parts = [
        part.strip()
        for part in re.split(r"[；;]", text)
        if part.strip() and part.strip() not in boilerplate
    ]
    text = "；".join(parts)
    text = text.replace("竞价否决，移出观察池", "竞价否决")
    text = text.replace("龙王战法只保留龙头，中军移出观察池", "降为中军")
    if "·" in text:
        segments = [
            segment.strip()
            for segment in text.split("·")
            if segment.strip()
            and segment.strip() not in {"龙头", "中军", "观察", "新入池"}
            and not re.fullmatch(r"\d+(?:\.\d+)?分", segment.strip())
        ]
        text = "·".join(segments)
    return text[:40].strip(" ，。；;·")


def _change_maps(changes: dict[str, Any] | None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    report = changes if isinstance(changes, dict) else {}
    added: dict[str, str] = {}
    removed: list[dict[str, Any]] = []
    for row in report.get("added") or []:
        if isinstance(row, dict) and str(row.get("code") or "").strip():
            added[str(row["code"]).strip()] = _brief_reason(row.get("reason"))
    for row in report.get("replaced") or []:
        if not isinstance(row, dict):
            continue
        in_code = str(row.get("in_code") or "").strip()
        if in_code:
            added[in_code] = _brief_reason(row.get("reason"))
        out_code = str(row.get("out_code") or "").strip()
        if out_code:
            removed.append(
                {
                    "code": out_code,
                    "name": row.get("out_name") or out_code,
                    "score": row.get("out_score"),
                    "reason": row.get("reason") or "被更强候选替换",
                }
            )
    removed.extend(row for row in report.get("dropped") or [] if isinstance(row, dict))
    return added, removed


def _format_current_line(item: dict[str, Any], *, is_new: bool, change_reason: str) -> str:
    action = _action_of(item)
    holding = item.get("bucket") == "position"
    if holding:
        icon = "🔄" if action in {"rebalance", "sell"} else "💰"
        tag = {
            "rebalance": "（🔧调仓）",
            "sell": "（💸卖出）",
        }.get(action, "")
    elif action in {"buy", "rebalance"}:
        icon = "🎯"
        tag = "（⏳待决）"
    else:
        icon = "👀"
        tag = "（🆕新进）" if is_new else ""
    parts = [f"{icon} {_identity(item)}{tag}，{_score_text(item.get('score'))}"]
    if holding:
        layers = _layers_text(item, holding=True)
        if layers:
            parts.append(layers)
        cost = _cost_text(item)
        if cost:
            parts.append(cost)
        parts.extend(_position_market_parts(item))
    elif action in {"buy", "rebalance"}:
        layers = _layers_text(item, holding=False)
        if layers:
            parts.append(layers)
    if action in {"buy", "rebalance", "sell"}:
        reason = _brief_reason(item.get("action_reason"))
        if reason:
            parts.append(reason)
    elif is_new and change_reason:
        parts.append(change_reason)
    return "，".join(parts)


def _format_pick_line(pick: dict[str, Any]) -> str:
    from src.ops.application.skill_watch.actionable_line import format_actionable_line

    return format_actionable_line(
        name=str(pick.get("name") or ""),
        code=str(pick.get("code") or ""),
        layers=pick.get("planned_layers") or pick.get("layers"),
        buy_price=pick.get("buy_price") or pick.get("close") or pick.get("ref_close"),
        pnl_pct=pick.get("pnl_pct"),
        stop_loss_pct=pick.get("stop_loss_pct"),
        take_profit_pct=pick.get("take_profit_pct"),
    )


def format_unified_pool_section(
    items: list[dict[str, Any]] | None,
    changes: dict[str, Any] | None = None,
) -> list[str]:
    """把龙王持股/动作/观察渲染为同一清单，移出项只作尾部变更记录。"""
    current = [dict(row) for row in (items or []) if isinstance(row, dict) and row.get("code")]
    report = changes if isinstance(changes, dict) else {}
    if not current and not any(report.get(key) for key in ("added", "replaced", "dropped", "upgraded")):
        return []
    seen: set[str] = set()
    current = [row for row in current if not (str(row["code"]) in seen or seen.add(str(row["code"])))]
    added, removed = _change_maps(changes)
    positions = sum(row.get("bucket") == "position" for row in current)
    pending = sum(
        row.get("bucket") != "position" and _action_of(row) in {"buy", "rebalance"}
        for row in current
    )
    observes = len(current) - positions - pending
    adjustments = sum(
        row.get("bucket") == "position" and _action_of(row) in {"rebalance", "sell"}
        for row in current
    )
    summary = (
        f"池内共{len(current)}只，💰持股{positions}只，"
        f"🎯待决{pending}只，👀观察{observes}只"
    )
    if adjustments:
        summary += f"，🔄调整{adjustments}只"
    lines = [summary]

    ordered = sorted(
        enumerate(current),
        key=lambda pair: (
            4 if _action_of(pair[1]) == "observe" and str(pair[1]["code"]) in added else _ACTION_PRIORITY[_action_of(pair[1])],
            pair[0],
        ),
    )
    current_codes = {str(row.get("code") or "").strip() for row in current}
    for _, row in ordered:
        code = str(row.get("code") or "").strip()
        lines.append(_format_current_line(row, is_new=code in added, change_reason=added.get(code, "")))

    removed_seen: set[str] = set()
    for row in removed:
        code = str(row.get("code") or "").strip()
        if not code or code in current_codes or code in removed_seen:
            continue
        removed_seen.add(code)
        line = f"👀 {_identity(row)}（🗑️移出），{_score_text(row.get('score'))}"
        reason = _brief_reason(row.get("reason"))
        lines.append(f"{line}，{reason}" if reason else line)
    return lines


def format_watch_pool_section(
    *,
    slug: str,
    items: list[dict[str, Any]] | None,
    changes: dict[str, Any] | None = None,
) -> list[str]:
    """龙回头走统一清单；其他战法保留原有分段格式。"""
    rows = [row for row in (items or []) if isinstance(row, dict)]
    if slug == "dragon-return":
        return format_unified_pool_section(rows, changes)

    from src.ops.application.skill_watch.paper_eligibility import is_observe_intent

    positions = [row for row in rows if row.get("bucket") == "position"]
    watches = [row for row in rows if row.get("bucket") != "position"]
    buys = [row for row in watches if _action_of(row) == "buy"]
    observes = [row for row in watches if is_observe_intent(row)]
    actions = [row for row in watches if _action_of(row) in {"sell", "rebalance", "holding"}]
    lines: list[str] = []
    if positions:
        text = " | ".join(format_pool_action_line(row) for row in positions[:3])
        lines.append(f"💼持股 {len(positions)}/3：{text}")
    if buys:
        text = " | ".join(_format_pick_line(row) for row in buys[:4])
        lines.append(f"🎯介入 {len(buys)}：{text}")
    if observes:
        from src.ops.application.skill_watch.observe_pool import format_observe_line

        text = " | ".join(format_observe_line(row) for row in observes[:5])
        lines.append(f"👀观察 {len(observes)}：{text}")
    if actions:
        text = " | ".join(format_pool_action_line(row) for row in actions[:5])
        lines.append(f"🔄动作 {len(actions)}：{text}")
    return lines


def format_pool_action_line(item: dict[str, Any]) -> str:
    action = str(item.get("action") or item.get("intent") or "").strip().lower()
    action_zh = {
        "holding": "持股",
        "buy": "买入",
        "observe": "观察",
        "sell": "卖出",
        "rebalance": "调仓",
    }.get(action, action or "监测")
    code = str(item.get("code") or "").strip()
    name = str(item.get("name") or "").strip()
    who = name or code
    suffix = f" {code}" if name and code and code != name else ""
    layer_text = ""
    try:
        if item.get("layers") is not None and float(item["layers"]) > 0:
            layer_text = f" {float(item['layers']):g}层"
    except (TypeError, ValueError):
        pass
    return f"{who}{suffix}{layer_text}·{action_zh}"
