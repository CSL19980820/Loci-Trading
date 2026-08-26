"""纸面介入一行：名称 · 层数 · 买入价 · 单一盈亏比例。

用户口径示例：``百花医药 · 3层 · 11.2 · -20%``（盈亏比例只有一个，无斜杠双值）。
数字必须来自扫描/成交/舱配置事实，禁止 AI 编造价位。
"""
from __future__ import annotations

from typing import Any


def layers_for_candidate(
    score: Any,
    *,
    role: str = "",
    max_layers: float = 3.0,
) -> float:
    """按形态分给层：高分多给，中军封顶更低；最小 0.5。"""
    try:
        points = float(score or 0)
    except (TypeError, ValueError):
        points = 0.0
    if points >= 85:
        layers = 3.0
    elif points >= 75:
        layers = 2.0
    elif points >= 65:
        layers = 1.0
    else:
        layers = 0.5
    if str(role or "") == "secondary":
        layers = min(layers, 1.5)
    cap = max(0.5, float(max_layers or 3.0))
    return min(cap, max(0.5, layers))


def _fmt_price(value: Any) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return ""
    if price <= 0:
        return ""
    text = f"{price:.2f}"
    if text.endswith("0"):
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_layers(value: Any) -> str:
    try:
        layers = float(value)
    except (TypeError, ValueError):
        return ""
    if layers <= 0:
        return ""
    if abs(layers - round(layers)) < 1e-9:
        return str(int(round(layers)))
    return f"{layers:.1f}".rstrip("0").rstrip(".")


def resolve_pnl_pct(row: dict[str, Any] | None = None, **overrides: Any) -> float | None:
    """只取一个盈亏比例：显式 pnl_pct > 止损 > 止盈。"""
    data = {**(row or {}), **overrides}
    for key in ("pnl_pct", "stop_loss_pct", "take_profit_pct"):
        raw = data.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _fmt_pnl(value: Any) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{pct:+.0f}%"


def format_actionable_line(
    *,
    name: str = "",
    code: str = "",
    layers: Any = None,
    buy_price: Any = None,
    pnl_pct: Any = None,
    stop_loss_pct: Any = None,
    take_profit_pct: Any = None,
) -> str:
    """``💰百花医药 · 3层 · 买11.2 · -20%``。"""
    who = str(name or "").strip() or str(code or "").strip() or "未命名"
    layer_txt = _fmt_layers(layers)
    price_txt = _fmt_price(buy_price)
    band = _fmt_pnl(
        resolve_pnl_pct(
            {"pnl_pct": pnl_pct, "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct}
        )
    )
    bits = [f"💰{who}"]
    if layer_txt:
        bits.append(f"{layer_txt}层")
    if price_txt:
        bits.append(f"买{price_txt}")
    if band:
        bits.append(band)
    return " · ".join(bits)


def enrich_actionable_fields(
    row: dict[str, Any],
    *,
    role: str = "",
    score: Any = None,
) -> dict[str, Any]:
    """给纸面候选补齐层数 / 买入价；盈亏比例只保留一个字段。"""
    out = dict(row)
    # 观察票禁止补可买层：0 是「不开仓」语义，不是缺失
    if str(out.get("intent") or "").strip().lower() == "observe":
        out["planned_layers"] = 0.0
        out["planned_layers_max"] = 0.0
        return out
    points = score if score is not None else out.get("score")
    role_key = role or str(out.get("role") or "")
    if out.get("planned_layers") in (None, "", 0, 0.0):
        out["planned_layers"] = layers_for_candidate(points, role=role_key)
    price = out.get("buy_price")
    if price in (None, "", 0, 0.0):
        price = out.get("close") or out.get("ref_close") or out.get("mark_price")
    if price not in (None, ""):
        try:
            out["buy_price"] = round(float(price), 2)
        except (TypeError, ValueError):
            pass
    pnl = resolve_pnl_pct(out)
    if pnl is not None:
        out["pnl_pct"] = pnl
    # 推送只认单一比例，避免下游再拼止损/止盈斜杠
    out.pop("take_profit_pct", None)
    if "stop_loss_pct" in out and "pnl_pct" in out:
        out.pop("stop_loss_pct", None)
    return out


__all__ = [
    "enrich_actionable_fields",
    "format_actionable_line",
    "layers_for_candidate",
    "resolve_pnl_pct",
]
