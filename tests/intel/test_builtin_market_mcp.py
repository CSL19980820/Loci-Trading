from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.ai.application.toolbus import build_toolbus
from src.intel.infrastructure.builtin_market_mcp import BUILTIN_MCP_NAME, call_builtin_tool
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


if __name__ == "__main__":
    unittest.main()
