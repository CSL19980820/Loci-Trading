"""研究维度目录。

目录只描述契约和当前接入状态，不把外部项目的静态评分当成事实。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Availability = Literal["local", "partial", "pending"]


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    """一个研究维度的输入、来源和质量边界。"""

    key: str
    name: str
    group: str
    summary: str
    expected_fields: tuple[str, ...]
    candidate_sources: tuple[str, ...]
    availability: Availability
    historical_safe: bool
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# UZI 固定版本实际 registry 中的 21 个 unique dim_key。
# 这里保留原 key，便于研究产物和外部资料互相引用；编号相同不代表同一维度。
DIMENSION_SPECS: tuple[DimensionSpec, ...] = (
    DimensionSpec(
        "0_basic", "基本资料", "基础", "身份、市场、行业与最新行情。",
        ("code", "name", "market", "industry", "close", "as_of"),
        ("market.db", "market.adapters", "akshare"), "partial", True,
    ),
    DimensionSpec(
        "1_financials", "财务质量", "基本面", "报表、盈利能力、现金流与分红。",
        ("report_period", "revenue", "net_profit", "operating_cash_flow", "roe"),
        ("official_disclosure", "akshare", "baostock"), "pending", False,
    ),
    DimensionSpec(
        "2_kline", "技术走势", "量价", "OHLCV、趋势与常用技术指标。",
        ("trade_date", "open", "high", "low", "close", "volume", "rsi14", "macd"),
        ("market.db", "market.adapters"), "local", True,
    ),
    DimensionSpec(
        "3_macro", "宏观环境", "外部环境", "利率、汇率、商品与增长环境。",
        ("observed_at", "rates", "fx", "commodities", "growth"),
        ("official_disclosure", "intel.mcp", "web.search"), "pending", False,
    ),
    DimensionSpec(
        "4_peers", "同行比较", "基本面", "同行宇宙、估值和经营指标比较。",
        ("peer_code", "industry", "pe", "pb", "rank"),
        ("market.db", "akshare", "official_disclosure"), "pending", False,
    ),
    DimensionSpec(
        "5_chain", "产业链", "基本面", "主营拆分、上下游与客户集中度。",
        ("business_segment", "upstream", "downstream", "customer_concentration"),
        ("official_disclosure", "akshare", "intel.mcp"), "pending", False,
    ),
    DimensionSpec(
        "6_fund_holders", "基金持仓", "资金", "基金持仓、机构行为与基金表现。",
        ("fund_code", "holder_ratio", "fund_manager", "as_of"),
        ("akshare", "official_disclosure"), "pending", False,
    ),
    DimensionSpec(
        "6_research", "卖方研究", "基本面", "研报覆盖、评级与目标价快照。",
        ("report_id", "rating", "target_price", "published_at"),
        ("official_disclosure", "akshare"), "pending", False,
    ),
    DimensionSpec(
        "7_industry", "行业景气", "基本面", "行业增速、渗透率与行业估值。",
        ("industry", "growth", "tam", "penetration", "industry_pe"),
        ("official_disclosure", "akshare", "intel.mcp"), "pending", False,
    ),
    DimensionSpec(
        "8_materials", "原材料", "产业链", "关键材料价格趋势与成本暴露。",
        ("material", "price", "price_change", "cost_ratio", "as_of"),
        ("market.adapters", "akshare", "official_disclosure"), "pending", False,
    ),
    DimensionSpec(
        "9_futures", "关联期货", "产业链", "关联合约、价格趋势与库存。",
        ("contract", "close", "inventory", "as_of"),
        ("market.adapters", "akshare", "official_disclosure"), "pending", False,
    ),
    DimensionSpec(
        "10_valuation", "估值", "基本面", "估值水平、历史分位与现金流估值。",
        ("pe", "pb", "percentile_5y", "fcf", "discount_rate"),
        ("official_disclosure", "akshare"), "pending", False,
    ),
    DimensionSpec(
        "11_governance", "公司治理", "基本面", "质押、董监高变动与治理事件。",
        ("pledge_ratio", "insider_trade", "management_change", "published_at"),
        ("official_disclosure", "akshare"), "pending", False,
    ),
    DimensionSpec(
        "12_capital_flow", "资金流", "资金", "资金流、融资融券、股东与解禁。",
        ("northbound", "margin", "capital_flow", "unlock", "as_of"),
        ("market.adapters", "akshare", "official_disclosure"), "partial", True,
    ),
    DimensionSpec(
        "13_policy", "政策", "外部环境", "政策方向、监管与补贴信息。",
        ("policy_id", "topic", "direction", "published_at", "source_url"),
        ("official_disclosure", "intel.mcp", "web.search"), "pending", False,
    ),
    DimensionSpec(
        "14_moat", "竞争壁垒", "基本面", "无形资产、转换成本、网络与规模优势。",
        ("intangible_assets", "switching_cost", "network_effect", "evidence"),
        ("official_disclosure", "intel.mcp"), "pending", False,
    ),
    DimensionSpec(
        "15_events", "事件公告", "事件", "公告、新闻、催化剂与风险时间线。",
        ("event_id", "event_type", "published_at", "title", "source_url"),
        ("official_disclosure", "intel.mcp", "akshare"), "pending", False,
    ),
    DimensionSpec(
        "16_lhb", "龙虎榜", "资金", "龙虎榜明细、席位和机构游资对比。",
        ("trade_date", "buy_amount", "sell_amount", "seat", "institution"),
        ("akshare", "official_disclosure"), "pending", True,
    ),
    DimensionSpec(
        "17_sentiment", "市场情绪", "外部环境", "平台热度、情绪温度与提及。",
        ("platform", "mentions", "positive_ratio", "temperature", "observed_at"),
        ("intel.mcp", "web.search"), "pending", False,
    ),
    DimensionSpec(
        "18_trap", "风险陷阱", "风险", "公告、量价和舆情驱动的风险提示。",
        ("risk_flags", "risk_score", "trigger_evidence", "as_of"),
        ("official_disclosure", "market.db", "intel.mcp"), "pending", False,
    ),
    DimensionSpec(
        "19_contests", "组合与赛道", "外部环境", "公开组合、社区提及与模拟赛。",
        ("portfolio_id", "mention", "return", "observed_at", "source_url"),
        ("intel.mcp", "web.search"), "pending", False,
    ),
)

_BY_KEY = {item.key: item for item in DIMENSION_SPECS}


def list_dimension_specs() -> list[DimensionSpec]:
    """返回稳定顺序的目录副本。"""
    return list(DIMENSION_SPECS)


def get_dimension_spec(key: str) -> DimensionSpec:
    """按 UZI 兼容 key 取目录项。"""
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"未知研究维度：{key}") from exc

