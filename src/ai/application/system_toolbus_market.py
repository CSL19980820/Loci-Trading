"""全局助手的只读行情工具。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4


def _json_value(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def market_kline(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.market import MarketStore

    code = str(args["code"])
    artifact_id = f"kline-{uuid4().hex}"
    title = f"{code} 日 K"
    payload: dict[str, Any] = {
        "code": code, "name": "", "period": "day", "adjust": "qfq",
        "price_unit": "元", "bars": [],
    }
    owner._artifact("qianlong_kline", title, {**payload}, status="loading", artifact_id=artifact_id)
    try:
        with MarketStore(owner.market_db) as store:
            payload["name"] = store.instruments_meta([code]).get(code, {}).get("name", "")
            frame = store.history(code, start=args.get("start"), end=args.get("end"), adjust="qfq")
        fields = ["trade_date", "open", "high", "low", "close", "volume", "amount", "turnover"]
        rows = [
            {key: _json_value(row.get(key)) for key in fields if key in row}
            for row in frame.tail(int(args.get("limit", 120))).to_dict("records")
        ]
    except Exception:
        owner._artifact("qianlong_kline", title, {**payload, "error": "K线数据读取失败"}, status="error", artifact_id=artifact_id)
        raise
    title = f"{payload['name']} {code} · 日 K".strip()
    owner._artifact("qianlong_kline", title, {**payload, "bars": rows}, status="ready", artifact_id=artifact_id)
    return _ok(rows)


def market_search(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.market import MarketStore

    needle = str(args["query"]).strip().lower()
    limit = int(args.get("limit", 30))
    with MarketStore(owner.market_db) as store:
        rows = store.list_instruments()
    selected = [
        {key: row.get(key, "") for key in ("code", "name", "market", "board", "industry", "status")}
        for row in rows
        if needle in str(row.get("code", "")).lower()
        or needle in str(row.get("name", "")).lower()
    ]
    return _ok(selected[:limit])


def build_market_tool_specs(owner: Any) -> dict[str, Any]:
    """延迟导入，避免与 SystemToolBus 的 ToolSpec 形成循环。"""
    from src.ai.application.system_toolbus import ToolSpec, _object

    read = False
    return {
        "market_kline": ToolSpec(
            "market_kline",
            "读取单票日 K。",
            _object(
                {
                    "code": {"type": "string", "pattern": "^\\d{6}$"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 240},
                },
                ["code"],
            ),
            read,
            lambda args: market_kline(owner, args),
        ),
        "market_search": ToolSpec(
            "market_search",
            "按代码或名称搜索标的。",
            _object(
                {
                    "query": {"type": "string", "minLength": 1, "maxLength": 32},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                ["query"],
            ),
            read,
            lambda args: market_search(owner, args),
        ),
    }
