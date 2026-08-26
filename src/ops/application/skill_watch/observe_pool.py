"""龙王观察池：粘性续盯 + 有限日更 + 变更汇报。

文案 / 规则常量见 ``observe_format``；本模块只保留入池合并逻辑。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.ops.application.skill_watch.observe_format import (
    OBSERVE_MONITOR_AI_RULES,
    OBSERVE_POOL_RULES,
    ROLE_EMOJI,
    code_of as _code,
    format_observe_change_report,
    format_observe_line,
    format_observe_reason,
    name_of as _name,
    observe_alert_records,
    observe_intraday_alerts,
    role_bad as _role_bad,
    role_badge,
    score_of as _score,
    text_of as _text,
)
from src.ops.application.skill_watch.paper_eligibility import is_observe_intent


def _theme_key(row: dict[str, Any]) -> tuple[str, str] | None:
    code = _text(row.get("theme_code"))
    name = _text(row.get("theme_name"))
    return ("code", code) if code else ("name", name) if name else None


def _theme_label(row: dict[str, Any]) -> str:
    return _text(row.get("theme_name")) or _text(row.get("theme_code")) or "空题材"


def _theme_limit_entry(row: dict[str, Any], limit: int) -> dict[str, Any]:
    return {
        "code": _code(row),
        "name": _name(row),
        "reason": f"同题材上限：{_theme_label(row)}最多{limit}只",
    }


def _age_days(row: dict[str, Any], trade_date: str | None) -> int | None:
    try:
        return max(
            0,
            (
                date.fromisoformat(_text(trade_date)[:10])
                - date.fromisoformat(
                    _text(row.get("observe_since") or row.get("last_seen_date"))[:10]
                )
            ).days,
        )
    except (TypeError, ValueError):
        try:
            return max(0, int(row["age_days"]))
        except (KeyError, TypeError, ValueError):
            return None


def _mark_age(
    row: dict[str, Any],
    *,
    trade_date: str | None,
    max_age_days: int,
) -> tuple[dict[str, Any], bool]:
    out = dict(row)
    age = _age_days(out, trade_date)
    newly = False
    if age is not None:
        out["age_days"] = age
        if age >= max(1, int(max_age_days)):
            newly = not bool(out.get("stale_observe"))
            out["stale_observe"] = True
            why = str(out.get("observe_reason") or "").strip()
            age_text = f"{age}天"
            if "久观无果" not in why:
                out["observe_reason"] = f"{why}·久观无果{age_text}" if why else f"久观无果{age_text}"
            elif age_text not in why:
                out["observe_reason"] = f"{why}·久观无果{age_text}"
    return out, newly


def select_daily_observes(
    ranked_or_picks: list[dict[str, Any]],
    *,
    buy_codes: set[str],
    min_score: float = 50.0,
    max_daily: int = 2,
    max_same_theme: int = 2,
) -> list[dict[str, Any]]:
    """当日候选观察：过滤可买/不合格，并限制单题材候选数。"""
    pool: list[dict[str, Any]] = []
    for row in ranked_or_picks:
        if not isinstance(row, dict):
            continue
        code = _code(row)
        if not code or code in buy_codes:
            continue
        if _score(row) < min_score or _role_bad(row):
            continue
        pool.append(row)
    pool.sort(key=lambda r: (-_score(r), _code(r)))
    selected: list[dict[str, Any]] = []
    counts: dict[tuple[str, str], int] = {}
    limit = max(1, int(max_daily))
    theme_limit = max(1, int(max_same_theme))
    for row in pool:
        key = _theme_key(row)
        if key and counts.get(key, 0) >= theme_limit:
            continue
        selected.append(row)
        if key:
            counts[key] = counts.get(key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _observe_dates(
    row: dict[str, Any],
    *,
    trade_date: str | None,
    old: dict[str, Any] | None = None,
    seen: bool,
) -> dict[str, Any]:
    """入池/续盯时写入 observe_since、last_seen_date、miss_days。"""
    out = dict(row)
    if not trade_date:
        return out
    if seen:
        out["last_seen_date"] = trade_date
        out["miss_days"] = 0
        out["observe_since"] = str(
            (old or {}).get("observe_since")
            or (old or {}).get("last_seen_date")
            or out.get("observe_since")
            or out.get("last_seen_date")
            or trade_date
        )
    return out


def _add_reason(row: dict[str, Any], *, default_why: str = "") -> str:
    explicit = str(row.get("observe_reason") or row.get("admission_reason") or "").strip()
    if explicit:
        return explicit
    why = default_why or "达观察线"
    return format_observe_reason(row, why=why)


def split_observe_upgraded_to_buy(
    previous_observe: list[dict[str, Any]],
    buy_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """旧观察票若进入可买列表，从合并输入剥离并产出升级汇报行。"""
    buy_by: dict[str, dict[str, Any]] = {}
    for row in buy_rows:
        if not isinstance(row, dict):
            continue
        code = _code(row)
        if code:
            buy_by[code] = row
    remaining: list[dict[str, Any]] = []
    upgraded: list[dict[str, Any]] = []
    for item in previous_observe:
        if not isinstance(item, dict):
            continue
        code = _code(item)
        if code and code in buy_by:
            src = buy_by[code]
            upgraded.append(
                {
                    "code": code,
                    "name": _name(src) or _name(item),
                    "reason": "原观察池",
                }
            )
        else:
            remaining.append(item)
    return remaining, upgraded


def merge_observe_pool(
    *,
    held_codes: set[str],
    fresh_observes: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    min_score: float = 50.0,
    max_pool: int = 5,
    max_daily_adds: int = 2,
    replace_margin: float = 8.0,
    trade_date: str | None = None,
    max_miss_days: int = 2,
    max_same_theme: int = 2,
    max_age_days: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """粘性合并观察池，并产出变更汇报。"""
    held = {str(c).strip() for c in held_codes if str(c).strip()}
    prev_by: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for item in previous_items:
        if not isinstance(item, dict) or not is_observe_intent(item):
            continue
        code = _code(item)
        if not code:
            continue
        if code in held:
            dropped.append(
                {
                    "code": code,
                    "name": _name(item),
                    "score": item.get("score"),
                    "reason": "已持仓，改走持仓续盯",
                }
            )
            continue
        if _role_bad(item) or (_score(item) < min_score and item.get("score") is not None):
            dropped.append(
                {
                    "code": code,
                    "name": _name(item),
                    "score": item.get("score"),
                    "reason": "走弱/破位或跌破观察分线",
                }
            )
            continue
        prev_by[code] = dict(item)
    fresh_by: dict[str, dict[str, Any]] = {}
    for item in fresh_observes:
        if not isinstance(item, dict):
            continue
        code = _code(item)
        if not code or code in held:
            continue
        if _score(item) < min_score or _role_bad(item):
            continue
        row = dict(item)
        row["intent"] = "observe"
        fresh_by[code] = row
    if trade_date:
        for code, old in list(prev_by.items()):
            if code in fresh_by:
                continue
            miss = int(old.get("miss_days") or 0) + 1
            if miss >= max(1, int(max_miss_days)):
                dropped.append(
                    {
                        "code": code,
                        "name": _name(old),
                        "score": old.get("score"),
                        "reason": f"连续{miss}日未命中扫描",
                    }
                )
                del prev_by[code]
            else:
                stale = dict(old)
                stale["miss_days"] = miss
                prev_by[code] = stale
    pool: dict[str, dict[str, Any]] = dict(prev_by)
    kept: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    stale_marked: list[dict[str, Any]] = []
    limited: list[dict[str, Any]] = []
    theme_limit = max(1, int(max_same_theme))
    pool_limit = max(0, int(max_pool))
    theme_counts: dict[tuple[str, str], int] = {}
    for code, old in list(pool.items()):
        if code in fresh_by:
            refreshed = dict(fresh_by[code])
            refreshed["observe_reason"] = str(
                old.get("observe_reason") or refreshed.get("observe_reason") or "续盯刷新"
            )
            pool[code] = _observe_dates(refreshed, trade_date=trade_date, old=old, seen=True)
        pool[code], newly_stale = _mark_age(
            pool[code], trade_date=trade_date, max_age_days=max_age_days
        )
        key = _theme_key(pool[code])
        if key:
            theme_counts[key] = theme_counts.get(key, 0) + 1
        entry = {"code": code, "name": _name(pool[code]), "score": pool[code].get("score")}
        if pool[code].get("stale_observe"):
            entry.update(
                {
                    "stale_observe": True,
                    "age_days": pool[code].get("age_days"),
                    "reason": pool[code].get("observe_reason"),
                }
            )
        kept.append(entry)
        if newly_stale:
            stale_marked.append(entry)
    candidates = sorted(
        (row for code, row in fresh_by.items() if code not in pool),
        key=lambda r: (-_score(r), _code(r)),
    )
    adds_left = max(0, int(max_daily_adds))
    for cand in candidates:
        if adds_left <= 0:
            break
        code = _code(cand)
        reason = _add_reason(cand, default_why="新入池")
        key = _theme_key(cand)
        if len(pool) < pool_limit:
            if key and theme_counts.get(key, 0) >= theme_limit:
                limited.append(_theme_limit_entry(cand, theme_limit))
                continue
            row = _observe_dates(dict(cand), trade_date=trade_date, seen=True)
            row["observe_reason"] = reason
            row["intent"] = "observe"
            row, _ = _mark_age(row, trade_date=trade_date, max_age_days=max_age_days)
            pool[code] = row
            if key:
                theme_counts[key] = theme_counts.get(key, 0) + 1
            added.append(
                {
                    "code": code,
                    "name": _name(row),
                    "score": row.get("score"),
                    "reason": reason,
                }
            )
            adds_left -= 1
            continue

        eligible = list(pool)
        if key and theme_counts.get(key, 0) >= theme_limit:
            eligible = [c for c in eligible if _theme_key(pool[c]) == key]
        if not eligible:
            if key:
                limited.append(_theme_limit_entry(cand, theme_limit))
            continue
        stale_targets = [c for c in eligible if pool[c].get("stale_observe")]
        if stale_targets:
            weakest_code = min(
                stale_targets,
                key=lambda c: (
                    -int(pool[c].get("age_days") or 0),
                    _score(pool[c]),
                    c,
                ),
            )
            stale_target = True
        else:
            weakest_code = min(eligible, key=lambda c: (_score(pool[c]), c))
            stale_target = False
        weak = pool[weakest_code]
        weak_score = _score(weak)
        cand_score = _score(cand)
        weak_unfit = _role_bad(weak) or weak_score < min_score
        if not stale_target and not weak_unfit and cand_score < weak_score + float(replace_margin):
            continue
        if stale_target:
            rep_why = f"久观无果·优先换新：替换{_name(weak)}·新{int(cand_score)}分"
            reason = _add_reason(cand, default_why=rep_why)
            if "久观无果" not in reason:
                reason = f"{reason}·{rep_why}"
        else:
            rep_why = (
                f"替换{_name(weak)}·新{int(cand_score)}分"
                + (
                    f"优于旧{int(weak_score)}分+{int(replace_margin)}"
                    if not weak_unfit
                    else "·旧票已不合格"
                )
            )
            reason = _add_reason(cand, default_why=rep_why)
        row = _observe_dates(dict(cand), trade_date=trade_date, seen=True)
        row["observe_reason"] = reason
        row["intent"] = "observe"
        row, _ = _mark_age(row, trade_date=trade_date, max_age_days=max_age_days)
        del pool[weakest_code]
        old_key = _theme_key(weak)
        if old_key:
            theme_counts[old_key] = max(0, theme_counts.get(old_key, 0) - 1)
        pool[code] = row
        if key:
            theme_counts[key] = theme_counts.get(key, 0) + 1
        replaced.append(
            {
                "out_code": weakest_code,
                "out_name": _name(weak),
                "out_score": weak.get("score"),
                "in_code": code,
                "in_name": _name(row),
                "in_score": row.get("score"),
                "reason": reason,
            }
        )
        kept = [k for k in kept if k.get("code") != weakest_code]
        stale_marked = [k for k in stale_marked if k.get("code") != weakest_code]
        adds_left -= 1
    ranked = sorted(pool.values(), key=lambda r: (-_score(r), _code(r)))
    report = {
        "kept": kept,
        "added": added,
        "replaced": replaced,
        "dropped": dropped,
        "stale": stale_marked,
        "limited": limited,
        "pool_size": len(ranked),
        "changed": bool(added or replaced or dropped or stale_marked or limited),
        "upgraded": [],
    }
    return ranked, report


__all__ = [
    "OBSERVE_MONITOR_AI_RULES",
    "OBSERVE_POOL_RULES",
    "ROLE_EMOJI",
    "format_observe_change_report",
    "format_observe_line",
    "format_observe_reason",
    "split_observe_upgraded_to_buy",
    "merge_observe_pool",
    "observe_alert_records",
    "observe_intraday_alerts",
    "role_badge",
    "select_daily_observes",
]
