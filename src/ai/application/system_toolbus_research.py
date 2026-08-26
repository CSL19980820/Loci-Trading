"""全局助手的只读研究工具。"""
from __future__ import annotations

from typing import Any


_METRIC_KEYS = (
    "close",
    "ma20",
    "ma60",
    "ma200",
    "rsi14",
    "macd_hist",
    "volume_ratio20",
    "stage",
    "vcp_possible",
    "bars",
)


def _catalog_projection() -> dict[str, Any]:
    from src.research import build_research_catalog

    catalog = build_research_catalog()
    return {
        "version": catalog["version"],
        "dimensions": [
            {
                "key": item["key"],
                "name": item["name"],
                "group": item["group"],
                "availability": item["availability"],
                "historical_safe": item["historical_safe"],
                "candidate_sources": item["candidate_sources"],
            }
            for item in catalog["dimensions"]
        ],
        "sources": [
            {
                "id": item["id"],
                "name_cn": item["name_cn"],
                "tier": item["tier"],
                "access": item["access"],
                "health": item["health"],
                "dims": item["dims"],
            }
            for item in catalog["sources"]
        ],
        "budgets": catalog["budgets"],
        "guardrails": catalog["guardrails"],
    }


def research_catalog(_: Any, __: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok

    return _ok(_catalog_projection())


def _profile_projection(body: dict[str, Any]) -> dict[str, Any]:
    dimensions = []
    for item in body["dimensions"]:
        values = item.get("values") or {}
        dimensions.append(
            {
                "key": item["key"],
                "name": item["name"],
                "quality": item["quality"],
                "source": item["source"],
                "as_of": item["as_of"],
                "data_gaps": item["data_gaps"],
                "metrics": {key: values[key] for key in _METRIC_KEYS if key in values},
                "evidence": [
                    {
                        "source_id": ref["source_id"],
                        "as_of": ref["as_of"],
                        "payload_sha256": ref["payload_sha256"],
                        "title": ref["title"],
                    }
                    for ref in item["evidence"]
                ],
            }
        )
    quality = body["quality"]
    return {
        "code": body["code"],
        "subject": {
            key: body["subject"].get(key, "")
            for key in ("code", "name", "market", "board", "industry", "status")
        },
        "budget": body["budget"],
        "requested_as_of": body["requested_as_of"],
        "generated_at": body["generated_at"],
        "quality": {
            "overall": quality["overall"],
            "blocked": quality["blocked"],
            "completeness_ratio": quality["completeness_ratio"],
            "market_revision": quality["market_revision"],
            "findings": quality["findings"],
        },
        "source_attempts": body["source_attempts"],
        "dimensions": dimensions,
        "artifact": {"id": "", "status": "transient", "write": "disabled"},
        "contract": body["contract"],
    }


def research_profile(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.market import MarketStore
    from src.research import build_research_profile

    with MarketStore(owner.market_db) as store:
        profile = build_research_profile(
            store,
            str(args["code"]),
            budget=str(args.get("budget") or "standard"),
            as_of=args.get("as_of") or None,
        )
    return _ok(_profile_projection(profile.to_dict()))


def build_research_tool_specs(owner: Any) -> dict[str, Any]:
    """延迟导入，避免与 SystemToolBus 的 ToolSpec 形成循环。"""
    from src.ai.application.system_toolbus import ToolSpec, _object

    read = False
    return {
        "research_catalog": ToolSpec(
            "research_catalog",
            "读取研究维度目录、候选来源和质量边界。",
            _object({}),
            read,
            lambda args: research_catalog(owner, args),
        ),
        "research_profile": ToolSpec(
            "research_profile",
            "只读读取本地研究剖面；返回质量、缺口和证据 hash，不生成生产信号。",
            _object(
                {
                    "code": {"type": "string", "pattern": "^\\d{6}$"},
                    "budget": {"type": "string", "enum": ["lite", "standard", "deep"]},
                    "as_of": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                },
                ["code"],
            ),
            read,
            lambda args: research_profile(owner, args),
        ),
    }
