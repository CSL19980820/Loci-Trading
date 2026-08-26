"""HTTP 请求模型的共用基类。

放 `src/shared` 而不是组合根：各限界上下文的 `api/schemas.py` 都要用它，
从组合根取会让「上下文 → 组合根」这条反向依赖一直存在。这里只有校验策略，
不含任何业务规则。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuantModel(BaseModel):
    """与账本写入同样的严格校验：多一个字段就 422，不静默忽略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UniverseSpecModel(QuantModel):
    """选股/回测股票池。未传时后端按 default_a_share（剔 ST、默认不含北交）。"""

    preset: str | None = Field(default="default_a_share", max_length=64)
    boards: list[Literal["main", "chi_next", "star", "bse"]] | None = None
    exclude_st: bool | None = None
    exclude_delisting: bool | None = None
    exclude_suspended: bool | None = None
    min_list_days: int | None = Field(default=None, ge=0, le=5000)
    industries_include: list[str] | None = None
    industries_exclude: list[str] | None = None
    codes_include: list[str] | None = None
    codes_exclude: list[str] | None = None
