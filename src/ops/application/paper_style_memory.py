"""战法级交易风格记忆与日终学习编排。

与全局助手 `ai_memories` 隔离：这里只服务纸面量化舱（每 slug 一份）。
默认日终**不**落教训/不吸入人设；仅当舱配置 ``eod_style_learn=true`` 时才评头论足→写 lessons→吸入 style_md。

教训提炼/吸入见 ``paper_style_lessons``（本模块再导出以保持旧 import 路径）。
"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.paper_style_lessons import (
    absorb_lessons_into_style,
    build_day_critique,
    extract_lessons_from_day,
)

logger = logging.getLogger(__name__)

_DEFAULT_WATCH = [
    "开盘情景下仓位与价位带是否要动态调整",
    "过高时减层 / 等回踩 / 本情景暂缓（不是对错）",
    "09:15-09:25 竞价纠偏：跟随 / 改计划 / 放弃 / 观望",
]

_DEFAULT_WATCH_NEXT_OPEN = [
    "T+1 开盘基线承接；过高时减层或等回踩舒适带",
    "一字/近涨停放弃——极端择位，不是『高开=错』",
    "持有期止损/到期卖出是否按战法执行",
]


def strategy_display_name(slug: str) -> str:
    """给人看的战法名；查不到注册表时用「本战法」。"""
    from src.ops.application.paper_copy_zh import strategy_display_name as _name

    return _name(slug)


def default_style_md(slug: str, *, entry_mode: str = "scenario") -> str:
    from src.ops.application.paper_copy_zh import strategy_display_name as _name

    label = _name(slug)
    if entry_mode == "next_open":
        buy_lines = [
            "- 基线：T+1 开盘接（高/平/低开同权）",
            "- 动态：过高可减层或等回踩舒适带再补；一字/近涨停放弃",
            "- 预案调的是仓位与价位，不是对错判决；不看分时分批、不补仓（按战法）",
        ]
        watch = _DEFAULT_WATCH_NEXT_OPEN
    else:
        buy_lines = [
            "- 平开：按计划层数接",
            "- 高开过高：减层、等回踩或本情景暂缓（可显式浅接）——动态择位",
            "- 低开：低吸带内接；深砸暂缓另议",
        ]
        watch = _DEFAULT_WATCH
    return "\n".join(
        [
            f"# 交易风格 · {label}",
            "",
            "## 该怎么买",
            *buy_lines,
            "",
            "## 该看哪些",
            *[f"- {h}" for h in watch],
            "",
            "## 教训（滚动）",
            "- （日终自动追加；AI/规则吸取后写入此处）",
            "",
        ]
    )


def _default_buy_rules(entry_mode: str) -> dict[str, Any]:
    if entry_mode == "next_open":
        return {
            "gap_up_default": "buy_at_open",
            "flat_default": "buy_at_open",
            "gap_down_default": "buy_at_open",
            "auction": "judge_only_until_0925",
            "veto": "limit_up_one_word_skip",
            "entry_mode": "next_open",
        }
    return {
        "gap_up_default": "no_chase",
        "flat_default": "buy_in_band",
        "gap_down_default": "buy_dip_in_band",
        "auction": "judge_only_until_0925",
        "entry_mode": "scenario",
    }


def ensure_style(
    store: Any, slug: str, *, entry_mode: str | None = None
) -> dict[str, Any]:
    from src.ops.application.nextday_plan import resolve_entry_mode

    mode = entry_mode or resolve_entry_mode(slug)
    style = store.get_paper_style(slug)
    if style.get("style_md"):
        from src.ops.application.paper_memory_graph import seed_default_graph

        if not store.list_paper_mem_nodes(slug, limit=1):
            seed_default_graph(store, slug, entry_mode=mode)
        # 潜龙等 next_open：纠正旧「高开不追 / 纯对错」文案为动态调仓择位
        rules = style.get("buy_rules") if isinstance(style.get("buy_rules"), dict) else {}
        md = str(style.get("style_md") or "")
        stale = (
            str(rules.get("gap_up_default") or "") == "no_chase"
            or "高开不追" in md
            or "动态" not in md
        )
        if mode == "next_open" and stale:
            style = store.upsert_paper_style(
                slug,
                style_md=default_style_md(slug, entry_mode=mode),
                watch_hints=list(_DEFAULT_WATCH_NEXT_OPEN),
                buy_rules=_default_buy_rules(mode),
                bump_revision=True,
            )
            seed_default_graph(store, slug, entry_mode=mode)
        return style
    style = store.upsert_paper_style(
        slug,
        style_md=default_style_md(slug, entry_mode=mode),
        watch_hints=list(
            _DEFAULT_WATCH_NEXT_OPEN if mode == "next_open" else _DEFAULT_WATCH
        ),
        buy_rules=_default_buy_rules(mode),
        bump_revision=True,
    )
    from src.ops.application.paper_memory_graph import seed_default_graph

    seed_default_graph(store, slug, entry_mode=mode)
    return style


def style_prompt_block(style: dict[str, Any], *, lessons: list[dict[str, Any]] | None = None) -> str:
    """注入 LLM / 规则旁注的紧凑风格块（优先附带记忆子图摘要）。"""
    from src.ops.application.paper_copy_zh import buy_rules_zh, lesson_kind_zh

    lines = [
        "【本战法交易风格记忆】",
        (style.get("style_md") or "")[:2200],
    ]
    hints = style.get("watch_hints") or []
    if hints:
        lines.append("该看：" + "；".join(str(h) for h in hints[:8]))
    rules = style.get("buy_rules") or {}
    if isinstance(rules, dict) and rules:
        lines.append("买法摘要：" + buy_rules_zh(rules))
    recent = lessons or []
    if recent:
        lines.append("近期未吸收教训：")
        for lesson in recent[:8]:
            lines.append(
                f"- [{lesson_kind_zh(lesson.get('kind'))}] "
                f"{lesson.get('title') or '暂无'}：{lesson.get('content') or '暂无'}"
            )
    return "\n".join(lines).strip()


def style_and_graph_prompt(store: Any, slug: str) -> str:
    """文档记忆 + 知识图 explore 子图，供预案/盯盘注入。"""
    style = ensure_style(store, slug)
    pending = store.list_paper_lessons(slug, limit=8, unabsorbed_only=True)
    doc = style_prompt_block(style, lessons=pending)
    try:
        from src.ops.application.paper_memory_graph import graph_prompt_block

        graph = graph_prompt_block(store, slug)
        if graph:
            return f"{doc}\n\n{graph}"
    except Exception:  # noqa: BLE001
        logger.warning("memory graph prompt failed for %s", slug, exc_info=True)
    return doc


def optional_llm_critique(
    *,
    model: str,
    thinking: str,
    critique_seed: str,
    style_md: str,
    lookback_text: str = "",
    store: Any | None = None,
    timeout_seconds: float = 1800.0,
) -> str:
    """可选：用模型润色评头论足（失败则返回空，不阻断日终）。"""
    if not model.strip():
        return ""
    if store is None:
        logger.warning("style llm critique skipped: missing ops store")
        return ""
    try:
        from src.ai import ChatMessage, chat_text_with_thinking_fallback, resolve_config

        config = resolve_config(store, model=model or "", timeout=timeout_seconds)
        system = (
            "你是战法纸面量化的复盘教练。必须基于「五交易日回看包」评头论足："
            "买过的、错过的（入池日早于复盘日且未买）、今日新入池、卖过的，对照完整日K；"
            "并分析窗口内环境（量能、涨跌家数、板块/行业）。"
            "硬约束：status=new_pick / 「今日新入池」的票禁止写成错过、踏空、零参与错误或五日窗踏空；"
            "只能写「今日才入池，执行看次日情景」；错过收益只看入池后 since_attention_return。"
            "指出真正的错过上涨、卖飞、逆势买入等纪律问题；资金流若标记 not_observed 不得编造。"
            "只使用给定事实数字；禁止编造未给出的价格、盈亏或板块涨幅。"
            "输出简洁中文要点（≤600字），分：环境 / 买对买错 / 错过与新入池 / 下五日纪律。"
        )
        user = (
            f"现有风格：\n{style_md[:1800]}\n\n"
            f"日终事实：\n{critique_seed}\n\n"
            f"五交易日回看：\n{lookback_text[:8000]}"
        )
        return chat_text_with_thinking_fallback(
            config,
            [ChatMessage(role="user", content=user)],
            system=system,
            thinking=thinking or "",
            max_tokens=4096,
            temperature=0.3,
            log=logger,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("style llm critique failed: %s", exc)
        return ""


def clear_paper_cabin_memory(store: Any, slug: str) -> dict[str, Any]:
    """清空舱级风格人设 / 教训 / 记忆图，不动持仓成交。"""
    counts = store.clear_paper_cabin_memory(slug)
    return {"slug": slug, **counts}


def run_eod_learning(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    positions: list[dict[str, Any]],
    fills_today: list[dict[str, Any]],
    rejects_today: list[dict[str, Any]] | None = None,
    model: str = "",
    thinking: str = "medium",
    market: Any | None = None,
    lookback: int = 5,
    include_capital_flow: bool = False,
    persist_memory: bool = False,
    llm_timeout_sec: float = 1800.0,
) -> dict[str, Any]:
    """日终回看。

    默认只产出五日回看 digest（给人看/推送），**不**写教训、不吸入风格、不长记忆图。
    ``persist_memory=True``（舱配置 ``eod_style_learn``）才走评头论足→落库→吸入人设。
    """
    from src.ops.application.paper_copy_zh import format_lookback_digest
    from src.ops.application.paper_decided_by import count_fills_by_decided_by

    lookback_pack: dict[str, Any] | None = None
    lookback_text = ""
    if market is not None:
        try:
            from src.ops.application.paper_eod_review import (
                build_eod_lookback_pack,
                format_lookback_for_prompt,
            )

            lookback_pack = build_eod_lookback_pack(
                store,
                market,
                slug=slug,
                trade_date=trade_date,
                lookback=lookback,
                include_capital_flow=include_capital_flow,
            )
            lookback_text = format_lookback_for_prompt(lookback_pack)
        except Exception:  # noqa: BLE001
            logger.warning("eod lookback pack failed for %s", slug, exc_info=True)
            lookback_pack = None
            lookback_text = "【五交易日回看】构建失败（not_observed），不得编造 K 线"

    fills_by_decided_by = count_fills_by_decided_by(fills_today)
    lookback_digest = format_lookback_digest(lookback_pack)
    lookback_summary = (
        {
            "days": (lookback_pack or {}).get("lookback_trading_days"),
            "universe_size": (lookback_pack or {}).get("universe_size"),
            "fills_by_decided_by": (lookback_pack or {}).get("fills_by_decided_by"),
            "bought": (lookback_pack or {}).get("bought"),
            "missed": (lookback_pack or {}).get("missed"),
            "new_picks": (lookback_pack or {}).get("new_picks"),
            "sold": (lookback_pack or {}).get("sold"),
            "environment": (lookback_pack or {}).get("environment"),
        }
        if lookback_pack
        else None
    )

    if not persist_memory:
        return {
            "critique": "",
            "lookback_digest": lookback_digest,
            "lessons": [],
            "absorbed": 0,
            "style": store.get_paper_style(slug),
            "lookback": lookback_summary,
            "fills_by_decided_by": fills_by_decided_by,
            "persist_memory": False,
        }

    style = ensure_style(store, slug)
    runs = store.list_monitor_runs(slug, limit=40)
    rejects = list(rejects_today or [])
    if not rejects:
        for run in runs:
            if trade_date in str(run.get("started_at") or ""):
                rejects.extend(run.get("rejects") or [])

    lessons_miss: list[dict[str, Any]] = []
    if lookback_pack is not None:
        try:
            from src.ops.application.paper_eod_review import extract_miss_lessons_from_pack

            lessons_miss = extract_miss_lessons_from_pack(
                slug=slug, trade_date=trade_date, pack=lookback_pack
            )
        except Exception:  # noqa: BLE001
            logger.warning("eod miss lessons failed for %s", slug, exc_info=True)

    lessons = extract_lessons_from_day(
        slug=slug,
        trade_date=trade_date,
        fills=fills_today,
        rejects=rejects,
        monitor_runs=runs,
        style=style,
    )
    lessons.extend(lessons_miss)

    saved = [store.add_paper_lesson(les) for les in lessons]
    try:
        from src.ops.application.paper_memory_graph import ingest_lesson_to_graph, seed_default_graph

        seed_default_graph(store, slug)
        for les in saved:
            ingest_lesson_to_graph(store, les)
    except Exception:  # noqa: BLE001
        logger.warning("lesson graph ingest failed for %s", slug, exc_info=True)

    critique = build_day_critique(
        slug=slug,
        trade_date=trade_date,
        positions=positions,
        fills=fills_today,
        rejects=rejects,
        lessons=lessons,
    )

    llm_extra = optional_llm_critique(
        model=model,
        thinking=thinking,
        critique_seed=(critique + ("\n\n" + lookback_digest if lookback_digest else ""))[:4000],
        style_md=str(style.get("style_md") or ""),
        lookback_text=lookback_text,
        store=store,
        timeout_seconds=llm_timeout_sec,
    )
    if llm_extra:
        critique = critique + "\n\n【AI评头论足】\n" + llm_extra
        store.add_paper_lesson(
            {
                "slug": slug,
                "trade_date": trade_date,
                "kind": "critique",
                "title": "AI评头论足（含五日回看）",
                "content": llm_extra[:1000],
                "evidence": {
                    "lookback_days": (lookback_pack or {}).get("lookback_trading_days"),
                    "universe_size": (lookback_pack or {}).get("universe_size"),
                },
            }
        )

    absorbed = absorb_lessons_into_style(store, slug)
    return {
        "critique": critique,
        "lookback_digest": lookback_digest,
        "lessons": saved,
        "absorbed": absorbed.get("absorbed", 0),
        "style": absorbed.get("style") or store.get_paper_style(slug),
        "lookback": lookback_summary,
        "fills_by_decided_by": fills_by_decided_by,
        "persist_memory": True,
    }


__all__ = [
    "_DEFAULT_WATCH",
    "_DEFAULT_WATCH_NEXT_OPEN",
    "_default_buy_rules",
    "absorb_lessons_into_style",
    "build_day_critique",
    "clear_paper_cabin_memory",
    "default_style_md",
    "ensure_style",
    "extract_lessons_from_day",
    "optional_llm_critique",
    "run_eod_learning",
    "strategy_display_name",
    "style_and_graph_prompt",
    "style_prompt_block",
]
