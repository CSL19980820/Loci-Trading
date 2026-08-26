"""企微选股 text 模板：预设、规范化、渲染。

占位符（仅替换花括号变量，不做表达式）：
- 标题区：{title} {kind} {date}
- 个股行：{name} {code} {pct}；技能另可有 {note}（≤40 字简要说明）
- 更多行：{n}
"""
from __future__ import annotations

from typing import Any, Literal

ScreenKindTag = Literal["量化", "技能"]
PresetId = Literal["default", "compact", "with_date", "custom"]

PLACEHOLDERS_HEADER = ("{title}", "{kind}", "{date}")
PLACEHOLDERS_PICK = ("{name}", "{code}", "{pct}", "{note}")

SKILL_NOTE_MAX = 40

DEFAULT_TEMPLATE: dict[str, Any] = {
    "preset": "default",
    "header": "【{title}】-{kind}",
    "intro": "",
    "pick": "📌 {name} {code} {pct}",
    "pick_no_pct": "📌 {name} {code}",
    "skill_pick": "📌 {name} {code} {pct}，{note}",
    "skill_pick_no_pct": "📌 {name} {code}，{note}",
    "empty": "📭 暂无符合条件的标的",
    "formal_empty": "📭 正式精选 0 只",
    "watch_header": "👀 低吸观察（不计正式胜率）",
    "watch_pick": "▫️ {name} {code} {pct}",
    "watch_pick_no_pct": "▫️ {name} {code}",
    "more": "…另有 {n} 只",
    "quant_tag": "量化",
    "skills_tag": "技能",
    "max_picks": 30,
}

PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "header": "【{title}】-{kind}",
        "intro": "",
        "pick": "📌 {name} {code} {pct}",
        "pick_no_pct": "📌 {name} {code}",
        "skill_pick": "📌 {name} {code} {pct}，{note}",
        "skill_pick_no_pct": "📌 {name} {code}，{note}",
        "empty": "📭 暂无符合条件的标的",
        "formal_empty": "📭 正式精选 0 只",
        "watch_header": "👀 低吸观察（不计正式胜率）",
        "watch_pick": "▫️ {name} {code} {pct}",
        "watch_pick_no_pct": "▫️ {name} {code}",
        "more": "…另有 {n} 只",
    },
    "compact": {
        "header": "【{title}】-{kind}",
        "intro": "",
        "pick": "📌 {name} {code} {pct}",
        "pick_no_pct": "📌 {name} {code}",
        "skill_pick": "📌 {name} {code} {pct}，{note}",
        "skill_pick_no_pct": "📌 {name} {code}，{note}",
        "empty": "📭 暂无符合条件的标的",
        "formal_empty": "📭 正式精选 0 只",
        "watch_header": "👀 低吸观察（不计正式胜率）",
        "watch_pick": "▫️ {name} {code} {pct}",
        "watch_pick_no_pct": "▫️ {name} {code}",
        "more": "…另有 {n} 只",
    },
    "with_date": {
        "header": "【{title}】-{kind}",
        "intro": "📅 {date}",
        "pick": "📌 {name} {code} {pct}",
        "pick_no_pct": "📌 {name} {code}",
        "skill_pick": "📌 {name} {code} {pct}，{note}",
        "skill_pick_no_pct": "📌 {name} {code}，{note}",
        "empty": "📭 暂无符合条件的标的",
        "formal_empty": "📭 正式精选 0 只",
        "watch_header": "👀 低吸观察（不计正式胜率）",
        "watch_pick": "▫️ {name} {code} {pct}",
        "watch_pick_no_pct": "▫️ {name} {code}",
        "more": "…另有 {n} 只",
    },
}

_SAMPLE_RESULT: dict[str, Any] = {
    "strategy": "潜龙拐点",
    "trade_date": "2026-07-30",
    "picks": [
        {"code": "300105", "name": "龙星科技", "pct_chg": 1.5, "note": "主线放量站上五日线"},
        {"code": "600018", "name": "上港集团", "pct_chg": 5, "note": "回踩确认后温和放量"},
        {"code": "000001", "name": "平安银行", "note": "防御仓样本无涨幅字段"},
    ],
}


def default_screen_template() -> dict[str, Any]:
    return dict(DEFAULT_TEMPLATE)


