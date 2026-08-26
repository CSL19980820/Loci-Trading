"""akshare 能力目录发现：导出筛选、docstring 解析与列名注解。

探针执行用例在 `test_akshare_probe.py`。
"""
from __future__ import annotations

from functools import lru_cache
import json
from types import SimpleNamespace

import pandas as pd

from src.market.infrastructure.akshare_catalog import (
    discover_stock_capabilities,
    probe_stock_capability,
)
from src.market.infrastructure.akshare_catalog_meta import MAX_DOC_SECTION_LENGTH
from src.market.infrastructure.akshare_probe_result import MAX_RESULT_COLUMNS


def _stock_catalog(*targets: object) -> SimpleNamespace:
    return SimpleNamespace(**{target.__name__: target for target in targets})


def test_discovery_keeps_real_callable_stock_exports_sorted_and_described() -> None:
    def stock_zeta(symbol: str, date: str) -> list[dict[str, str]]:
        """Zeta source. More implementation detail."""
        return [{"symbol": symbol, "date": date}]

    def stock_alpha(limit: int = 3) -> list[int]:
        return list(range(limit))

    stock_zeta.__module__ = "akshare.stock.feature"
    stock_alpha.__module__ = "akshare.stock.feature"

    ignored = lambda: None
    ignored.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zeta, stock_alpha, ignored)

    entries = discover_stock_capabilities(catalog)

    assert [entry["name"] for entry in entries] == ["stock_alpha", "stock_zeta"]
    assert entries[1]["default_params"] == {"symbol": "600519", "date": "20250101"}
    assert entries[0]["module"] == "akshare.stock.feature"
    assert entries[1]["doc"] == "Zeta source. More implementation detail."
    assert entries[0]["status"] == "available"
    assert entries[0]["execution_mode"] == "disabled"


def test_discovery_parses_param_and_return_sections_from_the_full_docstring() -> None:
    def stock_zh_a_hist(symbol: str = "000001", period: str = "daily") -> list[dict[str, str]]:
        """东方财富网-行情首页-沪深京 A 股-每日行情

        https://quote.eastmoney.com/concept/sh603777.html
        :param symbol: 股票代码
            可通过 stock_zh_a_spot_em 获取
        :type symbol: str
        :param period: choice of {'daily', 'weekly', 'monthly'}
        :type period: str
        :return: 每日行情数据
        :rtype: pandas.DataFrame
        """
        return [{"symbol": symbol, "period": period}]

    stock_zh_a_hist.__module__ = "akshare.stock_feature.stock_hist_em"

    entry = discover_stock_capabilities(_stock_catalog(stock_zh_a_hist))[0]

    assert entry["param_docs"] == {
        "symbol": "股票代码 可通过 stock_zh_a_spot_em 获取",
        "period": "choice of {'daily', 'weekly', 'monthly'}",
    }
    assert entry["returns"] == "每日行情数据"
    json.dumps(entry)


def test_discovery_leaves_doc_sections_empty_when_upstream_omits_them() -> None:
    def stock_zh_a_spot_em() -> list[dict[str, str]]:
        """东方财富网-沪深京 A 股-实时行情"""
        return [{"代码": "600519"}]

    def stock_zh_a_undocumented() -> None:
        return None

    for target in (stock_zh_a_spot_em, stock_zh_a_undocumented):
        target.__module__ = "akshare.stock_feature.stock_hist_em"

    entries = discover_stock_capabilities(
        _stock_catalog(stock_zh_a_spot_em, stock_zh_a_undocumented)
    )

    assert [entry["param_docs"] for entry in entries] == [{}, {}]
    assert [entry["returns"] for entry in entries] == ["", ""]


