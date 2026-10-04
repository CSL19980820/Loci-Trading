"""策略执行能力；未声明的引擎保持严格、不可推测的默认值。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionProfile:
    """pure/causal 覆盖全部信号与因子，而不只是最后一天的选中代码。

    ``finite`` 的 lookback_bars 是含当前根的依赖长度；``sensitive`` 表示
    计算必须保留原始历史起点，不能由它推断该策略应改读全历史。
    ``causal_from`` 限定因果承诺的最早日期；种子/锚点之前的结果不能据此复用。
    pure 只承诺相同输入下计算可复用，不等于截断后仍可复用。
    股票轴、复权锚点与每日股票池仍由执行编排保持原有语义。
    """

    pure: bool = False
    column_mode: str = "coupled"
    origin: str = "unknown"
    lookback_bars: int | None = None
    metadata_fields: tuple[str, ...] = ()
    causal: bool = False
    causal_from: str | None = None
