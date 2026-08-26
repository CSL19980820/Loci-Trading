"""纸面风格：日教训提炼与吸入人设（从 paper_style_memory 拆出，≤600）。"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_STYLE_CHARS = 6000
_MAX_LESSON_BULLETS = 40


def extract_lessons_from_day(
    *,
    slug: str,
    trade_date: str,
    fills: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    monitor_runs: list[dict[str, Any]],
    style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """确定性评头论足：从成交/拒单/竞价姿态提炼教训（不编造行情数字）。"""
    from src.ops.application.paper_decided_by import normalize_decided_by

    lessons: list[dict[str, Any]] = []
    buy_rules = (style or {}).get("buy_rules") or {}
    no_chase = str(buy_rules.get("gap_up_default") or "no_chase") == "no_chase"

    for reject in rejects:
        reason = str(reject.get("reason") or "")
        code = str(reject.get("code") or "")
        if "情景门闩" in reason or "竞价窗" in reason or "不在次日预案" in reason:
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "mistake",
                    "title": f"{code or '未知'} 被门闩拦住",
                    "content": reason or "试图在预案/竞价约束外买入",
                    "evidence": {"reject": reject},
                }
            )

    for fill in fills:
        action = str(fill.get("action") or "")
        reason = str(fill.get("reason") or "")
        code = str(fill.get("code") or "")
        decided_by = normalize_decided_by(fill.get("decided_by"))
        if action == "open" and no_chase and ("高开" in reason or "gap_up" in reason.lower()):
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "mistake",
                    "title": f"{code} 高开仍开仓",
                    "content": "风格默认高开不追，今日却开仓——下次竞价若高开优先放弃",
                    "evidence": {"fill": fill, "decided_by": decided_by},
                }
            )
        if action in {"take_profit", "trim_high"}:
            from src.ops.application.paper_copy_zh import FILL_ACTION_ZH

            action_zh = FILL_ACTION_ZH.get(action, action)
            lessons.append(
                {
                    "slug": slug,
                    "trade_date": trade_date,
                    "kind": "win",
                    "title": f"{code} {action_zh} 执行",
                    "content": "按纪律减仓/止盈；复盘是否过早或过晚，写入风格微调",
                    "evidence": {"fill": fill, "decided_by": decided_by},
                }
            )

    revise_n = 0
    abandon_n = 0
    follow_n = 0
    for run in monitor_runs:
        # 只计 started_at 属于当日的 run；禁止跨日 stance 污染当日教训
        if not str(run.get("started_at") or "").startswith(trade_date):
            continue
        snap = run.get("snapshot") if isinstance(run.get("snapshot"), dict) else {}
        for stance in snap.get("auction_stances") or []:
            if not isinstance(stance, dict):
                continue
            s = str(stance.get("stance") or "")
            if s == "revise":
                revise_n += 1
            elif s == "abandon":
                abandon_n += 1
            elif s == "follow":
                follow_n += 1

    if revise_n >= 2:
        lessons.append(
            {
                "slug": slug,
                "trade_date": trade_date,
                "kind": "revise",
                "title": "竞价多次纠偏",
                "content": f"今日至少 {revise_n} 次落在买点外——检查区间是否过窄，或高开/低开想法要改",
                "evidence": {"revise_count": revise_n},
            }
        )
    if abandon_n and follow_n == 0 and not fills:
        lessons.append(
            {
                "slug": slug,
                "trade_date": trade_date,
                "kind": "note",
                "title": "全日放弃未开仓",
                "content": "竞价/开盘对照后放弃且无成交——可能是纪律正确，记下触发条件以免下次手痒",
                "evidence": {"abandon_count": abandon_n},
            }
        )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for lesson in lessons:
        key = str(lesson.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(lesson)
    return unique


def build_day_critique(
    *,
    slug: str,
    trade_date: str,
    positions: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    lessons: list[dict[str, Any]],
) -> str:
    from src.ops.application.paper_copy_zh import lesson_kind_zh, strategy_display_name

    label = strategy_display_name(slug)
    lines = [
        f"【评头论足】{label} · {trade_date}",
        f"持仓 {len(positions)} · 成交 {len(fills)} · 拒单 {len(rejects)} · 教训 {len(lessons)}",
    ]
    for lesson in lessons[:12]:
        lines.append(
            f"- [{lesson_kind_zh(lesson.get('kind'))}] "
            f"{lesson.get('title') or '暂无'}：{lesson.get('content') or '暂无'}"
        )
    if not lessons:
        lines.append("- 本日无新增教训；保持情景纪律即可")
    return "\n".join(lines)


def _upsert_lesson_section(style_md: str, bullets: list[str]) -> str:
    from src.ops.application.paper_style_memory import default_style_md

    text = style_md.strip() or default_style_md("strategy")
    section = "## 教训（滚动）"
    block = section + "\n" + "\n".join(bullets)
    if section in text:
        pattern = re.compile(r"## 教训（滚动）[\s\S]*?(?=\n## |\Z)")
        text = pattern.sub(block.strip() + "\n", text, count=1)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    if len(text) > _MAX_STYLE_CHARS:
        text = text[: _MAX_STYLE_CHARS - 20] + "\n…(截断)\n"
    return text


def absorb_lessons_into_style(store: Any, slug: str, *, limit: int = 20) -> dict[str, Any]:
    """把未吸收教训并入风格记忆正文。"""
    from src.ops.application.paper_style_memory import (
        _DEFAULT_WATCH,
        ensure_style,
    )

    style = ensure_style(store, slug)
    pending = store.list_paper_lessons(slug, limit=limit, unabsorbed_only=True)
    if not pending:
        return {"absorbed": 0, "style": style}

    existing_bullets: list[str] = []
    section = "## 教训（滚动）"
    if section in (style.get("style_md") or ""):
        part = (style["style_md"].split(section, 1)[1] or "").split("\n## ", 1)[0]
        for line in part.splitlines():
            line = line.strip()
            if line.startswith("- ") and "日终自动追加" not in line:
                existing_bullets.append(line)

    new_bullets = [
        f"- [{les.get('trade_date')}][{les.get('kind')}] {les.get('title')}：{les.get('content')}"
        for les in pending
    ]
    merged = (new_bullets + existing_bullets)[:_MAX_LESSON_BULLETS]
    if not merged:
        merged = ["- （暂无）"]

    buy_rules = dict(style.get("buy_rules") or {})
    watch = list(style.get("watch_hints") or _DEFAULT_WATCH)
    for les in pending:
        if les.get("kind") == "mistake" and "高开" in str(les.get("title") or ""):
            buy_rules["gap_up_default"] = "no_chase"
            hint = "高开追价曾吃亏：竞价高开优先 abandon"
            if hint not in watch:
                watch.insert(0, hint)
        if les.get("kind") == "revise":
            hint = "买点区间多次 revise：次日预案放宽或写清例外"
            if hint not in watch:
                watch.insert(0, hint)

    next_md = _upsert_lesson_section(str(style.get("style_md") or ""), merged)
    updated = store.upsert_paper_style(
        slug,
        style_md=next_md,
        watch_hints=watch[:12],
        buy_rules=buy_rules,
        bump_revision=True,
    )
    store.mark_paper_lessons_absorbed([str(x["id"]) for x in pending if x.get("id")])
    try:
        from src.ops.application.paper_memory_graph import (
            ingest_lesson_to_graph,
            sync_style_doc_to_graph,
        )

        sync_style_doc_to_graph(store, slug, updated)
        for les in pending:
            ingest_lesson_to_graph(store, les)
    except Exception:  # noqa: BLE001
        logger.warning("ingest lessons to memory graph failed for %s", slug, exc_info=True)
    return {"absorbed": len(pending), "style": updated}
