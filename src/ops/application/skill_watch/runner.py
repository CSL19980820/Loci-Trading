"""Skill watch 编排：按信号引擎扫描，输出可审计的纸面提示。

调度由系统的 ``skill_watch`` Job 决定；本模块只管「扫一次并给信号」。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from datetime import datetime

from src.ops.application.jobs.context import JobError
from src.ops.application.skill_strategy_config import declared_signals, signal_engine_of
from src.ops.application.skill_watch.engine_registry import engine_spec, engine_target
from src.ops.application.skill_watch.tuning import load_tuning, stage_enabled

logger = logging.getLogger(__name__)

ALL_SIGNALS = (
    "buy_hint",
    "sell_hint",
    "watch_only",
    "paper_candidate",
    "gate_empty",
    "invalidated",
    "leader_watch",
    "leader_weak",
    "theme_interval_weak",
    "theme_interval_degraded",
)

def _load_scanner(engine: str) -> Callable[..., dict[str, Any]] | None:
    """引擎名 → 扫描函数。新增战法只加注册表条目，不写 if 丛林。"""
    target = engine_target(engine)
    if target is None:
        return None
    module_name, func_name = target.split(":")
    module = __import__(
        f"src.ops.application.skill_watch.{module_name}", fromlist=[func_name]
    )
    return getattr(module, func_name)


def skill_watch_mcp_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """战法监测旧入口：转交 market tape bridge。

    保留函数名是为了兼容旧 job；tape lane 不再从 ops 直接触碰 MCP。
    """
    from src.market import legacy_call_tool

    return legacy_call_tool(name, args)


def _default_call_tool(
    *, market_store: Any | None = None
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """盘中扫描统一走 market tape router。"""
    from src.market import make_legacy_tape_call

    return make_legacy_tape_call(store=market_store)


def wudao_availability_for_watch() -> dict[str, Any]:
    """返回悟道可选线路状态，供设置页/兼容调用方展示，不作为扫描硬闸门。"""
    try:
        from src.intel import wudao_availability
    except ImportError as exc:  # noqa: BLE001 — 精简部署可能不带 intel
        return {"available": False, "reason": f"情报模块不可用：{getattr(exc, 'name', exc)}"}
    return wudao_availability()


def _merge_live_observes(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    result: dict[str, Any],
    current_picks: list[dict[str, Any]],
    tuning: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把盘中扫描合并进唯一池，避免题材轮动抹掉仍健康的旧龙。"""
    if not trade_date:
        return current_picks, {}
    if not stage_enabled(tuning, "paper_candidates"):
        return current_picks, {}

    from src.ops.application.jobs.paper_quant_support import load_live_pool
    from src.ops.application.skill_watch.observe_pool import (
        merge_observe_pool,
        split_observe_upgraded_to_buy,
    )
    from src.ops.application.skill_watch.paper_eligibility import is_observe_intent

    previous = load_live_pool(store, slug=slug, trade_date=trade_date)
    if previous is None:
        return current_picks, {}

    scan_cfg = tuning.get("scan") if isinstance(tuning.get("scan"), dict) else {}
    entries: list[dict[str, Any]] = []
    entries.extend(row for row in result.get("entries") or [] if isinstance(row, dict))
    leader_map = result.get("leader_map")
    if isinstance(leader_map, dict):
        for key in ("leaders", "weakened"):
            entries.extend(row for row in leader_map.get(key) or [] if isinstance(row, dict))
    # 龙王 ranked 含个股涨停强度对题材内 secondary 的纠偏，须最后覆盖原始角色。
    if slug == "dragon-return":
        entries.extend(row for row in result.get("ranked") or [] if isinstance(row, dict))
    by_code = {
        str(row.get("code") or "").strip(): row
        for row in entries
        if str(row.get("code") or "").strip()
    }
    excluded = {
        str(code).strip()
        for code in result.get("auction_excluded") or []
        if str(code).strip()
    }

    previous_observes: list[dict[str, Any]] = []
    explicitly_removed: list[dict[str, Any]] = []
    for item in previous:
        if not isinstance(item, dict) or not is_observe_intent(item):
            continue
        code = str(item.get("code") or "").strip()
        current = by_code.get(code)
        if code in excluded:
            explicitly_removed.append(
                {
                    "code": code,
                    "name": item.get("name") or code,
                    "score": item.get("score"),
                    "reason": "竞价否决，移出观察池",
                }
            )
            continue
        if current is not None:
            role = str(current.get("role") or "").strip().lower()
            if role in {"follower", "weakened", "failed"}:
                explicitly_removed.append(
                    {
                        "code": code,
                        "name": item.get("name") or code,
                        "score": item.get("score"),
                        "reason": str(current.get("role_basis") or "角色走弱/结构破坏"),
                    }
                )
                continue
            if slug == "dragon-return" and role != "leader":
                explicitly_removed.append(
                    {
                        "code": code,
                        "name": item.get("name") or code,
                        "score": item.get("score"),
                        "reason": "龙王战法只保留龙头，中军移出观察池",
                    }
                )
                continue
            refreshed = dict(item)
            for key in ("name", "role", "role_label", "role_basis", "theme_code", "theme_name"):
                if current.get(key) is not None:
                    refreshed[key] = current[key]
            previous_observes.append(refreshed)
            continue
        if slug == "dragon-return" and str(item.get("role") or "").strip().lower() != "leader":
            explicitly_removed.append(
                {
                    "code": code,
                    "name": item.get("name") or code,
                    "score": item.get("score"),
                    "reason": "龙王战法只保留龙头，中军移出观察池",
                }
            )
            continue
        # 题材跌出当前前三只代表本轮未扫描到，不是走弱证据，继续续盯。
        previous_observes.append(dict(item))

    buy_rows = [row for row in current_picks if not is_observe_intent(row)]
    fresh_observes = [row for row in current_picks if is_observe_intent(row)]
    previous_observes, upgraded = split_observe_upgraded_to_buy(previous_observes, buy_rows)
    held_codes: set[str] = set()
    try:
        cabin = store.get_paper_cabin(slug) if hasattr(store, "get_paper_cabin") else None
        if isinstance(cabin, dict) and hasattr(store, "list_paper_positions"):
            held_codes = {
                str(row.get("code") or "").strip()
                for row in store.list_paper_positions(str(cabin.get("id") or ""))
                if str(row.get("code") or "").strip()
            }
    except Exception as exc:  # noqa: BLE001 — 持仓读取失败不应清空观察池
        logger.warning("load held codes failed for %s: %s", slug, exc)
    pool, report = merge_observe_pool(
        held_codes=held_codes,
        fresh_observes=fresh_observes,
        previous_items=previous_observes,
        min_score=float(scan_cfg.get("observe_min_score") or 50),
        max_pool=int(scan_cfg.get("max_observe_pool") or 5),
        max_daily_adds=int(scan_cfg.get("max_observe") or 2),
        replace_margin=float(scan_cfg.get("observe_replace_margin") or 8),
        # miss_days / age_days 是交易日级规则，不能按每 10 分钟的盘中轮次递增。
        trade_date=None,
        max_miss_days=int(scan_cfg.get("observe_max_miss_days") or 2),
        max_same_theme=int(scan_cfg.get("observe_max_same_theme") or 2),
        max_age_days=int(scan_cfg.get("observe_max_age_days") or 10),
    )
    if explicitly_removed:
        report["dropped"] = explicitly_removed + list(report.get("dropped") or [])
        report["changed"] = True
    if upgraded:
        report["upgraded"] = upgraded
        report["changed"] = True
    return [*buy_rows, *pool], report


