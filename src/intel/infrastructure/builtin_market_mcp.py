"""Loci 内置行情 MCP（进程内，不依赖 data/mcp.json）。

Skills 在 frontmatter 声明 ``mcp_servers: [loci-market]`` 即可挂载工具，
无需单独启动 HTTP MCP 进程。
"""
from __future__ import annotations

import json
from typing import Any

from src.intel.infrastructure.mcp import McpTool

BUILTIN_MCP_NAME = "loci-market"

_MAX_QUOTE_CODES = 20
_MAX_KLINE_ROWS = 60
_MAX_INSTRUMENT_ROWS = 50


def is_builtin_mcp_server(name: str) -> bool:
    return str(name).strip() == BUILTIN_MCP_NAME


def _schema(props: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def list_builtin_tools() -> list[McpTool]:
    return [
        McpTool(
            name="kline",
            description="查询 A 股日线 K 线（路由至本地适配器）。参数 code 必填，days 可选（默认 60，上限 150）。",
            input_schema=_schema(
                {
                    "code": {"type": "string", "description": "6 位证券代码，如 600519"},
                    "days": {"type": "integer", "description": "返回最近 N 根 K 线", "minimum": 1, "maximum": 150},
                },
                required=["code"],
            ),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="quote",
            description="批量实时/现价行情（富字段）。codes 为代码数组或逗号分隔字符串，最多 20 只。",
            input_schema=_schema(
                {
                    "codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "证券代码列表",
                    },
                    "code": {"type": "string", "description": "单只代码（与 codes 二选一）"},
                },
            ),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="quotes",
            description="quote 的别名：批量现价/富行情。",
            input_schema=_schema(
                {
                    "codes": {"type": "array", "items": {"type": "string"}},
                    "code": {"type": "string"},
                },
            ),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="instruments_search",
            description="搜索证券列表。优先查本地 market.db；无结果时可走远程 instruments 适配器。",
            input_schema=_schema(
                {
                    "q": {"type": "string", "description": "代码或名称关键词，可空"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "最多返回条数"},
                },
            ),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="lanes_catalog",
            description="列出已注册行情适配器及其支持的 lane（hist_daily / spot_batch 等）。",
            input_schema=_schema({}),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="capital_flow",
            description="个股主力资金流（东财）。返回近期净流入等字段摘要。",
            input_schema=_schema(
                {
                    "code": {"type": "string", "description": "证券代码，如 600519"},
                },
                required=["code"],
            ),
            server=BUILTIN_MCP_NAME,
        ),
        McpTool(
            name="minute",
            description="个股分钟 K（东财）。period: 1/5/15/30/60，默认 1。",
            input_schema=_schema(
                {
                    "code": {"type": "string", "description": "证券代码"},
                    "period": {
                        "type": "string",
                        "description": "分钟周期：1/5/15/30/60，默认 1",
                    },
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "回溯天数，默认 1",
                    },
                },
                required=["code"],
            ),
            server=BUILTIN_MCP_NAME,
        ),
    ]


def builtin_server_record() -> dict[str, Any]:
    tools = list_builtin_tools()
    return {
        "id": f"BUILTIN-{BUILTIN_MCP_NAME}",
        "name": BUILTIN_MCP_NAME,
        "url": "",
        "token": "",
        "token_last4": "",
        "has_token": False,
        "proxy_url": "",
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ],
        "tools_synced_at": "",
        "is_active": True,
        "note": "Loci 内置行情",
        "source": "builtin",
        "builtin": True,
    }


def _result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "text": text,
        "is_error": is_error,
        "raw": [{"type": "text", "text": text}],
    }


def _bare_tool_name(name: str, server: str = BUILTIN_MCP_NAME) -> str:
    prefix = f"{server}__"
    return name.split("__", 1)[1] if name.startswith(prefix) else name


