"""悟道优先的守护工具与行情；无可用悟道时使用系统行情工具。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import wait, FIRST_COMPLETED
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime
from types import SimpleNamespace
from threading import local
from typing import Any
from src.ops.application.guardian_quotes import quote_error
from src.shared.tenancy import current_tenant


def data_source() -> dict[str, Any]:
    from src.intel import BUILTIN_MCP_NAME, BUILTIN_WUDAO_NAME, collect_tools, wudao_availability
    status = wudao_availability()
    server = BUILTIN_WUDAO_NAME if status.get("available") else BUILTIN_MCP_NAME
    tools, _ = collect_tools([server])
    return {"server": server, "wudao": bool(status.get("available")),
            "label": "悟道优先" if status.get("available") else "系统行情",
            "reason": status.get("reason", ""), "tool_count": len(tools)}


def structured_result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("is_error") or payload.get("unavailable"):
        raise ValueError(str(payload.get("text") or "工具调用失败"))
    result = payload.get("structured")
    if not isinstance(result, dict):
        if payload.get("truncated"):
            raise ValueError("工具正文被截断且无完整结构化数据")
        result = json.loads(payload.get("text") or "{}")
    if not isinstance(result, dict) or result.get("success") is False:
        raise ValueError("工具未返回有效结果")
    return result


def minute_quote(payload: dict[str, Any], code: str) -> dict[str, Any]:
    root = structured_result(payload)
    data = root.get("data") or root
    if not isinstance(data, dict):
        raise ValueError("悟道分时数据格式无效")
    stock = data.get("stock") or {}
    if not isinstance(stock, dict):
        raise ValueError("悟道分时股票信息格式无效")
    if str(stock.get("code") or code) != code:
        raise ValueError("悟道返回了其他股票的分时")
    points = data.get("points") or []
    if not points:
        raise ValueError(f"悟道未返回 {code} 的实时分时")
    if not isinstance(points, list) or any(not isinstance(row, dict) for row in points):
        raise ValueError("悟道分时点格式无效")
    last = max(points, key=lambda row: str(row.get("time") or ""))
    stamp = datetime.fromisoformat(str(last.get("time") or ""))
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(ZoneInfo("Asia/Shanghai"))
    if isinstance(last.get("price"), bool):
        raise ValueError("行情价格不能是布尔值")
    return {"code": code, "name": stock.get("name", code), "price": float(last["price"]),
            "trade_date": stamp.date().isoformat(), "trade_time": stamp.strftime("%H:%M:%S"),
            "source": "wudao", "high": last.get("high"), "low": last.get("low")}


def snapshot(codes: list[str], *, include_minute: bool = False, force_refresh: bool = True,
             now: datetime | None = None, check_cancelled: Callable[[], None] | None = None,
             deadline: float | None = None) -> Any:
    from src.ai.application.agent_execution import reraise_stop
    from src.market.application.live_cache import build_monitor_snapshot

    def checkpoint() -> None:
        if check_cancelled:
            check_cancelled()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("实时取价超过本轮剩余预算")

    def current_time() -> datetime:
        return now or datetime.now(ZoneInfo("Asia/Shanghai"))

    checkpoint()
    source = data_source()
    from src.intel import call_mcp_tool
    quotes = {}
    # minute_data 的实际 schema 只接受单票。这里不伪造批量参数。
    def fetch(code):
        try:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("实时取价超过本轮剩余预算")
            payload = call_mcp_tool("minute_data", {"code": code, "format": "json", "detailLevel": "standard"},
                                    server=source["server"], pool="skill", cache=False,
                                    **({"deadline": deadline} if deadline is not None else {}))
            quote = minute_quote(payload, code)
            error = quote_error(code, quote, current_time())
            return code, {**quote, **({"error": error} if error else {})}
        except (ValueError, RuntimeError, KeyError, TypeError, OSError) as exc:
            reraise_stop(exc)
            return code, {"code": code, "error": f"实时取价失败：{exc}"}
    unique = list(dict.fromkeys(codes))
    if not unique:
        return SimpleNamespace(quotes={})
    pool = ThreadPoolExecutor(max_workers=min(4, len(unique)))

    def collect(futures: list) -> list:
        pending = set(futures)
        while pending:
            checkpoint()
            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
        checkpoint()
        return [future.result() for future in futures]

    try:
        if source["wudao"]:
            quotes = dict(collect([pool.submit(copy_context().run, fetch, code) for code in unique]))
        failed = [code for code in unique if quote_error(code, quotes.get(code, {}), current_time())]
        if failed:
            checkpoint()
            try:
                task = pool.submit(copy_context().run, build_monitor_snapshot, failed,
                                   include_minute=include_minute, force_refresh=force_refresh)
                fallback = collect([task])[0].quotes
                for code in failed:
                    quote = fallback.get(code, {})
                    error = quote_error(code, quote, current_time())
                    primary = quotes.get(code, {}).get("error")
                    if error is None:
                        quotes[code] = {**quote, **({"primary_error": primary} if primary else {})}
                    else:
                        quotes[code] = {**quotes.get(code, {}), "code": code, "error": primary or error, "fallback_error": error}
            except (ValueError, RuntimeError, OSError) as exc:
                reraise_stop(exc)
                for code in failed:
                    quotes[code] = {**quotes.get(code, {}), "code": code, "error": quotes.get(code, {}).get("error") or str(exc), "fallback_error": str(exc)}
        checkpoint()
        return SimpleNamespace(quotes=quotes)
    finally:
        # External reads finish under their transport timeout; cancelled results never reach settlement.
        pool.shutdown(wait=False, cancel_futures=True)


def agent_tools(protocol: str, *, read_only: bool = False,
                deadline: float | None = None) -> tuple[list[dict], Any, dict]:
    from src.ai.application.agent import make_mcp_executor
    from src.ai.application.agent_execution import reraise_stop
    from src.intel import McpClient, build_client, collect_tools, guarded_client_call

    def checkpoint() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("MCP工具超过本轮截止时间")

    checkpoint()
    source = data_source()
    if read_only and not source.get('wudao'):
        from src.ai.application.system_toolbus import SystemToolBus
        bus = SystemToolBus(palace_db=None, market_db=None, ops_db=None, protocol=protocol, read_only=True, attach_mcp=False)
        return bus.schemas, bus.executor, source
    tools, routing = collect_tools([source["server"]])
    # 咨询只读；自动交易员仍可管理外部自选，成交始终由本地账本提交。
    mutation_names = {'watchlist_group_create','watchlist_group_rename','watchlist_group_delete','watchlist_add','watchlist_remove','watchlist_update_stock','watchlist_update'}
    if read_only:
        tools = [t for t in tools if t.name.split('__')[-1] not in mutation_names]
    if not tools:
        raise ValueError("当前没有可用的行情工具")
    sessions = local()

    def bind_session() -> None:
        sessions.client = build_client(source["server"])
        sessions.execute = make_mcp_executor({source["server"]: sessions.client}, routing)
        sessions.tenant = current_tenant()

    bind_session()
    allowed = {t.name for t in tools} | set(routing)
    def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        checkpoint()
        if (read_only and name.split('__')[-1] in mutation_names) or name not in allowed:
            return {'is_error': True, 'text': '交易研究仅允许查询工具；观察与成交由本地账本统一提交。'}
        if getattr(sessions, "tenant", None) != current_tenant():
            bind_session()
        try:
            if deadline is not None and isinstance(sessions.client, McpClient):
                result = guarded_client_call(sessions.client, name, arguments, pool="skill", deadline=deadline)
            else:
                result = sessions.execute(name, arguments)
        except BaseException as exc:
            reraise_stop(exc)
            raise
        checkpoint()
        if isinstance(result.get("structured"), dict):
            # MCP transport 的 text 有 12K 展示截断，但 structuredContent 保留完整原始数据。
            result = {**result, "text": json.dumps(result["structured"], ensure_ascii=False, default=str)}
        elif result.get("truncated"):
            result = {**result, "is_error": True, "text": "工具结果被截断且无结构化正文，请缩小查询范围重新获取。"}
        return result
    schemas = [t.to_anthropic_schema() if protocol == "anthropic" else t.to_openai_schema() for t in tools]
    return schemas, executor, source
