"""研究目录和来源名片。"""
from __future__ import annotations

from typing import Any

from src.market import list_catalog
from src.research.domain.dimensions import list_dimension_specs


_RESEARCH_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "market.db",
        "name_cn": "本地行情仓",
        "base_url": "",
        "markets": ["A-share"],
        "dims": ["0_basic", "2_kline", "12_capital_flow", "18_trap"],
        "tier": "local",
        "access": "local",
        "health": "available",
        "notes": "只提供已入库事实和可重建技术指标；不含估值与定性结论。",
    },
    {
        "id": "market.adapters",
        "name_cn": "行情线路适配器",
        "base_url": "",
        "markets": ["A-share"],
        "dims": ["0_basic", "2_kline", "8_materials", "9_futures", "12_capital_flow"],
        "tier": "tier-1",
        "access": "adapter",
        "health": "registered",
        "notes": "注册不等于当前请求成功；实际命中源须由行情回执确认。",
    },
    {
        "id": "akshare",
        "name_cn": "AkShare 受控接口目录",
        "base_url": "https://akshare.akfamily.xyz/",
        "markets": ["A-share", "fund", "futures"],
        "dims": ["1_financials", "4_peers", "6_fund_holders", "6_research", "10_valuation", "15_events", "16_lhb"],
        "tier": "tier-1",
        "access": "catalog-probe",
        "health": "not_probed",
        "notes": "只有经目录探针和字段映射确认后才能进入研究结果。",
    },
    {
        "id": "official_disclosure",
        "name_cn": "官方披露",
        "base_url": "",
        "markets": ["A-share"],
        "dims": ["1_financials", "3_macro", "5_chain", "7_industry", "10_valuation", "11_governance", "13_policy", "14_moat", "15_events"],
        "tier": "tier-3",
        "access": "pending",
        "health": "not_connected",
        "notes": "需逐来源确认许可、发布时间和历史可回放口径。",
    },
    {
        "id": "intel.mcp",
        "name_cn": "受控外部情报 MCP",
        "base_url": "",
        "markets": ["A-share"],
        "dims": ["3_macro", "5_chain", "13_policy", "14_moat", "15_events", "17_sentiment", "18_trap", "19_contests"],
        "tier": "tier-2",
        "access": "configured-probe",
        "health": "not_probed",
        "notes": "必须保存实际 URL、抓取时间和内容 hash；不能把搜索片段当历史事实。",
    },
)


def build_research_catalog() -> dict[str, Any]:
    """返回研究工作台需要的静态契约与当前行情线路名片。"""
    adapters: list[dict[str, Any]] = []
    try:
        adapters = [dict(row) for row in list_catalog()]
    except Exception as exc:  # pragma: no cover - optional market dependency boundary
        adapters = [{"id": "market.adapters", "error": f"{type(exc).__name__}: {exc}"}]
    return {
        "version": "research-contract-v1",
        "dimensions": [item.to_dict() for item in list_dimension_specs()],
        "sources": [dict(item) for item in _RESEARCH_SOURCES],
        "market_adapters": adapters,
        "quality_values": ["full", "partial", "missing", "error"],
        "budgets": [
            {"id": "lite", "label": "轻量", "max_bars": 120, "external_fetch": False},
            {"id": "standard", "label": "标准", "max_bars": 320, "external_fetch": False},
            {"id": "deep", "label": "深度", "max_bars": 600, "external_fetch": False},
        ],
        "guardrails": {
            "production_signal": False,
            "static_scores_are_not_facts": True,
            "missing_data_stays_missing": True,
            "market_health_gate": True,
        },
    }