def normalize_screen_template(raw: Any) -> dict[str, Any]:
    """合并用户配置与默认值；非 custom 预设强制套用文案字段。"""
    base = default_screen_template()
    if not isinstance(raw, dict):
        return base
    out = {**base, **{k: raw[k] for k in base if k in raw}}
    preset = str(out.get("preset") or "default").strip()
    if preset not in PRESETS and preset != "custom":
        preset = "default"
    out["preset"] = preset
    try:
        max_picks = int(out.get("max_picks") or 30)
    except (TypeError, ValueError):
        max_picks = 30
    out["max_picks"] = max(1, min(50, max_picks))
    text_keys = (
        "header",
        "intro",
        "pick",
        "pick_no_pct",
        "skill_pick",
        "skill_pick_no_pct",
        "empty",
        "formal_empty",
        "watch_header",
        "watch_pick",
        "watch_pick_no_pct",
        "more",
        "quant_tag",
        "skills_tag",
    )
    for key in text_keys:
        out[key] = str(out.get(key) if out.get(key) is not None else base[key])
    if not out["header"].strip():
        out["header"] = str(base["header"])
    if not out["pick"].strip():
        out["pick"] = str(base["pick"])
    if not out["pick_no_pct"].strip():
        out["pick_no_pct"] = str(base["pick_no_pct"])
    if not out["skill_pick"].strip():
        out["skill_pick"] = str(base["skill_pick"])
    if not out["skill_pick_no_pct"].strip():
        out["skill_pick_no_pct"] = str(base["skill_pick_no_pct"])
    if not out["watch_pick"].strip():
        out["watch_pick"] = str(base["watch_pick"])
    if not out["watch_pick_no_pct"].strip():
        out["watch_pick_no_pct"] = str(base["watch_pick_no_pct"])
    if not out["quant_tag"].strip():
        out["quant_tag"] = "量化"
    if not out["skills_tag"].strip() or out["skills_tag"].strip().lower() == "skills":
        out["skills_tag"] = "技能"
    if preset in PRESETS:
        out.update(PRESETS[preset])
    return out


def resolve_kind_tag(kind: str, template: dict[str, Any] | None = None) -> str:
    tpl = normalize_screen_template(template)
    key = str(kind or "").strip().lower()
    if key in {"skills", "skill"}:
        return str(tpl["skills_tag"])
    return str(tpl["quant_tag"])


