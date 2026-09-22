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


_PRIMARY_QUOTE_SECONDS = 4.0
_DIRECT_QUOTE_SECONDS = 5.0
_SNAPSHOT_SECONDS = 20.0


def snapshot(codes: list[str], *, include_minute: bool = False, force_refresh: bool = True,
             now: datetime | None = None, check_cancelled: Callable[[], None] | None = None,
             deadline: float | None = None, require_order_book: bool = False) -> Any:
    """逐股保留结果；主源限时，给独立直连和系统备用源留出预算。"""
    from src.ai.application.agent_execution import reraise_stop
    from src.intel import call_mcp_tool
    from src.market.application.live_cache import build_monitor_snapshot
    from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter

    def checkpoint() -> None:
        if check_cancelled:
            check_cancelled()

    def current_time() -> datetime:
        return now or datetime.now(ZoneInfo("Asia/Shanghai"))

    def failure(exc: Exception) -> str:
        # 请求超时只淘汰该来源；任务取消/JobTimedOut 和其包装原因仍向上传播。
        try:
            reraise_stop(exc)
        except TimeoutError as timeout:
            return f"{type(timeout).__name__}: {str(timeout).strip() or '上游请求超时'}"
        return f"{type(exc).__name__}: {str(exc).strip() or '上游请求失败'}"

    checkpoint()
    started = time.monotonic()
    if deadline is not None and started >= deadline:
        raise TimeoutError("实时取价超过本轮剩余预算")
    unique = list(dict.fromkeys(codes))
    if not unique:
        return SimpleNamespace(quotes={})
    # 在调用方硬截止前留出返回余量，不能因一股超时丢掉其他股票的成功报价。
    end = min(started + _SNAPSHOT_SECONDS, deadline - 0.05 if deadline is not None else float('inf'))
    primary_end = min(started + _PRIMARY_QUOTE_SECONDS, started + max(0.0, end - started) / 3)
    quotes: dict[str, dict[str, Any]] = {}
    attempts: dict[str, list[dict[str, Any]]] = {code: [] for code in unique}
    # 独立线程池保证挂起的四个主源请求不能占住备用源的执行名额。
    primary_pool = ThreadPoolExecutor(max_workers=min(4, len(unique)), thread_name_prefix="guardian-primary")
    backup_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="guardian-backup")

    def collect(futures: dict, until: float, accept: Callable) -> None:
        def completed(future) -> None:
            try:
                value, error = future.result(), None
            except Exception as exc:
                value, error = None, failure(exc)
            accept(futures[future], value, error)

        pending = set(futures)
        while pending:
            checkpoint()
            remaining = until - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=min(0.05, remaining), return_when=FIRST_COMPLETED)
            for future in done:
                completed(future)
        for future in pending:
            if future.done():
                completed(future)
            else:
                future.cancel()
                accept(futures[future], None, "TimeoutError: 来源未在分配预算内返回")

    def record(code: str, quote: Any, error: str | None, stage: str) -> None:
        error = error or quote_error(code, quote, current_time())
        attempts[code].append({"stage": stage, "error": error or "", "checked_at": current_time().isoformat()})
        if error:
            previous = quotes.get(code, {})
            if quote_error(code, previous, current_time()) is not None:
                quotes[code] = {**previous, "code": code, "error": previous.get("error") or error,
                                **({"fallback_error": error} if stage != "primary" else {})}
        else:
            previous_error = quotes.get(code, {}).get("error")
            quotes[code] = {**quote, **({"primary_error": previous_error} if previous_error else {})}

    def missing() -> list[str]:
        return [code for code in unique if quote_error(code, quotes.get(code, {}), current_time())]

    def fetch(code: str, server: str) -> dict:
        payload = call_mcp_tool("minute_data", {"code": code, "format": "json", "detailLevel": "standard"},
                                server=server, pool="skill", cache=False, deadline=primary_end)
        return minute_quote(payload, code)

    try:
        discovery: dict[str, Any] = {}
        def accept_source(_key, value, error):
            discovery.update(source=value if isinstance(value, dict) else {}, error=error)
        task = primary_pool.submit(copy_context().run, data_source)
        collect({task: "source"}, primary_end, accept_source)
        source = discovery.get("source", {})
        if source.get("wudao") and time.monotonic() < primary_end:
            tasks = {primary_pool.submit(copy_context().run, fetch, code, source["server"]): code for code in unique}
            collect(tasks, primary_end, lambda code, q, error: record(code, q, error, "primary"))
        else:
            for code in unique:
                record(code, {}, discovery.get("error") or "主源未启用或发现超时", "primary")

        failed = missing()
        direct_codes = unique if require_order_book else failed
        books: dict[str, dict] = {}
        book_errors: dict[str, str] = {}
        if direct_codes and time.monotonic() < end:
            checkpoint()
            direct_end = min(time.monotonic() + _DIRECT_QUOTE_SECONDS,
                             time.monotonic() + max(0.0, end - time.monotonic()) / 2)
            def accept_direct(_key, rows, error):
                if not isinstance(rows, (list, tuple)):
                    error = error or "直连源返回格式无效"
                    rows = []
                by_code = {q.get("code"): q for q in rows or [] if isinstance(q, dict)}
                for code in direct_codes:
                    q = by_code.get(code)
                    problem = error or ("直连源未返回该股票" if q is None else quote_error(code, q, current_time()))
                    if not problem and not q.get("source"):
                        problem = "直连报价缺少来源"
                    if require_order_book:
                        if problem:
                            book_errors[code] = problem
                        else:
                            books[code] = dict(q)
                    if code in failed:
                        record(code, q, problem, "direct")
            task = backup_pool.submit(copy_context().run, TencentAdapter().fetch_live_quotes, direct_codes)
            collect({task: "direct"}, direct_end, accept_direct)

        failed = missing()
        if failed and time.monotonic() < end:
            checkpoint()
            def accept_backup(_key, result, error):
                rows = getattr(result, "quotes", {})
                for code in failed:
                    q = rows.get(code, {}) if isinstance(rows, dict) else {}
                    record(code, q, error, "system")
            task = backup_pool.submit(copy_context().run, build_monitor_snapshot, failed,
                                      include_minute=include_minute, force_refresh=force_refresh)
            collect({task: "system"}, end, accept_backup)
        checkpoint()
        for code in unique:
            row = quotes.setdefault(code, {"code": code, "error": "实时取价预算耗尽"})
            # 慢源等待期间，之前成功的报价也可能过期，返回前再次校验。
            problem = quote_error(code, row, current_time())
            if problem:
                row["error"] = problem
            row["quote_attempts"] = attempts[code]
            if require_order_book:
                if code in books:
                    row["order_book"] = books[code]
                else:
                    row["order_book_error"] = book_errors.get(code, "盘口取价预算耗尽")
        return SimpleNamespace(quotes=quotes)
    finally:
        primary_pool.shutdown(wait=False, cancel_futures=True)
        backup_pool.shutdown(wait=False, cancel_futures=True)


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