def test_discovery_caps_a_runaway_param_description() -> None:
    def stock_zh_a_hist(symbol: str = "000001") -> None:
        return None

    stock_zh_a_hist.__doc__ = ":param symbol: " + "股" * 500 + "\n:return: " + "表" * 500
    stock_zh_a_hist.__module__ = "akshare.stock_feature.stock_hist_em"

    entry = discover_stock_capabilities(_stock_catalog(stock_zh_a_hist))[0]

    assert len(str(entry["param_docs"]["symbol"])) == MAX_DOC_SECTION_LENGTH
    assert len(str(entry["returns"])) == MAX_DOC_SECTION_LENGTH


def test_probe_columns_carry_a_chinese_english_gloss() -> None:
    def stock_zh_a_hist(symbol: str) -> pd.DataFrame:
        return pd.DataFrame({"日期": ["2026-01-05"], "成交额": [1.0], "融资余额": [2.0]})

    stock_zh_a_hist.__module__ = "akshare.stock.feature"

    result = probe_stock_capability(
        "stock_zh_a_hist", {"symbol": "600519"}, resolver=_stock_catalog(stock_zh_a_hist)
    )

    assert result["columns"] == ["日期", "成交额", "融资余额"]
    assert result["columns_detail"] == [
        {"raw": "日期", "cn": "日期", "en": "date"},
        {"raw": "成交额", "cn": "成交额", "en": "amount"},
        {"raw": "融资余额", "cn": "融资余额", "en": ""},
    ]
    json.dumps(result)


def test_probe_column_gloss_respects_the_column_cap_and_failure_path() -> None:
    def stock_zh_a_hist(fail: bool = False) -> pd.DataFrame:
        if fail:
            raise RuntimeError("provider down")
        return pd.DataFrame({f"列{index}": [index] for index in range(80)})

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)

    result = probe_stock_capability("stock_zh_a_hist", resolver=catalog)
    failed = probe_stock_capability("stock_zh_a_hist", {"fail": True}, resolver=catalog)

    assert len(result["columns"]) == MAX_RESULT_COLUMNS
    assert len(result["columns_detail"]) == MAX_RESULT_COLUMNS
    assert failed["columns_detail"] == []


def test_discovery_accepts_cached_callable_not_only_functions() -> None:
    @lru_cache
    def stock_zh_a_spot_em() -> list[dict[str, str]]:
        return [{"code": "600519"}]

    stock_zh_a_spot_em.__module__ = "akshare.stock.stock_zh_a_spot"

    entries = discover_stock_capabilities(_stock_catalog(stock_zh_a_spot_em))

    assert len(entries) == 1
    assert entries[0]["execution_mode"] == "on_demand"
    assert entries[0]["status"] == "available"


def test_discovery_describes_required_inputs_without_disabling_on_demand_capability() -> None:
    def stock_individual_notice_report(
        security: str, symbol: str = "全部", page: int = 1
    ) -> list[dict[str, str]]:
        return [{"security": security, "symbol": symbol, "page": str(page)}]

    stock_individual_notice_report.__module__ = "akshare.stock_fundamental.stock_notice"

    entry = discover_stock_capabilities(_stock_catalog(stock_individual_notice_report))[0]

    assert entry["execution_mode"] == "on_demand"
    assert entry["status"] == "needs_parameters"
    assert entry["default_params"] == {
        "security": "600519",
        "symbol": "全部",
        "page": 1,
    }
    assert entry["parameters"] == [
        {
            "name": "security",
            "required": True,
            "kind": "positional_or_keyword",
            "annotation": "str",
            "has_default": False,
            "default": None,
            "sample": "600519",
        },
        {
            "name": "symbol",
            "required": False,
            "kind": "positional_or_keyword",
            "annotation": "str",
            "has_default": True,
            "default": "全部",
            "sample": "全部",
        },
        {
            "name": "page",
            "required": False,
            "kind": "positional_or_keyword",
            "annotation": "int",
            "has_default": True,
            "default": 1,
            "sample": 1,
        },
    ]
    json.dumps(entry)

    result = probe_stock_capability(
        "stock_individual_notice_report",
        {"security": "000001"},
        resolver=_stock_catalog(stock_individual_notice_report),
    )
    assert result["sample"] == [{"security": "000001", "symbol": "全部", "page": "1"}]
