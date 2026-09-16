"""冻结输入产物的体积契约与往返一致性。

冻结产物是研究回测的证据本体：主 run、对照组、train/OOS 都只吃这一份切片，
replay 还要按 hash 逐字节核对。所以两件事必须钉死：

1. **序列化是确定性的**——同一份输入永远得到同一串字节，否则 hash 自校验会
   随机失败。
2. **执行面板与信号面板同源时不重复写**——JSON 没有引用机制，重复的是实打实
   的几十 MB 文本；解码侧必须能把 null 还原回 panels。
"""
from __future__ import annotations

import json
import tracemalloc

import numpy as np
import pandas as pd
import pytest

from src.research.application.frozen import (
    CONTRACT_VERSION,
    _panel_payload,
    build_frozen_payload,
    payload_bytes,
)


def _panel(values: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(values, index=["2026-08-10", "2026-08-11"], columns=["600000", "600001"])


class _Engine:
    slug = "qianlong"
    entry_timing = "close"
    strategy_revision = "test-rev"


class _Resolved:
    codes = ["600000", "600001"]
    spec = {"preset": "test"}
    meta = {"600000": {"name": "甲"}}

    class funnel:  # noqa: N801
        @staticmethod
        def to_dict() -> dict[str, object]:
            return {}


def _context(*, separate_execution: bool) -> dict[str, object]:
    panels = {
        "close": _panel([[10.0, 20.0], [11.0, float("nan")]]),
        "open": _panel([[9.5, 19.5], [10.5, 20.5]]),
    }
    context: dict[str, object] = {
        "engine": _Engine(),
        "resolved": _Resolved(),
        "resolved_params": {},
        "signals": _panel([[1.0, 0.0], [0.0, 1.0]]),
        "panels": panels,
        "fields": ("close", "open"),
    }
    if separate_execution:
        context["execution_panels"] = {
            name: frame * 2.0 for name, frame in panels.items()
        }
    return context


def test_contract_is_v2() -> None:
    assert CONTRACT_VERSION == "research-frozen-input-v2"


def test_execution_same_as_panels_is_not_written_twice() -> None:
    payload = build_frozen_payload(_context(separate_execution=False))
    assert payload["execution_panels"] is None, "同源执行面板不应重复落盘"
    assert set(payload["panels"]) == {"close", "open"}


def test_separate_execution_panels_are_written_in_full() -> None:
    payload = build_frozen_payload(_context(separate_execution=True))
    assert payload["execution_panels"] is not None
    assert payload["execution_panels"]["close"] != payload["panels"]["close"]


def test_serialization_is_deterministic() -> None:
    """同一份输入两次序列化必须逐字节相同，否则 hash 自校验会随机失败。"""
    first = payload_bytes(build_frozen_payload(_context(separate_execution=False)))
    second = payload_bytes(build_frozen_payload(_context(separate_execution=False)))
    assert first == second


def test_large_unicode_payload_keeps_v2_bytes_with_bounded_encoding_memory() -> None:
    # 输入和旧版期望值在计量前构造，只计序列化本身的额外分配。
    payload = {"价格": [float(i) / 100 for i in range(100_000)], "说明": "真实行情😀\n"}
    expected = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    tracemalloc.start()
    try:
        actual = payload_bytes(payload)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < len(expected) * 4, "编码不可同时物化完整宽Unicode文本及其副本"


def test_serialization_has_no_indent_padding() -> None:
    """v2 用紧凑分隔符：真实行情价格很短，indent 的空白会占掉近一半体积。"""
    raw = payload_bytes(build_frozen_payload(_context(separate_execution=False)))
    text = raw.decode("utf-8")
    assert '": ' not in text and ",\n" not in text
    assert json.loads(text)["contract_version"] == CONTRACT_VERSION


def test_nan_becomes_null_not_a_bare_nan() -> None:
    """allow_nan=False：NaN 必须已经在编码阶段收敛成 None，否则直接抛错。"""
    payload = build_frozen_payload(_context(separate_execution=False))
    assert payload["panels"]["close"]["values"][1][1] is None
    payload_bytes(payload)  # 不抛 ValueError 即说明没有裸 NaN


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"a": [1.5, float("nan")]}, index=["d1", "d2"]),
        pd.DataFrame({"a": ["x", None]}, index=["d1", "d2"]),
    ],
)
def test_panel_payload_shapes_survive_both_dtypes(frame: pd.DataFrame) -> None:
    """浮点走快路径、非浮点走兜底，两条路的形状与缺失值语义必须一致。"""
    payload = _panel_payload(frame)
    assert payload["index"] == ["d1", "d2"]
    assert payload["columns"] == ["a"]
    assert payload["values"][1][0] is None


def test_float_fast_path_matches_cell_by_cell_encoding() -> None:
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(np.round(rng.normal(20, 3, (40, 25)), 2))
    frame.iloc[::7, ::5] = np.nan
    slow = [
        [None if value is None else value for value in row]
        for row in frame.astype(object).where(pd.notna(frame), None).values.tolist()
    ]
    assert _panel_payload(frame)["values"] == slow
