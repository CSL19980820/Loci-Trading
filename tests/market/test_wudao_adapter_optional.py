from __future__ import annotations

import pytest

from src.market.infrastructure.adapters import registry
from src.market.infrastructure.adapters.types import LANE_HIST_DAILY


@pytest.fixture(autouse=True)
def _reset_market_registry() -> None:
    registry.reset_registry()
    yield
    registry.reset_registry()


def test_wudao_runtime_availability_is_rechecked_without_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """悟道运行中启用、停用后，行情路由不能继续使用首次启动时的旧判断。"""
    available = False
    monkeypatch.setattr(registry, "wudao_adapter_enabled", lambda: available)

    assert "wudao" not in registry.enabled_adapter_ids(LANE_HIST_DAILY, config={})

    available = True
    assert "wudao" in registry.enabled_adapter_ids(LANE_HIST_DAILY, config={})

    available = False
    assert "wudao" not in registry.enabled_adapter_ids(LANE_HIST_DAILY, config={})


def test_wudao_stays_off_public_catalog_even_when_routing_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """数据源目录只露一张悟道 MCP；日 K 旁路可进路由但不单独占牌。"""
    monkeypatch.setattr(registry, "wudao_adapter_enabled", lambda: True)
    assert "wudao" in registry.enabled_adapter_ids(LANE_HIST_DAILY, config={})
    assert "wudao" not in {item["id"] for item in registry.list_catalog()}
