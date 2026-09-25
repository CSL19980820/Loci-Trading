"""助手并行只读证据子 Agent：角色化工具面 + brief 进主环。

设计：
- 按用户意图选 ≤3 个角色（market / qianlong / web / research）
- 每角色固定工具白名单；默认不挂 MCP；仅 web 可调用 web_search/web_fetch
- 侧栏仍发 subagent_*；主环只注入截断 brief（非终裁）
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.ai.application.agent import run_agent
from src.ai.application.system_toolbus import build_system_toolbus
from src.shared.tenancy import submit_with_tenant

EventCallback = Callable[[dict[str, Any]], None]
RoleName = Literal["market", "qianlong", "web", "research"]

_MAX_ROLES = 3
#: 并行取证的墙钟上限（秒）；到点后子 Agent 以失败 brief 收场，主环照常回答。
_EVIDENCE_SECONDS = 180.0
_BRIEF_PER_AGENT = 800
_BRIEF_TOTAL = 2400

_TOOL_ZH: dict[str, str] = {
    "qianlong_candidate_pool": "读取潜龙候选池",
    "qianlong_pool_evidence": "读取潜龙池证据",
    "market_kline": "拉取日 K",
    "market_search": "搜索标的",
    "research_catalog": "读取研究目录",
    "research_profile": "读取研究画像",
    "web_search": "检索公开网页",
    "web_fetch": "抓取网页正文",
}


@dataclass(frozen=True)
class EvidenceRoleSpec:
    id: str
    name: str
    role: RoleName
    focus: str
    allow_tools: frozenset[str]
    allow_web: bool = False
    max_rounds: int = 3
    max_tokens: int = 1400


_ROLE_TOOLS: dict[RoleName, frozenset[str]] = {
    "market": frozenset({"market_kline", "market_search"}),
    "qianlong": frozenset({"qianlong_candidate_pool", "qianlong_pool_evidence", "market_kline"}),
    "web": frozenset({"web_search", "web_fetch"}),
    "research": frozenset({"research_catalog", "research_profile"}),
}


def _tool_zh(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return "取证"
    if raw in _TOOL_ZH:
        return _TOOL_ZH[raw]
    if raw.startswith("market_"):
        return "查询行情"
    if raw.startswith("qianlong_"):
        return "读取潜龙"
    if raw.startswith("web_"):
        return "外网取证"
    if raw.startswith("research_"):
        return "读取研究"
    return "取证"


def plan_evidence_roles(prompt: str) -> list[EvidenceRoleSpec]:
    """按用户话术选出角色；上限 3，稳定顺序。"""
    text = (prompt or "").strip()
    if not text:
        return []
    planned: list[EvidenceRoleSpec] = []

    def add(role: RoleName, agent_id: str, name: str, focus: str) -> None:
        if any(item.role == role for item in planned):
            return
        if len(planned) >= _MAX_ROLES:
            return
        planned.append(
            EvidenceRoleSpec(
                id=agent_id,
                name=name,
                role=role,
                focus=focus,
                allow_tools=_ROLE_TOOLS[role],
                allow_web=(role == "web"),
            )
        )

    if any(token in text for token in ("潜龙", "候选", "精选", "选股")):
        add(
            "qianlong",
            "candidate-evidence",
            "候选证据",
            "读取潜龙候选池与池证据，核对既有裁决与证据缺口；禁止终裁锁票。",
        )
        add(
            "market",
            "market-evidence",
            "行情证据",
            "若请求含明确标的，读取本机日 K / 搜索标的，只汇报结构证据。",
        )
    if any(token in text for token in ("新闻", "公告", "政策", "舆情", "外网", "消息", "搜索", "资讯")):
        add(
            "web",
            "web-evidence",
            "外网证据",
            "用 web_search/web_fetch 收集公开网页要点；标明外网证据，不可当作账本或行情真值。",
        )
    if any(token in text for token in ("研究画像", "研究目录", "研究维度", "证据缺口")):
        add(
            "research",
            "research-evidence",
            "研究目录",
            "读取研究目录/画像，只汇报维度、质量与缺口，不编造指标数字。",
        )
    return planned[:_MAX_ROLES]


def format_evidence_briefs(results: list[dict[str, Any]]) -> str:
    """折叠进主环 system 的短 brief；空则返回空串。"""
    if not results:
        return ""
    blocks = [
        "# 并行只读证据（brief，非终裁）",
        "以下为子 Agent 摘要，仅作线索；行情与候选数字仍须主环工具复核。"
        "子 Agent 不得终裁交易。",
    ]
    used = 0
    for row in results:
        mark = "成功" if row.get("ok") else "失败"
        name = str(row.get("name") or row.get("id") or "证据")
        role = str(row.get("role") or "")
        body = str(row.get("text") or "").strip() or "(无输出)"
        # 失败 brief 缩短，避免把 empty_completion 用户文案当证据灌进主环
        if not row.get("ok"):
            body = body[:160]
        body = body[:_BRIEF_PER_AGENT]
        if len(body) >= _BRIEF_PER_AGENT:
            body = body[: _BRIEF_PER_AGENT - 1] + "…"
        chunk = f"## [{mark}] {name}" + (f"（{role}）" if role else "") + f"\n{body}"
        if used + len(chunk) > _BRIEF_TOTAL:
            remain = max(0, _BRIEF_TOTAL - used - 20)
            if remain > 40:
                blocks.append(chunk[:remain] + "…")
            blocks.append("（后续证据已截断）")
            break
        blocks.append(chunk)
        used += len(chunk)
    return "\n\n".join(blocks).strip()


def run_evidence_agents(
    *,
    config: Any,
    prompt: str,
    palace_db: str | None,
    market_db: str | None,
    ops_db: str | None,
    on_event: EventCallback | None = None,
    specs: list[EvidenceRoleSpec] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    """并行跑角色化只读取证；发 plan/subagent_*；返回结果列表供 brief。

    ``check_cancelled`` / ``deadline`` 透传给每个子 Agent：用户取消或整轮超时后
    子 Agent 不再继续请求模型。子 Agent 失败只落成失败 brief，不拖垮主回答；
    每行带 ``input_tokens`` / ``output_tokens`` 供调用方计费。
    """
    roles = list(specs) if specs is not None else plan_evidence_roles(prompt)
    if not roles:
        return []
    if deadline is not None:
        # 取证只是给主环的线索，不能吃掉主回答的全部时间预算。
        deadline = min(deadline, time.monotonic() + _EVIDENCE_SECONDS)
    if on_event:
        on_event(
            {
                "type": "plan",
                "steps": [
                    {"id": "evidence", "label": "并行收集只读证据", "status": "running"},
                    {"id": "main", "label": "主助手综合回答", "status": "queued"},
                    {"id": "answer", "label": "结论置底", "status": "queued"},
                ],
            }
        )

    def run_one(spec: EvidenceRoleSpec) -> dict[str, Any]:
        if on_event:
            on_event(
                {
                    "type": "subagent_start",
                    "id": spec.id,
                    "name": spec.name,
                    "role": spec.role,
                    "progress": 5,
                    "detail": "已启动",
                }
            )

        def child_event(payload: dict[str, Any]) -> None:
            if on_event is None:
                return
            kind = str(payload.get("type") or "")
            if kind == "round_start":
                on_event(
                    {
                        "type": "subagent_progress",
                        "id": spec.id,
                        "name": spec.name,
                        "progress": 35,
                        "detail": "正在整理证据",
                    }
                )
            elif kind == "tool_start":
                tool_name = str(payload.get("name") or "").strip()
                call_id = str(
                    payload.get("tool_receipt_id")
                    or payload.get("call_id")
                    or f"{spec.id}-{tool_name}-{payload.get('name') or 'tool'}"
                )
                on_event(
                    {
                        "type": "subagent_progress",
                        "id": spec.id,
                        "name": spec.name,
                        "progress": 70,
                        "detail": f"正在{_tool_zh(tool_name)}",
                    }
                )
                on_event(
                    {
                        "type": "subagent_tool",
                        "id": spec.id,
                        "name": spec.name,
                        "call_id": call_id,
                        "tool_name": tool_name or "工具",
                        "status": "running",
                        "arguments": payload.get("arguments")
                        if isinstance(payload.get("arguments"), dict)
                        else None,
                    }
                )
            elif kind == "tool_end":
                tool_name = str(payload.get("name") or "").strip()
                call_id = str(
                    payload.get("tool_receipt_id")
                    or payload.get("call_id")
                    or f"{spec.id}-{tool_name}"
                )
                ok = payload.get("ok") is not False
                preview = str(payload.get("preview") or "").strip()
                on_event(
                    {
                        "type": "subagent_tool",
                        "id": spec.id,
                        "name": spec.name,
                        "call_id": call_id,
                        "tool_name": tool_name or "工具",
                        "status": "done" if ok else "error",
                        "preview": preview[:240] if preview else None,
                        "elapsed_ms": payload.get("elapsed_ms"),
                    }
                )

        try:
            bus = build_system_toolbus(
                palace_db=palace_db,
                market_db=market_db,
                ops_db=ops_db,
                protocol=getattr(config, "protocol", "openai_compatible"),
                on_event=child_event,
                read_only=True,
                attach_mcp=False,
                allow_tools=set(spec.allow_tools),
            )
            net_rule = (
                "可调用 web_search/web_fetch；结果必须标明外网证据。"
                if spec.allow_web
                else "不得使用网络工具。"
            )
            result = run_agent(
                config,
                system=(
                    f"你是 Loci 的只读子 Agent（角色={spec.role}）。"
                    f"只能调用已给出的只读工具，{net_rule}"
                    "不得写入、不得给出交易终裁或锁票。"
                    "用简洁中文汇报证据要点，优先列事实与缺口。"
                ),
                user_prompt=f"任务：{spec.focus}\n原始用户请求：{prompt}",
                tool_schemas=bus.schemas,
                tool_executor=bus.executor,
                max_rounds=max(spec.max_rounds, 5),
                max_tokens=spec.max_tokens,
                emit_terminal_event=False,
                check_cancelled=check_cancelled,
                deadline=deadline,
            )
            ok = result.stopped_reason == "completed"
            text = (result.text or "").strip()[:4000]
            if not ok:
                text = text or f"子 Agent 未完成（{result.stopped_reason}）"
            detail = text[:360] if text else ("已完成只读取证" if ok else "取证失败")
            if on_event:
                on_event(
                    {
                        "type": "subagent_end",
                        "id": spec.id,
                        "name": spec.name,
                        "role": spec.role,
                        "ok": ok,
                        "progress": 100,
                        "detail": detail,
                    }
                )
            return {
                "id": spec.id,
                "name": spec.name,
                "role": spec.role,
                "ok": ok,
                "text": text,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            usage = getattr(exc, "usage", None)
            usage = usage if isinstance(usage, dict) else {}
            if on_event:
                on_event(
                    {
                        "type": "subagent_end",
                        "id": spec.id,
                        "name": spec.name,
                        "role": spec.role,
                        "ok": False,
                        "progress": 100,
                        "detail": detail,
                    }
                )
            return {
                "id": spec.id,
                "name": spec.name,
                "role": spec.role,
                "ok": False,
                "text": detail,
                "model": str(usage.get("model") or ""),
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            }

    results: list[dict[str, Any]] = []
    workers = min(2, len(roles))
    # 这个池是**在助手 worker 线程里**临时起的，而 worker 已经带着发起用户的
    # 租户上下文（AssistantManager 经 submit_with_tenant 投递）。子线程不继承
    # ContextVar，裸 pool.submit 会让每个证据子 Agent 的工具面（行情/账本/研究，
    # 全部按 current_tenant() 解析库）掉回主租户——子 Agent 会读到管理员的数据
    # 并把它当成用户自己的证据讲出来。必须 submit_with_tenant。
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ai-evidence") as pool:
        futures = {submit_with_tenant(pool, run_one, spec): spec for spec in roles}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 — 取证是线索，不能把主回答一起带崩
                results.append({"id": spec.id, "name": spec.name, "role": spec.role,
                                "ok": False, "text": f"{type(exc).__name__}: {exc}"})
    order = {spec.id: i for i, spec in enumerate(roles)}
    results.sort(key=lambda row: order.get(str(row.get("id")), 999))
    return results
