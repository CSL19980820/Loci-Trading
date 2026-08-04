"""AkShare 目录辅助：批量探测与版本检查（无上桌名单）。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.market.infrastructure.akshare_tools import (
    MAX_BATCH_PROBE,
    catalog_entries,
    check_akshare_version,
    clear_catalog_cache,
    probe_stock_capabilities_batch,
)

_CATALOG = [
    {
        "name": "stock_zh_a_hist",
        "doc": "A 股历史行情",
        "source": "eastmoney",
        "category": "history",
        "status": "available",
        "returns": "每日行情数据",
        "default_params": {"symbol": "600519"},
        "param_docs": {"symbol": "股票代码"},
        "parameters": [
            {"name": "symbol", "required": True, "annotation": "str", "sample": "600519"}
        ],
    },
    {
        "name": "stock_zh_a_spot_em",
        "doc": "A 股实时行情",
        "source": "eastmoney",
        "category": "spot_quotes",
        "status": "available",
        "returns": "",
        "default_params": {},
        "param_docs": {},
        "parameters": [],
    },
]


class CatalogCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_catalog_cache()
        self.addCleanup(clear_catalog_cache)

    def test_catalog_entries_cache_once(self) -> None:
        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_CATALOG,
        ) as discover:
            first = catalog_entries()
            second = catalog_entries()
        self.assertEqual(first, _CATALOG)
        self.assertIs(first, second)
        discover.assert_called_once()


class VersionCheckTests(unittest.TestCase):
    def test_check_skips_network_when_asked(self) -> None:
        with patch(
            "src.market.infrastructure.akshare_tools.installed_akshare_version",
            return_value="1.2.3",
        ), patch(
            "src.market.infrastructure.akshare_tools._fetch_pypi_latest",
            side_effect=AssertionError("不该联网"),
        ):
            body = check_akshare_version(fetch_latest=False)
        self.assertEqual(body["installed"], "1.2.3")
        self.assertIsNone(body["latest"])
        self.assertFalse(body["update_available"])

    def test_update_available_when_pypi_differs(self) -> None:
        with patch(
            "src.market.infrastructure.akshare_tools.installed_akshare_version",
            return_value="1.0.0",
        ), patch(
            "src.market.infrastructure.akshare_tools._fetch_pypi_latest",
            return_value="1.2.0",
        ):
            body = check_akshare_version(fetch_latest=True)
        self.assertEqual(body["latest"], "1.2.0")
        self.assertTrue(body["update_available"])


class BatchProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_catalog_cache()
        self.addCleanup(clear_catalog_cache)

    def test_batch_probes_page_and_reports_cursor(self) -> None:
        outcomes = {
            "stock_zh_a_hist": {
                "rows": 10,
                "columns": ["date"],
                "sample": [],
                "error": None,
                "elapsed_ms": 1.0,
            },
            "stock_zh_a_spot_em": {
                "rows": None,
                "columns": [],
                "sample": [],
                "error": "timeout",
                "elapsed_ms": 6.0,
            },
        }

        def fake_probe(name, params, **_kwargs):  # noqa: ANN001, ARG001
            return outcomes[name]

        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_CATALOG,
        ), patch(
            "src.market.infrastructure.akshare_tools.probe_stock_capability",
            side_effect=fake_probe,
        ):
            page = probe_stock_capabilities_batch(offset=0, limit=1)
            rest = probe_stock_capabilities_batch(offset=1, limit=10)

        self.assertEqual(page["ok"], 1)
        self.assertEqual(page["next_offset"], 1)
        self.assertFalse(page["done"])
        self.assertEqual(rest["failed"], 1)
        self.assertTrue(rest["done"])
        self.assertIsNone(rest["next_offset"])
        self.assertLessEqual(MAX_BATCH_PROBE, 200)

    def test_batch_probe_retries_then_reports_failure(self) -> None:
        calls = {"n": 0}

        def flaky(name, params, **_kwargs):  # noqa: ANN001, ARG001
            calls["n"] += 1
            return {
                "rows": None,
                "columns": [],
                "sample": [],
                "error": "HTTPError: 502",
                "elapsed_ms": 10.0,
            }

        with patch(
            "src.market.infrastructure.akshare_tools.discover_stock_capabilities",
            return_value=_CATALOG,
        ), patch(
            "src.market.infrastructure.akshare_tools.probe_stock_capability",
            side_effect=flaky,
        ), patch("src.market.infrastructure.akshare_tools.time.sleep"):
            page = probe_stock_capabilities_batch(names=["stock_zh_a_hist"], offset=0, limit=1)

        self.assertEqual(calls["n"], 2)
        self.assertEqual(page["failed"], 1)
        self.assertFalse(page["results"][0]["ok"])
        self.assertEqual(page["results"][0]["attempts"], 2)


class ProbeRowBudgetTests(unittest.TestCase):
    def test_mcp_calls_may_ask_for_more_rows_than_a_ui_probe(self) -> None:
        from src.market.infrastructure import akshare_catalog

        frame_rows = [{"date": f"2026-07-{day:02d}"} for day in range(1, 29)]
        captured: dict[str, object] = {}

        def fake_run(name, params, *, timeout_seconds, max_sample_rows, slots):  # noqa: ANN001, ARG001
            captured["rows"] = max_sample_rows
            return {"rows": len(frame_rows), "columns": ["date"], "sample": frame_rows}

        with patch.object(akshare_catalog, "run_akshare_probe", side_effect=fake_run), patch.object(
            akshare_catalog, "_probe_target", return_value=lambda **_kwargs: None
        ), patch.object(akshare_catalog, "_signature", return_value=_EmptySignature()):
            akshare_catalog.probe_stock_capability("stock_zh_a_hist", {}, max_sample_rows=30)
        self.assertEqual(captured["rows"], 30)

        with patch.object(akshare_catalog, "run_akshare_probe", side_effect=fake_run), patch.object(
            akshare_catalog, "_probe_target", return_value=lambda **_kwargs: None
        ), patch.object(akshare_catalog, "_signature", return_value=_EmptySignature()):
            akshare_catalog.probe_stock_capability("stock_zh_a_hist", {}, max_sample_rows=9999)
        self.assertEqual(captured["rows"], akshare_catalog.MAX_MCP_SAMPLE_ROWS)

        with patch.object(akshare_catalog, "run_akshare_probe", side_effect=fake_run), patch.object(
            akshare_catalog, "_probe_target", return_value=lambda **_kwargs: None
        ), patch.object(akshare_catalog, "_signature", return_value=_EmptySignature()):
            akshare_catalog.probe_stock_capability("stock_zh_a_hist", {})
        self.assertEqual(captured["rows"], akshare_catalog.MAX_SAMPLE_ROWS)


class _EmptySignature:
    parameters: dict[str, object] = {}

    def bind(self, **kwargs):  # noqa: ANN003, ANN201
        if kwargs:
            raise TypeError("unexpected parameters")
        return self


if __name__ == "__main__":
    unittest.main()
