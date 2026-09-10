"""全局助手的系统工具面。

默认挂载：账本/行情/策略/运维/记忆 + ask_user（HITL）+ web_search/web_fetch + 活跃 MCP。
仍禁止 shell、任意文件、raw SQL、券商下单；URL 仅允许 web_* 与 MCP 工具。
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from threading import Thread
from time import monotonic
from typing import Any, Callable

from src.ai.application.system_tool_result import ToolResult, ok as _ok
from src.ai.application.tool_schema import tool_schema
from src.ai.domain.assistant import AssistantError
from src.shared.observability import (
    correlation_scope,
    current as current_observation,
    event as observation_event,
    new_id,
    span as observation_span,
)
GrantIssuer = Callable[[str, str, dict[str, Any]], dict[str, Any] | None]
GrantConsumer = Callable[[str, str, str, dict[str, Any]], str]
GrantCompleter = Callable[[str, dict[str, Any], str], None]
EventCallback = Callable[[dict[str, Any]], None]
logger = logging.getLogger(__name__)

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
    #: web_search / web_fetch / MCP 等可携带 URL 参数
    allow_urls: bool = False
    #: 可选的执行预算；不配置时由底层 client 或业务用例自行控制。
    timeout_seconds: float | None = None


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        result["required"] = required
    return result


def _normalize_ask_questions(raw: Any) -> list[dict[str, Any]]:
    """Normalize ask_user.questions[]; empty/invalid entries dropped."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not qid or not prompt:
            continue
        row: dict[str, Any] = {"id": qid[:64], "prompt": prompt[:2000]}
        opts = item.get("options")
        if isinstance(opts, list):
            cleaned = [str(o).strip() for o in opts if str(o).strip()][:12]
            if cleaned:
                row["options"] = cleaned
        if item.get("allow_free_text") is True:
            row["allow_free_text"] = True
        out.append(row)
    return out


def _safe(value: Any, *, allow_urls: bool = False) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _FORBIDDEN.search(str(key)):
                # url 键在 allow_urls 工具上放行
                if allow_urls and re.fullmatch(r"urls?|endpoint|link", str(key), re.I):
                    _safe(item, allow_urls=True)
                    continue
                raise AssistantError("工具参数不得包含凭据、URL、文件、命令或 SQL")
            _safe(item, allow_urls=allow_urls)
    elif isinstance(value, list):
        for item in value:
            _safe(item, allow_urls=allow_urls)
    elif isinstance(value, str) and ("http://" in value.lower() or "https://" in value.lower()):
        if not allow_urls:
            raise AssistantError("工具参数不得包含 URL")


