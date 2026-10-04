"""猎隼只读候选快照：系统产出是研究入口，持仓不是新仓资格。"""
from __future__ import annotations

import copy
import inspect
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import EXCLUDE_BACKFILL_SQL, EXCLUDE_STALE_API_SCREEN_SQL
from src.market import scheduled_trading_days
from src.ops.application.retired_slugs import is_retired_strategy_slug
from src.ops.application.screen.storage import get_screen_package
from src.ops.application.skills import resolve_skill
from src.strategy import is_builtin_registered

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVE_DECISIONS = frozenset({"精选", "观察"})
POOL_PREFIX = "unified_monitor_pool:"
WINDOW_TRADING_DAYS = 5
_STOCK_IDENTIFIER = re.compile(r"^(?:(?:sh|sz|bj))?(\d{6})(?:\.(?:sh|sz|bj))?$", re.IGNORECASE)
_STOCK_CODE_FIELDS = frozenset({"code", "stock_code", "symbol", "security_code", "ts_code"})
_OMIT = object()
_SCOPE_METADATA_FIELDS = frozenset({"as_of", "research_date", "historical_review", "candidate_codes", "research_codes",
    "strategy_slugs", "sources", "warnings", "complete", "snapshot_basis", "note", "review_snapshot_count",
    "window", "active_strategy_slugs", "active_sources", "source_completeness", "lifecycle_ready", "auto_observe_codes"})


def _trading_window(target: date) -> dict:
    """只按已公告交易所日程计龄；不使用日K入库日期或普通工作日猜测。"""
    dates = scheduled_trading_days(date(target.year, 1, 1).isoformat(), target.isoformat())
    if len(dates) < WINDOW_TRADING_DAYS:
        dates = scheduled_trading_days(date(target.year - 1, 1, 1).isoformat(), target.isoformat())
    if len(dates) < WINDOW_TRADING_DAYS:
        raise ValueError("已公告交易所日历不足五个交易日，不能确定候选有效窗口")
    dates = dates[-WINDOW_TRADING_DAYS:]
    return {"trading_days": WINDOW_TRADING_DAYS, "dates": dates, "start": dates[0], "end": dates[-1],
            "calendar_basis": "exchange_announced_schedule", "signal_day_is_day_one": True}


def _active_formula_sources(ops: Any) -> list[dict]:
    """读真实选股开关，不创建任务、重载目录或执行公式。"""
    if ops is None or not hasattr(ops, "list_jobs") or not hasattr(ops, "is_screen_job_opted_out"):
        raise ValueError("选股公式开关不可用")
    result = []
    for job in ops.list_jobs():
        if job.get("kind") != "screen" or not job.get("enabled"):
            continue
        config = job.get("config") if isinstance(job.get("config"), dict) else {}
        name = str(job.get("name") or "")
        slug = str(config.get("strategy") or (name[len("screen:"):] if name.startswith("screen:") else "")).strip()
        schedule = config.get("schedule") if isinstance(config.get("schedule"), dict) else {}
        if not slug or is_retired_strategy_slug(slug) or schedule.get("mode") == "off" or ops.is_screen_job_opted_out(slug):
            continue
        package = get_screen_package(slug)
        if package is not None:
            if not package.enabled:
                continue
            definition = "installed_screen_package"
        elif is_builtin_registered(slug):
            definition = "builtin_strategy"
        else:
            # 删除公式后遗留的启用任务行不能继续授予候选资格。
            continue
        result.append({"strategy_slug": slug, "job_id": str(job.get("id") or ""), "job_name": name,
                       "enabled": True, "schedule_mode": str(schedule.get("mode") or "cron"),
                       "definition_basis": definition})
    return sorted(result, key=lambda row: (row["strategy_slug"], row["job_id"]))


def _window_evidence(row: dict, window: dict, expirations: dict[str, str | None]) -> dict:
    day = str(row["date"])
    age = len(window["dates"]) - window["dates"].index(day)
    # 显示有效期也使用公告日程。跨未知年度时不给推测日期，当前资格仍由后向窗口决定。
    if day not in expirations:
        signal = date.fromisoformat(day)
        try:
            future_days = scheduled_trading_days(day, (signal + timedelta(days=35)).isoformat())
            expirations[day] = future_days[WINDOW_TRADING_DAYS - 1] if len(future_days) >= WINDOW_TRADING_DAYS else None
        except ValueError:
            expirations[day] = None
    return {**row, "signal_date": day, "age_trading_days": age, "expires_on": expirations[day],
            "valid_for_trading_days": WINDOW_TRADING_DAYS}


