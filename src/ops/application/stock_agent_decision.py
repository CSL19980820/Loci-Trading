"""独立智能体决策与持续修订的研究计划。"""
from pydantic import Field

from src.ops.application.guardian_decision import GuardianDecision, parse_decision


class StockAgentDecision(GuardianDecision):
    close_keep_codes: list[str] | None = Field(default=None,
        description="仅在用户设置常态持仓上限且临时超配时需要，明确收盘留仓并包含全部T+1锁定股票。")
    research_plan: str | None = Field(default=None,
        description="精炼的工作记忆：有效假设、必要依据引用、仍有效的参与/降级/退出条件与待验证问题；不重复summary或写研究流水。更新须保留仍有效的必要条件，null沿用，空字符串清空。")


def parse_stock_agent_decision(text: str, *, require_execution_terms: bool = False) -> StockAgentDecision:
    return parse_decision(text, require_execution_terms=require_execution_terms, decision_type=StockAgentDecision)
