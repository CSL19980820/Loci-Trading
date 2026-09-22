"""Discover research tools on demand without resending the entire MCP catalog."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.shared.tenancy import current_tenant


class ToolSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = ""
    names: list[str] = Field(default_factory=list, max_length=10)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=10)


class ResearchToolCatalog:
    """The agent keeps this schema list by reference; discovery extends the next request."""

    def __init__(self, protocol: str, schemas: list[dict], checkpoint: Any) -> None:
        from src.ai.application.tool_schema import tool_schema

        self.tenant = current_tenant()
        self.checkpoint = checkpoint
        self.catalog = {(s.get("function") or s)["name"]: copy.deepcopy(s) for s in schemas}
        essential = {"guardian_quotes", "guardian_runtime", "guardian_account_read", "guardian_calculate", "guardian_preflight"}
        # 每轮高频的盘面/资金查询保留入口，避免为几百字schema多付一轮模型延迟。
        market_core = {"market_overview", "intraday_main_flow", "theme_intraday_capital"}
        self.loaded = {name for name in self.catalog if name in essential or name.split("__")[-1] in market_core}
        self.schemas = [self.catalog[name] for name in sorted(self.loaded)]
        self.schemas.append(tool_schema(protocol, "guardian_tools_search",
            "按中英文关键词或完整names发现并加载工具，下一次模型请求即可直接调用。空query分页浏览全部工具；"
            "支持MCP行情、资金、新闻、全市场筛选、网页、历史决策、策略、预演等，未加载不代表不可用。",
            ToolSearch.model_json_schema()))

    def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.checkpoint()
        if current_tenant() != self.tenant:
            return {"is_error": True, "text": "工具目录不属于当前租户"}
        query = ToolSearch.model_validate(arguments)
        if query.names and not set(query.names) <= self.catalog.keys():
            return {"is_error": True, "text": "未知工具名称，请先按关键词搜索本轮目录"}
        words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", query.query.casefold())
        # 模型会写“板块资金 主力净流入 全市场”，不能要求每个长词同时逐字命中。
        grams = {word[i:i+2] for word in words if re.fullmatch(r"[\u4e00-\u9fff]+", word)
                 for i in range(len(word)-1)}
        ranked = []
        for name, schema in self.catalog.items():
            body = schema.get("function") or schema
            haystack = (name + " " + body.get("description", "")).casefold()
            score = sum(10 for word in words if word in haystack) + sum(1 for gram in grams if gram in haystack)
            if (query.names and name in query.names) or (not query.names and (not words or score)):
                ranked.append((score, name))
        if words and not query.names:
            ranked.sort(key=lambda row: -row[0])
        matches = [name for _, name in ranked]
        page = matches[query.offset:query.offset + query.limit]
        for name in page:
            if name not in self.loaded:
                self.schemas.append(self.catalog[name])
                self.loaded.add(name)
        return {"text": json.dumps({"total": len(matches), "offset": query.offset,
            "next_offset": query.offset + len(page) if query.offset + len(page) < len(matches) else None,
            "loaded": [{"name": name, "description_excerpt": (self.catalog[name].get("function") or self.catalog[name]).get("description", "")[:180]}
                       for name in page],
            "no_match_hint": "没有命中；用更短关键词，或空query分页浏览目录。" if not matches else "",
            "note": "以上工具的完整参数定义已加入可调用工具列表，直接按schema调用；完整目录仍可继续分页搜索。"}, ensure_ascii=False)}

    def metrics(self) -> dict[str, int]:
        return {"available_tools": len(self.catalog), "loaded_tools": len(self.loaded),
                "full_tool_schema_characters": len(json.dumps(list(self.catalog.values()), ensure_ascii=False)),
                "loaded_tool_schema_characters": len(json.dumps(self.schemas, ensure_ascii=False))}
