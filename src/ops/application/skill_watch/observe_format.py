"""观察池文案 / 规则常量 / 盘中预警（从 observe_pool 拆出，压行数）。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.ops.application.skill_watch.roles import EXIT_ROLES, ROLE_LABEL
from src.ops.application.skill_watch.paper_eligibility import is_observe_intent

#: 完整观察池规则（入池/粘性/替换/汇报）——日终扫描与文档注入；不注入盯盘 monitor。
OBSERVE_POOL_RULES = """
【观察池规则·必须遵守】
目标：盯住「好票」续看，不是每日换一批好看的名字。
一、是否加入（全部满足才可入池）
1. 角色为龙头或中军（跟风/走弱/结构破坏一律不进）。
2. 形态分 ≥ 观察最低分（默认 50）；分数缺失则不新入。
3. 当前未持仓；本轮也不是可买票（可买走可买路径）。
4. 能用一句话说清入池理由（角色+分+为何值得盯）；禁止无理由塞票。
二、粘性与日更（防轮换）
5. 已在池内且仍合格 → 默认「已有·续盯」，刷新分数即可，禁止无故换出。
6. 当日「新增」最多 1～2 只；未持仓观察池总量 ≤ 5；同一题材默认最多 2 只。
7. 旧池超出题材上限时保持粘性；只有新增/替换受题材上限约束，受限必须汇报。
8. 池满才允许「替换」：新票分 ≥ 池内最弱票分 + 替换分差（默认 +8），或最弱票已走弱/破位/跌破分线。
9. 观察达到最长寿命仍合格可续盯但要标记「久观无果」；有合格新票时可优先换新并说明原因。
三、汇报（预案变更时必写）
10. 必须区分：已有 / 新增（含理由）/ 替换（旧←新+理由）；无变动写「无变动·续盯」。
11. 观察票只巡检，禁止开仓/加仓/低吸；持仓不占观察名额。
""".strip()

#: 盯盘 monitor 专用：极短巡检约束，不含入池/汇报规则。
OBSERVE_MONITOR_AI_RULES = """
【观察票巡检】
观察票只巡检，禁止开仓/加仓/低吸；注意角色走弱/破位/大跌可在 notes 用中文提示；不要改观察池、不要汇报池变更；notes 禁止英文字段名。
""".strip()

#: 角色固定 emoji（企微文案用，不随机，避免同一票换脸）
ROLE_EMOJI: dict[str, str] = {
    "leader": "🐲",
    "龙头": "🐲",
    "secondary": "🛡️",
    "中军": "🛡️",
    "follower": "👣",
    "跟风": "👣",
    "weakened": "⚠️",
    "走弱": "⚠️",
    "failed": "💥",
    "结构破坏": "💥",
}


def score_of(row: dict[str, Any]) -> float:
    try:
        return float(row.get("score") if row.get("score") is not None else -1)
    except (TypeError, ValueError):
        return -1.0


def code_of(row: dict[str, Any]) -> str:
    return str(row.get("code") or "").strip()


def text_of(value: Any) -> str:
    return str(value or "").strip()


def name_of(row: dict[str, Any]) -> str:
    return str(row.get("name") or code_of(row) or "").strip()


def role_bad(row: dict[str, Any]) -> bool:
    role = str(row.get("role") or "").strip().lower()
    label = str(row.get("role_label") or "").strip()
    exit_labels = {ROLE_LABEL[r] for r in EXIT_ROLES}
    return role in EXIT_ROLES or label in exit_labels


def role_badge(role_label: Any, role: Any = None) -> str:
    """角色徽章：优先 emoji，未知角色退回原文。"""
    for key in (role, role_label):
        text = str(key or "").strip()
        if text in ROLE_EMOJI:
            return ROLE_EMOJI[text]
    text = str(role_label or role or "").strip()
    return text or "👀"


def _quote_last(quotes: dict[str, Any], code: str) -> float | None:
    q = quotes.get(code) if isinstance(quotes, dict) else None
    if not isinstance(q, dict):
        return None
    for key in ("price", "last", "close"):
        raw = q.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _role_alert_tag(row: dict[str, Any]) -> str:
    role = str(row.get("role") or "").strip().lower()
    label = str(row.get("role_label") or "").strip()
    if role == "failed" or label == "结构破坏":
        return "结构破坏"
    return "走弱"


def observe_alert_records(
    items: list[dict[str, Any]],
    quotes: dict[str, Any] | None = None,
    *,
    min_score: float = 50.0,
    drop_pct: float = -5.0,
) -> list[dict[str, Any]]:
    """盘中观察预警结构化记录（kind + reason），供落盘与文案共用。"""
    quotes = quotes or {}
    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not is_observe_intent(item):
            continue
        code = code_of(item)
        name = name_of(item)
        if not code:
            continue
        kind = ""
        reason = ""
        if role_bad(item):
            kind = "structure_failed" if _role_alert_tag(item) == "结构破坏" else "role_weak"
            reason = _role_alert_tag(item)
        elif item.get("score") is not None and score_of(item) < min_score:
            kind = "score_below_min"
            reason = "跌破分线"
        else:
            last = _quote_last(quotes, code)
            ref = item.get("ref_close")
            try:
                ref_f = float(ref) if ref is not None else 0.0
            except (TypeError, ValueError):
                ref_f = 0.0
            if last is not None and ref_f > 0:
                pct = (last / ref_f - 1.0) * 100.0
                if pct <= drop_pct:
                    kind = "drop_pct"
                    reason = f"{pct:.1f}%"
        if kind and reason:
            records.append(
                {
                    "code": code,
                    "name": name,
                    "kind": kind,
                    "alert_kind": kind,
                    "reason": reason,
                }
            )
    return records


def format_observe_alert_line(record: Mapping[str, Any]) -> str:
    """结构化预警 → 一行紧凑文案。"""
    name = str(record.get("name") or record.get("code") or "").strip()
    code = str(record.get("code") or "").strip()
    reason = str(record.get("reason") or "").strip()
    return f"⚠️观察预警 {name} {code} · {reason}".strip()


def observe_intraday_alerts(
    items: list[dict[str, Any]],
    quotes: dict[str, Any] | None = None,
    *,
    min_score: float = 50.0,
    drop_pct: float = -5.0,
) -> list[str]:
    """盘中观察预警文案；规则与 ``observe_alert_records`` 同源。"""
    return [
        format_observe_alert_line(row)
        for row in observe_alert_records(
            items, quotes, min_score=min_score, drop_pct=drop_pct
        )
    ]


def format_observe_line(item: dict[str, Any], *, index: int | None = None) -> str:
    """一行观察：1、👀 百花医药 600721，58分，🐲，仅观察"""
    name = name_of(item)
    code = code_of(item)
    score = item.get("score")
    try:
        score_txt = f"{int(float(score))}分" if score is not None else "暂无分"
    except (TypeError, ValueError):
        score_txt = "暂无分"
    badge = role_badge(item.get("role_label"), item.get("role"))
    decision = text_of(item.get("decision_reason"))
    tail = decision or "仅观察"
    body = f"👀 {name} {code}，{score_txt}，{badge}，{tail}".strip(" ，")
    if index is not None:
        return f"{index}、{body}"
    return body


def role_display(row: dict[str, Any]) -> str:
    """可读角色名：优先 role_label，其次 ROLE_LABEL。"""
    label = str(row.get("role_label") or "").strip()
    if label:
        return label
    role = str(row.get("role") or "").strip().lower()
    if role in ROLE_LABEL:
        return ROLE_LABEL[role]
    badge = role_badge(row.get("role_label"), row.get("role"))
    return badge if badge != "👀" else "观察"


def format_observe_reason(row: dict[str, Any], *, why: str = "") -> str:
    """`{角色}·{题材}·{分}分·{为何盯}`；题材缺省省略该段。"""
    role = role_display(row)
    theme = text_of(row.get("theme_name")) or text_of(row.get("theme_code"))
    score = score_of(row)
    score_txt = f"{int(score)}分" if score >= 0 else "暂无分"
    parts: list[str] = [role]
    if theme:
        parts.append(theme)
    parts.append(score_txt)
    if why:
        parts.append(why)
    return "·".join(parts)


def format_observe_change_report(report: dict[str, Any] | None) -> str:
    """企微/预案：观察池变更段；无变动时不输出段。"""
    if not report:
        return ""
    kept = list(report.get("kept") or [])
    added = list(report.get("added") or [])
    replaced = list(report.get("replaced") or [])
    dropped = list(report.get("dropped") or [])
    upgraded = list(report.get("upgraded") or [])
    changed = bool(
        report.get("changed")
        or upgraded
        or added
        or replaced
        or dropped
        or report.get("stale")
        or report.get("limited")
    )
    if not changed:
        return ""
    lines = ["🔄【观察池变更】"]
    if kept:
        names = "、".join(
            f"{name_of(k) or k.get('code')}"
            + (
                f"（久观无果·已观察{k.get('age_days')}天）"
                if k.get("stale_observe") and k.get("age_days") is not None
                else "（久观无果）"
                if k.get("stale_observe")
                else ""
            )
            for k in kept[:5]
            if k.get("code")
        )
        lines.append(f"✅续盯 {len(kept)}：{names}")
    for row in upgraded:
        lines.append(
            f"⬆️升级可买 {name_of(row)} {row.get('code')}（{row.get('reason') or '原观察池'}）"
        )
    for row in added:
        reason = str(row.get("reason") or "达观察线").strip()
        # 「新入池」对用户像「今天才第一次看见」；改成更贴切说法
        if reason in {"新入池", "达观察线"}:
            reason = "本轮新进观察"
        else:
            reason = reason.replace("·新入池", "").replace("新入池", "").strip("· ") or "本轮新进观察"
        lines.append(f"🆕新进观察 {name_of(row)} {row.get('code')}（{reason}）")
    for row in replaced:
        lines.append(
            f"🔀替换 {name_of({'name': row.get('out_name'), 'code': row.get('out_code')})} "
            f"← {name_of({'name': row.get('in_name'), 'code': row.get('in_code')})}"
            f"（{row.get('reason') or '优胜劣汰'}）"
        )
    limited = list(report.get("limited") or [])
    for row in limited[:3]:
        lines.append(
            f"⏸️暂不新增 {name_of(row)} {row.get('code')}（{row.get('reason') or '题材已达上限'}）"
        )
    for row in dropped[:3]:
        lines.append(
            f"🗑️移出 {name_of(row)} {row.get('code')}（{row.get('reason') or '不再观察'}）"
        )
    return "\n".join(lines)


__all__ = [
    "OBSERVE_MONITOR_AI_RULES",
    "OBSERVE_POOL_RULES",
    "ROLE_EMOJI",
    "code_of",
    "format_observe_alert_line",
    "format_observe_change_report",
    "format_observe_line",
    "format_observe_reason",
    "name_of",
    "observe_alert_records",
    "observe_intraday_alerts",
    "role_bad",
    "role_badge",
    "role_display",
    "score_of",
    "text_of",
]
