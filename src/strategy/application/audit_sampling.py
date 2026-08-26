"""大宇宙动态前视探测的面板列分片。

全市场 5000+ 列一次性跑截断一致性会拖死回测/尾盘选股，但不能只抽 hash 前
40 列——后半段漏检会产生假阴性。

热路径（``guard_strategy``）：列数 <= ``FULL_UNIVERSE_THRESHOLD`` 时全列；
否则按 ``LOCI_AUDIT_PANEL_SAMPLE_SIZE``（默认 200，上限 500）分片，每片独立
跑截断一致性，任一片 block 即 fail-closed，覆盖全部列。

``sample_panel_columns`` / ``prepare_guard_panels`` 仍供测试与诊断复用分层抽样。
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from typing import Any, Mapping, Sequence

import pandas as pd

FULL_UNIVERSE_THRESHOLD = 100
DEFAULT_AUDIT_PANEL_SAMPLE_SIZE = 200
MAX_AUDIT_PANEL_SAMPLE_SIZE = 500
_ENV_AUDIT_PANEL_SAMPLE_SIZE = "LOCI_AUDIT_PANEL_SAMPLE_SIZE"


def resolve_audit_panel_sample_size() -> int:
    """读取环境变量 ``LOCI_AUDIT_PANEL_SAMPLE_SIZE``，非法值回退默认。"""
    raw = os.environ.get(_ENV_AUDIT_PANEL_SAMPLE_SIZE, str(DEFAULT_AUDIT_PANEL_SAMPLE_SIZE))
    try:
        size = int(raw)
    except (TypeError, ValueError):
        size = DEFAULT_AUDIT_PANEL_SAMPLE_SIZE
    return max(1, min(size, MAX_AUDIT_PANEL_SAMPLE_SIZE))


def sample_panel_columns(
    columns: Sequence[Any],
    *,
    sample_size: int | None = None,
    full_threshold: int = FULL_UNIVERSE_THRESHOLD,
) -> list[Any]:
    """为动态前视探测挑选列子集。

    - 小宇宙：原样返回全部列。
    - 大宇宙：边界锚点 + hash 分散，总数不超过 ``sample_size``。
    """
    cols = list(columns)
    total = len(cols)
    if total <= full_threshold:
        return cols

    target = min(sample_size or resolve_audit_panel_sample_size(), total)
    anchors: list[Any] = []
    seen: set[Any] = set()

    def _add(col: Any) -> None:
        if col not in seen:
            anchors.append(col)
            seen.add(col)

    if total >= 1:
        _add(cols[0])
        _add(cols[-1])
    if total >= 3:
        _add(cols[total // 2])
    if total >= 5:
        _add(cols[total // 4])
        _add(cols[(3 * total) // 4])

    remaining = target - len(anchors)
    if remaining > 0:
        pool = [col for col in cols if col not in seen]
        hash_sorted = sorted(
            pool,
            key=lambda col: hashlib.md5(str(col).encode("utf-8")).hexdigest(),
        )
        for col in hash_sorted[:remaining]:
            _add(col)

    # 保持原面板列序，便于 diff 与调试
    anchor_set = set(anchors)
    return [col for col in cols if col in anchor_set]


def _subset_panel_columns(
    panels: Mapping[str, Any],
    columns: set[Any],
) -> dict[str, Any]:
    subset: dict[str, Any] = {}
    for key, value in panels.items():
        if isinstance(value, pd.DataFrame) and not value.empty:
            keep = [col for col in value.columns if col in columns]
            subset[key] = value.loc[:, keep] if keep else value
        else:
            subset[key] = value
    return subset


def iter_guard_panel_shards(
    panels: Mapping[str, Any],
    *,
    shard_size: int | None = None,
    reference_field: str = "close",
) -> Iterator[dict[str, Any]]:
    """按列分片 yield 面板子集，合并后覆盖 reference 的全部列。"""
    reference = panels.get(reference_field)
    if not isinstance(reference, pd.DataFrame) or reference.empty:
        yield dict(panels)
        return

    cols = list(reference.columns)
    if len(cols) <= FULL_UNIVERSE_THRESHOLD:
        yield _subset_panel_columns(panels, set(cols))
        return

    chunk = shard_size or resolve_audit_panel_sample_size()
    for start in range(0, len(cols), chunk):
        yield _subset_panel_columns(panels, set(cols[start : start + chunk]))


def prepare_guard_panels(
    panels: Mapping[str, Any],
    *,
    sample_size: int | None = None,
    reference_field: str = "close",
) -> dict[str, Any]:
    """按抽样策略裁剪 DataFrame 面板，供 ``guard_strategy`` 动态截断探测。"""
    reference = panels.get(reference_field)
    if not isinstance(reference, pd.DataFrame) or reference.empty:
        return dict(panels)

    sample_cols = sample_panel_columns(
        list(reference.columns),
        sample_size=sample_size,
    )
    if len(sample_cols) >= reference.shape[1]:
        return dict(panels)

    sample_set = set(sample_cols)
    guard_panels: dict[str, Any] = {}
    for key, value in panels.items():
        if isinstance(value, pd.DataFrame) and not value.empty:
            keep = [col for col in value.columns if col in sample_set]
            guard_panels[key] = value.loc[:, keep] if keep else value
        else:
            guard_panels[key] = value
    return guard_panels