def _validate_schema(value: Any, schema: dict[str, Any], *, path: str = "arguments") -> None:
    """执行工具入口所需的最小 JSON Schema 校验。

    这里不引入 jsonschema 依赖，只覆盖 MCP/内置工具实际用到的 object、
    array、string、number、boolean 约束；未知 schema 关键字保持向后兼容。
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise AssistantError(f"{path} 必须是对象")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        missing = [str(key) for key in required if key not in value]
        if missing:
            raise AssistantError(f"{path} 缺少必填参数：{', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = [str(key) for key in value if key not in properties]
            if unknown:
                raise AssistantError(f"{path} 包含未声明参数：{', '.join(unknown[:8])}")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_schema(item, child, path=f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise AssistantError(f"{path} 必须是数组")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise AssistantError(f"{path} 数量不能少于 {schema['minItems']}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise AssistantError(f"{path} 数量不能超过 {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value[:512]):
                _validate_schema(item, item_schema, path=f"{path}[{index}]")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise AssistantError(f"{path} 必须是字符串")
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise AssistantError(f"{path} 长度不足")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise AssistantError(f"{path} 长度超过上限")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(str(pattern), value) is None:
            raise AssistantError(f"{path} 格式不合法")
        return
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise AssistantError(f"{path} 必须是整数")
    if expected == "number" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise AssistantError(f"{path} 必须是数字")
    if expected == "boolean" and not isinstance(value, bool):
        raise AssistantError(f"{path} 必须是布尔值")


class SystemToolBus:
    """固定注册的业务工具；所有写入在 handler 前消费运行绑定的 ExecutionGrant。"""

    def __init__(
        self, *, palace_db: str | None, market_db: str | None, ops_db: str | None,
        protocol: str = "openai_compatible", grant_issuer: GrantIssuer | None = None,
        grant_consumer: GrantConsumer | None = None, grant_completer: GrantCompleter | None = None,
        on_event: EventCallback | None = None, scheduler_reloader: Callable[[], None] | None = None,
        read_only: bool = False, attach_mcp: bool = True,
        allow_tools: set[str] | frozenset[str] | None = None,
        tool_timeout_seconds: float | None = None,
    ) -> None:
        self.palace_db, self.market_db, self.ops_db = palace_db, market_db, ops_db
        self.protocol = protocol
        self.grant_issuer, self.grant_consumer = grant_issuer, grant_consumer
        self.grant_completer, self.on_event, self._last_grant_id = grant_completer, on_event, ""
        self._scheduler_reloader = scheduler_reloader
        try:
            parsed_timeout = float(tool_timeout_seconds) if tool_timeout_seconds is not None else 0.0
        except (TypeError, ValueError):
            parsed_timeout = 0.0
        self._tool_timeout_seconds = parsed_timeout if parsed_timeout > 0 else None
        self._background_threads: list[Thread] = []
        self._candidate_pool_snapshots: dict[tuple[str, str], frozenset[str]] = {}
        self._candidate_pool_evidence: dict[tuple[str, str], frozenset[str]] = {}
        self._read_only = read_only
        self._mcp_attached = 0
        self._mcp_routing: dict[str, str] = {}
        specs = self._register()
        # MCP 一律只读；注册后再滤一次写工具即可（避免双重过滤）。
        # 只读子 Agent 传 attach_mcp=False，避免重复扫 mcp.json / 建客户端。
        # allow_tools：角色化子 Agent 白名单（在 MCP/只读过滤之后再裁）。
        self._specs = dict(specs)
        if attach_mcp:
            from src.ai.application.system_toolbus_mcp import mount_default_mcp

            mount_default_mcp(self)
        if read_only:
            self._specs = {name: spec for name, spec in self._specs.items() if not spec.write}
        if allow_tools is not None:
            allow = {str(name).strip() for name in allow_tools if str(name).strip()}
            self._specs = {name: spec for name, spec in self._specs.items() if name in allow}

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            tool_schema(self.protocol, spec.name, spec.description, spec.parameters)
            for spec in self._specs.values()
        ]

    def catalog(self) -> list[dict[str, Any]]:
        """前端上下文用量用：含 schema_tokens / mcp tags，贴近真实 tools JSON 体积。"""
        import json

        from src.ai.application.context_usage import estimate_tokens

        routing = getattr(self, "_mcp_routing", {}) or {}
        out: list[dict[str, Any]] = []
        for item in self._specs.values():
            schema_blob = json.dumps(
                {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            row: dict[str, Any] = {
                "name": item.name,
                "description": item.description,
                "risk": "write" if item.write else "read",
                "schema_tokens": estimate_tokens(schema_blob),
            }
            if item.name in routing or "__" in item.name:
                row["tags"] = ["mcp", "dynamic"]
            out.append(row)
        return out

    def executor(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return {"text": "未注册的系统工具", "is_error": True}
        if not isinstance(arguments, dict):
            return {"text": "工具参数必须是对象", "is_error": True}
        receipt_id = new_id("tool")
        started = monotonic()
        timeout_seconds = spec.timeout_seconds or self._tool_timeout_seconds
        inherited = current_observation()
        result: ToolResult
        deferred = False
        try:
            self._last_grant_id = ""
            if self._read_only and spec.write:
                raise AssistantError("只读助手无权执行写工具")
            _validate_schema(arguments, spec.parameters)
            _safe(arguments, allow_urls=spec.allow_urls)
            if self.on_event:
                self.on_event(
                    {
                        "type": "tool_start",
                        "name": name,
                        "arguments": arguments,
                        "tool_receipt_id": receipt_id,
                    }
                )
            with observation_span(
                "system_tool.invoke",
                trace_id=inherited.trace_id,
                run_id=inherited.run_id,
                job_id=inherited.job_id,
                tool_receipt_id=receipt_id,
                labels={"component": "system_toolbus", "operation": "invoke"},
            ):
                result = spec.handler(arguments)
            deferred = bool(result.pop("_grant_deferred", False))
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
        elapsed_ms = max(0, int((monotonic() - started) * 1000))
        timed_out = timeout_seconds is not None and elapsed_ms > int(timeout_seconds * 1000)
        if timed_out:
            if spec.write and self._last_grant_id:
                self._finalize_grant(
                    self._last_grant_id,
                    {"error": f"工具超过 timeout={timeout_seconds:g}s"},
                    status="failed",
                )
            result = {
                "text": f"工具超时（>{timeout_seconds:g}s）",
                "is_error": True,
                "meta": {"timeout": True},
            }
        elif spec.write and self._last_grant_id and not deferred:
            self._finalize_grant(self._last_grant_id, result.get("structured", {}))
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        result["meta"] = {**meta, "tool_receipt_id": receipt_id}
        result["tool_receipt_id"] = receipt_id
        with correlation_scope(
            trace_id=inherited.trace_id,
            run_id=inherited.run_id,
            job_id=inherited.job_id,
            tool_receipt_id=receipt_id,
        ):
            observation_event(
                logger,
                logging.INFO if not result.get("is_error") else logging.WARNING,
                "system_tool_invocation",
                fields={
                    "operation": "invoke",
                    "outcome": "error" if result.get("is_error") else "ok",
                },
            )
        if self.on_event:
            from src.ai.application.system_toolbus_preview import tool_event_preview

            self.on_event(
                {
                    "type": "tool_end",
                    "name": name,
                    "ok": not result.get("is_error"),
                    "preview": tool_event_preview(name, result),
                    "elapsed_ms": elapsed_ms,
                    "tool_receipt_id": receipt_id,
                }
            )
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

    def _artifact(
        self, kind: str, title: str, data: dict[str, Any], *, status: str = "ready",
    ) -> None:
        if self.on_event:
            payload: dict[str, Any] = {
                "type": "artifact", "kind": kind, "title": title, "data": data, "status": status,
            }
            self.on_event(payload)

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
        specs = {
            "ask_user": ToolSpec(
                "ask_user",
                "需要用户抉择时必须调用：单题用 prompt + options；多题用 questions"
                "[{id,prompt,options?,allow_free_text?}]，用户一次提交全部答案。",
                _object(
                    {
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "options": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {"type": "string", "minLength": 1, "maxLength": 80},
                        },
                        "questions": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": _object(
                                {
                                    "id": {"type": "string", "minLength": 1, "maxLength": 64},
                                    "prompt": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 2000,
                                    },
                                    "options": {
                                        "type": "array",
                                        "maxItems": 12,
                                        "items": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 80,
                                        },
                                    },
                                    "allow_free_text": {"type": "boolean"},
                                },
                                ["id", "prompt"],
                            ),
                        },
                    },
                ),
                read,
                self._ask_user,
            ),
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
            "system_tool_catalog": ToolSpec(
                "system_tool_catalog",
                "读取系统工具目录（含默认挂载的 MCP 与 web_search）。",
                _object({}),
                read,
                self._tool_catalog,
            ),
        }
        specs.update(_ledger_specs(self))
        specs.update(_qianlong_specs(self))
        specs.update(_market_specs(self))
        specs.update(_research_specs(self))
        specs.update(_ops_specs(self))
        specs.update(_memory_specs(self))
        from src.ai.application.system_toolbus_web import web_specs

        specs.update(web_specs(self))
        return specs

    def _ask_user(self, arguments: dict[str, Any]) -> ToolResult:
        """Cursor/Hermes 式交互问答：暂停主环，等用户回复后再开下一轮。"""
        questions = _normalize_ask_questions(arguments.get("questions"))
        prompt = str(arguments.get("prompt") or "").strip()
        raw_options = arguments.get("options") or []
        if not isinstance(raw_options, list):
            raw_options = [raw_options]
        options = [str(item).strip() for item in raw_options if str(item).strip()][:12]
        if not questions and not prompt:
            return {
                "text": "ask_user 需要 prompt 或 questions",
                "is_error": True,
                "meta": {},
            }
        if questions:
            summary = prompt or str(questions[0].get("prompt") or "请确认下一步")
            ask: dict[str, Any] = {
                "prompt": summary,
                "options": options,
                "questions": questions,
            }
        else:
            ask = {"prompt": prompt or "请确认下一步", "options": options}
        return {
            "text": str(ask["prompt"]),
            "is_error": False,
            "meta": {
                "pause": True,
                "needs_hitl": True,
                "ask": ask,
            },
        }

    def _strategy_catalog(self, _: dict[str, Any]) -> ToolResult:
        from src.strategy import describe_all
        return _ok(describe_all())

    def _strategy_screen(self, args: dict[str, Any]) -> ToolResult:
        from src.ai.application.system_toolbus_strategy import run_strategy_screen

        return run_strategy_screen(self, args)

    def _tool_catalog(self, _: dict[str, Any]) -> ToolResult:
        return _ok(
            {
                "tools": self.catalog(),
                "dynamic_mcp": "mounted" if getattr(self, "_mcp_attached", 0) else "empty",
                "mcp_tool_count": int(getattr(self, "_mcp_attached", 0) or 0),
                "web_tools": ["web_search", "web_fetch"],
                "skill_cli": "slash_prompt",
            }
        )


def _qianlong_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_qianlong import build_qianlong_tool_specs

    return build_qianlong_tool_specs(owner)


def _ledger_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_ledger import build_ledger_tool_specs

    return build_ledger_tool_specs(owner)


def _ops_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_ops import build_ops_tool_specs

    return build_ops_tool_specs(owner)


def _market_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_market import build_market_tool_specs

    return build_market_tool_specs(owner)


def _research_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_research import build_research_tool_specs

    return build_research_tool_specs(owner)


def _memory_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus_memory import build_memory_tool_specs

    return build_memory_tool_specs(owner)


def build_system_toolbus(**kwargs: Any) -> SystemToolBus:
    return SystemToolBus(**kwargs)