def format_pct(value: Any) -> str:
    """格式化为 +1.5% / +5% / -2.3%。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(number - round(number)) < 1e-9:
        return f"{number:+.0f}%"
    text = f"{number:+.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def clip_skill_note(text: Any, *, limit: int = SKILL_NOTE_MAX) -> str:
    """技能推送用简要说明，最多 limit 个字。"""
    note = " ".join(str(text or "").strip().split())
    if not note:
        return ""
    if len(note) <= limit:
        return note
    if limit <= 1:
        return note[:limit]
    return note[: limit - 1] + "…"


def extract_skill_note(pick: dict[str, Any], *, limit: int = SKILL_NOTE_MAX) -> str:
    """从 pick 常见字段取一行说明并截断。"""
    for key in (
        "note",
        "wecom_note",
        "summary",
        "thesis",
        "why_now",
        "reason",
        "brief",
        "one_liner",
    ):
        raw = pick.get(key)
        if isinstance(raw, str) and raw.strip():
            return clip_skill_note(raw, limit=limit)
    support = pick.get("support") or pick.get("bull_evidence") or pick.get("evidence")
    if isinstance(support, list):
        for item in support:
            if isinstance(item, str) and item.strip():
                return clip_skill_note(item, limit=limit)
    if isinstance(support, str) and support.strip():
        return clip_skill_note(support, limit=limit)
    return ""


def format_screen_picks_text(
    result: dict[str, Any],
    *,
    kind_tag: str = "量化",
    title: str | None = None,
    template: dict[str, Any] | None = None,
) -> str:
    """按配置渲染选股企微正文（纯 text）。"""
    tpl = normalize_screen_template(template)
    name = _resolve_title(result, title)
    trade_date = str(result.get("trade_date") or "").strip()
    kind = str(kind_tag or tpl["quant_tag"]).strip() or str(tpl["quant_tag"])
    if kind.lower() == "skills":
        kind = str(tpl["skills_tag"])
    skill_mode = kind == str(tpl["skills_tag"]) or str(kind_tag or "").strip().lower() in {
        "skills",
        "skill",
        "技能",
    }
    picks = result.get("picks") or []
    watch_picks = result.get("watch_picks") or []
    max_picks = int(tpl["max_picks"])

    lines: list[str] = []
    header = _fill(
        str(tpl["header"]),
        {"title": name, "kind": kind, "date": trade_date or "—", "note": ""},
    ).strip()
    if header:
        lines.append(header)
    intro = _fill(
        str(tpl["intro"]),
        {"title": name, "kind": kind, "date": trade_date or "—", "note": ""},
    ).rstrip()
    if intro:
        lines.append(intro)

    rendered = _append_pick_rows(
        lines,
        picks,
        tpl=tpl,
        skill_mode=skill_mode,
        max_picks=max_picks,
    )

    if rendered == 0:
        empty = str(tpl["formal_empty"] if watch_picks else tpl["empty"]).strip()
        if empty:
            lines.append(empty)
    elif len(picks) > rendered:
        more = _fill(str(tpl["more"]), {"n": str(len(picks) - rendered), "note": ""}).strip()
        if more:
            lines.append(more)

    if watch_picks:
        watch_header = str(tpl["watch_header"]).strip()
        if watch_header:
            lines.append(watch_header)
        watch_rendered = _append_pick_rows(
            lines,
            watch_picks,
            tpl=tpl,
            skill_mode=False,
            max_picks=max_picks,
            watch_mode=True,
        )
        if len(watch_picks) > watch_rendered:
            more = _fill(
                str(tpl["more"]),
                {"n": str(len(watch_picks) - watch_rendered), "note": ""},
            ).strip()
            if more:
                lines.append(more)
    return "\n".join(lines)


def _append_pick_rows(
    lines: list[str],
    picks: Any,
    *,
    tpl: dict[str, Any],
    skill_mode: bool,
    max_picks: int,
    watch_mode: bool = False,
) -> int:
    rendered = 0
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        code = str(pick.get("code") or "").strip()
        if not code:
            continue
        stock_name = str(pick.get("name") or code).strip() or code
        pct = _pick_pct(pick)
        pct_text = format_pct(pct) if pct is not None else ""
        note = extract_skill_note(pick) if skill_mode else ""
        if watch_mode:
            row_tpl = str(
                tpl["watch_pick"] if pct_text else tpl["watch_pick_no_pct"]
            )
        elif skill_mode and note:
            row_tpl = str(
                tpl["skill_pick"] if pct_text else tpl["skill_pick_no_pct"]
            )
        else:
            row_tpl = str(tpl["pick"] if pct_text else tpl["pick_no_pct"])
        fallback_key = (
            "watch_pick_no_pct"
            if watch_mode
            else ("skill_pick_no_pct" if skill_mode and note else "pick_no_pct")
        )
        if not pct_text and "{pct}" in row_tpl:
            row_tpl = str(tpl[fallback_key])
        row = _fill(
            row_tpl,
            {"name": stock_name, "code": code, "pct": pct_text, "note": note},
        ).strip()
        if row:
            lines.append(row)
        rendered += 1
        if rendered >= max_picks:
            break
    return rendered


def preview_screen_template(
    template: dict[str, Any] | None = None,
    *,
    kind: Literal["quant", "skills"] = "quant",
) -> str:
    """系统设置页用的即时预览。"""
    tpl = normalize_screen_template(template)
    tag = resolve_kind_tag(kind, tpl)
    return format_screen_picks_text(_SAMPLE_RESULT, kind_tag=tag, template=tpl)


def load_screen_template(store: Any) -> dict[str, Any]:
    raw = {}
    if store is not None:
        try:
            raw = store.get_setting("wecom_screen_template", {}) or {}
        except Exception:
            raw = {}
    return normalize_screen_template(raw)


def _resolve_title(result: dict[str, Any], title: str | None) -> str:
    name = (title or "").strip()
    if not name:
        raw = (
            result.get("skill_name")
            or result.get("strategy")
            or result.get("skill")
            or result.get("name")
            or "选股"
        )
        name = str(raw).strip()
    if name.startswith("screen:"):
        name = name[len("screen:") :]
    # 定时任务通常只保存 slug；通知标题必须展示用户能识别的中文名。
    builtin_names = {
        "qianlong-close-v3": "潜龙出海（V3）",
        "qianfu-close": "潜伏（已下线）",
        "qianfu-1450": "潜伏（已下线）",
        "qianlong-tail-v1": "潜龙尾盘（已下线）",
        "lugw-haidi": "海底捞月（已下线）",
        "rsi30-dip": "RSI22 次日低吸（已下线）",
        "sanyuan-tail-v1": "三源尾盘共振（15:30）",
        "yangshi-tail-v1": "杨氏尾盘选股（15:30）",
    }
    name = builtin_names.get(name, name)
    return name or "选股"


def _pick_pct(pick: dict[str, Any]) -> float | None:
    for key in ("pct_chg", "change_pct", "pct", "percent", "close_pct_chg"):
        if pick.get(key) is None:
            continue
        try:
            return float(pick[key])
        except (TypeError, ValueError):
            continue
    return None


def _fill(pattern: str, values: dict[str, str]) -> str:
    text = pattern or ""
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
