"""严格 JSON 归一：非有限浮点收敛成 null。

回测与研究的产物要写进 run card 并做 sha256 自校验，而 ``Infinity`` / ``NaN``
不是合法 JSON，落库前必须先收敛。这段逻辑此前在 ``backtest`` 的三个
``research_*`` 模块与 ``research`` 的 ``backtest_support`` 里各抄了一份，四份
逐行等价，只有变量名和 dict/Mapping 的判定宽窄不同。

**不包括** ``research/application/snapshot.py`` 的同名私有函数：那份还要处理
pandas / numpy 标量与 datetime，是另一件事，不要顺手合过来。
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


def jsonable(value: Any) -> Any:
    """dict / list 递归归一；非有限浮点转 None，其余原样返回。"""
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        return None
    return value
