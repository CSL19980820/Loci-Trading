"""选股结果的末尾版本复核。

`data_snapshot` 里的 `market_revision` 是**取证那一刻**的水位。选股要跑几十秒到
十几分钟，期间如果有人写了行情库（同步撞车、spot 刷新），结果就是半新半旧的
数据算出来的，而旧实现里**没有任何痕迹**能看出来。

这个文件钉住三件事：一致时不加字段（不污染现有契约）、不一致时显式标出、
复核本身失败不许拖垮已经算完的结果。
"""
from __future__ import annotations

from typing import Any

from src.strategy.application.screener import _seal_snapshot


class _Store:
    """只提供 market_revision 的最小替身。"""

    def __init__(self, revision: str | Exception) -> None:
        self._revision = revision

    def market_revision(self) -> str:
        if isinstance(self._revision, Exception):
            raise self._revision
        return self._revision


def test_same_revision_leaves_the_snapshot_untouched() -> None:
    snapshot: dict[str, Any] = {"market_revision": "42", "rows": 100}
    out = _seal_snapshot(_Store("42"), snapshot)
    assert out == snapshot
    assert "revision_changed_during_run" not in out


def test_changed_revision_is_marked_with_both_ends() -> None:
    out = _seal_snapshot(_Store("43"), {"market_revision": "42", "rows": 100})
    assert out["revision_changed_during_run"] is True
    assert out["market_revision"] == "42"
    assert out["market_revision_end"] == "43"
    assert out["rows"] == 100


def test_snapshot_without_a_revision_is_passed_through() -> None:
    """调用方传进来的快照可能根本没有版本号（旧契约），不能因此报错。"""
    snapshot: dict[str, Any] = {"rows": 1}
    assert _seal_snapshot(_Store("9"), snapshot) == snapshot


def test_a_failing_recheck_never_takes_down_a_finished_run() -> None:
    """库已经不可读时，选股结果照样要交出去——缺这个字段等于「没复核」。"""
    snapshot: dict[str, Any] = {"market_revision": "42", "rows": 100}
    out = _seal_snapshot(_Store(RuntimeError("disk I/O error")), snapshot)
    assert out == snapshot