def _record_role_history(
    *,
    store: Any,
    slug: str,
    tuning: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """把本次角色判定追加进留痕表，并回带最近的角色变化。

    留痕失败只降级为空历史——盯盘信号比归档重要，不能因为写库出错就丢信号。
    """
    entries = result.get("entries")
    if store is None or not stage_enabled(tuning, "role_history") or not isinstance(entries, list):
        return {"recorded": 0, "transitions": [], "role_history": []}
    final_entries = [dict(row) for row in entries if isinstance(row, dict)]
    if slug == "dragon-return":
        ranked_by_code = {
            str(row.get("code") or "").strip(): row
            for row in result.get("ranked") or []
            if isinstance(row, dict) and str(row.get("code") or "").strip()
        }
        seen_codes: set[str] = set()
        for index, row in enumerate(final_entries):
            code = str(row.get("code") or "").strip()
            if code:
                seen_codes.add(code)
            if code in ranked_by_code:
                final_entries[index] = {**row, **ranked_by_code[code]}
        final_entries.extend(
            dict(row) for code, row in ranked_by_code.items() if code not in seen_codes
        )
    gate = result.get("market_gate") if isinstance(result.get("market_gate"), dict) else {}
    try:
        recorded = store.record_leader_roles(
            slug,
            trade_date=str(result.get("trade_date") or ""),
            observed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            gate_state=str(gate.get("state") or ""),
            entries=final_entries,
        )
        from src.ops.application.skill_watch.role_stats import role_transitions

        # 一次读库同时喂 transitions 与调参建议，避免 runner 再打 2000 行。
        role_history = store.list_leader_roles(slug, limit=600)
        return {
            "recorded": recorded,
            "transitions": role_transitions(role_history, limit=10),
            "role_history": role_history,
        }
    except Exception as exc:  # noqa: BLE001 — 归档失败不该毁掉本次信号
        logger.warning("skill_watch 角色留痕失败 %s：%s", slug, exc)
        return {"recorded": 0, "transitions": [], "role_history": []}


def _ai_summary(
    *,
    store: Any,
    skill: dict[str, Any],
    config: dict[str, Any],
    signals: list[dict[str, Any]],
) -> str:
    provider_name = str(config.get("provider") or "").strip()
    if not provider_name:
        return ""
    try:
        from src.ai import ChatMessage, chat, resolve_config
        from dataclasses import replace

        from src.ops.application.jobs.paper_quant_support import paper_llm_timeout_sec

        provider = resolve_config(store, provider_name, model=str(config.get("model") or ""))
        # 扫描摘要与纸面决策共用慢推理预算，避免同一轮先在摘要阶段被短超时截断。
        provider = replace(provider, timeout=paper_llm_timeout_sec(config))
        compact = [
            {
                "type": s.get("type"),
                "code": s.get("code"),
                "title": s.get("title") or s.get("message") or "",
            }
            for s in signals
            if isinstance(s, dict)
        ]
        prompt = (
            f"战法 {skill.get('name') or skill.get('slug')} 本次扫描命中信号：\n"
            f"{compact}\n\n"
            "用 3 行以内中文概括：已观察到的证据、关键风险、下一步观察点。"
            "不要使用买入、卖出、介入、加仓等指令性措辞，也不要改变规则信号。"
            "只能基于以上信号，不要编造未给出的代码或价格。"
        )
        response = chat(
            provider,
            [ChatMessage(role="user", content=prompt)],
            max_tokens=512,
            temperature=0.2,
            thinking=str(config.get("thinking") or "off"),
        )
        return str(response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 — AI 只是增强，失败不该毁掉信号
        logger.warning("skill_watch AI 摘要失败 %s：%s", skill.get("slug"), exc)
        return ""


def run_skill_watch(
    config: dict[str, Any],
    *,
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    store: Any | None = None,
    market_store: Any | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """跑一轮战法监测。

    ``persist=False`` 供 watch-preview 试跑：仍读 tuning 与上一轮池状态（否则
    预览结果不准），但不写角色留痕、不合并统一池。
    """
    slug = str(config.get("skill") or config.get("slug") or "").strip()
    if not slug:
        raise JobError("skill_watch 需要 skill/slug")

    from src.ops.application.skills import resolve_skill

    skill = resolve_skill(slug)
    if skill is None:
        raise JobError(f"未安装技能：{slug}")
    if not skill.get("enabled", True):
        return {"skipped": True, "reason": "skill_disabled", "slug": slug}

    engine = signal_engine_of(skill)
    scanner = _load_scanner(engine)
    if scanner is None:
        return {"skipped": True, "reason": "no_signal_engine", "slug": slug, "engine": engine}

    tuning = load_tuning(store, slug)
    effective_call_tool = call_tool or _default_call_tool(market_store=market_store)
    scan_kwargs: dict[str, Any] = {"tuning": tuning}
    spec = engine_spec(engine)
    if market_store is not None and spec is not None and spec.needs_market_store:
        scan_kwargs["market_store"] = market_store
    if store is not None and spec is not None and spec.needs_ops_store:
        # 只有自带跨轮状态机的引擎收 store，也只有它需要知道本轮是否落盘。
        scan_kwargs["store"] = store
        scan_kwargs["persist"] = persist
    result = scanner(effective_call_tool, **scan_kwargs)
    history = _record_role_history(
        store=store if persist else None, slug=slug, tuning=tuning, result=result
    )

    from src.ops.application.skill_watch.paper_eligibility import filter_openable_picks

    raw_picks = result.get("picks") if isinstance(result.get("picks"), list) else []
    # 幂等二次过滤：扫描器可能已滤过；空 auction_excluded 也不能跳过防御
    openable, excluded = filter_openable_picks(raw_picks)
    excluded_codes = [
        str(row.get("code"))
        for row in excluded
        if isinstance(row, dict) and row.get("code")
    ]
    observe_changes: dict[str, Any] = {}
    pool_merge_warning = ""
    if persist and store is not None and spec is not None and spec.emits_observe:
        try:
            openable, observe_changes = _merge_live_observes(
                store,
                slug=slug,
                trade_date=str(result.get("trade_date") or ""),
                result=result,
                current_picks=openable,
                tuning=tuning,
            )
        except Exception as exc:  # noqa: BLE001 — 池合并失败不阻断当轮新扫描
            logger.warning("merge live observes failed for %s: %s", slug, exc)
            pool_merge_warning = "统一监察池合并失败，已保留上一快照"
    # 盘中只认一份当日池；规则合并后的空结果同样落盘，确保明确移出立即生效。
    unified_snapshot: dict[str, Any] | None = None
    if persist and store is not None:
        try:
            from src.ops.application.jobs.paper_quant_support import save_live_pool
            from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

            if not pool_merge_warning:
                save_live_pool(
                    store,
                    slug=slug,
                    trade_date=str(result.get("trade_date") or ""),
                    picks=openable,
                )
            unified_snapshot = get_unified_monitor_pool(
                store,
                slug=slug,
                trade_date=str(result.get("trade_date") or ""),
            )
        except Exception as exc:  # noqa: BLE001 — 盘中池落盘失败不阻断监测摘要
            logger.warning("save live pool failed for %s: %s", slug, exc)

    suggestions: list[dict[str, Any]] = []
    if store is not None:
        try:
            from src.ops.application.skill_watch.role_stats import suggest_tuning_adjustments

            role_history = history.get("role_history") or []
            # role_history 段关闭时不二次 list_leader_roles（避免白打 600 行）
            if (
                not role_history
                and stage_enabled(tuning, "role_history")
                and hasattr(store, "list_leader_roles")
            ):
                role_history = store.list_leader_roles(slug, limit=600)
            suggestions = suggest_tuning_adjustments(role_history, current_tuning=tuning)
        except Exception as exc:  # noqa: BLE001 — 建议失败不该毁掉扫描
            logger.warning("suggest_tuning_adjustments failed: %s", exc)
            suggestions = []

    allowed = set(declared_signals(skill) or ALL_SIGNALS)
    # 旧安装包可能仍只声明 buy_hint；引擎自带的信号不能因旧 manifest 被静默丢弃。
    if spec is not None:
        allowed.update(spec.signals)
    signals = [s for s in result.get("signals") or [] if s.get("type") in allowed]
    skill_name = str(skill.get("name") or slug)

    from src.ops.application.skill_watch.watch_summary import format_watch_summary

    body = format_watch_summary(
        skill_name=skill_name,
        slug=slug,
        trade_date=str(result.get("trade_date") or ""),
        gate=result.get("market_gate") if isinstance(result.get("market_gate"), dict) else None,
        auction=result.get("auction") if isinstance(result.get("auction"), dict) else None,
        signals=signals,
        picks=(unified_snapshot or {}).get("items") or openable,
        transitions=history["transitions"],
        themes=result.get("themes") if isinstance(result.get("themes"), list) else None,
        leaders=(
            (result.get("leader_map") or {}).get("leaders")
            if isinstance(result.get("leader_map"), dict)
            else None
        ),
        observe_changes=observe_changes,
    )
    if slug != "dragon-return" and observe_changes.get("changed"):
        from src.ops.application.skill_watch.observe_pool import format_observe_change_report

        change_text = format_observe_change_report(observe_changes)
        if change_text:
            body = f"{body}\n\n{change_text}".strip()

    ai_note = ""
    if signals and store is not None and config.get("watch_use_ai", False):
        ai_note = _ai_summary(store=store, skill=skill, config=config, signals=signals)
        if ai_note:
            body = f"{body}\n\n{ai_note}".strip()

    # 引擎 extras（market_gate / auction / themes…）先铺底；runner 出口字段后写，
    # 避免 result["picks"] 盖掉 paper_eligibility 过滤结果，或冲掉 suggestions。
    _owned = {
        "signals",
        "picks",
        "auction_excluded",
        "suggestions",
        "slug",
        "engine",
        "available",
        "tuning",
        "role_transitions",
        "roles_recorded",
        "validation",
        "validation_label",
        "summary",
        "ai_summary",
        "tape_readiness",
        "provider_id",
        "provider_ids",
        "warnings",
        "observe_changes",
    }
    # provider 不可用只是数据质量降级；扫描已执行，闸门自己负责 fail-closed。
    # 热路径不再默认重探测 tape_readiness（会触发各 provider is_available，
    # 本地题材 lane 尤贵）；仅透传闸门已有健康字段。
    gate = result.get("market_gate") if isinstance(result.get("market_gate"), dict) else {}
    readiness: dict[str, Any] = {
        "ready": str(gate.get("data_status") or "") not in {"degraded", "error", "missing"},
        "skipped": True,
        "missing_lanes": [],
        "source": "market_gate",
        "data_status": gate.get("data_status"),
    }
    if config.get("probe_tape_readiness"):
        try:
            from src.market import tape_readiness

            readiness = tape_readiness(
                trade_date=str(result.get("trade_date") or ""),
                store=market_store,
            )
            readiness["skipped"] = False
        except Exception as exc:  # noqa: BLE001 — 健康元数据失败不毁掉扫描结果
            readiness = {
                "ready": False,
                "skipped": False,
                "missing_lanes": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
    audit_warnings = list(
        dict.fromkeys(
            [
                *(str(item) for item in gate.get("quality_warnings") or []),
                *(str(item) for item in gate.get("provider_warnings") or []),
                *([pool_merge_warning] if pool_merge_warning else []),
            ]
        )
    )

    payload = {
        **{k: v for k, v in result.items() if k not in _owned},
        "slug": slug,
        "skill_name": skill_name,
        "engine": engine,
        "available": True,
        "tuning": tuning,
        "role_transitions": history["transitions"],
        "roles_recorded": history["recorded"],
        "signals": signals,
        "picks": (unified_snapshot or {}).get("items") or openable,
        "unified_pool": unified_snapshot,
        "auction_excluded": excluded_codes,
        "suggestions": suggestions,
        "validation": result.get("validation", "unverified"),
        "validation_label": result.get("validation_label", "未经过前向验证"),
        "summary": body or "无新信号",
        "ai_summary": ai_note,
        "degraded": str(gate.get("data_status") or "") == "degraded",
        "tape_readiness": readiness,
        "provider_id": gate.get("provider_id"),
        "provider_ids": gate.get("provider_ids") or {},
        "warnings": audit_warnings,
        "observe_changes": observe_changes,
    }
    return payload
