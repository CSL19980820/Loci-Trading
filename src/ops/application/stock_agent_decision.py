"""独立智能体决策与持续修订的研究计划。"""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.ops.application.falcon_learning import FalconLearning
from src.ops.application.guardian_decision import (
    GuardianDecision,
    normalize_stock_code,
    parse_decision,
)


class StockAssessment(BaseModel):
    """每股本轮结论；研究判断不代表提交意图或成交。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    code: str = Field(pattern=r"^\d{6}$")
    stance: Literal["participate", "wait", "avoid", "exit", "unreviewed"]
    summary: str = Field(min_length=1, max_length=120)
    expected_entry_price: float | None = Field(default=None, gt=0, strict=True, description="有实际依据的预期进场参考价，单位元；不是成交价或自动挂单")
    focus: bool = False
    data_status: Literal["available", "partial", "missing"] = "partial"
    evidence_refs: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(default_factory=list, max_length=8)

    @field_validator("code", mode="before")
    @classmethod
    def plain_code(cls, value: Any) -> Any:
        return normalize_stock_code(value)

    @model_validator(mode="after")
    def unreviewed_has_no_target(self) -> "StockAssessment":
        if self.stance == "unreviewed" and (self.expected_entry_price is not None or self.focus):
            raise ValueError("未复核对象不能宣称重点研究或提供进场参考价")
        return self


class StockResearchPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=r"^\d{6}$")
    entry_condition: str = Field(default="", max_length=160)
    exit_condition: str = Field(default="", max_length=160)
    invalidation: str = Field(default="", max_length=120)
    next_check: str = Field(default="", max_length=100)

    @field_validator("code", mode="before")
    @classmethod
    def plain_code(cls, value: Any) -> Any:
        return normalize_stock_code(value)


class StockResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    market_view: str = Field(default="", max_length=160)
    next_trade_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    stocks: list[StockResearchPlanItem] = Field(default_factory=list)


class StockResearchDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    market_summary: str = Field(default="", max_length=200)
    changes: str = Field(default="", max_length=240)
    next_steps: str = Field(default="", max_length=160)


class StockAgentDecision(GuardianDecision):
    close_keep_codes: list[str] | None = Field(default=None,
        description="仅在用户设置常态持仓上限且临时超配时需要，明确收盘留仓并包含全部T+1锁定股票。")
    research_plan: str | None = Field(default=None,
        description="精炼的工作记忆：有效假设、必要依据引用、仍有效的参与/降级/退出条件与待验证问题；不重复summary或写研究流水。更新须保留仍有效的必要条件，null沿用，空字符串清空。")
    assessments: list[StockAssessment] = Field(default_factory=list,
        description="逐股复核观察池与持仓，各股一句结论；focus仅表示重点研究，未复核用unreviewed如实注明")
    research_plan_structured: StockResearchPlan | None = Field(default=None,
        description="简洁的下一轮工作计划；日期只使用authority_calendar的next_trade_date，null沿用旧计划")
    detail: StockResearchDetail | None = Field(default=None, description="本轮短日记：市场结论、重要变化、下一步；不重复每股评估")
    learning: FalconLearning | None = Field(default=None,
        description="仅猎隼日/周复盘使用的增量经验与选股/判分优化建议；null或空列表沿用旧记忆，不授权修改策略。")

    @field_validator("close_keep_codes", mode="before")
    @classmethod
    def plain_codes(cls, value: Any) -> Any:
        return [normalize_stock_code(item) for item in value] if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_research_codes(self) -> "StockAgentDecision":
        for items in (self.assessments, self.research_plan_structured.stocks if self.research_plan_structured else []):
            if len({item.code for item in items}) != len(items):
                raise ValueError("每股评估或计划中同一股票不能重复")
        return self


def parse_stock_agent_decision(text: str, *, require_execution_terms: bool = False) -> StockAgentDecision:
    return parse_decision(text, require_execution_terms=require_execution_terms, decision_type=StockAgentDecision)