def _timestamp(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=SHANGHAI) if stamp.tzinfo is None else stamp.astimezone(SHANGHAI)


def _json(value: Any) -> dict:
    try:
        result = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _code(value: Any) -> str:
    code = str(value or "").strip()
    return code if len(code) == 6 and code.isascii() and code.isdigit() else ""


def _stock_identifier(value: Any) -> str:
    if type(value) not in {str, int}:
        return ""
    match = _STOCK_IDENTIFIER.fullmatch(str(value or "").strip())
    return match.group(1) if match else ""


def _candidate_evidence(row: dict, code: str) -> dict:
    """只投影该候选证据；内部全池快照不转交模型，也不另存可回读原文。"""
    omitted = {"internal_snapshots": 0, "foreign_stock_entries": 0}

    def project(value: Any, *, root: bool = False) -> Any:
        if isinstance(value, dict):
            identifiers = {_stock_identifier(item) for field, item in value.items()
                           if str(field).casefold() in _STOCK_CODE_FIELDS}
            if not root and any(identifier and identifier != code for identifier in identifiers):
                omitted["foreign_stock_entries"] += 1
                return _OMIT
            result = {}
            for key, item in value.items():
                if str(key).casefold() == "_data_snapshot":
                    omitted["internal_snapshots"] += 1
                    continue
                identifier = _stock_identifier(key)
                if identifier and identifier != code:
                    omitted["foreign_stock_entries"] += 1
                    continue
                identifier = _stock_identifier(item) if str(key).casefold() in _STOCK_CODE_FIELDS else ""
                if identifier and identifier != code:
                    omitted["foreign_stock_entries"] += 1
                    continue
                if isinstance(item, list) and (str(key).casefold().endswith("_codes") or str(key).casefold() in {"codes", "symbols"}):
                    kept = []
                    for entry in item:
                        identifier = _stock_identifier(entry)
                        if identifier and identifier != code:
                            omitted["foreign_stock_entries"] += 1
                        else:
                            kept.append(entry)
                    item = kept
                child = project(item)
                if child is not _OMIT:
                    result[key] = child
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                child = project(item)
                if child is not _OMIT:
                    result.append(child)
            return result
        if isinstance(value, str):
            identifier = _stock_identifier(value)
            if identifier and identifier != code:
                omitted["foreign_stock_entries"] += 1
                return _OMIT
            # 源证据可能把结构再次编码成JSON字符串；不让编码成为快照/代码过滤旁路。
            if value.lstrip().startswith(("{", "[")):
                try:
                    decoded = json.loads(value)
                except ValueError:
                    return value
                if isinstance(decoded, (dict, list)):
                    projected = project(decoded)
                    return _OMIT if projected is _OMIT else json.dumps(projected, ensure_ascii=False)
        return value

    result = project(row, root=True)
    if any(omitted.values()):
        prior = result.get("evidence_scope") or {}
        prior = prior if isinstance(prior, dict) else {}
        def previous_count(field: str) -> int:
            value = prior.get(field, 0)
            return value if type(value) is int and value >= 0 else 0
        result["evidence_scope"] = {"stock_code": code,
            "internal_snapshots_omitted": omitted["internal_snapshots"] + previous_count("internal_snapshots_omitted"),
            "foreign_stock_entries_omitted": omitted["foreign_stock_entries"] + previous_count("foreign_stock_entries_omitted"),
            "note": "内部全池快照与其他股票条目已省略，仅保留该候选的信号、判分及来源依据；过滤后的代码列表不代表原筛选宇宙，未另存可回读的全池原文。"}
    return result


def project_falcon_candidate_scope(scope: dict | None) -> dict:
    """供旧日记入口使用的只读投影，完整保留候选，不回传全池原始材料。"""
    if not isinstance(scope, dict):
        return {}
    result = {key: copy.deepcopy(value) for key, value in scope.items() if key in _SCOPE_METADATA_FIELDS}
    result["candidates"] = [_candidate_evidence(row, code) for row in scope.get("candidates", [])
                            if isinstance(row, dict) and (code := _code(row.get("code")))]
    return result


