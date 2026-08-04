"""全局助手的静态工具面。

这里刻意不复用 Skill ToolBus：没有 CLI、动态 MCP、shell、文件、URL 或 SQL。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from threading import Thread
from time import monotonic
from typing import Any, Callable

from src.ai.domain.assistant import AssistantError, validate_qianlong_decisions


ToolResult = dict[str, Any]
GrantIssuer = Callable[[str, str, dict[str, Any]], dict[str, Any] | None]
GrantConsumer = Callable[[str, str, str, dict[str, Any]], str]
GrantCompleter = Callable[[str, dict[str, Any], str], None]
EventCallback = Callable[[dict[str, Any]], None]

_FORBIDDEN = re.compile(
    r"(sql|shell|command|file|path|url|endpoint|proxy|api.?key|secret|password|credential|authorization|(?:^|[_-])(?:access|refresh|bearer)?[_-]?token(?:$|[_-])|broker[ _-]?order|order)",
    re.I,
)
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    write: bool
    handler: Callable[[dict[str, Any]], ToolResult]


def _schema(name: str, description: str, parameters: dict[str, Any], protocol: str) -> dict[str, Any]:
    if protocol == "anthropic":
        return {"name": name, "description": description, "input_schema": parameters}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        result["required"] = required
    return result


def _safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _FORBIDDEN.search(str(key)):
                raise AssistantError("工具参数不得包含凭据、URL、文件、命令或 SQL")
            _safe(item)
    elif isinstance(value, list):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and ("http://" in value.lower() or "https://" in value.lower()):
        raise AssistantError("工具参数不得包含 URL")


class SystemToolBus:
    """固定注册的业务工具；所有写入在 handler 前消费运行绑定的 ExecutionGrant。"""

    def __init__(
        self, *, palace_db: str | None, market_db: str | None, ops_db: str | None,
        protocol: str = "openai_compatible", grant_issuer: GrantIssuer | None = None,
        grant_consumer: GrantConsumer | None = None, grant_completer: GrantCompleter | None = None,
        on_event: EventCallback | None = None, scheduler_reloader: Callable[[], None] | None = None,
        read_only: bool = False,
    ) -> None:
        self.palace_db, self.market_db, self.ops_db = palace_db, market_db, ops_db
        self.protocol = protocol
        self.grant_issuer, self.grant_consumer = grant_issuer, grant_consumer
        self.grant_completer, self.on_event, self._last_grant_id = grant_completer, on_event, ""
        self._scheduler_reloader = scheduler_reloader
        self._background_threads: list[Thread] = []
        self._candidate_pool_snapshots: dict[tuple[str, str], frozenset[str]] = {}
        self._candidate_pool_evidence: dict[tuple[str, str], frozenset[str]] = {}
        self._read_only = read_only
        specs = self._register()
        self._specs = {name: spec for name, spec in specs.items() if not read_only or not spec.write}

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [_schema(spec.name, spec.description, spec.parameters, self.protocol) for spec in self._specs.values()]

    def catalog(self) -> list[dict[str, Any]]:
        return [{"name": item.name, "description": item.description, "risk": "write" if item.write else "read"} for item in self._specs.values()]

    def executor(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return {"text": "未注册的系统工具", "is_error": True}
        if not isinstance(arguments, dict):
            return {"text": "工具参数必须是对象", "is_error": True}
        try:
            self._last_grant_id = ""
            _safe(arguments)
            if self.on_event:
                self.on_event({"type": "tool_start", "name": name, "arguments": arguments})
            result = spec.handler(arguments)
            deferred = bool(result.pop("_grant_deferred", False))
            if spec.write and self._last_grant_id and not deferred:
                self._finalize_grant(self._last_grant_id, result.get("structured", {}))
        except AssistantError as exc:
            if spec.write and self._last_grant_id:
                self._finalize_grant(self._last_grant_id, {"error": str(exc)}, status="failed")
            result = {"text": str(exc), "is_error": True}
        except Exception as exc:
            if spec.write and self._last_grant_id:
                self._finalize_grant(
                    self._last_grant_id,
                    {"error": f"{type(exc).__name__}: {exc}"},
                    status="failed",
                )
            result = {"text": f"系统工具失败：{type(exc).__name__}: {exc}", "is_error": True}
        if self.on_event:
            self.on_event({"type": "tool_end", "name": name, "ok": not result.get("is_error"), "preview": str(result.get("text", ""))[:400]})
        return result

    def _grant(self, action: str, target: str, parameters: dict[str, Any]) -> str:
        if self.grant_issuer is None or self.grant_consumer is None:
            raise AssistantError("写操作需要服务端 ExecutionGrant")
        grant = self.grant_issuer(action, target, parameters)
        if grant is None:
            raise AssistantError("AI 运行已取消或执行凭据不可用")
        self._last_grant_id = str(grant["id"])
        return self.grant_consumer(self._last_grant_id, action, target, parameters)

    def _finalize_grant(
        self, grant_id: str, result: dict[str, Any], *, status: str = "completed",
    ) -> None:
        if self.grant_completer is not None:
            self.grant_completer(grant_id, result, status)

    def _artifact(self, kind: str, title: str, data: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event({"type": "artifact", "kind": kind, "title": title, "data": data})

    def wait_for_background_tasks(
        self,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        timeout: float = 30.0,
    ) -> bool:
        """有限等待助手发起的后台任务，取消或超时后交由任务历史继续观测。"""
        deadline = monotonic() + max(0.0, timeout)
        while self._background_threads:
            self._background_threads = [thread for thread in self._background_threads if thread.is_alive()]
            if not self._background_threads:
                return True
            if is_cancelled is not None and is_cancelled():
                if self.on_event:
                    self.on_event({"type": "warning", "message": "AI 运行已取消；后台任务仍在执行，可在任务历史查看。"})
                return False
            remaining = deadline - monotonic()
            if remaining <= 0:
                if self.on_event:
                    self.on_event({"type": "warning", "message": "后台任务仍在执行；助手已停止等待，可在任务历史查看。"})
                return False
            self._background_threads[0].join(timeout=min(0.25, remaining))
        return True

    def _reload_scheduler(self) -> None:
        if self._scheduler_reloader is None:
            return
        try:
            self._scheduler_reloader()
        except Exception as exc:  # 任务已写入，重载失败只作为可见告警。
            if self.on_event:
                self.on_event({"type": "warning", "message": f"任务已保存，但调度器重载失败：{exc}"})

    def _register(self) -> dict[str, ToolSpec]:
        read = False
        write = True
        specs = {
            "ledger_dashboard": ToolSpec("ledger_dashboard", "读取账本仪表盘。", _object({}), read, self._ledger_dashboard),
            "ledger_positions": ToolSpec("ledger_positions", "读取当前持仓。", _object({}), read, self._ledger_positions),
            "ledger_trades": ToolSpec("ledger_trades", "查询成交记录。", _object({"code": {"type": "string", "pattern": "^\\d{6}$"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}), read, self._ledger_trades),
            "ledger_record_trade": ToolSpec("ledger_record_trade", "记录成交；不执行券商下单。", _object({"action": {"type": "string", "enum": ["BUY", "SELL"]}, "code": {"type": "string", "pattern": "^\\d{6}$"}, "shares": {"type": "integer", "minimum": 1}, "price": {"type": "number", "minimum": 0}, "occurred_on": {"type": "string"}, "name": {"type": "string"}, "reason": {"type": "string"}}, ["action", "code", "shares", "price"]), write, self._ledger_record_trade),
            "ledger_adjust_positions": ToolSpec(
                "ledger_adjust_positions", "一次记录用户口述的多笔买卖，并自动调整持仓、交割与余票成本。",
                _object({"trades": {"type": "array", "minItems": 1, "maxItems": 40, "items": _object({"action": {"type": "string", "enum": ["BUY", "SELL"]}, "code": {"type": "string", "pattern": "^\\d{6}$"}, "shares": {"type": "integer", "minimum": 1}, "price": {"type": "number", "minimum": 0}, "occurred_on": {"type": "string"}, "name": {"type": "string"}, "reason": {"type": "string"}}, ["action", "code", "shares", "price"])}}, ["trades"]),
                write, self._ledger_adjust_positions,
            ),
            "ledger_record_cashflow": ToolSpec("ledger_record_cashflow", "记录账户出入金，不计入交易盈亏。", _object({"amount": {"type": "number"}, "occurred_on": {"type": "string"}, "note": {"type": "string"}}, ["amount"]), write, self._ledger_record_cashflow),
            "ledger_record_daily_pnl": ToolSpec("ledger_record_daily_pnl", "写入或修正券商口径当日盈亏。", _object({"broker_pnl": {"type": "number"}, "market_pnl": {"type": "number"}, "occurred_on": {"type": "string"}, "note": {"type": "string"}}, ["broker_pnl"]), write, self._ledger_record_daily_pnl),
            "ledger_record_snapshot": ToolSpec("ledger_record_snapshot", "记录账户总资产和可选现金快照。", _object({"total_assets": {"type": "number", "minimum": 0}, "cash": {"type": "number", "minimum": 0}, "occurred_on": {"type": "string"}, "note": {"type": "string"}}, ["total_assets"]), write, self._ledger_record_snapshot),
            "ledger_upsert_candidate": ToolSpec("ledger_upsert_candidate", "新增或更新一条候选裁决。", _object({"code": {"type": "string", "pattern": "^\\d{6}$"}, "name": {"type": "string"}, "decision": {"type": "string", "enum": ["精选", "观察", "落选"]}, "reason": {"type": "string", "minLength": 1}, "occurred_on": {"type": "string"}, "pool_id": {"type": "string"}, "score": {"type": "number"}, "timing": {"type": "string"}, "invalidation": {"type": "string"}}, ["code", "decision", "reason"]), write, self._ledger_upsert_candidate),
            "ledger_delete_candidate": ToolSpec("ledger_delete_candidate", "删除一条候选裁决。", _object({"candidate_id": {"type": "string", "minLength": 1}}, ["candidate_id"]), write, self._ledger_delete_candidate),
            "ledger_delete_candidate_pool": ToolSpec("ledger_delete_candidate_pool", "删除指定日期和候选池的全部候选。", _object({"occurred_on": {"type": "string"}, "pool_id": {"type": "string", "minLength": 1}}, ["occurred_on", "pool_id"]), write, self._ledger_delete_candidate_pool),
            "ledger_record_plan": ToolSpec("ledger_record_plan", "新增一条交易预案。", _object({"code": {"type": "string", "pattern": "^\\d{6}$"}, "title": {"type": "string", "minLength": 1}, "scenario": {"type": "string", "minLength": 1}, "occurred_on": {"type": "string"}, "entry_zone": {"type": "string"}, "stop_price": {"type": "number"}, "target_price": {"type": "number"}, "layers": {"type": "number", "exclusiveMinimum": 0}, "invalidation": {"type": "string"}, "note": {"type": "string"}}, ["code", "title", "scenario"]), write, self._ledger_record_plan),
            "ledger_record_review": ToolSpec("ledger_record_review", "新增一条候选、预案或成交复盘。", _object({"entity_type": {"type": "string", "enum": ["candidate", "plan", "trade"]}, "entity_id": {"type": "string", "minLength": 1}, "outcome": {"type": "string", "minLength": 1}, "reviewed_on": {"type": "string"}, "strategy_tag": {"type": "string"}, "return_pct": {"type": "number"}, "max_favorable_pct": {"type": "number"}, "max_adverse_pct": {"type": "number"}, "lesson": {"type": "string"}, "next_rule": {"type": "string"}}, ["entity_type", "entity_id", "outcome"]), write, self._ledger_record_review),
            "qianlong_candidate_pool": ToolSpec("qianlong_candidate_pool", "读取潜龙候选池。", _object({"occurred_on": {"type": "string"}, "pool_id": {"type": "string"}}), read, self._qianlong_pool),
            "qianlong_pool_evidence": ToolSpec("qianlong_pool_evidence", "读取潜龙整池的本机日 K 摘要，供从 6-10 只中精选 0-2 只。", _object({"occurred_on": {"type": "string"}, "pool_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["occurred_on"]), read, self._qianlong_pool_evidence),
            "qianlong_commit": ToolSpec("qianlong_commit", "整池提交潜龙 6-10 只、0-2 精选及三档裁决。", _object({"occurred_on": {"type": "string"}, "pool_id": {"type": "string"}, "decisions": {"type": "array", "minItems": 6, "maxItems": 10, "items": {"type": "object"}}}, ["occurred_on", "decisions"]), write, self._qianlong_commit),
            "market_kline": ToolSpec("market_kline", "读取单票日 K。", _object({"code": {"type": "string", "pattern": "^\\d{6}$"}, "start": {"type": "string"}, "end": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 240}}, ["code"]), read, self._market_kline),
            "market_search": ToolSpec("market_search", "按代码或名称搜索标的。", _object({"query": {"type": "string", "minLength": 1, "maxLength": 32}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["query"]), read, self._market_search),
            "strategy_catalog": ToolSpec("strategy_catalog", "读取内置策略目录。", _object({}), read, self._strategy_catalog),
            "strategy_screen": ToolSpec(
                "strategy_screen",
                "运行已注册战法并回传本机行情证据和候选结果。",
                _object(
                    {
                        "strategy": {"type": "string", "minLength": 1, "maxLength": 120},
                        "trade_date": {"type": "string"},
                        "params": {"type": "object"},
                        "codes": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 300,
                            "items": {"type": "string", "pattern": "^\\d{6}$"},
                        },
                    },
                    ["strategy"],
                ),
                read,
                self._strategy_screen,
            ),
            "system_tool_catalog": ToolSpec("system_tool_catalog", "读取静态系统工具目录；动态 MCP 已禁用。", _object({}), read, self._tool_catalog),
        }
        specs.update(_ops_specs(self))
        return specs

    def _ledger_dashboard(self, _: dict[str, Any]) -> ToolResult:
        from src.ledger import PalaceStore
        with PalaceStore(self.palace_db) as store:
            data = store.dashboard_payload()
        return _ok(data)

    def _ledger_positions(self, _: dict[str, Any]) -> ToolResult:
        from src.ledger import PalaceStore
        with PalaceStore(self.palace_db) as store:
            return _ok(store.positions_payload())

    def _ledger_trades(self, args: dict[str, Any]) -> ToolResult:
        from src.ledger import PalaceStore
        with PalaceStore(self.palace_db) as store:
            return _ok(store.trades_payload(code=args.get("code"), limit=int(args.get("limit", 100))))

    def _ledger_record_trade(self, args: dict[str, Any]) -> ToolResult:
        values = {key: args[key] for key in ("action", "code", "shares", "price")}
        values.update(
            {
                key: args[key]
                for key in ("occurred_on", "name", "reason")
                if key in args and str(args[key]).strip()
            }
        )
        values["action"] = str(values["action"]).upper()
        values["code"] = str(values["code"])
        values["shares"] = int(values["shares"])
        values["price"] = float(values["price"])
        key = self._grant("ledger.record_trade", str(values.get("name") or values["code"]), values)
        from src.ledger import PalaceStore
        with PalaceStore(self.palace_db) as store:
            result = store.record_trades(
                [{**values, "source": "ai_assistant", "correlation_id": key, "metadata": {"source": "ai_assistant", "idempotency_key": key}}],
                idempotency_key=key,
            )[0]
        return _ok(result)

    def _ledger_adjust_positions(self, args: dict[str, Any]) -> ToolResult:
        raw_trades = args.get("trades")
        if not isinstance(raw_trades, list) or not raw_trades:
            raise AssistantError("持仓调整至少需要一笔成交")
        trades: list[dict[str, Any]] = []
        for item in raw_trades:
            if not isinstance(item, dict):
                raise AssistantError("每笔成交必须是对象")
            action = str(item.get("action") or "").upper()
            code = str(item.get("code") or "").strip()
            shares = int(item.get("shares") or 0)
            price = float(item.get("price") or 0)
            if action not in {"BUY", "SELL"} or not re.fullmatch(r"\d{6}", code):
                raise AssistantError("成交必须包含 BUY/SELL 和 6 位代码")
            if shares <= 0 or price < 0:
                raise AssistantError("成交股数必须大于 0，价格不能为负数")
            trade = {"action": action, "code": code, "shares": shares, "price": price}
            for key in ("occurred_on", "name", "reason"):
                if item.get(key) is not None and str(item[key]).strip():
                    trade[key] = str(item[key]).strip()
            trades.append(trade)
        grant = self._grant("ledger.adjust_positions", "持仓调整", {"trades": trades})
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            positions = {
                str(row["code"]): int(row["shares"])
                for row in store.positions_payload()
            }
            cash = store.broker_cash()
            for trade in trades:
                code, shares = str(trade["code"]), int(trade["shares"])
                notional = shares * float(trade["price"])
                if trade["action"] == "SELL":
                    if shares > positions.get(code, 0):
                        raise AssistantError(f"{code} 卖出 {shares} 股超过当前持仓")
                    positions[code] = positions.get(code, 0) - shares
                    if cash is not None:
                        cash += notional
                else:
                    if cash is not None and cash + 1e-9 < notional:
                        raise AssistantError(f"买入 {code} 所需资金超过当前可用现金")
                    positions[code] = positions.get(code, 0) + shares
                    if cash is not None:
                        cash -= notional
            records = store.record_trades(
                [
                    {
                        **trade,
                        "source": "ai_assistant",
                        "correlation_id": grant,
                        "metadata": {"source": "ai_assistant", "idempotency_key": grant},
                    }
                    for trade in trades
                ],
                idempotency_key=grant,
            )
        return _ok({"records": records, "count": len(records)})

    def _ledger_record_cashflow(self, args: dict[str, Any]) -> ToolResult:
        values = {"amount": float(args["amount"])}
        for key in ("occurred_on", "note"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = str(args[key]).strip()
        grant = self._grant("ledger.record_cashflow", "账户出入金", values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            event_id = store.record_account_event(
                kind="CASHFLOW",
                **values,
                source="ai_assistant",
                metadata={"source": "ai_assistant", "idempotency_key": grant},
            )
        return _ok({"id": event_id, **values})

    def _ledger_record_daily_pnl(self, args: dict[str, Any]) -> ToolResult:
        values = {"broker_pnl": float(args["broker_pnl"])}
        for key in ("market_pnl", "occurred_on", "note"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = float(args[key]) if key == "market_pnl" else str(args[key]).strip()
        grant = self._grant("ledger.record_daily_pnl", "当日盈亏", values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            result = store.record_daily_pnl(
                **values,
                source="ai_assistant",
                metadata={"source": "ai_assistant", "idempotency_key": grant},
            )
        return _ok(result)

    def _ledger_record_snapshot(self, args: dict[str, Any]) -> ToolResult:
        values = {"total_assets": float(args["total_assets"])}
        for key in ("cash", "occurred_on", "note"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = float(args[key]) if key == "cash" else str(args[key]).strip()
        grant = self._grant("ledger.record_snapshot", "账户资产", values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            snapshot_id = store.record_snapshot(**values, source="ai_assistant")
        return _ok({"id": snapshot_id, **values, "idempotency_key": grant})

    def _ledger_upsert_candidate(self, args: dict[str, Any]) -> ToolResult:
        values = {
            "code": str(args["code"]),
            "name": str(args.get("name") or ""),
            "decision": str(args["decision"]),
            "reason": str(args["reason"]),
        }
        for key in ("occurred_on", "pool_id", "timing"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = str(args[key]).strip()
        if args.get("score") is not None:
            values["score"] = float(args["score"])
        invalidation = str(args.get("invalidation") or "").strip()
        if invalidation:
            values["evidence"] = {"invalidation": invalidation}
        values["tier"] = {"精选": "selected", "观察": "watch", "落选": "reject"}[values["decision"]]
        grant = self._grant("ledger.upsert_candidate", values["code"], values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            candidate_id = store.record_candidate(
                **values,
                rule_version="潜龙" if "潜龙" in values.get("reason", "") else "manual",
                source="ai_assistant",
            )
        self._artifact("candidate_verdict", "候选裁决", {"candidates": [{**values, "id": candidate_id}]})
        return _ok({"id": candidate_id, **values, "idempotency_key": grant})

    def _ledger_delete_candidate(self, args: dict[str, Any]) -> ToolResult:
        candidate_id = str(args["candidate_id"]).strip()
        grant = self._grant("ledger.delete_candidate", candidate_id, {"candidate_id": candidate_id})
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            removed = store.delete_candidate(candidate_id)
        if not removed:
            raise AssistantError("候选不存在")
        return _ok({"candidate_id": candidate_id, "removed": True, "idempotency_key": grant})

    def _ledger_delete_candidate_pool(self, args: dict[str, Any]) -> ToolResult:
        values = {"occurred_on": str(args["occurred_on"]), "pool_id": str(args["pool_id"])}
        grant = self._grant("ledger.delete_candidate_pool", values["pool_id"], values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            removed = store.delete_candidates_for_pool(**values)
        return _ok({**values, "removed": removed, "idempotency_key": grant})

    def _ledger_record_plan(self, args: dict[str, Any]) -> ToolResult:
        values = {key: str(args[key]).strip() for key in ("code", "title", "scenario")}
        for key in ("occurred_on", "entry_zone", "invalidation", "note"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = str(args[key]).strip()
        for key in ("stop_price", "target_price", "layers"):
            if args.get(key) is not None:
                values[key] = float(args[key])
        grant = self._grant("ledger.record_plan", values["code"], values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            plan_id = store.record_plan(**values, source="ai_assistant")
        return _ok({"id": plan_id, **values, "idempotency_key": grant})

    def _ledger_record_review(self, args: dict[str, Any]) -> ToolResult:
        values = {key: str(args[key]).strip() for key in ("entity_type", "entity_id", "outcome")}
        for key in ("reviewed_on", "strategy_tag", "lesson", "next_rule"):
            if args.get(key) is not None and str(args[key]).strip():
                values[key] = str(args[key]).strip()
        for key in ("return_pct", "max_favorable_pct", "max_adverse_pct"):
            if args.get(key) is not None:
                values[key] = float(args[key])
        grant = self._grant("ledger.record_review", values["entity_id"], values)
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            review_id = store.record_review(**values, source="ai_assistant")
        return _ok({"id": review_id, **values, "idempotency_key": grant})

    def _qianlong_pool(self, args: dict[str, Any]) -> ToolResult:
        from src.ledger import PalaceStore
        with PalaceStore(self.palace_db) as store:
            rows = store.candidates_payload(args.get("occurred_on"))
        pool_id = str(args.get("pool_id") or "")
        if pool_id:
            rows = [row for row in rows if row.get("pool_id") == pool_id]
        if rows and args.get("occurred_on"):
            pools = {str(row.get("pool_id") or "") for row in rows}
            if len(pools) == 1:
                self._candidate_pool_snapshots[(str(args["occurred_on"]), pools.pop())] = frozenset(
                    str(row.get("code") or "") for row in rows
                )
        self._artifact("candidate_verdict", "潜龙候选裁决", {"candidates": rows})
        return _ok(rows)

    def _qianlong_pool_evidence(self, args: dict[str, Any]) -> ToolResult:
        day = str(args["occurred_on"])
        pool_id = str(args.get("pool_id") or "")
        limit = int(args.get("limit", 10))
        from src.ledger import PalaceStore
        from src.market import MarketStore

        with PalaceStore(self.palace_db) as palace:
            candidates = palace.candidates_payload(day)
        if pool_id:
            candidates = [row for row in candidates if row.get("pool_id") == pool_id]
        candidates = candidates[:limit]
        if candidates:
            effective_pool = pool_id or str(candidates[0].get("pool_id") or "")
            pools = {str(row.get("pool_id") or "") for row in candidates}
            if len(pools) == 1:
                self._candidate_pool_evidence[(day, effective_pool)] = frozenset(
                    str(row.get("code") or "") for row in candidates
                )
        evidence: list[dict[str, Any]] = []
        with MarketStore(self.market_db) as market:
            for candidate in candidates:
                code = str(candidate.get("code") or "")
                frame = market.history(code, end=day, adjust="qfq").tail(60)
                rows = frame.to_dict("records") if not frame.empty else []
                closes = [float(row["close"]) for row in rows if row.get("close") is not None]
                volumes = [float(row["volume"]) for row in rows if row.get("volume") is not None]
                last = closes[-1] if closes else None
                prev = closes[-2] if len(closes) > 1 else None
                ma5 = round(sum(closes[-5:]) / min(5, len(closes)), 4) if closes else None
                ma20 = round(sum(closes[-20:]) / min(20, len(closes)), 4) if closes else None
                recent_volume = volumes[-1] if volumes else None
                prior_volumes = volumes[-6:-1]
                evidence.append(
                    {
                        **candidate,
                        "close": last,
                        "pct_chg": round((last / prev - 1) * 100, 2)
                        if last is not None and prev not in (None, 0) else None,
                        "ma5": ma5,
                        "ma20": ma20,
                        "ma5_gap_pct": round((last / ma5 - 1) * 100, 2)
                        if last is not None and ma5 not in (None, 0) else None,
                        "ma20_gap_pct": round((last / ma20 - 1) * 100, 2)
                        if last is not None and ma20 not in (None, 0) else None,
                        "volume_ratio": round(recent_volume / (sum(prior_volumes) / len(prior_volumes)), 2)
                        if recent_volume is not None and prior_volumes and sum(prior_volumes) else None,
                    }
                )
        self._artifact("candidate_verdict", f"{day} 潜龙候选证据", {"candidates": evidence})
        return _ok({"occurred_on": day, "pool_id": pool_id, "candidates": evidence})

    def _qianlong_commit(self, args: dict[str, Any]) -> ToolResult:
        rows = validate_qianlong_decisions(args.get("decisions"))
        day, pool_id = str(args["occurred_on"]), str(args.get("pool_id") or "")
        from src.ledger import PalaceStore

        with PalaceStore(self.palace_db) as store:
            existing = store.candidates_payload(day)
            pools = {str(item.get("pool_id") or "") for item in existing}
            if not pool_id:
                if len(pools) != 1:
                    raise AssistantError("请明确要精炼的潜龙候选池")
                pool_id = pools.pop()
            existing = [item for item in existing if item.get("pool_id") == pool_id]
            expected = {str(item.get("code") or "") for item in existing}
            submitted = {str(item["code"]) for item in rows}
            if not expected:
                raise AssistantError("候选池为空；请先录入 6-10 只候选再做潜龙精选")
            if submitted != expected:
                missing = sorted(expected - submitted)
                extra = sorted(submitted - expected)
                raise AssistantError(f"提交必须覆盖候选池全部代码；缺少 {missing}，多出 {extra}")
            snapshot_key = (day, pool_id)
            if (
                self._candidate_pool_snapshots.get(snapshot_key) != frozenset(expected)
                or self._candidate_pool_evidence.get(snapshot_key) != frozenset(expected)
            ):
                raise AssistantError("提交前必须先读取该候选池及其本机日 K 证据")
        canonical = {"occurred_on": day, "pool_id": pool_id, "decisions": rows}
        key = self._grant("qianlong.commit_pool", pool_id or "潜龙候选池", canonical)
        from src.ai.application.system_toolbus_ledger import commit_qianlong_candidates

        ids = commit_qianlong_candidates(
            palace_db=self.palace_db, rows=rows, day=day, pool_id=pool_id, idempotency_key=key,
        )
        result = {"ids": ids, "pool_size": len(ids), "selected": sum(row["decision"] == "精选" for row in rows)}
        self._artifact("candidate_verdict", "潜龙候选裁决", {"candidates": rows})
        return _ok(result)

    def _market_kline(self, args: dict[str, Any]) -> ToolResult:
        from src.market import MarketStore
        with MarketStore(self.market_db) as store:
            frame = store.history(str(args["code"]), start=args.get("start"), end=args.get("end"), adjust="qfq")
        fields = ["trade_date", "open", "high", "low", "close", "volume", "amount", "turnover"]
        rows = [{key: _json_value(row.get(key)) for key in fields if key in row} for row in frame.tail(int(args.get("limit", 120))).to_dict("records")]
        self._artifact("qianlong_kline", f"{args['code']} 日 K", {"bars": rows})
        return _ok(rows)

    def _market_search(self, args: dict[str, Any]) -> ToolResult:
        needle, limit = str(args["query"]).strip().lower(), int(args.get("limit", 30))
        from src.market import MarketStore
        with MarketStore(self.market_db) as store:
            rows = store.list_instruments()
        selected = [{key: row.get(key, "") for key in ("code", "name", "market", "board", "industry", "status")} for row in rows if needle in str(row.get("code", "")).lower() or needle in str(row.get("name", "")).lower()]
        return _ok(selected[:limit])

    def _strategy_catalog(self, _: dict[str, Any]) -> ToolResult:
        from src.strategy import describe_all
        return _ok(describe_all())

    def _strategy_screen(self, args: dict[str, Any]) -> ToolResult:
        from src.ai.application.system_toolbus_strategy import run_strategy_screen

        return run_strategy_screen(self, args)

    def _tool_catalog(self, _: dict[str, Any]) -> ToolResult:
        return _ok({"tools": self.catalog(), "dynamic_mcp": "disabled", "skill_cli": "disabled"})


def _json_value(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _ok(data: Any) -> ToolResult:
    return {"text": json.dumps(data, ensure_ascii=False, default=str)[:12000], "structured": data, "is_error": False}


def _ops_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_ops import build_ops_tool_specs

    return build_ops_tool_specs(owner)


def build_system_toolbus(**kwargs: Any) -> SystemToolBus:
    return SystemToolBus(**kwargs)
