"""P0-2：guard_strategy 挂热路径；open + 裸用盘中字段 fail-closed。"""
from __future__ import annotations

import pytest

from src.strategy.application.audit import LookAheadError, audit_source, guard_strategy


class _OpenBareCloseEngine:
    slug = "bad-open-close"
    entry_timing = "open"
    name = "坏策略"

    def min_bars(self) -> int:
        return 30

    def required_fields(self) -> tuple[str, ...]:
        return ("close",)

    def compute(self, panels, params=None):  # noqa: ANN001
        # 故意裸用当日 close，供 AST 静态审计命中
        close = panels["close"]
        return close


_BAD_SOURCE = '''
class BadOpen:
    entry_timing = "open"
    def compute(self, panels, params=None):
        close = panels["close"]
        return close
'''


def test_audit_source_blocks_open_bare_close() -> None:
    report = audit_source(_BAD_SOURCE, entry_timing="open", strategy="bad")
    assert report.failed
    assert any(f.check == "intraday_field" for f in report.findings)


def test_guard_strategy_raises_on_static_block() -> None:
    with pytest.raises(LookAheadError):
        guard_strategy(_OpenBareCloseEngine())
