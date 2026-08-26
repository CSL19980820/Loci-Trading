"""战法监测推送正文：能一行就一行，中文短句，轻量 emoji。"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.skill_watch.roles import ROLE_LABEL
from src.ops.application.skill_watch.watch_labels import watch_short_name

_SIGNAL_LABEL = {
    "buy_hint": "候选",
    "sell_hint": "风险",
    "watch_only": "观察",
    "paper_candidate": "纸面",
    "invalidated": "失效",
    "leader_watch": "龙头",
    "leader_weak": "走弱",
    "theme_interval_weak": "区间走弱",
    "theme_interval_degraded": "区间降级",
    "gate_empty": "空仓",
}

_SIGNAL_EMOJI = {
    "buy_hint": "📌",
    "sell_hint": "⚠️",
    "watch_only": "👀",
    "paper_candidate": "📌",
    "invalidated": "❌",
    "leader_watch": "🐉",
    "leader_weak": "⚠️",
    "theme_interval_weak": "📉",
    "theme_interval_degraded": "📉",
}

_MISSING_LABEL = {
    "promotion_rate": "晋级率",
    "theme_strength": "主线强度",
    "height": "梯队高度",
    "broken_rate": "炸板率",
    "breadth": "宽度",
    "temperature": "温度",
}

_GATE_HEAD = {
    "dragon": ("🚀", "进攻"),
    "observe": ("👀", "观察"),
    "empty": ("🛑", "空仓"),
}

_SKIP_SIGNAL_TYPES = frozenset({"gate_empty"})
_MARKET_CODES = frozenset({"market", "MARKET", "大盘", ""})
_ASCII_WORD = re.compile(r"[A-Za-z_]{2,}")
_THEME_CODE = re.compile(r"\b\d{5,6}k?\b", re.IGNORECASE)
_TZ = ZoneInfo("Asia/Shanghai")


def _short_skill_name(skill_name: str, slug: str) -> str:
    name = str(skill_name or "").strip()
    if not name or _looks_like_slug(name):
        name = watch_short_name(slug=str(slug or "").strip()) or ""
    if "·" in name:
        name = name.split("·", 1)[0].strip() or name
    if name.endswith("实战战法"):
        name = name[: -len("实战战法")].strip() or name
    return name or "战法"


def _looks_like_slug(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and ("-" in text or "_" in text) and bool(re.search(r"[A-Za-z]", text))


def _zh_role(role: str) -> str:
    key = str(role or "").strip()
    if not key:
        return ""
    return ROLE_LABEL.get(key, key if not _ASCII_WORD.search(key) else "")


def _display_name(*, name: str = "", code: str = "") -> str:
    who = str(name or "").strip()
    raw_code = str(code or "").strip()
    if raw_code.lower() in _MARKET_CODES or raw_code.lower() == "market":
        raw_code = ""
    if who and who.lower() == "market":
        who = ""
    if who and _looks_like_slug(who):
        who = ""
    if who:
        return who
    digits = re.sub(r"\D", "", raw_code)
    if len(digits) == 6 and not re.search(r"[A-Za-z]", raw_code):
        return digits
    return ""


def _scrub_user_text(text: str) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    out = out.replace("market", "").replace("MARKET", "")
    # 技术指标英文缩写 → 中文（推送可读）
    out = re.sub(r"\bMA\s*10\b", "十日线", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMA\s*5\b", "五日线", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMA\s*20\b", "二十日线", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMA\s*250\b", "年线", out, flags=re.IGNORECASE)
    out = _THEME_CODE.sub("", out)
    out = re.sub(r"[；;]\s*[；;]", "；", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ；;·")
    return out


def _clean_reasons(gate: dict[str, Any]) -> list[str]:
    raw = gate.get("reasons") if isinstance(gate.get("reasons"), list) else []
    out: list[str] = []
    for item in raw:
        text = _scrub_user_text(str(item or ""))
        if not text or text.startswith("关键数据不完整") or text.startswith("数据非当日"):
            continue
        if text not in out:
            out.append(text)
    return out


def _fmt_clock(snapshot: str) -> str:
    text = str(snapshot or "").strip()
    if not text:
        return ""
    try:
        # 悟道多为 UTC：2026-08-07T03:02:02.655Z
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(_TZ)
        else:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_TZ)
            else:
                dt = dt.astimezone(_TZ)
        return dt.strftime("%H:%M")
    except ValueError:
        return ""


def _fmt_day(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text[5:]  # MM-DD
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[4:6]}-{digits[6:8]}"
    return text


def _head_line(gate: dict[str, Any], trade_date: str) -> str:
    """时间 + 闸门 + 依据/缺项，尽量压成一行。"""
    state = str(gate.get("state") or "")
    emoji, head = _GATE_HEAD.get(state, ("ℹ️", "未知"))
    missing = [str(x) for x in (gate.get("missing") or []) if str(x).strip()]
    degraded = str(gate.get("data_status") or "") == "degraded" or bool(missing)
    reasons = _clean_reasons(gate)
    freshness = gate.get("freshness") if isinstance(gate.get("freshness"), dict) else {}
    stale = bool(freshness.get("stale")) or any(
        str(r).startswith("数据非当日") for r in (gate.get("reasons") or [])
    )
    day = _fmt_day(
        str(freshness.get("actual_trade_date") or gate.get("trade_date") or trade_date or "")
    )
    clock = _fmt_clock(str(freshness.get("snapshot_time") or ""))
    when = f"📅{day}"
    if clock and not stale:
        when = f"📅{day} {clock}"
    if stale:
        when = f"📅{day}·非实时"

    warnings = [str(x) for x in (gate.get("quality_warnings") or [])]
    tool_blown = any(
        w.endswith(":tool_error") or w in {"mcp_unavailable", "market_gate_unavailable"}
        for w in warnings
    )
    reason_join = "；".join(str(r) for r in (gate.get("reasons") or []) if str(r).strip())
    cred_broken = "凭据" in reason_join or "解密" in reason_join or any(
        "凭据" in w or "解密" in w for w in warnings
    )

    gate_bit = f"{emoji}{head}"
    if state == "empty" and stale:
        gate_bit = f"{emoji}{head}·非当日"
    elif state == "empty" and cred_broken:
        gate_bit = f"{emoji}{head}·悟道凭据失效"
    elif state == "empty" and tool_blown:
        gate_bit = f"{emoji}{head}·悟道调用失败"
    elif state == "empty" and degraded:
        gate_bit = f"{emoji}{head}·数据不全"

    bits = [when, gate_bit]
    if state == "empty" and cred_broken:
        bits.append("请到设置→MCP 重新保存悟道 API Key")
    elif state == "empty" and tool_blown:
        bits.append("三路快照未取到，请检查悟道 Key/配额后重跑监测")
    elif state == "empty" and degraded and missing:
        labels = "、".join(_MISSING_LABEL[m] for m in missing if m in _MISSING_LABEL)
        if labels:
            bits.append(f"缺：{labels}")
    if reasons and not (cred_broken or tool_blown):
        label = "已见" if (state == "empty" and degraded and not stale) else "依据"
        bits.append(f"{label}：{'；'.join(reasons[:4])}")
    elif state == "empty" and not degraded:
        bits.append("依据：风险信号触发空仓")

    if state == "empty":
        bits.append("→不扩仓")
    return " · ".join(bits)


def _format_signal_line(signal: dict[str, Any]) -> str:
    kind = str(signal.get("type") or "")
    if kind in _SKIP_SIGNAL_TYPES:
        return ""
    # 区间强度：给用户看「主线区间对照失败/走弱」，不要堆「四象限/软过滤」术语
    if kind == "theme_interval_degraded":
        status = str(signal.get("role") or "").strip()
        detail = _scrub_user_text(str(signal.get("reason") or ""))
        if status == "concept_unavailable":
            return "📉区间强势题材本轮取不到盘中数据（主线仍按盘中强度排序）"
        if status == "unmatched" or "未对齐" in detail or "未命中" in detail:
            return "📉主线区间强度暂不可用（题材对照未对齐，仍按盘中强度排序）"
        if status == "unavailable" or "不可用" in detail or "为空" in detail:
            return "📉主线区间强度暂不可用（已退回盘中强度排序）"
        if status == "partial" or "部分" in detail:
            return "📉主线区间强度仅部分命中（未命中题材仍按盘中强度）"
        return "📉主线区间强度降级（仍按盘中强度排序）"
    if kind == "theme_interval_weak":
        who = _display_name(
            name=str(signal.get("name") or ""),
            code=str(signal.get("code") or ""),
        )
        reason = _scrub_user_text(str(signal.get("reason") or ""))
        if who and reason:
            return f"📉主线走弱 {who}：{reason}"
        if who:
            return f"📉主线走弱 {who}"
        return f"📉主线走弱{('：' + reason) if reason else ''}"
    if kind == "invalidated":
        who = _display_name(
            name=str(signal.get("name") or ""),
            code=str(signal.get("code") or ""),
        )
        reason = _scrub_user_text(str(signal.get("reason") or ""))
        if "：" in reason:
            reason = reason.split("：", 1)[1].strip() or reason
        reason = reason.replace("或失守", "或跌破").replace("曾强但已", "")
        if who and reason:
            return f"❌失效 {who}：{reason}"
        if who:
            return f"❌失效 {who}"
        return f"❌失效{('：' + reason) if reason else ''}"

    label = _SIGNAL_LABEL.get(kind)
    if not label:
        return ""
    icon = _SIGNAL_EMOJI.get(kind, "•")
    who = _display_name(
        name=str(signal.get("name") or ""),
        code=str(signal.get("code") or ""),
    )
    score = signal.get("score")
    role = _zh_role(str(signal.get("role") or signal.get("role_label") or ""))
    reason = _scrub_user_text(str(signal.get("reason") or signal.get("theme") or ""))
    if role and reason.startswith(role):
        role = ""
    bits = [f"{icon}{label}"]
    if who:
        bits.append(who)
    if role and role != label:
        bits.append(role)
    if score is not None and str(score) != "":
        bits.append(f"分{score}")
    if reason and kind not in {"paper_candidate", "buy_hint", "leader_watch"}:
        # 理由过长时只留冒号后半段
        if "：" in reason:
            reason = reason.split("：", 1)[1].strip() or reason
        bits.append(reason)
    return " ".join(str(b) for b in bits if b)


def _pct(value: float | None, *, digits: int = 1) -> str:
    if value is None:
        return ""
    pct = value * 100.0 if abs(value) <= 1.5 else value
    return f"{pct:.{digits}f}%"


def _fmt_yi(amount: float | None) -> str:
    """题材主力净额多为元；情绪 main_net_yi 已是亿元。"""
    if amount is None:
        return ""
    yi = amount / 1e8 if abs(amount) >= 1e5 else amount
    sign = "+" if yi >= 0 else ""
    if abs(yi) >= 100:
        return f"{sign}{yi:.0f}亿"
    return f"{sign}{yi:.1f}亿"


def _metrics_line(gate: dict[str, Any]) -> str:
    """盘面仪表：晋级/封板/炸板/跌停/宽度/温度/涨跌停家数。

    非当日（stale）不输出，避免把昨收截面写成此刻盘面。
    """
    freshness = gate.get("freshness") if isinstance(gate.get("freshness"), dict) else {}
    if freshness.get("stale"):
        return ""
    metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
    if not metrics:
        return ""
    bits: list[str] = []
    promotion = _pct(metrics.get("promotion_rate"))
    if promotion:
        bits.append(f"晋级{promotion}")
    seal = _pct(metrics.get("seal_rate"))
    if seal:
        bits.append(f"封板{seal}")
    broken = _pct(metrics.get("broken_rate"))
    if broken:
        bits.append(f"炸板{broken}")
    down_rate = _pct(metrics.get("limit_down_rate"))
    if down_rate:
        bits.append(f"跌停率{down_rate}")
    breadth = _pct(metrics.get("breadth"))
    if breadth:
        bits.append(f"宽度{breadth}")
    temperature = metrics.get("temperature")
    if temperature is not None:
        temp = temperature if abs(float(temperature)) > 1.5 else float(temperature) * 100.0
        bits.append(f"温度{temp:.0f}")
    height = metrics.get("height")
    if height is not None:
        bits.append(f"最高{int(height) if float(height) == int(float(height)) else height}板")
    up = metrics.get("limit_up_count")
    down = metrics.get("limit_down_count")
    if up is not None or down is not None:
        up_s = f"{int(up)}" if up is not None else "—"
        down_s = f"{int(down)}" if down is not None else "—"
        bits.append(f"涨停{up_s}/跌停{down_s}")
    main_net = metrics.get("main_net_yi")
    if main_net is not None:
        bits.append(f"主力{_fmt_yi(float(main_net))}")
    clock = _fmt_clock(str(freshness.get("snapshot_time") or ""))
    if clock:
        bits.append(f"截至{clock}")
    if freshness.get("is_realtime") is False:
        bits.append("快照")
    if not bits:
        return ""
    return "📊盘面 " + " · ".join(bits)


def _themes_line(themes: list[dict[str, Any]] | None, *, stale: bool = False) -> str:
    """最强板块 + 涨幅 + 主力净流入（仅当日盘中截面；不引用 boomReason）。"""
    if stale:
        return ""
    rows = [
        t
        for t in (themes or [])
        if isinstance(t, dict) and str(t.get("theme_name") or "").strip()
    ]
    if not rows:
        return ""

    def _strength(row: dict[str, Any]) -> float:
        value = row.get("strength")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(rows, key=_strength, reverse=True)[:3]
    bits: list[str] = []
    for row in ranked:
        name = str(row.get("theme_name") or "").strip()
        interval = str(row.get("interval_label") or "").strip()
        pct = row.get("pct_chg")
        try:
            pct_s = f"{float(pct):+.1f}%" if pct is not None else ""
        except (TypeError, ValueError):
            pct_s = ""
        try:
            flow = (
                _fmt_yi(float(row.get("main_net_amount")))
                if row.get("main_net_amount") is not None
                else ""
            )
        except (TypeError, ValueError):
            flow = ""
        detail = " ".join(x for x in (interval, pct_s, flow) if x)
        bits.append(f"{name}({detail})" if detail else name)
    return "🏷最强 " + " · ".join(bits)


def _leaders_line(
    leaders: list[dict[str, Any]] | None,
    *,
    stale: bool = False,
    trade_date: str = "",
) -> str:
    """龙头地图摘要：名(题材·板)·当日涨跌。

    涨跌优先认涨停标记；日 K 末根日期对不上监测日则不写涨跌，避免把昨收当现价。
    """
    if stale:
        return ""
    rows = [r for r in (leaders or []) if isinstance(r, dict)]
    if not rows:
        return ""
    day = str(trade_date or "").strip()[:10]
    bits: list[str] = []
    for row in rows[:3]:
        who = _display_name(name=str(row.get("name") or ""), code=str(row.get("code") or ""))
        if not who:
            continue
        theme = str(row.get("theme_name") or "").strip()
        level = row.get("ladder_level")
        level_s = ""
        try:
            if level is not None and float(level) > 0:
                lv = float(level)
                level_s = f"{int(lv)}板" if lv == int(lv) else f"{lv}板"
        except (TypeError, ValueError):
            level_s = ""
        tag = "·".join(x for x in (theme, level_s) if x)

        move_s = ""
        if row.get("is_limit_up") or row.get("in_ladder"):
            move_s = "涨停"
        else:
            bar_date = str(row.get("bar_date") or "").strip()[:10]
            today = row.get("today_pct")
            bar_ok = (not day) or (not bar_date) or (bar_date == day)
            if bar_ok and today is not None:
                try:
                    move_s = f"{float(today):+.1f}%"
                except (TypeError, ValueError):
                    move_s = ""
        body = who
        if tag:
            body = f"{who}({tag}"
            if move_s:
                body += f" {move_s}"
            body += ")"
        elif move_s:
            body = f"{who} {move_s}"
        bits.append(body)
    if not bits:
        return ""
    return "🐉龙头 " + " · ".join(bits)


def format_watch_summary(
    *,
    skill_name: str,
    slug: str = "",
    trade_date: str = "",
    gate: dict[str, Any] | None = None,
    auction: dict[str, Any] | None = None,
    signals: list[dict[str, Any]] | None = None,
    picks: list[dict[str, Any]] | None = None,
    transitions: list[dict[str, Any]] | None = None,
    themes: list[dict[str, Any]] | None = None,
    leaders: list[dict[str, Any]] | None = None,
    observe_changes: dict[str, Any] | None = None,
) -> str:
    """生成监测推送正文（不含外层【任务名】包装）。"""
    short = _short_skill_name(skill_name, slug)
    lines: list[str] = []

    has_gate = isinstance(gate, dict) and bool(gate)
    gate_freshness = (
        gate.get("freshness") if has_gate and isinstance(gate.get("freshness"), dict) else {}
    )
    gate_stale = bool(gate_freshness.get("stale"))
    if has_gate:
        lines.append(_head_line(gate, trade_date))
        metrics_line = _metrics_line(gate)
        if metrics_line:
            lines.append(metrics_line)
    else:
        day = _fmt_day(trade_date) or short
        lines.append(f"📅{day}")

    themes_line = _themes_line(themes, stale=gate_stale)
    if themes_line:
        lines.append(themes_line)

    leaders_line = _leaders_line(
        leaders,
        stale=gate_stale,
        trade_date=str(
            (gate_freshness.get("actual_trade_date") if gate_freshness else "")
            or (gate.get("trade_date") if has_gate else "")
            or trade_date
            or ""
        ),
    )
    if leaders_line:
        lines.append(leaders_line)

    if isinstance(auction, dict) and auction.get("active"):
        stances = auction.get("stances") or []
        changed = [*auction.get("abandoned", []), *auction.get("downgraded", [])]
        lines.append(f"🔔竞价复核{len(stances)}只，降级/放弃{len(changed)}只")

    pick_rows = [p for p in (picks or []) if isinstance(p, dict)]
    buy_rows = [
        row
        for row in pick_rows
        if row.get("bucket") != "position"
        and str(row.get("action") or row.get("intent")) == "buy"
    ]
    from src.ops.application.skill_watch.watch_pool_format import format_watch_pool_section

    lines.extend(
        format_watch_pool_section(slug=slug, items=pick_rows, changes=observe_changes)
    )

    signal_rows = [s for s in (signals or []) if isinstance(s, dict)]
    pick_codes = {str(p.get("code") or "") for p in pick_rows}
    gate_state = str(gate.get("state") or "") if has_gate else ""
    # 空仓时角色行最多 3 条；已有龙头地图行则少占一行
    signal_cap = 2 if leaders_line else (3 if gate_state == "empty" else 4)
    signal_bits: list[str] = []
    for signal in signal_rows:
        kind = str(signal.get("type") or "")
        if kind in _SKIP_SIGNAL_TYPES:
            continue
        if has_gate and kind == "watch_only" and str(signal.get("code") or "").lower() in {
            "market",
            "",
        }:
            continue
        if kind == "paper_candidate" and str(signal.get("code") or "") in pick_codes:
            continue
        # 龙头/走弱已在龙头地图行展示时，信号行不再重复同名
        if leaders_line and kind in {"leader_watch", "leader_weak"}:
            continue
        text = _format_signal_line(signal)
        if text:
            signal_bits.append(text)
        if len(signal_bits) >= signal_cap:
            break
    # 有可买介入时信号行让位；仅观察或无 picks 时仍出信号（含区间走弱）
    if signal_bits and not buy_rows:
        lines.append(" | ".join(signal_bits))

    # 推送只报当前角色（龙头/中军/走弱），不报「中军→龙头」互转（易误读）
    _ = transitions

    if len(lines) == 1 and not has_gate:
        return "无新信号"
    return "\n".join(lines)
