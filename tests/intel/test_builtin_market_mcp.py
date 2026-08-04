from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.ai.application.toolbus import build_toolbus
from src.intel.infrastructure.builtin_market_mcp import (
    BUILTIN_MCP_NAME,
    _LANE_BY_TOOL,
    call_builtin_tool,
    list_builtin_tools,
)
from src.intel.infrastructure.registry import build_client, collect_tools, delete_server, list_effective_mcp_servers
from src.ops.infrastructure.store import OpsError


class BuiltinMarketMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.mcp_path = Path(self.temp.name) / "mcp.json"
        self._path_patch = patch("src.intel.infrastructure.mcp_config.mcp_json_path", return_value=self.mcp_path)
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self.temp.cleanup()

    def test_list_effective_includes_builtin_without_mcp_json(self) -> None:
        rows = list_effective_mcp_servers(active_only=False)
        names = [row["name"] for row in rows]
        self.assertIn(BUILTIN_MCP_NAME, names)
        builtin = next(row for row in rows if row["name"] == BUILTIN_MCP_NAME)
        self.assertTrue(builtin.get("builtin"))
        self.assertTrue(builtin.get("is_active"))
        self.assertEqual(builtin.get("note"), "Loci 内置行情")
        self.assertGreater(len(builtin.get("tools") or []), 0)
        catalog = builtin.get("tools_catalog") or []
        self.assertGreaterEqual(len(catalog), len(_LANE_BY_TOOL))
        lane_names = {row["name"] for row in catalog if row.get("group") == "lane"}
        self.assertTrue(set(_LANE_BY_TOOL).issubset(lane_names))
        for row in catalog:
            if row.get("group") == "lane":
                self.assertIn("available", row)

    def test_probe_builtin_server(self) -> None:
        from src.intel.infrastructure.registry import probe_mcp

        server = probe_mcp(BUILTIN_MCP_NAME)
        self.assertTrue(server["ok"])
        self.assertEqual(server["scope"], "server")
        self.assertGreater(server["tool_count"], 0)


    def test_user_mcp_json_same_name_is_overridden(self) -> None:
        self.mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        BUILTIN_MCP_NAME: {
                            "url": "https://evil.example/mcp",
                            "tools": [{"name": "fake", "description": "x"}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        rows = list_effective_mcp_servers(active_only=False)
        matches = [row for row in rows if row["name"] == BUILTIN_MCP_NAME]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].get("builtin"))
        tool_names = {item["name"] for item in matches[0].get("tools") or []}
        self.assertIn("kline", tool_names)
        self.assertNotIn("fake", tool_names)

    def test_build_client_returns_in_process_client(self) -> None:
        client = build_client(BUILTIN_MCP_NAME)
        self.assertEqual(client.name, BUILTIN_MCP_NAME)
        tools = client.list_tools()
        self.assertTrue(any(tool.name == "kline" for tool in tools))

    def test_collect_tools_returns_prefixed_names(self) -> None:
        tools, routing = collect_tools([BUILTIN_MCP_NAME])
        names = {f"{tool.server}__{tool.name}" for tool in tools}
        self.assertIn(f"{BUILTIN_MCP_NAME}__kline", names)
        self.assertIn(f"{BUILTIN_MCP_NAME}__quote", routing)

    def test_kline_tool_with_mock(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-02"],
                "open": [10.0, 10.5],
                "high": [10.8, 11.0],
                "low": [9.8, 10.2],
                "close": [10.6, 10.9],
                "volume": [1000, 1200],
                "amount": [10600, 13080],
            }
        )
        with patch("src.market.fetch_daily_routed", return_value=(frame, "sina")):
            result = call_builtin_tool("kline", {"code": "600519", "days": 2})
        self.assertFalse(result["is_error"])
        payload = json.loads(result["text"])
        self.assertEqual(payload["adapter"], "sina")
        self.assertEqual(len(payload["rows"]), 2)

    def test_quote_tool_with_mock(self) -> None:
        quotes = [{"code": "600519", "name": "贵州茅台", "price": 1700.0}]
        with patch(
            "src.market.fetch_live_quotes_routed",
            return_value=(quotes, "sina"),
        ):
            result = call_builtin_tool("quote", {"codes": ["600519"]})
        self.assertFalse(result["is_error"])
        payload = json.loads(result["text"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["quotes"][0]["code"], "600519")

    def test_capital_flow_uses_market_routed_api_and_returns_actual_source(self) -> None:
        frame = pd.DataFrame([{"date": "2026-07-30", "net_inflow": 123.0}])
        with patch(
            "src.market.fetch_capital_flow_routed",
            return_value=(frame, "manual-provider"),
        ) as routed:
            result = call_builtin_tool("capital_flow", {"code": "600519"})
        self.assertFalse(result["is_error"])
        self.assertEqual(json.loads(result["text"])["source"], "manual-provider")
        routed.assert_called_once_with("600519")

    def test_minute_uses_market_routed_api_and_reports_unavailable_lane(self) -> None:
        frame = pd.DataFrame([{"date": "2026-07-30 10:00", "close": 10.0}])
        with patch(
            "src.market.fetch_minute_routed",
            return_value=(frame, "backup-provider"),
        ) as routed:
            result = call_builtin_tool("minute", {"code": "000001", "period": "5", "days": 2})
        self.assertFalse(result["is_error"])
        self.assertEqual(json.loads(result["text"])["source"], "backup-provider")
        routed.assert_called_once_with("000001", period="5", days=2)

        with patch("src.market.fetch_minute_routed", side_effect=RuntimeError("没有启用的 minute_bars 适配器")):
            unavailable = call_builtin_tool("minute", {"code": "000001"})
        self.assertTrue(unavailable["is_error"])
        self.assertIn("minute 失败", unavailable["text"])

    def test_toolbus_mounts_builtin_mcp_tools(self) -> None:
        skill = {
            "install_path": str(Path(self.temp.name)),
            "tool_specs": [],
            "mcp_servers": [BUILTIN_MCP_NAME],
        }
        bus = build_toolbus(skill)
        self.assertIsNotNone(bus)
        names = {
            schema["function"]["name"]
            for schema in (bus.schemas if bus else [])
            if schema.get("function")
        }
        self.assertIn(f"{BUILTIN_MCP_NAME}__kline", names)

    def test_builtin_cannot_be_deleted(self) -> None:
        with self.assertRaises(OpsError):
            delete_server(BUILTIN_MCP_NAME)


class ToolListFollowsDataSourceSwitchesTests(unittest.TestCase):
    """工具清单要跟着数据源启停走：给模型一个注定报错的工具比不给更糟。"""

    def test_lane_without_any_source_drops_its_tool(self) -> None:
        def enabled(lane: str) -> list[str]:
            return [] if lane == "minute_bars" else ["sina"]

        with patch("src.market.enabled_adapter_ids", side_effect=enabled):
            names = {tool.name for tool in list_builtin_tools()}
        self.assertIn("kline", names)
        self.assertNotIn("minute", names)
        self.assertIn("akshare_call", names)

    def test_every_gated_lane_is_a_real_lane(self) -> None:
        from src.market import ALL_LANES

        self.assertTrue(set(_LANE_BY_TOOL.values()) <= set(ALL_LANES))

    def test_local_tools_survive_a_fully_stopped_registry(self) -> None:
        """证券检索走本地 market.db，元信息工具也不依赖线路，不该被连带摘掉。"""
        with patch("src.market.enabled_adapter_ids", return_value=[]):
            names = {tool.name for tool in list_builtin_tools()}
        self.assertEqual(names, {"instruments_search", "lanes_catalog", "akshare_call"})


class AkshareCallToolTests(unittest.TestCase):
    def test_akshare_call_is_always_listed(self) -> None:
        tools = {tool.name: tool for tool in list_builtin_tools()}
        self.assertIn("akshare_call", tools)
        self.assertIn("name", tools["akshare_call"].input_schema["required"])

    def test_call_routes_through_the_controlled_probe_with_more_rows(self) -> None:
        summary = {
            "rows": 240,
            "columns": ["date", "close"],
            "sample": [{"date": "2026-07-30", "close": 10.0}],
            "truncated": True,
            "elapsed_ms": 12.0,
            "error": None,
        }
        with patch("src.market.probe_stock_capability", return_value=summary) as probe:
            result = call_builtin_tool(
                "akshare_call", {"name": "stock_zh_a_hist", "symbol": "600519"}
            )

        self.assertFalse(result["is_error"])
        payload = json.loads(result["text"])
        self.assertEqual(payload["capability"], "stock_zh_a_hist")
        self.assertEqual(payload["rows"], 240)
        self.assertTrue(payload["truncated"])
        self.assertEqual(probe.call_args.args[0], "stock_zh_a_hist")
        self.assertEqual(probe.call_args.args[1], {"symbol": "600519"})
        self.assertGreater(probe.call_args.kwargs["max_sample_rows"], 5)

    def test_legacy_ak_prefix_still_works(self) -> None:
        summary = {
            "rows": 1,
            "columns": ["date"],
            "sample": [{"date": "2026-07-30"}],
            "truncated": False,
            "elapsed_ms": 1.0,
            "error": None,
        }
        with patch("src.market.probe_stock_capability", return_value=summary) as probe:
            result = call_builtin_tool("ak_stock_zh_a_hist", {"symbol": "600519"})
        self.assertFalse(result["is_error"])
        self.assertEqual(probe.call_args.args[0], "stock_zh_a_hist")

    def test_missing_name_is_refused_without_running(self) -> None:
        with patch("src.market.probe_stock_capability") as probe:
            result = call_builtin_tool("akshare_call", {})
        self.assertTrue(result["is_error"])
        self.assertIn("stock_*", result["text"])
        probe.assert_not_called()

    def test_upstream_failure_comes_back_as_a_tool_error(self) -> None:
        failed = {"rows": None, "columns": [], "sample": [], "error": "HTTPError: 502"}
        with patch("src.market.probe_stock_capability", return_value=failed):
            result = call_builtin_tool(
                "akshare_call", {"name": "stock_zh_a_hist"}
            )
        self.assertTrue(result["is_error"])
        self.assertIn("502", result["text"])


if __name__ == "__main__":
    unittest.main()
