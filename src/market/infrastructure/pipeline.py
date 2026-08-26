"""共享归一管线：原始表 → 仓内出口契约。

fetcher 只负责取原始报文；列映射、数值化、单位换算、缺列质检只走这里。
放在 infrastructure 根下，避免 sources ↔ adapters 循环依赖。
"""
from __future__ import annotations

import pandas as pd

from src.market.domain.source_contract import LaneContract, Unit


class NormalizeError(RuntimeError):
    """归一失败。adapter 包装为 AdapterError，source 包装为 SourceError。"""


def normalize(
    raw: pd.DataFrame | None,
    contract: LaneContract,
    *,
    who: str,
    empty_label: str | None = None,
) -> pd.DataFrame:
    """按契约归一：rename → 数值化 → 单位换算 → 缺列校验 → 选列。"""
    label = empty_label or f"{who}数据"
    if raw is None or raw.empty:
        raise NormalizeError(f"{label}为空")

    out = raw.copy()
    source_used: dict[str, str] = {}

    for field in contract.fields:
        source = _first_present(out, field.sources)
        if source is None:
            continue
        if field.target in source_used:
            continue
        if source == field.target:
            source_used[field.target] = source
            continue
        if field.target in out.columns:
            # 目标列已在（仓内口径），保留它；并列中文源列不覆盖、不二次换算。
            source_used[field.target] = field.target
            continue
        out = out.rename(columns={source: field.target})
        source_used[field.target] = source

    for field in contract.fields:
        if field.target not in out.columns:
            continue
        if field.numeric:
            out[field.target] = pd.to_numeric(out[field.target], errors="coerce")
        source = source_used.get(field.target, field.target)
        unit = field.unit_for(source)
        if unit == Unit.LOTS_TO_SHARES:
            out[field.target] = out[field.target] * 100.0
        elif unit == Unit.PERCENT_TO_RATIO:
            out[field.target] = out[field.target] / 100.0
        elif unit == Unit.RATIO_TO_PERCENT:
            # 反方向：源给小数（新浪 changeratio=0.0245），仓内这列统一百分数。
            # 东财同一列给的就是 2.45，两家混进同一列差 100 倍且不会报错，
            # 所以口径转换只能在契约声明处做，不许留给调用方各自判断。
            out[field.target] = out[field.target] * 100.0

    missing = [name for name in contract.required_columns() if name not in out.columns]
    if missing:
        raise NormalizeError(f"{who}缺列：{missing}")

    if contract.keep_unmapped:
        return out.reset_index(drop=True)

    keep = [name for name in contract.output_columns() if name in out.columns]
    return out[keep].reset_index(drop=True)


def empty_spot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["code", "date", "open", "high", "low", "close", "volume", "amount"]
    )


def _first_present(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in frame.columns:
            return name
    return None
