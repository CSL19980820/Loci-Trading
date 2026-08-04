"""任务栏 / 顶栏用的实时行情条。

走 spot_batch 线路（粘性选路）；失败时返回空列表并带 error，
前端显示「行情暂不可用」而不是编价。
"""
from __future__ import annotations

from datetime import datetime
import logging
import threading
import time
from typing import Any

from src.market.infrastructure.store import MarketError, normalize_code

logger = logging.getLogger(__name__)

#: 默认指数：上证 / 深证 / 创业 / 科创
DEFAULT_INDICES: tuple[tuple[str, str], ...] = (
    ("000001", "上证"),
    ("399001", "深证"),
    ("399006", "创业"),
    ("000688", "科创"),
)

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "key": None, "payload": None}
_CACHE_TTL = 3.0


class _LiveTapeFlight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.payload: dict[str, Any] | None = None
        self.error: Exception | None = None


_INFLIGHT: dict[tuple[Any, ...], _LiveTapeFlight] = {}


def _live_tape_request_key(
    position_codes: list[dict[str, Any]] | None,
    extra_codes: list[str] | None,
) -> tuple[Any, ...]:
    """为 single-flight 建立稳定请求键；不把 ``use_cache`` 纳入键。"""
    positions: list[tuple[str, str, int, float]] = []
    for item in position_codes or []:
        code = _normalize_live_code(item.get("code"))
        if code is None:
            continue
        positions.append(
            (
                code,
                str(item.get("name") or "").strip(),
                int(item.get("shares") or 0),
                float(item.get("cost") or 0),
            )
        )
    extras = tuple(
        code
        for raw in extra_codes or []
        if (code := _normalize_live_code(raw)) is not None
    )
    return tuple(positions), extras


def _normalize_live_code(value: Any) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return normalize_code(text)
    except MarketError:
        return None


def _safe_normalize_live_code(value: Any, *, kind: str) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    normalized = _normalize_live_code(text)
    if normalized is None:
        logger.warning("忽略实时行情中的非法%s代码 %r", kind, text)
        return None
    return normalized