def _quant_candidates(palace_path: str, cutoff: datetime, dates: list[str], active_slugs: set[str]) -> list[dict]:
    # 读现有库，不初始化 schema，也不触发候选去重/修订写入。
    uri = Path(palace_path).resolve().as_uri() + "?mode=ro"
    if not dates or not active_slugs:
        return []
    clauses = ["occurred_on IN (" + ",".join("?" for _ in dates) + ")",
               "strategy_slug IN (" + ",".join("?" for _ in active_slugs) + ")",
               "(source = 'job:screen' OR source LIKE 'api:screen%')",
               *EXCLUDE_BACKFILL_SQL, EXCLUDE_STALE_API_SCREEN_SQL]
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM candidate_reviews WHERE " + " AND ".join(clauses),
                            (*dates, *sorted(active_slugs))).fetchall()
    visible = []
    for row in rows:
        stamp = _timestamp(row["created_at"])
        if stamp is None:
            raise ValueError("活动公式窗口内候选缺少可核实来源时点")
        if stamp <= cutoff:
            visible.append(dict(row))
    result = []
    for row in visible:
        if not (code := _code(row["code"])):
            continue
        result.append(_candidate_evidence({"code": code, "name": row["name"], "origin": "quant",
            "date": row["occurred_on"], "observed_at": row["created_at"], "produced_at": row["created_at"],
            "source": row["source"], "pool_id": row["pool_id"], "candidate_id": row["id"],
            "evidence_id": "candidate:" + str(row["id"]),
            "strategy_slug": row["strategy_slug"], "strategy_revision": row["strategy_revision"],
            "score": row["score"], "decision": row["decision"], "timing": row["timing"],
            "reason": row["reason"], "rule_version": row["rule_version"], "tier": row["tier"],
            "effective_params": _json(row["effective_params_json"]), "evidence": _json(row["evidence_json"]),
            "entry_eligible": row["decision"] in ACTIVE_DECISIONS, "formula_active": True}, code))
    return result


def _skill_candidates(ops: Any, cutoff: datetime, dates: list[str], warnings: list[str], *, historical_review: bool) -> list[dict]:
    if ops is None or not hasattr(ops, "conn"):
        warnings.append("技能监察池不可用；本轮未把缺失来源视为有候选。")
        return []
    keys = ops.conn.execute("SELECT key FROM meta WHERE key LIKE ? ORDER BY key", (POOL_PREFIX + "%",)).fetchall()
    active_watch_slugs = None
    if not historical_review:
        if not hasattr(ops, "list_jobs"):
            raise ValueError("技能产出开关不可用")
        active_watch_slugs = set()
        for job in ops.list_jobs():
            config = job.get("config") if isinstance(job.get("config"), dict) else {}
            schedule = config.get("schedule") if isinstance(config.get("schedule"), dict) else {}
            slug = str(config.get("skill") or "").strip()
            if job.get("kind") != "skill_watch" or not job.get("enabled") or not slug or schedule.get("mode") == "off":
                continue
            skill = resolve_skill(slug)
            if skill and skill.get("enabled", True) and not is_retired_strategy_slug(slug):
                active_watch_slugs.add(slug)
    result = []
    for row in keys:
        key = str(row["key"])
        snapshot = ops.get_setting(key, None)
        if not isinstance(snapshot, dict):
            continue
        date = str(snapshot.get("trade_date") or "")
        slug = str(snapshot.get("slug") or key[len(POOL_PREFIX):])
        stamp = _timestamp(snapshot.get("updated_at"))
        if not date or date > cutoff.date().isoformat() or stamp is None or stamp > cutoff:
            warnings.append(f"技能 {key[len(POOL_PREFIX):]} 无截止时点前可核实的快照，已跳过。")
            continue
        if date not in dates or (active_watch_slugs is not None and slug not in active_watch_slugs):
            continue
        for item in snapshot.get("items") or []:
            if not isinstance(item, dict) or item.get("bucket") == "position" or not (code := _code(item.get("code"))):
                continue
            item_stamp = _timestamp(item.get("observed_at") or item.get("updated_at") or snapshot["updated_at"])
            if item_stamp is None or item_stamp > cutoff:
                continue
            action = str(item.get("action") or item.get("intent") or "observe").lower()
            result.append(_candidate_evidence({**item, "code": code, "name": str(item.get("name") or code),
                "origin": "skill", "date": date, "observed_at": item_stamp.isoformat(), "produced_at": item_stamp.isoformat(),
                "source": str(item.get("candidate_feed") or snapshot.get("source") or key),
                "strategy_slug": slug,
                "pool_id": key, "score": item.get("score"), "evidence": copy.deepcopy(item),
                "evidence_id": f"skill:{date}:{key[len(POOL_PREFIX):]}:{code}:{item_stamp.isoformat()}",
                "entry_eligible": action not in {"sell", "close", "reduce", "take_profit", "stop_loss", "stop_cut", "trim_high", "reject", "rejected", "drop", "dropped", "unwatch"}}, code))
    return result


