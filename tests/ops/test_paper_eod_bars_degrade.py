"""日终回看取数的降级路径。

``_lookback_panels`` 的 except 分支原来引用了一个模块里根本没定义的 ``logger``，
于是「面板批量取数失败就退回逐票 history」这条降级路径一执行就 NameError，
把一次可恢复的查询失败升级成整个日终回看任务崩溃。ruff 的 F821 抓到了它。
这个文件钉住降级本身能跑通。
"""
from __future__ import annotations

from typing import Any

import pytest

from src.ops.application.paper_eod_bars import _lookback_panels


class _ExplodingMarket:
    """有 load_panel 但一调就炸——真实场景是 SQLite disk I/O error / 库被占。"""

    def load_panel(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("market.db is locked")


class _NoPanelMarket:
    """老版本的行情仓没有批量接口。"""


def test_panel_failure_degrades_instead_of_raising(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        out = _lookback_panels(_ExplodingMarket(), ["600000"], start="2026-08-01", end="2026-08-27")
    assert out is None
    assert any("load_panel" in record.message for record in caplog.records)


def test_missing_batch_api_or_empty_codes_returns_none() -> None:
    assert _lookback_panels(_NoPanelMarket(), ["600000"], start="2026-08-01", end="2026-08-27") is None
    assert _lookback_panels(_ExplodingMarket(), [], start="2026-08-01", end="2026-08-27") is None
