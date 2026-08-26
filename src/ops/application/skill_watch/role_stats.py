"""角色留痕的推导：存活、转移、预警提前量、持仓告警。

留痕表只存**观测事实**（某时刻某票是什么角色）；存活天数、转移矩阵这类
指标都能从事实推出来，按仓规不入库，在这里即时算——避免出现第二套真相。

所有函数都是纯函数，入参是 ``store.list_leader_roles()`` 的时间倒序输出，
可以直接喂造好的行做测试。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.ops.application.skill_watch.roles import EXIT_ROLES, ROLE_LABEL


def _ascending(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """留痕按时间倒序返回；推导按时间正序更好读。"""
    rows = [dict(row) for row in history if row.get("code")]
    rows.sort(key=lambda row: (str(row.get("observed_at") or ""), str(row.get("code"))))
    return rows


def _by_code(history: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _ascending(history):
        grouped.setdefault(str(row["code"]), []).append(row)
    return grouped


def role_transitions(
    history: Sequence[Mapping[str, Any]],
    *,
    limit: int = 30,
    grouped: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """角色真正变过的那些点。相邻两次观测角色不同才算一次转移。"""
    transitions: list[dict[str, Any]] = []
    groups = grouped if grouped is not None else _by_code(history)
    for code, rows in groups.items():
        for previous, current in zip(rows, rows[1:], strict=False):
            if previous["role"] == current["role"]:
                continue
            transitions.append(
                {
                    "code": code,
                    "name": current.get("name") or previous.get("name") or code,
                    "theme_name": current.get("theme_name") or previous.get("theme_name") or "",
                    "from_role": previous["role"],
                    "to_role": current["role"],
                    "from_at": previous.get("observed_at"),
                    "to_at": current.get("observed_at"),
                    "basis": current.get("role_basis") or "",
                }
            )
    transitions.sort(key=lambda item: str(item["to_at"]), reverse=True)
    return transitions[: max(1, min(int(limit), 200))]


def _leader_survival(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """当过龙头的票，按「被判为龙头的交易日数」排。"""
    rows: list[dict[str, Any]] = []
    for code, observations in grouped.items():
        days = sorted({str(row["trade_date"]) for row in observations if row["role"] == "leader"})
        if not days:
            continue
        rows.append(
            {
                "code": code,
                "name": observations[-1].get("name") or code,
                "theme_name": observations[-1].get("theme_name") or "",
                "leader_days": len(days),
                "first_leader_day": days[0],
                "last_leader_day": days[-1],
                "current_role": observations[-1]["role"],
                "still_leader": observations[-1]["role"] == "leader",
            }
        )
    rows.sort(key=lambda row: (-int(row["leader_days"]), str(row["code"])))
    return rows


def _warning_lead(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """走弱信号比结构破坏早多少个交易日——衡量这套判定给了多少提前量。"""
    leads: list[int] = []
    for observations in grouped.values():
        all_days = sorted({str(row["trade_date"]) for row in observations})
        index = {day: position for position, day in enumerate(all_days)}
        weakened_day: str | None = None
        for row in observations:
            role = row["role"]
            if role == "weakened" and weakened_day is None:
                weakened_day = str(row["trade_date"])
            elif role == "failed" and weakened_day is not None:
                leads.append(index[str(row["trade_date"])] - index[weakened_day])
                weakened_day = None
            elif role in {"leader", "secondary"}:
                weakened_day = None
    if not leads:
        return {"samples": 0, "avg_days": None, "min_days": None, "max_days": None}
    return {
        "samples": len(leads),
        "avg_days": round(sum(leads) / len(leads), 2),
        "min_days": min(leads),
        "max_days": max(leads),
    }


def summarize_role_history(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """一份可直接展示的角色演进摘要。空历史返回零值结构，不返回 None。"""
    grouped = _by_code(history)
    matrix: dict[str, int] = {}
    for item in role_transitions(history, limit=200, grouped=grouped):
        matrix[f"{item['from_role']}->{item['to_role']}"] = (
            matrix.get(f"{item['from_role']}->{item['to_role']}", 0) + 1
        )
    role_days: dict[str, int] = {}
    for observations in grouped.values():
        for role in ROLE_LABEL:
            days = {str(row["trade_date"]) for row in observations if row["role"] == role}
            if days:
                role_days[role] = role_days.get(role, 0) + len(days)
    return {
        "observations": sum(len(rows) for rows in grouped.values()),
        "codes": len(grouped),
        "trade_days": len({str(row["trade_date"]) for rows in grouped.values() for row in rows}),
        "role_days": role_days,
        "transition_matrix": dict(sorted(matrix.items(), key=lambda kv: -kv[1])),
        "leader_survival": _leader_survival(grouped)[:10],
        "warning_lead": _warning_lead(grouped),
    }


def position_role_alerts(
    *,
    positions: Sequence[Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """持仓里角色已走弱/破位的票——这是最直接的退出证据。"""
    grouped = _by_code(history)
    alerts: list[dict[str, Any]] = []
    for position in positions:
        code = str(position.get("code") or "")
        observations = grouped.get(code)
        if not code or not observations:
            continue
        latest = observations[-1]
        role = str(latest.get("role") or "")
        if role not in EXIT_ROLES:
            continue
        alerts.append(
            {
                "code": code,
                "name": position.get("name") or latest.get("name") or code,
                "layers": position.get("layers"),
                "role": role,
                "role_label": ROLE_LABEL.get(role, role),
                "role_basis": latest.get("role_basis") or "",
                "observed_at": latest.get("observed_at"),
                "theme_name": latest.get("theme_name") or "",
            }
        )
    return alerts


def role_lessons(
    *,
    slug: str,
    trade_date: str,
    alerts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """把持仓角色告警落成教训，供风格记忆吸收。"""
    return [
        {
            "slug": slug,
            "trade_date": trade_date,
            "kind": "role_alert",
            "title": f"{alert.get('name')} {alert.get('code')} 已判{alert.get('role_label')}仍在持仓",
            "content": (
                f"龙头地图在 {alert.get('observed_at')} 把它判为"
                f"{alert.get('role_label')}：{alert.get('role_basis')}。"
                "下次出现同样角色变化时，优先考虑减仓或退出，不要等价格再确认一遍。"
            ),
            "evidence": dict(alert),
        }
        for alert in alerts
    ]


def suggest_tuning_adjustments(
    history: Sequence[Mapping[str, Any]],
    *,
    current_tuning: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """基于留痕频率推导调参**建议**（只读文案，绝不写入 watch_tuning）。"""
    _ = current_tuning  # 预留：后续可对照当前档给出更细建议
    if not history:
        return []

    summary = summarize_role_history(history)
    matrix = summary.get("transition_matrix") or {}
    lead = summary.get("warning_lead") or {}
    role_days = summary.get("role_days") or {}
    suggestions: list[dict[str, Any]] = []

    leader_weakened = int(matrix.get("leader->weakened", 0))
    weakened_failed = int(matrix.get("weakened->failed", 0))
    leader_failed = int(matrix.get("leader->failed", 0))
    trade_days = int(summary.get("trade_days") or 0)

    if leader_weakened >= 2 and trade_days >= 3:
        suggestions.append(
            {
                "direction": "tighten_weakened_drawdown",
                "message": (
                    f"留痕中龙头→走弱已出现 {leader_weakened} 次，"
                    "可考虑收紧「走弱回撤线」或套用偏防守预设"
                ),
            }
        )

    avg_lead = lead.get("avg_days")
    if lead.get("samples", 0) >= 2 and avg_lead is not None and float(avg_lead) < 1.5:
        suggestions.append(
            {
                "direction": "tighten_weakened_drawdown",
                "message": (
                    f"走弱预警平均提前量仅 {avg_lead} 个交易日，判定偏晚，"
                    "建议收紧「走弱回撤线」"
                ),
            }
        )

    if leader_failed >= 1:
        suggestions.append(
            {
                "direction": "tighten_role_thresholds",
                "message": (
                    f"有 {leader_failed} 次龙头直接判为结构破坏（未经过走弱），"
                    "建议收紧角色判定阈值"
                ),
            }
        )

    leader_days = int(role_days.get("leader", 0))
    exit_days = int(role_days.get("weakened", 0)) + int(role_days.get("failed", 0))
    if leader_days >= 4 and exit_days / leader_days > 0.45 and int(summary.get("codes") or 0) >= 2:
        suggestions.append(
            {
                "direction": "reduce_max_candidates",
                "message": (
                    "走弱/破位角色日占比较高，可考虑降低「候选上限」"
                    "或减少同时跟踪标的"
                ),
            }
        )

    if weakened_failed >= 2:
        suggestions.append(
            {
                "direction": "tighten_abandon_gap",
                "message": (
                    f"走弱→破位已出现 {weakened_failed} 次，"
                    "可考虑收紧「放弃低开%」让竞价更早放弃弱势龙头"
                ),
            }
        )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in suggestions:
        direction = str(item.get("direction") or "")
        if direction in seen:
            continue
        seen.add(direction)
        unique.append(item)
    return unique


def format_tuning_suggestions(suggestions: Sequence[Mapping[str, Any]]) -> str:
    """日终正文里的调参建议段；空列表返回空串。"""
    if not suggestions:
        return ""
    lines = ["🔧【调参建议·仅参考】"]
    lines.extend(f"- {item.get('message')}" for item in suggestions if item.get("message"))
    lines.append("以上仅基于留痕频率推导，不会自动改参；请在调参面板确认后保存。")
    return "\n".join(lines)


def format_role_review(summary: Mapping[str, Any], alerts: Sequence[Mapping[str, Any]]) -> str:
    """日终正文里的角色演进段。没有留痕时返回空串，不占版面。"""
    if not summary.get("observations"):
        return ""
    lines = [
        f"🧬【角色演进】{summary.get('codes') or 0} 只 / {summary.get('trade_days') or 0} 个交易日 / "
        f"{summary.get('observations') or 0} 次观测"
    ]
    survival = list(summary.get("leader_survival") or [])[:5]
    if survival:
        lines.append("🐲龙头存活：" + "；".join(
            f"{row['name']}({row['code']}) {row['leader_days']}日"
            + ("·仍是龙头" if row["still_leader"] else f"·现{ROLE_LABEL.get(row['current_role'], '暂无')}")
            for row in survival
        ))
    matrix = summary.get("transition_matrix") or {}
    if matrix:
        from src.ops.application.skill_watch.observe_pool import ROLE_EMOJI

        bits: list[str] = []
        for key, value in list(matrix.items())[:6]:
            raw = str(key)
            if "->" in raw:
                left, right = raw.split("->", 1)
                left_zh = ROLE_LABEL.get(left, left)
                right_zh = ROLE_LABEL.get(right, right)
                label = (
                    f"{ROLE_EMOJI.get(left, '')}{left_zh}→"
                    f"{ROLE_EMOJI.get(right, '')}{right_zh}"
                )
            else:
                label = raw
            bits.append(f"{label} {value}次")
        lines.append("🔀角色转移：" + "；".join(bits))
    lead = summary.get("warning_lead") or {}
    if lead.get("samples"):
        avg = lead.get("avg_days")
        mn = lead.get("min_days")
        mx = lead.get("max_days")
        avg_txt = "暂无" if avg is None else str(avg)
        mn_txt = "暂无" if mn is None else str(mn)
        mx_txt = "暂无" if mx is None else str(mx)
        lines.append(
            f"走弱预警提前量：{lead['samples']} 例，平均 {avg_txt} 个交易日"
            f"（{mn_txt}~{mx_txt}）"
        )
    if alerts:
        lines.append("持仓角色告警：" + "；".join(
            f"{alert['name']}({alert['code']}) 已判{alert['role_label']}——{alert['role_basis']}"
            for alert in alerts
        ))
    return "\n".join(lines)


__all__ = [
    "EXIT_ROLES",
    "ROLE_LABEL",
    "format_role_review",
    "format_tuning_suggestions",
    "position_role_alerts",
    "role_lessons",
    "role_transitions",
    "suggest_tuning_adjustments",
    "summarize_role_history",
]
