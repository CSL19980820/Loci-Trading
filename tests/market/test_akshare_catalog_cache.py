"""AkShare 目录读路径：进程内缓存 + 样例参数只算一次。

背景（这两条都出过问题）：
- `GET /api/market/akshare/catalog` 与 `/sources` 曾绕开 `catalog_entries()`
  的进程内缓存，**每个请求**把 `vars(akshare)` 全量反射一遍（约 400 个
  `inspect.signature` / `getdoc` / docstring 解析）。
- `_capability_entry` 里 `default_params` 与 `_parameter_descriptions`
  各算一次 `_sample_params`，同一条能力算了两遍。

发现/探测本身的用例在 `test_akshare_catalog.py` / `test_akshare_probe.py`。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import src.market.infrastructure.akshare_catalog as catalog_module
from src.market.application.akshare import discover_stock_capabilities
from src.market.infrastructure.akshare_tools import clear_catalog_cache


def _fake_akshare() -> SimpleNamespace:
    """两个够真的 `stock_*` 导出：一个带日期窗口，一个只有默认值。"""

    def stock_alpha(symbol: str, start_date: str = "19700101") -> list[dict[str, str]]:
        """Alpha source."""
        return [{"symbol": symbol, "start_date": start_date}]

    def stock_beta(limit: int = 3) -> list[int]:
        """Beta source."""
        return list(range(limit))

    stock_alpha.__module__ = "akshare.stock.feature"
    stock_beta.__module__ = "akshare.stock.feature"
    return SimpleNamespace(stock_alpha=stock_alpha, stock_beta=stock_beta)


@pytest.fixture()
def clean_cache():
    """缓存是模块级全局，前后都清，别让相邻用例互相污染。"""
    clear_catalog_cache()
    yield
    clear_catalog_cache()


@pytest.fixture()
def reflections(clean_cache) -> list[str]:
    """替掉默认解析源（不 import 真 akshare），并记录反射了几次。"""
    namespace = dict(vars(_fake_akshare()))
    calls: list[str] = []

    def _resolve(resolver: Any = None) -> dict[str, Any]:
        calls.append("resolve")
        return dict(namespace)

    with patch.object(catalog_module, "_resolve_source", _resolve):
        yield calls


def test_second_read_serves_cache_without_reflecting_again(reflections: list[str]) -> None:
    first = discover_stock_capabilities()
    second = discover_stock_capabilities()

    assert [entry["name"] for entry in first] == ["stock_alpha", "stock_beta"]
    assert reflections == ["resolve"], "第二次读路径不该重做 vars(akshare) 反射"
    assert first is second


def test_clear_catalog_cache_forces_fresh_reflection(reflections: list[str]) -> None:
    """换了 akshare 版本靠既有的 clear_catalog_cache() 失效，不另造机制。"""
    discover_stock_capabilities()
    clear_catalog_cache()
    discover_stock_capabilities()

    assert len(reflections) == 2


def test_sample_params_runs_once_per_capability(reflections: list[str]) -> None:
    with patch.object(
        catalog_module, "_sample_params", wraps=catalog_module._sample_params
    ) as sample_params:
        entries = discover_stock_capabilities()

    assert len(entries) == 2
    assert sample_params.call_count == 2, "每条能力只该取样一次，别算两遍"


def test_shared_samples_keep_default_params_and_parameter_samples_aligned(
    reflections: list[str],
) -> None:
    """共用一份样例后，两个字段仍必须同源，且安全日期窗口照旧生效。"""
    alpha, beta = discover_stock_capabilities()

    for entry in (alpha, beta):
        defaults = entry["default_params"]
        for parameter in entry["parameters"]:
            assert parameter["sample"] == defaults.get(parameter["name"])

    assert alpha["default_params"]["symbol"] == "600519"
    assert alpha["default_params"]["start_date"] != "19700101"
    assert beta["default_params"] == {"limit": 3}