def load_falcon_candidates(palace_path: str, ops: Any, *, as_of: datetime,
                           research_date: str | None = None, historical_review: bool = False) -> dict:
    """读当前开启选股公式近五个公告交易日的全部系统产出，不裁成前 N 只。

    量化明确落选仍供评分复盘，但不授权开仓。历史量化只接受本账户保存的
    候选快照，不读取允许原位改判的原表。技能仅接受截止前已保存的快照。
    """
    now = as_of.replace(tzinfo=SHANGHAI) if as_of.tzinfo is None else as_of.astimezone(SHANGHAI)
    target = datetime.fromisoformat(research_date or now.date().isoformat()).date()
    if target > now.date():
        raise ValueError("候选研究日期不能晚于本轮时点")
    cutoff = min(now, datetime.combine(target, time.max, SHANGHAI))
    warnings: list[str] = []
    complete = True
    candidates = []
    window = {"trading_days": WINDOW_TRADING_DAYS, "dates": [], "start": None, "end": None,
              "calendar_basis": "exchange_announced_schedule", "signal_day_is_day_one": True}
    active_sources = []
    calendar_ready = False
    active_sources_ready = False
    quant_ready = False
    skill_ready = False
    try:
        window = _trading_window(target)
        calendar_ready = True
    except (ValueError, OSError, TypeError) as exc:
        complete = False
        warnings.append(f"权威交易日历不可用（{type(exc).__name__}）；不按自然日或已入库行情日期猜测有效期，本轮不授权新增候选且不执行观察池自动清理。")
    if historical_review:
        warnings.append("历史量化裁决原表允许原位改判且created_at不随改判更新；本轮不读取原表分数、裁决、理由、参数或证据，仅使用本账户截止前已保存的candidate_scope。缺少保存快照时不重建未知评分或资格。")
    else:
        try:
            active_sources = _active_formula_sources(ops)
            active_sources_ready = True
        except (sqlite3.Error, OSError, KeyError, ValueError, TypeError) as exc:
            complete = False
            warnings.append(f"公式选股开关读取失败（{type(exc).__name__}）；本轮不授权新增候选且不执行观察池自动清理。")
        try:
            if calendar_ready and active_sources_ready:
                candidates = _quant_candidates(str(palace_path), cutoff, window["dates"],
                                               {row["strategy_slug"] for row in active_sources})
                quant_ready = True
        except (sqlite3.Error, OSError, KeyError, ValueError, TypeError) as exc:
            complete = False
            warnings.append(f"量化候选读取失败（{type(exc).__name__}）；本轮不授权新观察、买入或加仓，已有持仓仍可管理退出。")
    try:
        if calendar_ready:
            candidates.extend(_skill_candidates(ops, cutoff, window["dates"], warnings, historical_review=historical_review))
            skill_ready = True
    except (sqlite3.Error, OSError, KeyError, ValueError, TypeError) as exc:
        complete = False
        warnings.append(f"技能候选读取失败（{type(exc).__name__}）；本轮不授权新观察、买入或加仓，已有持仓仍可管理退出。")
    if not complete:
        candidates = []
    if historical_review:
        warnings.append("技能池仅保留当前快照，缺失截止前快照无法重建；不会把当前时间的快照移到旧日期。")
    expirations: dict[str, str | None] = {}
    candidates = [_window_evidence(row, window, expirations) for row in candidates]
    candidates.sort(key=lambda row: (row["date"], row["origin"], row["code"], str(row.get("strategy_slug") or "")))
    eligible = {row["code"] for row in candidates if row["entry_eligible"]}
    return {"as_of": cutoff.isoformat(), "research_date": target.isoformat(), "historical_review": historical_review,
        "candidates": candidates, "candidate_codes": sorted(eligible),
        "research_codes": sorted({row["code"] for row in candidates}),
        "strategy_slugs": sorted({row["strategy_slug"] for row in candidates if row.get("strategy_slug")}),
        "sources": sorted({row["source"] for row in candidates}), "warnings": list(dict.fromkeys(warnings)),
        "complete": complete, "snapshot_basis": "active_formula_outputs_last_five_exchange_trading_days",
        "window": window, "active_sources": active_sources,
        "active_strategy_slugs": sorted({row["strategy_slug"] for row in active_sources}),
        "auto_observe_codes": sorted({row["code"] for row in candidates if row["origin"] == "quant" and row["entry_eligible"]}),
        "lifecycle_ready": bool(complete and calendar_ready and active_sources_ready and quant_ready and not historical_review),
        "source_completeness": {"calendar": calendar_ready, "active_formula_config": active_sources_ready,
            "quant_window": quant_ready, "skill_current_snapshot": skill_ready, "skill_window_history": False},
        "note": "未再次筛选市场、未按数量额度裁剪。当前开启公式在五个公告交易日内的精选/观察均保留来源资格，较新落选只供判分研究；关闭公式或超期才撤回该来源。技能只读取当前可见且未过期、仍开启的监察快照，已覆盖或裁掉的历史技能记录无法恢复；历史复盘不重建当时的公式开关。"}


