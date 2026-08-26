"""MCP 客户端、URL 校验与服务器注册表。

响应解析在 `test_intel_parsing.py`，agent 回路在 `test_intel_agent_loop.py`。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import httpx2

from src.intel.infrastructure.mcp import (
    MAX_RESPONSE_BYTES,
    MAX_TOOL_SCHEMA_BYTES,
    McpClient,
    McpError,
    validate_mcp_url,
)
from src.intel.infrastructure.registry import build_client, collect_tools, probe_mcp, save_server
from src.ops.infrastructure.store import OpsError


class McpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = McpClient(name="demo", url="https://example.com/mcp", token="t")
        # 除握手顺序专测外，其余测试只关心目标 RPC，避免 initialize 占掉 mock 返回值。
        self.client._initialized = True
        self.client._initialize_result = {"serverInfo": {"name": "demo"}}

    def _rpc_returns(self, payloads: list[dict]):
        return patch.object(self.client, "_rpc", side_effect=payloads)

    def test_lists_tools_across_pages(self) -> None:
        """分页必须走完，否则后面的工具会静默丢失。"""
        pages = [
            {"tools": [{"name": "a", "description": "A"}], "nextCursor": "c1"},
            {"tools": [{"name": "b", "description": "B"}]},
        ]
        with self._rpc_returns(pages):
            tools = self.client.list_tools()
        self.assertEqual([t.name for t in tools], ["a", "b"])
        self.assertTrue(all(t.server == "demo" for t in tools))

    def test_skips_malformed_tool_entries(self) -> None:
        with self._rpc_returns([{"tools": [{"description": "无名"}, {"name": "ok"}]}]):
            self.assertEqual([t.name for t in self.client.list_tools()], ["ok"])

    def test_call_tool_joins_text_blocks(self) -> None:
        payload = {"content": [{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}]}
        with self._rpc_returns([payload]):
            result = self.client.call_tool("demo__kline", {"code": "600519"})
        self.assertEqual(result["text"], "第一段\n第二段")
        self.assertFalse(result["is_error"])

    def test_call_tool_strips_the_server_prefix(self) -> None:
        """模型看到的是带前缀的名字，发给 server 的必须是原名。"""
        with patch.object(self.client, "_rpc", return_value={"content": []}) as rpc:
            self.client.call_tool("demo__kline", {"code": "600519"})
        self.assertEqual(rpc.call_args[0][1]["name"], "kline")

    def test_error_flag_is_preserved(self) -> None:
        payload = {"content": [{"type": "text", "text": "配额用尽"}], "isError": True}
        with self._rpc_returns([payload]):
            self.assertTrue(self.client.call_tool("x", {})["is_error"])

    def test_initializes_once_before_tool_discovery_and_call(self) -> None:
        calls: list[str] = []
        self.client._initialized = False
        self.client._initialize_result = {}

        def rpc(method: str, _params=None) -> dict:
            calls.append(method)
            if method == "initialize":
                return {"serverInfo": {"name": "demo"}}
            if method == "tools/list":
                return {"tools": []}
            return {"content": []}

        with patch.object(self.client, "_rpc", side_effect=rpc), patch.object(self.client, "_notify"):
            self.client.list_tools()
            self.client.call_tool("demo__kline", {})

        self.assertEqual(calls, ["initialize", "tools/list", "tools/call"])

    def test_repeated_pagination_cursor_fails_fast(self) -> None:
        calls = 0

        def rpc(_method: str, _params=None) -> dict:
            nonlocal calls
            calls += 1
            if calls > 2:
                raise AssertionError("重复游标没有终止请求")
            return {"tools": [], "nextCursor": "same"}

        with patch.object(self.client, "_rpc", side_effect=rpc), self.assertRaisesRegex(McpError, "重复"):
            self.client.list_tools()
        self.assertEqual(calls, 2)

    def test_client_disables_environment_proxy_configuration(self) -> None:
        with patch("src.intel.infrastructure.mcp.validate_mcp_url"), patch(
            "src.intel.infrastructure.mcp.needs_system_proxy", return_value=False
        ), patch("src.intel.infrastructure.mcp.httpx2.Client") as client_cls:
            self.client._client()
        self.assertFalse(client_cls.call_args.kwargs.get("trust_env", True))
        self.assertFalse(client_cls.call_args.kwargs.get("follow_redirects", True))

    def test_client_uses_system_proxy_for_clash_fake_ip(self) -> None:
        """Fake-IP 直连必挂；与 Cursor/Node 一样此时读 HTTPS_PROXY。"""
        with patch("src.intel.infrastructure.mcp.validate_mcp_url"), patch(
            "src.intel.infrastructure.mcp.needs_system_proxy", return_value=True
        ), patch("src.intel.infrastructure.mcp.httpx2.Client") as client_cls:
            self.client._client()
        self.assertTrue(client_cls.call_args.kwargs.get("trust_env"))

    def test_headers_include_mcp_protocol_version_like_hermes(self) -> None:
        headers = self.client._headers()
        self.assertEqual(headers.get("Mcp-Protocol-Version"), "2025-03-26")
        self.assertIn("text/event-stream", headers.get("Accept", ""))

    def test_response_body_has_a_hard_byte_cap(self) -> None:
        transport = httpx2.MockTransport(
            lambda _request: httpx2.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        )
        with patch.object(
            self.client,
            "_client",
            return_value=httpx2.Client(transport=transport),
        ):
            with self.assertRaisesRegex(McpError, "响应过大"):
                self.client._rpc("initialize")

    def test_external_error_body_is_never_exposed(self) -> None:
        secret = "mcp-super-secret"
        transport = httpx2.MockTransport(
            lambda _request: httpx2.Response(
                500,
                content=f"Authorization: Bearer {secret}".encode(),
            )
        )
        with patch.object(
            self.client,
            "_client",
            return_value=httpx2.Client(transport=transport),
        ):
            with self.assertRaises(McpError) as ctx:
                self.client._rpc("initialize")
        self.assertIn("500", str(ctx.exception))
        self.assertNotIn(secret, str(ctx.exception))

    def test_json_rpc_error_body_is_never_exposed(self) -> None:
        secret = "mcp-jsonrpc-secret"
        transport = httpx2.MockTransport(
            lambda _request: httpx2.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32000, "message": f"token={secret}"},
                },
            )
        )
        with patch.object(
            self.client,
            "_client",
            return_value=httpx2.Client(transport=transport),
        ):
            with self.assertRaises(McpError) as ctx:
                self.client._rpc("initialize")
        self.assertIn("MCP 协议错误", str(ctx.exception))
        self.assertNotIn(secret, str(ctx.exception))

    def test_rejects_an_oversized_tool_schema(self) -> None:
        oversized = {"type": "object", "description": "x" * (MAX_TOOL_SCHEMA_BYTES + 1)}
        with self._rpc_returns([{"tools": [{"name": "oversized", "inputSchema": oversized}]}]):
            with self.assertRaisesRegex(McpError, "inputSchema 超过"):
                self.client.list_tools()


class McpUrlValidationTests(unittest.TestCase):
    def test_allowlisted_loopback_http_resolves_with_default_http_port(self) -> None:
        with patch.dict(os.environ, {"PALACE_MCP_LOOPBACK_HTTP_HOSTS": "localhost"}), patch(
            "src.intel.infrastructure.mcp.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
        ) as resolve:
            self.assertEqual(validate_mcp_url("http://localhost/mcp", resolve=True), "http://localhost/mcp")

        self.assertEqual(resolve.call_args.args[1], 80)

    def test_dns_private_address_is_rejected_even_for_https_hostnames(self) -> None:
        with patch(
            "src.intel.infrastructure.mcp.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
        ), self.assertRaisesRegex(McpError, "解析到了内网"):
            validate_mcp_url("https://looks-public.example/mcp", resolve=True)

    def test_proxy_fake_ip_dns_is_allowed_for_https_hostnames(self) -> None:
        """Clash Fake-IP（198.18/15）解析结果不能拦死悟道等公网 MCP。"""
        with patch(
            "src.intel.infrastructure.mcp.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.140", 443))],
        ):
            self.assertEqual(
                validate_mcp_url("https://stock.quicktiny.cn/api/mcp", resolve=True),
                "https://stock.quicktiny.cn/api/mcp",
            )
            from src.intel.infrastructure.mcp import needs_system_proxy

            self.assertTrue(needs_system_proxy("https://stock.quicktiny.cn/api/mcp"))

    def test_literal_fake_ip_https_is_still_rejected(self) -> None:
        with self.assertRaisesRegex(McpError, "内网|回环|保留"):
            validate_mcp_url("https://198.18.0.140/api/mcp", resolve=False)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.mcp_path = Path(self.temp.name) / "mcp.json"
        self._path_patch = patch("src.intel.infrastructure.mcp_config.mcp_json_path", return_value=self.mcp_path)
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self.temp.cleanup()

    def _save(self, **overrides):
        params = {
            "name": "demo-mcp",
            "url": "https://example.com/mcp",
            "token": "lb_secret_1234",
            "verify": False,
        }
        params.update(overrides)
        return save_server(**params)

    def test_legacy_wudao_a_stock_key_migrates_to_canonical_wudao(self) -> None:
        from src.intel.infrastructure.mcp_config import migrate_wudao_server_name

        self.mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "wudao-a-stock": {
                            "url": "https://stock.quicktiny.cn/api/mcp",
                            "note": "legacy",
                            "tools": [{"name": "kline"}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(migrate_wudao_server_name(self.mcp_path))
        raw = json.loads(self.mcp_path.read_text(encoding="utf-8"))
        self.assertIn("wudao", raw["mcpServers"])
        self.assertNotIn("wudao-a-stock", raw["mcpServers"])
        self.assertEqual(raw["mcpServers"]["wudao"]["tools"][0]["name"], "kline")

    def test_token_is_plaintext_in_mcp_json_and_masked_in_api(self) -> None:
        record = self._save()
        self.assertTrue(str(record["token_last4"]).endswith("1234"))
        self.assertNotIn("token", record)
        self.assertTrue(record["has_token"])
        raw = json.loads(self.mcp_path.read_text(encoding="utf-8"))
        cfg = raw["mcpServers"]["demo-mcp"]
        self.assertEqual(cfg.get("token"), "lb_secret_1234")
        self.assertNotIn("encrypted_token", cfg)
        self.assertNotIn("headers", cfg)

    def test_corrupt_config_is_not_silently_replaced(self) -> None:
        original = "{not valid json"
        self.mcp_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(OpsError, "格式错误"):
            self._save()

        self.assertEqual(self.mcp_path.read_text(encoding="utf-8"), original)

    def test_client_is_rebuilt_with_the_token(self) -> None:
        self._save()
        client = build_client("demo-mcp")
        self.assertEqual(client.token, "lb_secret_1234")

    def test_client_preserves_custom_auth_headers_from_cursor_config(self) -> None:
        self.mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "custom": {
                            "url": "https://example.com/mcp",
                            "headers": {"X-API-Key": "custom-secret", "Authorization": "Basic abc"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        client = build_client("custom")

        self.assertEqual(client.token, "")
        self.assertEqual(client._headers()["X-API-Key"], "custom-secret")
        self.assertEqual(client._headers()["Authorization"], "Basic abc")

    def test_url_must_be_http(self) -> None:
        with self.assertRaises(OpsError):
            self._save(url="ftp://example.com")

    def test_rejects_insecure_or_internal_mcp_destinations(self) -> None:
        for url in (
            "http://example.com/mcp",
            "https://127.0.0.1/mcp",
            "https://10.0.0.8/mcp",
            "https://[::1]/mcp",
            "https://trusted.example@evil.example/mcp",
        ):
            with self.subTest(url=url), self.assertRaises(OpsError):
                self._save(url=url)

    def test_rejects_configured_proxy(self) -> None:
        with self.assertRaises(OpsError):
            self._save(proxy_url="http://proxy.example:8080")

    def test_short_token_is_not_exposed_by_masking(self) -> None:
        record = self._save(token="abc")
        self.assertEqual(record["token_last4"], "****")

    def test_updating_without_a_token_keeps_the_existing_one(self) -> None:
        self._save()
        self._save(token=None, url="https://example.com/mcp2")
        client = build_client("demo-mcp")
        self.assertEqual(client.url, "https://example.com/mcp2")
        self.assertEqual(client.token, "lb_secret_1234")

    def test_legacy_ciphertext_is_unusable_until_reentered(self) -> None:
        from src.intel.infrastructure.mcp_config import (
            get_mcp_server_from_json,
            upsert_mcp_server_json,
        )

        self.mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "demo-mcp": {
                            "url": "https://example.com/mcp",
                            "encrypted_token": "YWJjZGVmZ2hpams=",
                            "token_last4": "****cret",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        row = get_mcp_server_from_json("demo-mcp")
        assert row is not None
        self.assertFalse(row["is_usable"])
        self.assertIn("废弃", row["skip_reason"])

        upsert_mcp_server_json(
            name="demo-mcp",
            url="https://example.com/mcp",
            token=None,
            note="keepalive",
        )
        after = json.loads(self.mcp_path.read_text(encoding="utf-8"))
        self.assertNotIn("encrypted_token", after["mcpServers"]["demo-mcp"])
        self.assertEqual(after["mcpServers"]["demo-mcp"]["note"], "keepalive")

    def test_legacy_ciphertext_purged_by_migrate(self) -> None:
        from src.intel.infrastructure.mcp_config import migrate_encrypted_mcp_tokens

        self.mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "demo-mcp": {
                            "url": "https://example.com/mcp",
                            "encrypted_token": "YWJjZGVmZ2hpams=",
                            "token": "keep-me",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(migrate_encrypted_mcp_tokens(self.mcp_path), 1)
        raw = json.loads(self.mcp_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["mcpServers"]["demo-mcp"]["token"], "keep-me")
        self.assertNotIn("encrypted_token", raw["mcpServers"]["demo-mcp"])

    def test_server_without_token_is_marked_unusable_and_skipped(self) -> None:
        from src.intel.infrastructure.mcp_config import upsert_mcp_server_json
        from src.intel.infrastructure.registry import list_effective_mcp_servers

        upsert_mcp_server_json(name="bare", url="https://example.com/mcp", token="")
        rows = list_effective_mcp_servers(active_only=False)
        bare = next(item for item in rows if item["name"] == "bare")
        self.assertFalse(bare["is_usable"])
        self.assertIn("Key", bare["skip_reason"])
        self.assertEqual(
            [item["name"] for item in list_effective_mcp_servers(active_only=True)],
            ["loci-market"],
        )
        with self.assertRaisesRegex(OpsError, "未配置 API Key"):
            build_client("bare")

    def test_expired_server_is_skipped_after_expires_at(self) -> None:
        from datetime import date, timedelta
        from unittest.mock import patch

        from src.intel.infrastructure.registry import list_effective_mcp_servers

        expired = (date.today() - timedelta(days=1)).isoformat()
        record = self._save(name="paid", expires_at=expired)
        self.assertEqual(record["expires_at"], expired)
        self.assertFalse(record["is_usable"])
        with patch("src.intel.infrastructure.mcp_config.date") as mock_date:
            mock_date.today.return_value = date.today()
            mock_date.fromisoformat = date.fromisoformat
            active = list_effective_mcp_servers(active_only=True)
        self.assertEqual([item["name"] for item in active], ["loci-market"])
        with self.assertRaisesRegex(OpsError, "过期"):
            build_client("paid")

    def test_collect_tools_narrows_to_the_allow_list(self) -> None:
        """一个 server 有 60+ 工具，全塞进 prompt 会占掉大量上下文。"""
        from src.intel.infrastructure.mcp_config import upsert_mcp_server_json

        upsert_mcp_server_json(
            name="demo-mcp",
            url="https://example.com/mcp",
            token="lb_test_token",
            tools=[
                {"name": "kline", "description": "K线"},
                {"name": "limit_up_ladder", "description": "涨停梯队"},
                {"name": "sec_filings", "description": "海外披露"},
            ],
        )
        tools, routing = collect_tools(["demo-mcp"], allow=["kline", "limit_up_ladder"])
        self.assertEqual(sorted(t.name for t in tools), ["kline", "limit_up_ladder"])
        self.assertEqual(routing["demo-mcp__kline"], "demo-mcp")

    def test_inactive_servers_are_excluded(self) -> None:
        from src.intel.infrastructure.mcp_config import upsert_mcp_server_json

        upsert_mcp_server_json(
            name="off",
            url="https://x/mcp",
            token="lb_test_token",
            disabled=True,
            tools=[{"name": "t", "description": "d"}],
        )
        tools, _ = collect_tools(server_names=["off"])
        self.assertEqual(tools, [])

    def test_probe_returns_failure_when_refresh_after_ping_fails(self) -> None:
        self._save()

        class Client:
            @staticmethod
            def ping() -> dict:
                return {"tool_count": 1}

        with patch("src.intel.infrastructure.registry.build_client", return_value=Client()), patch(
            "src.intel.infrastructure.registry.refresh_tools", side_effect=McpError("refresh timeout")
        ):
            result = probe_mcp("demo-mcp")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "MCP 服务暂不可用")