def _parse_codes(args: dict[str, Any]) -> list[str]:
    raw = args.get("codes") or args.get("code")
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.replace("，", ",").replace(";", ",")
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def _tool_kline(args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("code") or "").strip()
    if not code:
        return _result("缺少参数 code", is_error=True)
    days = int(args.get("days") or _MAX_KLINE_ROWS)
    days = max(1, min(days, 150))

    try:
        from src.market import fetch_daily_routed

        frame, adapter_id = fetch_daily_routed(code)
    except Exception as exc:
        return _result(f"K 线取数失败：{type(exc).__name__}: {exc}", is_error=True)

    if frame is None or frame.empty:
        return _result(f"{code} 无日线数据", is_error=True)

    tail = frame.tail(min(days, _MAX_KLINE_ROWS))
    latest = tail.iloc[-1]
    summary = (
        f"{code} 日线 | adapter={adapter_id} | 总 {len(frame)} 根 | 展示最近 {len(tail)} 根\n"
        f"最新 {latest.get('date', '')}: "
        f"O={latest.get('open')} H={latest.get('high')} L={latest.get('low')} "
        f"C={latest.get('close')} V={latest.get('volume')}"
    )
    cols = [c for c in ("date", "open", "high", "low", "close", "volume", "amount") if c in tail.columns]
    rows: list[dict[str, Any]] = []
    for _, row in tail.iterrows():
        rows.append({col: row.get(col) for col in cols})
    payload = {"summary": summary, "adapter": adapter_id, "rows": rows}
    return _result(json.dumps(payload, ensure_ascii=False, default=str))


def _tool_quotes(args: dict[str, Any]) -> dict[str, Any]:
    codes = _parse_codes(args)
    if not codes:
        return _result("缺少 codes 或 code", is_error=True)
    codes = codes[:_MAX_QUOTE_CODES]

    try:
        from src.market import fetch_live_quotes_routed

        rows, adapter_id = fetch_live_quotes_routed(codes)
    except Exception as exc:
        return _result(f"现价取数失败：{type(exc).__name__}: {exc}", is_error=True)

    if not rows:
        return _result(f"未拿到行情：{', '.join(codes)}", is_error=True)

    compact = rows[:_MAX_QUOTE_CODES]
    text = json.dumps(
        {"adapter": adapter_id, "count": len(compact), "quotes": compact},
        ensure_ascii=False,
        default=str,
    )
    return _result(text)