def falcon_research_scope(payload: dict) -> dict:
    """复盘读取截止内已保存的原始候选，研究名单不扩大本轮新仓资格。"""
    scope = project_falcon_candidate_scope(payload.get("candidate_scope"))
    snapshots = []
    if payload.get("analysis_only"):
        cutoff = _timestamp(payload.get("research_cutoff") or payload.get("as_of"))
        day = str(payload.get("research_date") or "")
        for run in (payload.get("review_evidence") or {}).get("runs", []):
            snapshot = run.get("candidate_scope") or (run.get("detail") or {}).get("candidate_scope") or {}
            stamp = _timestamp(snapshot.get("as_of"))
            if stamp is None or cutoff is None or stamp > cutoff or (day and stamp.date().isoformat() > day):
                continue
            snapshots.append(project_falcon_candidate_scope(snapshot))
    rows = {}
    for snapshot in [*snapshots, scope]:
        for row in snapshot.get("candidates", []):
            key = row.get("evidence_id") or (row.get("origin"), row.get("code"), row.get("strategy_slug"), row.get("date"))
            if key not in rows:
                rows[key] = _candidate_evidence(row, str(row.get("code") or ""))  # 保存时点优先，旧快照同样不得夹带全池证据。
    scope["candidates"] = list(rows.values())
    scope["research_codes"] = sorted({code for snapshot in [scope, *snapshots]
                                      for value in snapshot.get("research_codes", []) if (code := _code(value))})
    scope["strategy_slugs"] = sorted({str(slug) for snapshot in [scope, *snapshots]
                                     for slug in snapshot.get("strategy_slugs", []) if slug})
    scope["review_snapshot_count"] = len(snapshots)
    return scope


def falcon_research_codes(payload: dict) -> set[str]:
    scope = falcon_research_scope(payload)
    return {code for value in scope.get("research_codes", []) if (code := _code(value))} | {
        code for position in payload.get("portfolio", {}).get("positions", [])
        if position.get("quantity", 0) > 0 and (code := _code(position.get("code")))}


def read_falcon_strategy(slug: str, scope: dict, *, historical_review: bool = False) -> dict:
    """只读本轮候选来源定义，不执行 compute、预览、回测或新的市场筛选。"""
    if slug not in set(scope.get("strategy_slugs", [])):
        raise ValueError("只允许读取本轮候选的来源策略/技能定义")
    if historical_review:
        return {"slug": slug, "definition_available": False,
                "candidate_evidence": [_candidate_evidence(row, str(row.get("code") or ""))
                                       for row in scope.get("candidates", []) if row.get("strategy_slug") == slug],
                "note": "历史复盘只读当时候选证据；当前技能源码和参数不能冒充历史版本。"}
    from src.ops.application.screen.storage import get_screen_package
    package = get_screen_package(slug)
    if package is not None:
        return {"slug": slug, "name": package.name, "description": package.description,
                "strategy_revision": package.package_revision, "updated_at": package.updated_at,
                "manifest": package.screen, "formula": package.formula, "code": package.code,
                "instructions": package.body, "read_only": True, "definition_basis": "current_installed_version"}
    from src.strategy import get, is_builtin_registered
    if not is_builtin_registered(slug):
        return {"slug": slug, "definition_available": False, "note": "此候选来源未提供可读的量化定义；保留原始评分证据。"}
    engine = get(slug)
    try:
        source = inspect.getsource(type(engine))
    except (OSError, TypeError):
        source = ""
    return {"slug": slug, "name": engine.name, "description": engine.description,
            "strategy_revision": str(getattr(engine, "strategy_revision", "")),
            "entry_timing": engine.entry_timing, "required_fields": list(engine.required_fields()),
            "params": engine.default_params(), "code": source, "read_only": True,
            "definition_basis": "current_installed_version"}
