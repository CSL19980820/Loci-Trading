"""纸面跟随推送：持仓摘要行 + hold 状态节流 + 中文相位/情景。"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any

DEFAULT_OBSERVE_ALERT_COOLDOWN_MINUTES = 30.0
_ALERT_COOLDOWN_SETTING = "paper_follow_observe_alert_cooldown"
_MAX_ALERT_COOLDOWN_ENTRIES = 256
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{0,3}\d{4,6})(?![A-Za-z0-9])")
_ALERT_PREFIX_RE = re.compile(r"^\s*(?:⚠️\s*)?观察预警\s*", re.I)
_ALERT_MARKER_RE = re.compile(r"\s*[·•]\s*")

_PHASE_ZH = {
    "pre_auction": "盘前",
    "auction": "竞价",
    "open": "开盘",
    "regular": "盘中",
    "closed": "已收盘",
}

_STANCE_ZH = {
    "confirmed": "确认",
    "downgraded": "降级",
    "abandoned": "放弃",
    "abandon": "放弃",
    "pending": "待定",
    "follow": "跟随",
    "revise": "修正",
    "wait": "等待",
}

# 不用 \\b：Unicode 下汉字也算 word，`其gap_up预案` 会洗不掉。
_ASCII_WORD = r"(?<![A-Za-z0-9_]){0}(?![A-Za-z0-9_])"


def _aw(token: str) -> re.Pattern[str]:
    return re.compile(_ASCII_WORD.format(re.escape(token)), re.I)


_REASON_REPLACEMENTS = (
    # 字段名泄漏（模型 notes 常见）
    (re.compile(r"entry_allowed\s*=\s*false", re.I), "不允许开仓"),
    (re.compile(r"entry_allowed\s*=\s*true", re.I), "允许开仓"),
    (re.compile(r"intent\s*=\s*observe", re.I), "观察票"),
    (re.compile(r"intent\s*=\s*buy", re.I), "可买票"),
    (re.compile(r"stance\s*=\s*", re.I), ""),
    (re.compile(r"buy\s*=\s*true", re.I), "预案可买"),
    (re.compile(r"buy\s*=\s*false", re.I), "预案不买"),
    # 情景 / 动作英文
    (_aw("gap_up"), "高开"),
    (_aw("gap_down"), "低开"),
    (_aw("flat"), "平开"),
    (_aw("abandon"), "放弃"),
    (_aw("abandoned"), "放弃"),
    (_aw("downgraded"), "降级"),
    (_aw("confirmed"), "确认"),
    (_aw("pending"), "待定"),
    (_aw("follow"), "跟随"),
    (_aw("revise"), "修正"),
    (_aw("wait"), "等待"),
    (_aw("scenario"), "情景"),
    (_aw("open"), "开仓"),
    (_aw("add"), "加仓"),
    (_aw("buy_dip"), "低吸"),
    (_aw("hold"), "持有"),
)


def phase_zh(phase: str) -> str:
    key = str(phase or "").strip()
    return _PHASE_ZH.get(key, key if key and not re.search(r"[A-Za-z]", key) else "盘中")


def stance_zh(stance: str) -> str:
    key = str(stance or "").strip().lower()
    if key in _STANCE_ZH:
        return _STANCE_ZH[key]
    if key and not re.search(r"[A-Za-z_]", key):
        return key
    return "待定"


def scrub_follow_reason(text: str) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    for pattern, repl in _REASON_REPLACEMENTS:
        out = pattern.sub(repl, out)
    out = out.replace("情景预案不买", "预案不买")
    # 同义重复：「观察票（观察票）」「不允许开仓（不允许开仓）」
    out = re.sub(r"([\u4e00-\u9fff]{2,12})[（(]\1[）)]", r"\1", out)
    # 清洗后空括号 / 重复标点
    out = re.sub(r"[（(]\s*[）)]", "", out)
    out = re.sub(r"[；;]{2,}", "；", out)
    out = re.sub(r"[，,]{2,}", "，", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ；;—-")
    return out


def format_stance_line(stance: dict[str, Any]) -> str:
    """竞价/开盘一行，全中文。"""
    if not isinstance(stance, dict):
        return ""
    who = str(stance.get("name") or stance.get("code") or "").strip()
    gap = stance.get("gap_pct")
    try:
        gap_txt = "" if gap is None else f"{float(gap):+.2f}%"
    except (TypeError, ValueError):
        gap_txt = ""
    reason = scrub_follow_reason(str(stance.get("reason") or ""))
    bits = [who, stance_zh(str(stance.get("stance") or "")), gap_txt]
    line = " ".join(b for b in bits if b)
    if reason:
        line = f"{line} — {reason}" if line else reason
    return line.strip(" —")


def _quote_price(quotes: dict[str, Any], code: str) -> float | None:
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


def format_position_lines(
    positions: list[dict[str, Any]],
    quotes: dict[str, Any] | None = None,
    *,
    limit: int = 6,
) -> list[str]:
    """持仓一行：名称 · N层 · 成本 · 浮动盈亏%（价来自 TTL，缺价则省略浮动）。"""
    quotes = quotes or {}
    lines: list[str] = []
    for pos in positions[:limit]:
        if not isinstance(pos, dict):
            continue
        code = str(pos.get("code") or "").strip()
        name = str(pos.get("name") or code or "").strip()
        try:
            layers = float(pos.get("layers") or 0)
        except (TypeError, ValueError):
            layers = 0.0
        if layers <= 0:
            continue
        try:
            cost = float(pos.get("mark_cost") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        bits = [f"📦{name}", f"{layers:g}层"]
        if cost > 0:
            bits.append(f"成本{cost:g}")
        last = _quote_price(quotes, code)
        if last is not None and cost > 0:
            pnl = (last / cost - 1.0) * 100.0
            bits.append(f"{pnl:+.1f}%")
        lines.append(" · ".join(bits))
    return lines


def _fingerprint_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _normalise_alert_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n·•|;；")


def _split_alert_parts(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = _fingerprint_text(value)
        parts = [part.strip() for part in re.split(r"\s*\|\s*|\r?\n", text) if part.strip()]
    if len(parts) < 2:
        return parts

    # Production fingerprints join complete warning lines with "|". Compact
    # test/legacy forms such as "600519|跌破分线" are one logical line.
    grouped: list[str] = []
    for part in parts:
        if grouped and not _CODE_RE.search(part):
            grouped[-1] = f"{grouped[-1]} · {part}"
        else:
            grouped.append(part)
    return grouped


def _parse_alert_row(value: str) -> tuple[str, str, str]:
    text = _normalise_alert_text(value)
    body = _ALERT_PREFIX_RE.sub("", text, count=1)
    marker = _ALERT_MARKER_RE.search(body)
    head = body[: marker.start()] if marker else body
    matches = list(_CODE_RE.finditer(head)) or list(_CODE_RE.finditer(body))
    match = matches[-1] if matches else None

    if marker:
        reason = body[marker.end() :]
    elif match:
        reason = body[match.end() :].lstrip(" \t:：|,-")
    else:
        reason = body

    if match:
        code = match.group(1).upper()
    else:
        # An opaque legacy fingerprint still gets isolated instead of
        # suppressing alerts from a different ticket.
        code = f"line:{body.casefold()}"
    reason = _normalise_alert_text(reason) or "未注明"
    return code, reason.casefold(), text


def _parse_alert_rows(value: Any) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for part in _split_alert_parts(value):
        code, reason, raw = _parse_alert_row(part)
        key = (code, reason)
        if key in seen:
            continue
        seen.add(key)
        rows.append((code, reason, raw))
    return rows


def _normalise_cooldown_minutes(value: Any) -> float:
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return DEFAULT_OBSERVE_ALERT_COOLDOWN_MINUTES
    if not isfinite(minutes):
        return DEFAULT_OBSERVE_ALERT_COOLDOWN_MINUTES
    return max(0.0, minutes)


def _coerce_now(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            current = datetime.fromisoformat(raw)
        except ValueError:
            current = datetime.now(timezone.utc)
    else:
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_stored_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_alert_entries(store: Any) -> list[dict[str, str]]:
    raw = store.get_setting(_ALERT_COOLDOWN_SETTING, {})
    if isinstance(raw, dict):
        raw_entries = raw.get("entries", [])
    elif isinstance(raw, list):
        raw_entries = raw
    else:
        raw_entries = []
    if not isinstance(raw_entries, list):
        return []

    entries: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        entry = {
            "slug": str(item.get("slug") or "").strip(),
            "trade_date": str(item.get("trade_date") or "").strip(),
            "code": str(item.get("code") or "").strip().upper(),
            "reason": _normalise_alert_text(item.get("reason")).casefold(),
            "last_pushed_at": str(item.get("last_pushed_at") or "").strip(),
        }
        if not all(entry.values()) or _parse_stored_at(entry["last_pushed_at"]) is None:
            continue
        entries.append(entry)
    return entries


def _alert_entry_key(entry: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        entry["slug"],
        entry["trade_date"],
        entry["code"],
        entry["reason"],
    )


def _claim_observe_alert_rows(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    alert_fp: Any,
    now: datetime | str | None,
    cooldown_minutes: Any,
) -> tuple[list[tuple[str, str, str]], set[tuple[str, str]]]:
    current = _coerce_now(now)
    cooldown = _normalise_cooldown_minutes(cooldown_minutes)
    slug_key = str(slug or "").strip()
    date_key = str(trade_date or "").strip()
    entries_by_key: dict[tuple[str, str, str, str], dict[str, str]] = {}
    state_changed = False

    for entry in _load_alert_entries(store):
        last = _parse_stored_at(entry["last_pushed_at"])
        if last is None:
            state_changed = True
            continue
        age_minutes = (current - last).total_seconds() / 60.0
        if age_minutes >= cooldown:
            state_changed = True
            continue
        key = _alert_entry_key(entry)
        previous = entries_by_key.get(key)
        if previous is None or entry["last_pushed_at"] > previous["last_pushed_at"]:
            entries_by_key[key] = entry
        else:
            state_changed = True

    rows = _parse_alert_rows(alert_fp)
    current_keys = {(code, reason) for code, reason, _ in rows}
    allowed: list[tuple[str, str, str]] = []
    now_text = current.isoformat(timespec="seconds")
    for code, reason, raw in rows:
        key = (slug_key, date_key, code, reason)
        if key in entries_by_key:
            continue
        allowed.append((code, reason, raw))
        entries_by_key[key] = {
            "slug": slug_key,
            "trade_date": date_key,
            "code": code,
            "reason": reason,
            "last_pushed_at": now_text,
        }
        state_changed = True

    entries = sorted(
        entries_by_key.values(),
        key=lambda item: item["last_pushed_at"],
        reverse=True,
    )
    if len(entries) > _MAX_ALERT_COOLDOWN_ENTRIES:
        entries = entries[:_MAX_ALERT_COOLDOWN_ENTRIES]
        state_changed = True
    if state_changed:
        store.set_setting(
            _ALERT_COOLDOWN_SETTING,
            {"version": 1, "entries": entries},
        )
    return allowed, current_keys


def filter_observe_alert_lines(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    alert_lines: list[str],
    now: datetime | str | None = None,
    cooldown_minutes: float = DEFAULT_OBSERVE_ALERT_COOLDOWN_MINUTES,
) -> list[str]:
    """保留本轮可推的预警行；持仓和正常观察行不经过此过滤。"""
    allowed, _ = _claim_observe_alert_rows(
        store,
        slug=slug,
        trade_date=trade_date,
        alert_fp=alert_lines,
        now=now,
        cooldown_minutes=cooldown_minutes,
    )
    return [raw for _, _, raw in allowed]


def _snapshot_alert_keys(value: Any) -> set[tuple[str, str]] | None:
    if not isinstance(value, dict):
        return None
    raw_alerts = value.get("alerts")
    if not isinstance(raw_alerts, list):
        return None
    keys: set[tuple[str, str]] = set()
    for item in raw_alerts:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        reason = _normalise_alert_text(item.get("reason")).casefold()
        if code and reason:
            keys.add((code, reason))
    return keys


def should_push_hold_snapshot(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    phase: str,
    positions: list[dict[str, Any]],
    notes: str,
    market_gate: dict[str, Any] | None,
    observe_items: list[dict[str, Any]] | None = None,
    observe_alert_fp: str = "",
    now: datetime | str | None = None,
    cooldown_minutes: float = DEFAULT_OBSERVE_ALERT_COOLDOWN_MINUTES,
) -> bool:
    """无成交时的巡检推送：基础快照去重，预警行按票/因冷却。"""
    from src.ops.application.skill_watch.paper_eligibility import is_observe_intent

    pos_fp = "|".join(
        sorted(
            f"{p.get('code')}:{float(p.get('layers') or 0):g}"
            for p in positions
            if isinstance(p, dict) and float(p.get("layers") or 0) > 0
        )
    )
    obs_fp = "|".join(
        sorted(
            str(i.get("code") or "")
            for i in (observe_items or [])
            if isinstance(i, dict) and is_observe_intent(i) and i.get("code")
        )
    )
    if not pos_fp and not obs_fp:
        return False
    gate_state = ""
    if isinstance(market_gate, dict):
        gate_state = str(market_gate.get("state") or market_gate.get("mode") or "")
    alert_fp = _fingerprint_text(observe_alert_fp)
    allowed_alerts, current_alert_keys = _claim_observe_alert_rows(
        store,
        slug=slug,
        trade_date=trade_date,
        alert_fp=alert_fp,
        now=now,
        cooldown_minutes=cooldown_minutes,
    )
    # AI notes 只留审计，不参与推送状态。自由文本每轮轻微改写会造成虚假“状态变化”；
    # 真正动作已经由成交、拒单、持仓层数和市场闸门单独进入指纹。
    notes_text = str(notes or "").strip()[:120]
    legacy_token = (
        f"{trade_date}|{phase}|pos:{pos_fp}|obs:{obs_fp}|alert:{alert_fp}|{gate_state}|"
        f"{notes_text}"
    )
    base_token = f"{trade_date}|{phase}|pos:{pos_fp}|obs:{obs_fp}|{gate_state}"
    key = f"paper_follow_hold:{slug}"
    prev = store.get_setting(key)
    previous_base_matches = False
    previous_alert_keys: set[tuple[str, str]] | None = None
    if isinstance(prev, dict):
        previous_base_matches = prev.get("base") == base_token
        previous_alert_keys = _snapshot_alert_keys(prev)
    elif isinstance(prev, str):
        previous_base_matches = prev in {base_token, legacy_token}
        if previous_base_matches:
            previous_alert_keys = set(current_alert_keys)

    # A legacy string has no timestamp. Treat an exact old fingerprint as
    # already delivered once, while new/changed reasons still pass through.
    if prev == legacy_token and allowed_alerts:
        allowed_alerts = []

    first_snapshot = prev is None
    base_changed = first_snapshot or not previous_base_matches
    alerts_changed = (
        previous_alert_keys is not None and previous_alert_keys != current_alert_keys
    )
    should_push = bool(base_changed or alerts_changed or allowed_alerts)
    if not should_push:
        return False

    if current_alert_keys:
        snapshot: Any = {
            "version": 2,
            "base": base_token,
            "alerts": [
                {"code": code, "reason": reason}
                for code, reason in sorted(current_alert_keys)
            ],
        }
    else:
        snapshot = base_token
    store.set_setting(key, snapshot)
    return True