def fetch_live_quotes(
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """批量拉实时富行情（经适配器选路）。``codes`` 为 6 位代码。"""
    from src.market.infrastructure.adapters import AdapterError, fetch_live_quotes_routed

    clean = [
        normalized
        for code in codes
        if (normalized := _safe_normalize_live_code(code, kind="请求")) is not None
    ]
    if not clean:
        return []
    try:
        rows, _aid = fetch_live_quotes_routed(
            clean, instrument_types=instrument_types
        )
        return rows
    except AdapterError as exc:
        logger.warning("实时行情失败：%s", exc)
        raise


def build_live_tape(
    *,
    position_codes: list[dict[str, Any]] | None = None,
    extra_codes: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """组装快照；相同请求并发时共享一次外部行情请求。"""
    request_key = _live_tape_request_key(position_codes, extra_codes)
    with _CACHE_LOCK:
        if (
            use_cache
            and _CACHE["key"] == request_key
            and _CACHE["payload"] is not None
            and time.monotonic() - float(_CACHE["at"]) < _CACHE_TTL
        ):
            return dict(_CACHE["payload"])
        flight = _INFLIGHT.get(request_key)
        if flight is None:
            flight = _LiveTapeFlight()
            _INFLIGHT[request_key] = flight
            owner = True
        else:
            owner = False

    if not owner:
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        if flight.payload is None:
            raise RuntimeError("实时行情 single-flight 未返回结果")
        return dict(flight.payload)

    try:
        payload = _build_live_tape_uncached(
            position_codes=position_codes,
            extra_codes=extra_codes,
            use_cache=use_cache,
            _cache_key=request_key,
        )
        flight.payload = payload
        return dict(payload)
    except Exception as exc:
        flight.error = exc
        raise
    finally:
        with _CACHE_LOCK:
            if _INFLIGHT.get(request_key) is flight:
                _INFLIGHT.pop(request_key, None)
        flight.done.set()


def _build_live_tape_uncached(
    *,
    position_codes: list[dict[str, Any]] | None = None,
    extra_codes: list[str] | None = None,
    use_cache: bool = True,
    _cache_key: tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    """组装顶栏/托盘用的行情快照。

    position_codes: [{"code","name","shares","cost"}, ...]
    """
    index_specs = [
        {
            "code": code,
            "label": label,
            "kind": "index",
            "instrument_type": "INDEX",
        }
        for code, label in DEFAULT_INDICES
    ]
    holdings: list[dict[str, Any]] = []
    for item in position_codes or []:
        code = str(item.get("code", "")).strip()
        normalized = _safe_normalize_live_code(code, kind="持仓")
        if normalized is None:
            continue
        holdings.append(
            {
                "code": normalized,
                "label": str(item.get("name") or code),
                "kind": "position",
                "instrument_type": "STOCK",
                "shares": int(item.get("shares") or 0),
                "cost": float(item.get("cost") or 0),
            }
        )

    extras: list[dict[str, Any]] = []
    for raw in extra_codes or []:
        code = str(raw).strip()
        normalized = _safe_normalize_live_code(code, kind="自选")
        if normalized is None:
            continue
        extras.append(
            {
                "code": normalized,
                "label": code,
                "kind": "watch",
                "instrument_type": "STOCK",
            }
        )

    specs = index_specs + holdings + extras
    cache_key = _cache_key or tuple(
        (
            str(spec.get("code") or ""),
            str(spec.get("label") or ""),
            str(spec.get("kind") or ""),
            str(spec.get("instrument_type") or ""),
            int(spec.get("shares") or 0),
            float(spec.get("cost") or 0),
        )
        for spec in specs
    )
    now = time.monotonic()
    with _CACHE_LOCK:
        if (
            use_cache
            and _CACHE["key"] == cache_key
            and _CACHE["payload"] is not None
            and now - float(_CACHE["at"]) < _CACHE_TTL
        ):
            return dict(_CACHE["payload"])

    types = {s["code"]: str(s.get("instrument_type") or "STOCK") for s in specs}
    codes = [s["code"] for s in specs]

    try:
        quotes = fetch_live_quotes(codes, instrument_types=types)
        error = ""
        source = "sina"
        if quotes:
            source = str(quotes[0].get("source") or "sina")
    except Exception as exc:  # pragma: no cover - 网络失败
        quotes = []
        error = f"{type(exc).__name__}: {exc}"
        source = ""

    quote_map = {str(q.get("code")): q for q in quotes}
    items: list[dict[str, Any]] = []
    for spec in specs:
        q = quote_map.get(spec["code"])
        if not q:
            items.append(
                {
                    **spec,
                    "price": None,
                    "pct": None,
                    "change": None,
                    "ok": False,
                }
            )
            continue
        row = {
            **spec,
            "name": q.get("name") or spec["label"],
            "price": q.get("price"),
            "pct": q.get("pct"),
            "change": q.get("change"),
            "prev_close": q.get("prev_close"),
            "trade_time": q.get("trade_time"),
            "source": q.get("source") or source,
            "ok": True,
        }
        if spec["kind"] == "position" and spec.get("shares") and q.get("price") is not None:
            row["market_value"] = round(float(q["price"]) * int(spec["shares"]), 2)
            if spec.get("cost"):
                # 相对成本浮盈；托盘/顶栏主展示仍用今日 pct，避免和涨跌色打架
                row["pnl_pct"] = round((float(q["price"]) / float(spec["cost"]) - 1) * 100, 2)
        items.append(row)

    indices = [i for i in items if i["kind"] == "index"]
    positions = [i for i in items if i["kind"] == "position"]
    title_bits: list[str] = []
    for idx in indices[:3]:
        if idx.get("ok") and idx.get("pct") is not None:
            sign = "+" if idx["pct"] >= 0 else ""
            title_bits.append(f"{idx['label']}{sign}{idx['pct']:.1f}%")
    # 仓：持仓今日涨跌（市值加权），不是相对成本浮盈
    pos_day = [p for p in positions if p.get("ok") and p.get("pct") is not None]
    if pos_day:
        total_mv = sum(float(p.get("market_value") or 0) for p in pos_day)
        if total_mv > 0:
            avg = sum(float(p["pct"]) * float(p.get("market_value") or 0) for p in pos_day) / total_mv
        else:
            avg = sum(float(p["pct"]) for p in pos_day) / len(pos_day)
        sign = "+" if avg >= 0 else ""
        title_bits.append(f"仓{sign}{avg:.1f}%")

    payload = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source or "none",
        "error": error,
        "title": " · ".join(title_bits) if title_bits else "Loci",
        "indices": indices,
        "positions": positions,
        "watches": [i for i in items if i["kind"] == "watch"],
        "items": items,
    }
    with _CACHE_LOCK:
        _CACHE["at"] = time.monotonic()
        _CACHE["key"] = cache_key
        _CACHE["payload"] = payload
    return payload


def _fmt_tray_pct(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.1f}%"


def portfolio_day_pct(positions: list[dict[str, Any]]) -> float | None:
    """持仓组合今日涨跌：按市值加权；缺市值时退回等权。"""
    weighted = 0.0
    weight = 0.0
    for p in positions:
        pct = p.get("pct")
        if pct is None:
            continue
        mv = p.get("market_value")
        if mv is None:
            price = p.get("price")
            shares = p.get("shares")
            if price is not None and shares:
                mv = float(price) * float(shares)
        if mv and float(mv) > 0:
            weighted += float(pct) * float(mv)
            weight += float(mv)
    if weight > 0:
        return weighted / weight
    pcts = [float(p["pct"]) for p in positions if p.get("pct") is not None]
    if not pcts:
        return None
    return sum(pcts) / len(pcts)


#: Windows NotifyIcon ``szTip`` 上限（含 pystray 校验）；超长会 ValueError，托盘变「暂不可用」。
TRAY_TITLE_MAX = 128


def format_tray_title(tape: dict[str, Any]) -> str:
    """托盘悬停文案：仓置顶 + 指数 + 持仓今日涨跌；总长 ≤ ``TRAY_TITLE_MAX``。

    系统气泡不支持着色；用 ▲▼ 代替涨跌色。持仓一律用今日 ``pct``，
    不用相对成本 ``pnl_pct``。不加装饰分隔线——在 128 字预算里挤不下。
    """
    indices = tape.get("indices") or []
    positions = tape.get("positions") or []
    as_of = str(tape.get("as_of") or "")
    clock = ""
    if " " in as_of:
        clock = as_of.split(" ", 1)[1][:5]

    pos_ok = [p for p in positions if p.get("ok") and p.get("pct") is not None]
    bag = portfolio_day_pct(pos_ok) if pos_ok else None

    head = f"仓 {_fmt_tray_pct(bag)}" if bag is not None else "仓 —"
    if clock:
        head = f"{head} · {clock}"
    lines = [head]

    # 指数两行两列（短标签）
    idx_cells: list[str] = []
    for item in indices[:4]:
        label = str(item.get("label") or item.get("name") or item.get("code") or "")
        if len(label) > 2:
            label = label[:2]
        idx_cells.append(f"{label} {_fmt_tray_pct(item.get('pct'))}")
    if idx_cells:
        row1 = idx_cells[0:2]
        row2 = idx_cells[2:4]
        if row1:
            lines.append("  ".join(row1))
        if row2:
            lines.append("  ".join(row2))
    else:
        lines.append("指数 暂无")

    if pos_ok:
        ranked = sorted(pos_ok, key=lambda p: float(p.get("pct") or 0))
        for p in ranked[:8]:
            name = str(p.get("name") or p.get("label") or p.get("code") or "")
            if len(name) > 4:
                name = name[:4]
            pct = float(p.get("pct") or 0)
            mark = "▲" if pct > 0 else ("▼" if pct < 0 else "·")
            candidate = "\n".join([*lines, f"{mark}{name} {_fmt_tray_pct(pct)}"])
            if len(candidate) > TRAY_TITLE_MAX:
                break
            lines.append(f"{mark}{name} {_fmt_tray_pct(pct)}")
    elif positions:
        lines.append("持仓 暂无价")
    else:
        lines.append("持仓 空仓")

    text = "\n".join(line for line in lines if line)
    return text[:TRAY_TITLE_MAX]
