"""价格提醒条件评估与扫描。"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.market import normalize_code
from src.market.application.live_cache import get_cached_quotes


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _op_eval(left: float | None, op: str, right: Any) -> bool:
    if left is None:
        return False
    o = (op or "").strip().lower()
    if o in ("between", "in"):
        if not isinstance(right, (list, tuple)) or len(right) != 2:
            return False
        lo = _safe_float(right[0])
        hi = _safe_float(right[1])
        if lo is None or hi is None:
            return False
        return lo <= left <= hi
    rv = _safe_float(right)
    if rv is None:
        return False
    if o == ">":
        return left > rv
    if o == ">=":
        return left >= rv
    if o == "<":
        return left < rv
    if o == "<=":
        return left <= rv
    if o in ("=", "=="):
        return left == rv
    if o in ("!=", "<>"):
        return left != rv
    return False


def eval_condition_group(group: dict[str, Any], quote: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    op = str(group.get("op") or "and").lower()
    items = group.get("conditions") or group.get("items") or []
    if not isinstance(items, list) or not items:
        return False, []
    details: list[dict[str, Any]] = []
    bools: list[bool] = []
    for cond in items:
        if not isinstance(cond, dict):
            continue
        ctype = str(cond.get("type") or cond.get("field") or "").strip().lower()
        if ctype in ("price", "close"):
            left = _safe_float(quote.get("price") if quote.get("price") is not None else quote.get("close"))
        elif ctype in ("pct", "change_pct"):
            left = _safe_float(quote.get("pct") if quote.get("pct") is not None else quote.get("change_pct"))
        else:
            details.append({"type": ctype, "error": "unsupported_type", "matched": False})
            bools.append(False)
            continue
        ok = _op_eval(left, str(cond.get("op") or ""), cond.get("value"))
        details.append(
            {
                "type": ctype,
                "op": cond.get("op"),
                "target": cond.get("value"),
                "actual": left,
                "matched": ok,
            }
        )
        bools.append(ok)
    if not bools:
        return False, details
    matched = any(bools) if op == "or" else all(bools)
    return matched, details


def _shanghai_day(now: datetime | None = None) -> str:
    tz = ZoneInfo("Asia/Shanghai")
    current = now.astimezone(tz) if now else datetime.now(tz)
    return current.strftime("%Y-%m-%d")


def _can_trigger(rule: dict[str, Any], *, now: datetime) -> tuple[bool, str]:
    if not rule.get("enabled", True):
        return False, "disabled"
    expire = str(rule.get("expire_at") or "").strip()
    if expire:
        try:
            exp = datetime.fromisoformat(expire.replace("Z", "+00:00"))
            if now > exp:
                return False, "expired"
        except ValueError:
            pass
    day = _shanghai_day(now)
    count = int(rule.get("trigger_count_today") or 0)
    if str(rule.get("trigger_date") or "") != day:
        count = 0
    max_per_day = int(rule.get("max_triggers_per_day") or 0)
    if max_per_day > 0 and count >= max_per_day:
        return False, "daily_limit"
    if str(rule.get("repeat_mode") or "") == "once" and rule.get("last_trigger_at"):
        return False, "once_triggered"
    last = str(rule.get("last_trigger_at") or "").strip()
    if last:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            cooldown = max(0, int(rule.get("cooldown_minutes") or 0)) * 60
            if (now - last_dt).total_seconds() < cooldown:
                return False, "cooldown"
        except ValueError:
            pass
    return True, "ok"


def format_rule_hits(items: list[dict[str, Any]]) -> str:
    if not items:
        return "【价格提醒】\n今日暂无规则命中。"
    lines = [f"【价格提醒】共 {len(items)} 条"]
    for item in items[:12]:
        lines.append(
            f"{item.get('name') or item.get('code')} {item.get('code')} · "
            f"{item.get('rule_name') or item.get('rule_id')} · "
            f"价 {item.get('price')}"
        )
    if len(items) > 12:
        lines.append(f"…另有 {len(items) - 12} 条")
    return "\n".join(lines)


def scan_alert_rules(store: Any, *, dry_run: bool = False) -> dict[str, Any]:
    from src.ops.application.notify_dispatch import dispatch_text

    rules = store.list_alert_rules(enabled_only=True)
    if not rules:
        return {"total_rules": 0, "triggered": 0, "items": []}
    codes: list[str] = []
    for rule in rules:
        try:
            codes.append(normalize_code(str(rule.get("code") or "")))
        except Exception:
            continue
    quotes, _adapters, _hits = get_cached_quotes(codes)
    now = datetime.now().astimezone()
    day = _shanghai_day(now)
    triggered: list[dict[str, Any]] = []
    skipped = 0

    for rule in rules:
        try:
            code = normalize_code(str(rule.get("code") or ""))
        except Exception:
            skipped += 1
            continue
        quote = quotes.get(code)
        if not quote:
            skipped += 1
            continue
        can, reason = _can_trigger(rule, now=now)
        if not can:
            skipped += 1
            continue
        matched, details = eval_condition_group(rule.get("condition_group") or {}, quote)
        if not matched:
            skipped += 1
            continue
        price = quote.get("price")
        item = {
            "rule_id": rule["id"],
            "rule_name": rule.get("name") or "",
            "code": code,
            "name": quote.get("name") or code,
            "price": price,
            "conditions": details,
        }
        bucket = now.strftime("%Y%m%d%H%M")
        if dry_run:
            item["status"] = "would_trigger"
            triggered.append(item)
            continue
        hit = store.insert_alert_hit(
            {
                "rule_id": rule["id"],
                "trigger_bucket": bucket,
                "trigger_time": now.isoformat(timespec="seconds"),
                "snapshot": {"quote": quote, "conditions": details},
            }
        )
        if not hit:
            skipped += 1
            continue
        count = int(rule.get("trigger_count_today") or 0)
        if str(rule.get("trigger_date") or "") != day:
            count = 0
        store.touch_alert_trigger(
            rule["id"],
            trigger_at=now.isoformat(timespec="seconds"),
            trigger_date=day,
            trigger_count_today=count + 1,
        )
        body = format_rule_hits([item])
        outcome = dispatch_text(
            store,
            title="价格提醒",
            body=body,
            channel_ids=[str(x) for x in (rule.get("channel_ids") or [])] or None,
        )
        item["notify"] = outcome
        triggered.append(item)
    return {
        "total_rules": len(rules),
        "triggered": len(triggered),
        "skipped": skipped,
        "items": triggered,
        "dry_run": dry_run,
    }
