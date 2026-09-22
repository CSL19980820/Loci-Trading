"""Bounded, revisable research memory; never an execution policy."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_EXPERIENCES = 8
MAX_EXPERIENCE_CHARACTERS = 1600
STATUS_LABELS = {"proposed": "待验证", "supported": "有证据支持", "refuted": "已反证",
                 "inconclusive": "尚无定论", "corrected": "已纠正"}


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,23}$")
    hypothesis: str = Field(min_length=1, max_length=600)
    validation_plan: str = Field(min_length=1, max_length=600)
    status: Literal["proposed", "supported", "refuted", "inconclusive", "corrected"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


def experience_text(items: list[dict]) -> str:
    """This exact string is the memory port sent to the model, including references."""
    if not items:
        return ""
    lines = ["经验沉淀（研究参考，可修订或忽略，不是交易指令；待验证不等于已证实）："]
    for item in items:
        lines.append(f"[{item['id']}·{STATUS_LABELS[item['status']]}] {item['hypothesis']}\n"
                     f"验证：{item['validation_plan']}\n证据：{'、'.join(item['evidence_ids']) or '待补充'}")
    return "\n".join(lines)


def validate_experience(items: list[dict]) -> list[dict]:
    if len(items) > MAX_EXPERIENCES:
        raise ValueError(f"经验沉淀最多{MAX_EXPERIENCES}条，请合并、取舍，不截断句子")
    normalized = [ExperienceEntry.model_validate(item).model_dump() for item in items]
    if len({item['id'] for item in normalized}) != len(normalized):
        raise ValueError("经验编号不能重复；修订已有经验沿用原编号")
    if len(experience_text(normalized)) > MAX_EXPERIENCE_CHARACTERS:
        raise ValueError(f"经验沉淀含状态、编号和证据引用合计最多{MAX_EXPERIENCE_CHARACTERS}字符，请精炼后重新输出")
    return normalized