def _tool_instruments_search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("q") or args.get("query") or "").strip()
    limit = max(1, min(int(args.get("limit") or 30), _MAX_INSTRUMENT_ROWS))

    try:
        from src.shared.paths import market_db
        from src.market import MarketStore

        with MarketStore(market_db()) as store:
            total, rows = store.page_instruments(q=q, limit=limit)
        if rows:
            items = [
                {"code": r.get("code"), "name": r.get("name"), "type": r.get("instrument_type")}
                for r in rows
            ]
            payload = {"source": "local", "total": total, "count": len(items), "items": items}
            return _result(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass

    try:
        from src.market import fetch_instruments_routed

        frame, adapter_id = fetch_instruments_routed()
    except Exception as exc:
        return _result(f"证券列表不可用：{type(exc).__name__}: {exc}", is_error=True)

    if frame is None or frame.empty:
        return _result("远程证券列表为空", is_error=True)

    subset = frame
    if q and "code" in frame.columns:
        needle = q.lower()
        mask = frame["code"].astype(str).str.contains(needle, case=False, na=False)
        if "name" in frame.columns:
            mask = mask | frame["name"].astype(str).str.contains(needle, case=False, na=False)
        subset = frame[mask]
    head = subset.head(limit)
    items = head.to_dict(orient="records")
    payload = {
        "source": "remote",
        "adapter": adapter_id,
        "total": int(len(subset)),
        "count": len(items),
        "items": items,
    }
    return _result(json.dumps(payload, ensure_ascii=False, default=str))


def _tool_lanes_catalog(_args: dict[str, Any]) -> dict[str, Any]:
    from src.market import ALL_LANES, enabled_adapter_ids, list_catalog

    catalog = list_catalog()
    lanes = {
        lane: enabled_adapter_ids(lane)
        for lane in ALL_LANES
    }
    payload = {"adapters": catalog, "enabled_by_lane": lanes}
    return _result(json.dumps(payload, ensure_ascii=False))


def _tool_capital_flow(args: dict[str, Any]) -> dict[str, Any]:
    from src.market import get_adapter, normalize_code

    code = normalize_code(str(args.get("code") or ""))
    if not code:
        return _result("缺少 code", is_error=True)
    try:
        adapter = get_adapter("eastmoney")
        frame = adapter.fetch_capital_flow(code)  # type: ignore[attr-defined]
    except Exception as exc:
        return _result(f"capital_flow 失败：{type(exc).__name__}: {exc}", is_error=True)
    if frame is None or getattr(frame, "empty", True):
        return _result(f"{code} 资金流为空", is_error=True)
    rows = frame.tail(20).to_dict(orient="records")
    for row in rows:
        for key, value in list(row.items()):
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            elif hasattr(value, "item"):
                try:
                    row[key] = value.item()
                except Exception:
                    row[key] = str(value)
    return _result(
        json.dumps(
            {"code": code, "source": "eastmoney", "rows": rows, "total": int(len(frame))},
            ensure_ascii=False,
            default=str,
        )
    )


def _tool_minute(args: dict[str, Any]) -> dict[str, Any]:
    from src.market import get_adapter, normalize_code

    code = normalize_code(str(args.get("code") or ""))
    if not code:
        return _result("缺少 code", is_error=True)
    period = str(args.get("period") or "1").strip() or "1"
    days = int(args.get("days") or 1)
    days = max(1, min(days, 5))
    try:
        adapter = get_adapter("eastmoney")
        frame = adapter.fetch_minute(code, period=period, days=days)  # type: ignore[attr-defined]
    except Exception as exc:
        return _result(f"minute 失败：{type(exc).__name__}: {exc}", is_error=True)
    if frame is None or getattr(frame, "empty", True):
        return _result(f"{code} 分钟线为空", is_error=True)
    rows = frame.tail(60).to_dict(orient="records")
    for row in rows:
        for key, value in list(row.items()):
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            elif hasattr(value, "item"):
                try:
                    row[key] = value.item()
                except Exception:
                    row[key] = str(value)
    return _result(
        json.dumps(
            {
                "code": code,
                "period": period,
                "source": "eastmoney",
                "rows": rows,
                "total": int(len(frame)),
            },
            ensure_ascii=False,
            default=str,
        )
    )


_HANDLERS: dict[str, Any] = {
    "kline": _tool_kline,
    "quote": _tool_quotes,
    "quotes": _tool_quotes,
    "instruments_search": _tool_instruments_search,
    "lanes_catalog": _tool_lanes_catalog,
    "capital_flow": _tool_capital_flow,
    "minute": _tool_minute,
}


def call_builtin_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    server: str = BUILTIN_MCP_NAME,
) -> dict[str, Any]:
    """与 McpClient.call_tool 相同返回形状。"""
    bare = _bare_tool_name(name, server)
    handler = _HANDLERS.get(bare)
    if handler is None:
        available = ", ".join(sorted(_HANDLERS))
        return _result(f"未知工具 {bare}。可用：{available}", is_error=True)
    try:
        return handler(arguments or {})
    except Exception as exc:
        return _result(f"工具失败：{type(exc).__name__}: {exc}", is_error=True)


class InProcessMcpClient:
    """duck-type 兼容 McpClient：list_tools / call_tool / ping。"""

    def __init__(self, name: str = BUILTIN_MCP_NAME) -> None:
        self.name = name
        self.url = ""

    def list_tools(self) -> list[McpTool]:
        return list_builtin_tools()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return call_builtin_tool(name, arguments, server=self.name)

    def ping(self) -> dict[str, Any]:
        tools = self.list_tools()
        return {
            "ok": True,
            "server_name": BUILTIN_MCP_NAME,
            "server_version": "builtin",
            "protocol_version": "in-process",
            "tool_count": len(tools),
            "sample_tools": [tool.name for tool in tools[:12]],
        }
