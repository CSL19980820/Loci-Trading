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

from src.market.infrastructure.store import normalize_code

logger = logging.getLogger(__name__)

#: 默认指数：上证 / 深证 / 创业 / 科创
DEFAULT_INDICES: tuple[tuple[str, str], ...] = (
    ("000001", "上证"),
    ("399001", "深证"),
    ("399006", "创业"),
    ("000688", "科创"),
)

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL = 3.0


def fetch_live_quotes(
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """批量拉实时富行情（经适配器选路）。``codes`` 为 6 位代码。"""
    from src.market.infrastructure.adapters import AdapterError, fetch_live_quotes_routed

    clean = [normalize_code(c) for c in codes if str(c).strip()]
    if not clean:
        return []
    try:
        rows, _aid = fetch_live_quotes_routed(
            clean, instrument_types=instrument_types
        )
        return rows
    except AdapterError as exc:
        logger.warning("实时行情失败：%s", exc)
        return []


def build_live_tape(
    *,
    position_codes: list[dict[str, Any]] | None = None,
    extra_codes: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """组装顶栏/托盘用的行情快照。

    position_codes: [{"code","name","shares","cost"}, ...]
    """
    now = time.monotonic()
    with _CACHE_LOCK:
        if use_cache and _CACHE["payload"] is not None and now - float(_CACHE["at"]) < _CACHE_TTL:
            return dict(_CACHE["payload"])

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
        if not code:
            continue
        holdings.append(
            {
                "code": normalize_code(code),
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
        if not code:
            continue
        extras.append(
            {
                "code": normalize_code(code),
                "label": code,
                "kind": "watch",
                "instrument_type": "STOCK",
            }
        )

    specs = index_specs + holdings + extras
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
        if spec["kind"] == "position" and spec.get("shares") and spec.get("cost"):
            row["pnl_pct"] = (
                round((q["price"] / spec["cost"] - 1) * 100, 2) if spec["cost"] else None
            )
            row["market_value"] = round(q["price"] * spec["shares"], 2)
        items.append(row)

    indices = [i for i in items if i["kind"] == "index"]
    positions = [i for i in items if i["kind"] == "position"]
    title_bits: list[str] = []
    for idx in indices[:3]:
        if idx.get("ok") and idx.get("pct") is not None:
            sign = "+" if idx["pct"] >= 0 else ""
            title_bits.append(f"{idx['label']}{sign}{idx['pct']:.1f}%")
    pos_ok = [p for p in positions if p.get("ok") and p.get("pnl_pct") is not None]
    if pos_ok:
        avg = sum(float(p["pnl_pct"]) for p in pos_ok) / len(pos_ok)
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
        _CACHE["payload"] = payload
    return payload
