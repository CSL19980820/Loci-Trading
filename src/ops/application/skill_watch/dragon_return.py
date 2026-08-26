"""龙回头监测：龙空龙闸门 → 龙头地图（龙头战法角色）→ 回头形态 → 可买/观察。

本模块消费 `leader_map` 的结构证据，但龙王池只收龙头：题材龙头直接合格；
题材内被标为 secondary、但个股当日涨停的强人气票按个股强度纠偏为龙头。
普通中军、走弱与破位的票直接排除。

龙王战法大成体三层：
- 龙空龙：市场进攻/观察/空仓闸门
- 龙头战法：角色地图（谁是龙头/中军，次日观察池）
- 龙回头：形态达标的可买候选
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.ops.application.skill_watch import payload as pl
from src.ops.application.skill_watch.leader_map import scan_leader_map
from src.ops.application.skill_watch.market_regime import today_trade_date

#: 龙王只做龙头，不让中军与龙头竞争观察位。
ELIGIBLE_ROLES = ("leader",)
SUITE_ID = "dragon-king"


def _dragon_leader_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """按个股强度校正题材内角色；普通中军不进入龙王池。"""
    role = str(entry.get("role") or "").strip().lower()
    if role == "leader":
        return dict(entry)
    if role != "secondary" or not bool(entry.get("is_limit_up")):
        return None
    promoted = dict(entry)
    promoted.update(
        {
            "role": "leader",
            "role_label": "龙头",
            "role_basis": "个股涨停，人气与涨幅强，按龙头观察",
            "role_promoted_from": "secondary",
        }
    )
    return promoted


def _suite_checks(
    row: Mapping[str, Any],
    *,
    gate: Mapping[str, Any],
    candidate_score: float,
) -> dict[str, dict[str, Any]]:
    """同一候选的三层联合审计；任何一层失败都只能观察，不能买入。"""
    role = str(row.get("role") or "").strip().lower()
    role_label = str(row.get("role_label") or role or "角色").strip()
    role_passed = role in ELIGIBLE_ROLES
    role_reason = str(row.get("role_basis") or "").strip()
    if not role_reason:
        role_reason = f"{role_label}角色合格" if role_passed else f"{role_label}角色不合格"

    gate_state = str(gate.get("state") or "").strip().lower()
    gate_passed = bool(gate.get("entry_allowed"))
    gate_reason = str(gate.get("reason") or "").strip()
    if not gate_reason:
        gate_reason = {
            "dragon": "进攻窗口",
            "observe": "观察窗口",
            "empty": "空仓窗口",
        }.get(gate_state, "市场闸门未放行")

    zone_ready = bool(row.get("buy_zone_ready"))
    score = float(row.get("score") or 0)
    score_ready = score >= float(candidate_score)
    dragon_passed = zone_ready and score_ready
    dragon_reason = str(row.get("buy_zone_reason") or "未达回头买点").strip()
    if zone_ready and not score_ready:
        dragon_reason = f"形态已到位，但{score:g}分未达{float(candidate_score):g}分可买线"

    return {
        "leader_playbook": {
            "passed": role_passed,
            "role": role,
            "reason": role_reason,
        },
        "market_gate": {
            "passed": gate_passed,
            "state": gate_state,
            "reason": gate_reason,
        },
        "dragon_return": {
            "passed": dragon_passed,
            "buy_zone_ready": zone_ready,
            "score_ready": score_ready,
            "reason": dragon_reason,
        },
    }


def _suite_passed(checks: Mapping[str, Any]) -> bool:
    return all(
        isinstance(checks.get(key), Mapping) and bool(checks[key].get("passed"))
        for key in ("leader_playbook", "market_gate", "dragon_return")
    )


def _suite_summary(checks: Mapping[str, Any]) -> str:
    leader = (
        checks.get("leader_playbook")
        if isinstance(checks.get("leader_playbook"), Mapping)
        else {}
    )
    gate = checks.get("market_gate") if isinstance(checks.get("market_gate"), Mapping) else {}
    dragon = (
        checks.get("dragon_return")
        if isinstance(checks.get("dragon_return"), Mapping)
        else {}
    )

    leader_text = "龙头身份合格" if leader.get("passed") else "龙头身份不合格"
    gate_state = str(gate.get("state") or "")
    gate_text = {
        "dragon": "龙空龙进攻窗",
        "observe": "龙空龙观察窗",
        "empty": "龙空龙空仓",
    }.get(gate_state, "龙空龙未放行")
    dragon_reason = str(dragon.get("reason") or "未达回头买点").strip()
    dragon_text = "龙回头买点通过" if dragon.get("passed") else f"龙回头{dragon_reason}"
    return f"{leader_text}；{gate_text}；{dragon_text}"


def score_pullback(
    stats: Mapping[str, Any] | None,
    *,
    name: str = "",
    ladder_row: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """回头形态打分。入参是 `kline_stats.trend_stats` 的结果，不重复算 K 线。"""
    metrics = dict(stats or {})
    if not metrics:
        return 0, {"reason": "kline_too_short"}

    close = float(metrics["close"])
    ma10 = float(metrics["ma10"])
    ma20 = float(metrics["ma20"])
    drawdown = float(metrics["drawdown_pct"])
    pullback_days = int(metrics.get("pullback_days_recent", metrics["pullback_days"]))
    pullback_depth = float(metrics.get("pullback_depth_pct", drawdown))
    pullback_drawdown = float(metrics.get("pullback_drawdown_pct", drawdown))
    shrink = float(metrics["vol_shrink"])
    today_pct = float(metrics["today_pct"])
    vol_ratio = float(metrics["vol_ratio"])
    strong_days = int(metrics["strong_days"])
    gain_20 = float(metrics.get("gain_20_pct") or 0)
    ladder_level = pl.field(ladder_row or {}, "ladder_level")
    if ladder_level is None:
        ladder_level = metrics.get("ladder_level")

    score = min(35, strong_days * 8)
    if gain_20 >= 15:
        score += 4
    if ladder_level is not None:
        level = float(ladder_level)
        score += 20 if level >= 3 else 14 if level >= 2 else 6
    if 8 <= pullback_depth <= 28:
        score += 18
    elif 5 <= pullback_depth < 8 or 28 < pullback_depth <= 32:
        score += 8
    if 3 <= pullback_days <= 10:
        score += 10
    if shrink <= 0.65:
        score += 10
    if close >= ma10 * 0.98:
        score += 8
    if close >= ma20 * 0.96:
        score += 4
    if today_pct >= 3 and vol_ratio >= 1.3:
        score += 12
    elif today_pct >= 1.5 and vol_ratio >= 1.1:
        score += 6
    if close < ma20 * 0.94 and vol_ratio > 1.2:
        score -= 15

    # candidate_score=100 是调参侧的硬关闭档，形态分最高保留为 99。
    return max(0, min(99, score)), {
        "name": name or str(metrics.get("name") or ""),
        "drawdown_pct": drawdown,
        "pullback_days": pullback_days,
        "pullback_depth_pct": pullback_depth,
        "pullback_drawdown_pct": pullback_drawdown,
        "vol_shrink": shrink,
        "today_pct": today_pct,
        "today_vol_ratio": vol_ratio,
        "ma10": ma10,
        "ma20": ma20,
        "strong_days": strong_days,
        "gain_20_pct": gain_20,
        "ladder_level": ladder_level,
    }


def _paper_pick(
    row: Mapping[str, Any],
    *,
    gate: Mapping[str, Any],
    intent: str,
    auction_cfg: Mapping[str, Any] | None = None,
    observe_reason: str = "",
) -> dict[str, Any]:
    from src.ops.application.skill_watch.actionable_line import enrich_actionable_fields
    from src.ops.application.skill_watch.observe_pool import format_observe_reason

    code = str(row.get("code") or "")
    name = str(row.get("name") or code)
    role_label = str(row.get("role_label") or "主线票")
    score = row.get("score")
    suite_checks = dict(row.get("suite_checks") or {})
    decision_reason = str(row.get("decision_reason") or _suite_summary(suite_checks)).strip()
    if intent == "observe":
        theme = str(row.get("theme_name") or "").strip()
        why = observe_reason or decision_reason or "观察"
        full_reason = format_observe_reason(dict(row), why=why)
        thesis = f"{role_label}" + (f" · {theme}" if theme else "")
        if why:
            thesis = f"{thesis} · {why}" if thesis else why
        veto = ["观察票不开仓", "破位/走弱移出"]
        layers = 0.0
    else:
        theme = str(row.get("theme_name") or "").strip()
        thesis = f"{role_label}回头 · 分{score}" + (f" · {theme}" if theme else "")
        veto = ["未过竞价/开盘门闩不跟随", "跌破回调低点放弃"]
        layers = None
    base: dict[str, Any] = {
        "code": code,
        "name": name,
        "score": score,
        "close": row.get("close"),
        "ref_close": row.get("close"),
        "role": row.get("role"),
        "role_label": role_label,
        "intent": intent,
        "suite": SUITE_ID,
        "suite_layer": SUITE_ID,
        "suite_checks": suite_checks,
        "decision_reason": decision_reason,
        "thesis": thesis,
        "validation": "unverified",
        "validation_label": "未经过前向验证",
        "veto": veto,
        "auction": dict(auction_cfg or {}),
        "source_evidence": {
            "trade_date": gate.get("trade_date"),
            "market_gate": gate.get("state"),
            "role": row.get("role"),
            "theme_code": row.get("theme_code"),
            "score": score,
            "intent": intent,
            "buy_zone_ready": row.get("buy_zone_ready"),
            "buy_zone_reason": row.get("buy_zone_reason"),
            "pullback_depth_pct": row.get("pullback_depth_pct"),
            "pullback_drawdown_pct": row.get("pullback_drawdown_pct"),
            "pullback_days": row.get("pullback_days"),
            "suite_checks": suite_checks,
        },
        "auction_stance": row.get("auction_stance"),
        "auction_reason": row.get("auction_reason"),
        "role_basis": row.get("role_basis"),
    }
    if intent == "observe":
        base["observe_reason"] = full_reason
    if layers is not None:
        base["planned_layers"] = layers
        base["planned_layers_max"] = layers
    return enrich_actionable_fields(
        base,
        role=str(row.get("role") or ""),
        score=score,
    )


def _current_role_signals(leader_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    """当前角色条（龙头/走弱）；一段式推送用，不含闸门复读。"""
    out: list[dict[str, Any]] = []
    for signal in leader_map.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        if str(signal.get("type") or "") in {"leader_watch", "leader_weak"}:
            out.append(dict(signal))
        if len(out) >= 6:
            break
    return out


def _rank_eligible(
    leader_map: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from src.ops.application.skill_watch.paper_eligibility import is_auction_abandoned

    eligible_entries: list[dict[str, Any]] = []
    for row in leader_map.get("entries") or []:
        if not isinstance(row, dict) or is_auction_abandoned(row):
            continue
        eligible = _dragon_leader_entry(row)
        if eligible is not None:
            eligible_entries.append(eligible)
    ranked: list[dict[str, Any]] = []
    for entry in eligible_entries:
        score, meta = score_pullback(entry, name=str(entry["name"]), ladder_row=entry)
        ranked.append(
            {
                **meta,
                "code": entry["code"],
                "name": entry.get("name") or str(meta.get("name") or ""),
                "close": entry["close"],
                "role": entry["role"],
                "role_label": entry["role_label"],
                "role_promoted_from": entry.get("role_promoted_from"),
                "is_limit_up": bool(entry.get("is_limit_up")),
                "theme_code": entry.get("theme_code"),
                "theme_name": entry.get("theme_name"),
                "gain_20_pct": entry.get("gain_20_pct"),
                "score": score,
                "auction_stance": entry.get("auction_stance"),
                "auction_reason": entry.get("auction_reason"),
                "role_basis": entry.get("role_basis"),
            }
        )
    ranked.sort(key=lambda item: (-int(item["score"]), str(item["code"])))
    return ranked


def _buy_zone_status(
    row: Mapping[str, Any],
    *,
    role_params: Mapping[str, Any],
) -> tuple[bool, str]:
    """龙回头可买区硬门槛：有高度/涨幅、近期确有回撤、结构未破。"""
    level = float(row.get("ladder_level") or 0)
    gain_20 = float(row.get("gain_20_pct") or 0)
    min_level = float(role_params.get("leader_min_level") or 2)
    min_gain = float(role_params.get("leader_min_gain_20") or 15)
    if level < min_level and gain_20 < min_gain:
        return False, "热度/阶段涨幅不足"

    pullback_days = int(row.get("pullback_days") or 0)
    pullback_depth = float(row.get("pullback_depth_pct") or 0)
    drawdown = float(row.get("pullback_drawdown_pct") or 0)
    if pullback_days < 1:
        return False, "尚未回撤"
    if pullback_days > 10:
        return False, "回撤时间过长"
    if pullback_depth < 5:
        return False, "回撤深度不足"
    if pullback_depth > 32 or drawdown > 28:
        return False, "回撤过深"

    close = float(row.get("close") or 0)
    ma20 = float(row.get("ma20") or 0)
    if ma20 <= 0 or close < ma20 * 0.94:
        return False, "回撤结构已破"
    return True, "进入回头买点区"


def scan_dragon_return(
    call_tool: Any,
    *,
    tuning: Mapping[str, Any] | None = None,
    market_store: Any | None = None,
) -> dict[str, Any]:
    """确定性龙王扫描：可买（龙回头）+ 观察（龙头战法角色），不代表买卖指令。

    空仓日仍扫角色并产出「次日观察」；仅进攻窗且形态达线才进「可买」。
    """
    from src.ops.application.skill_watch.tuning import section, stage_enabled

    trade_date = today_trade_date()
    leader_map = scan_leader_map(
        call_tool,
        trade_date=trade_date,
        skip_when_empty=False,
        tuning=tuning,
        market_store=market_store,
    )
    scan_cfg = section(tuning, "scan")
    from src.ops.application.skill_watch.observe_pool import select_daily_observes

    candidate_score = float(scan_cfg["candidate_score"])
    max_candidates = int(scan_cfg["max_candidates"])
    max_observe = int(scan_cfg.get("max_observe") or 2)
    observe_min_score = float(scan_cfg.get("observe_min_score") or 50)
    allow_candidates = stage_enabled(tuning, "paper_candidates")

    gate = leader_map["market_gate"]
    base = {
        "trade_date": trade_date,
        "market_gate": gate,
        "themes": leader_map["themes"],
        "auction": leader_map.get("auction"),
        "entries": leader_map["entries"],
        "leader_map": {
            "leaders": leader_map["leaders"],
            "weakened": leader_map["weakened"],
        },
        "suite": SUITE_ID,
        "validation": "unverified",
        "validation_label": "未经过前向验证",
    }

    ranked = _rank_eligible(leader_map)
    role_cfg = section(tuning, "roles")
    for row in ranked:
        ready, reason = _buy_zone_status(row, role_params=role_cfg)
        row["buy_zone_ready"] = ready
        row["buy_zone_reason"] = reason
        checks = _suite_checks(row, gate=gate, candidate_score=candidate_score)
        row["suite_checks"] = checks
        row["suite_all_passed"] = _suite_passed(checks)
        row["decision_reason"] = _suite_summary(checks)
    from src.ops.application.skill_watch.paper_eligibility import filter_openable_picks

    auction_cfg = section(tuning, "auction")
    raw_picks: list[dict[str, Any]] = []
    if allow_candidates:
        qualified = [
            row
            for row in ranked
            if row.get("suite_all_passed")
        ]
        buy_rows: list[dict[str, Any]] = []
        if max_candidates > 0:
            buy_rows = qualified[:max_candidates]
            raw_picks.extend(
                _paper_pick(row, gate=gate, intent="buy", auction_cfg=auction_cfg)
                for row in buy_rows
            )
        buy_codes = {str(r.get("code")) for r in buy_rows}
        observe_rows = select_daily_observes(
            ranked,
            buy_codes=buy_codes,
            min_score=observe_min_score,
            max_daily=max_observe,
            max_same_theme=int(scan_cfg.get("observe_max_same_theme") or 2),
        )
        raw_picks.extend(
            _paper_pick(
                row,
                gate=gate,
                intent="observe",
                auction_cfg=auction_cfg,
                observe_reason=str(row.get("decision_reason") or "联合条件未全部通过"),
            )
            for row in observe_rows
        )

    picks, excluded = filter_openable_picks(raw_picks)
    buy_picks = [p for p in picks if str(p.get("intent") or "buy") == "buy"]
    observe_picks = [p for p in picks if str(p.get("intent") or "") == "observe"]

    signals: list[dict[str, Any]] = []
    if gate.get("state") == "empty":
        signals.append(
            {
                "type": "gate_empty",
                "code": "market",
                "reason": str(gate.get("reason") or "空仓窗口"),
                "validation": "unverified",
            }
        )
    if not allow_candidates:
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": "纸面候选已关闭，本次只出监测信号",
                "validation": "unverified",
            }
        )
    elif buy_picks:
        signals.extend(
            {
                "type": "paper_candidate",
                "code": item["code"],
                "name": item.get("name") or "",
                "role": item.get("role") or "",
                "role_label": item.get("role_label") or "",
                "score": item["score"],
                "intent": "buy",
                "reason": "龙头身份、龙空龙进攻窗、龙回头买点同时通过，进入次日可买",
                "validation": "unverified",
            }
            for item in buy_picks
        )
    elif not gate.get("entry_allowed"):
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": str(gate.get("reason") or "市场未进入进攻窗口"),
                "validation": "unverified",
            }
        )
    elif ranked:
        signals.append(
            {
                "type": "watch_only",
                "code": ranked[0]["code"],
                "name": ranked[0].get("name") or "",
                "score": ranked[0]["score"],
                "reason": (
                    "市场窗口尚可，但"
                    f"{ranked[0].get('buy_zone_reason') or '回头形态分未达可买线'}，已进观察"
                ),
                "validation": "unverified",
            }
        )
    else:
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": "主线暂无龙头角色可供回头",
                "validation": "unverified",
            }
        )
    for item in observe_picks[:5]:
        signals.append(
            {
                "type": "leader_watch",
                "code": item["code"],
                "name": item.get("name") or "",
                "role": item.get("role") or "",
                "score": item.get("score"),
                "intent": "observe",
                "reason": str(item.get("decision_reason") or "三层联合条件未全过，继续观察"),
                "validation": "unverified",
            }
        )
    # 透传龙头地图的区间强度走弱预警（软信号，不改开仓判定）
    signals.extend(
        signal
        for signal in (leader_map.get("theme_interval_warnings") or leader_map.get("signals") or [])
        if str(signal.get("type") or "") in {"theme_interval_weak", "theme_interval_degraded"}
    )
    signals.extend(
        {
            "type": "invalidated",
            "code": row["code"],
            "name": row.get("name") or "",
            "reason": f"{row['role_label']}：{row['role_basis']}",
            "validation": "unverified",
        }
        for row in leader_map["weakened"][:2]
    )
    # 空仓日仍附带地图角色条（可能与 observe 信号重叠，推送侧去重）
    if gate.get("state") == "empty":
        signals.extend(_current_role_signals(leader_map))

    return {
        **base,
        "ranked": ranked[:8],
        "picks": picks,
        "auction_excluded": [
            str(row.get("code"))
            for row in excluded
            if isinstance(row, dict) and row.get("code")
        ],
        "signals": signals,
        "theme_interval_warnings": list(leader_map.get("theme_interval_warnings") or []),
        "theme_interval": dict(leader_map.get("theme_interval") or {}),
        "pool_size": len(leader_map["entries"]),
        "buy_count": len(buy_picks),
        "observe_count": len(observe_picks),
    }


__all__ = ["ELIGIBLE_ROLES", "SUITE_ID", "scan_dragon_return", "score_pullback"]
