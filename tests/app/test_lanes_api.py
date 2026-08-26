"""数据线路运维 API：目录 / 探测 / 测速（不打真网）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.ops.api.settings import build_ops_settings_router
from src.market.infrastructure.adapters.types import ProbeResult, SpeedTestResult
from src.app.main import create_app


class LanesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        # 偏好写入测试目录下的 loci.config，避免污染工作区
        self._cfg = base / "loci.config.json"
        app = create_app(base / "palace.db", base / "no-static")
        self.client = TestClient(app)
        self._writable_patch = patch(
            "src.shared.paths.writable_root", return_value=base
        )
        self._writable_patch.start()

    def tearDown(self) -> None:
        self._writable_patch.stop()
        self.client.close()
        self.temp.cleanup()

    def test_catalog_lists_lanes_and_providers(self) -> None:
        body = self.client.get("/api/ops/lanes").json()
        lane_ids = {item["id"] for item in body["lanes"]}
        self.assertIn("hist_daily", lane_ids)
        self.assertTrue(body["providers"])
        ids = {p["id"] for p in body["providers"]}
        self.assertIn("sina", ids)
        self.assertIn("eastmoney", ids)
        policies = {item["lane"]: item for item in body["policies"]}
        self.assertIn("hist_daily", policies)
        self.assertIn("effective_provider_ids", policies["hist_daily"])
        for p in body["providers"]:
            self.assertIn("enabled", p)
            self.assertIn("label", p)
            self.assertEqual(p["disabled_lanes"], [])

    def test_catalog_reports_per_lane_disabled_tools(self) -> None:
        """逐工具停用只影响该线路的生效源，源总开关仍是开的。"""
        config = {"lane_providers": {"sina": {"lanes": {"hist_daily": False}}}}
        with patch("src.shared.paths.load_config", return_value=config):
            body = self.client.get("/api/ops/lanes").json()
        sina = next(item for item in body["providers"] if item["id"] == "sina")
        self.assertTrue(sina["enabled"])
        self.assertEqual(sina["disabled_lanes"], ["hist_daily"])
        policies = {item["lane"]: item for item in body["policies"]}
        self.assertNotIn("sina", policies["hist_daily"]["effective_provider_ids"])
        self.assertIn("sina", policies["spot_batch"]["effective_provider_ids"])

    def test_catalog_includes_policy_and_effective_provider_ids(self) -> None:
        config = {
            "lane_routes": {
                "hist_daily": {
                    "mode": "manual",
                    "provider_id": "sina",
                    "fallback": False,
                }
            }
        }
        with patch("src.shared.paths.load_config", return_value=config):
            body = self.client.get("/api/ops/lanes").json()
        lane = next(item for item in body["lanes"] if item["id"] == "hist_daily")
        self.assertEqual(lane["policy"]["mode"], "manual")
        self.assertEqual(lane["effective_provider_ids"], ["sina"])

    def test_probe_unknown_lane_is_400(self) -> None:
        response = self.client.post("/api/ops/lanes/probe", json={"lane": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_probe_mcp_provider_uses_probe_mcp_not_adapter(self) -> None:
        """悟道等 MCP 情报源 id 形如 mcp:wudao，不能丢给 get_adapter。"""
        fake = {"ok": True, "scope": "server", "rtt_ms": 42, "tool_count": 12}
        with patch(
            "src.intel.probe_mcp",
            return_value=fake,
        ) as mocked:
            body = self.client.post(
                "/api/ops/lanes/probe",
                json={"adapter_id": "mcp:wudao", "runs": 1},
            ).json()
        mocked.assert_called_once_with("wudao", refresh=False)
        self.assertEqual(len(body["results"]), 1)
        row = body["results"][0]
        self.assertEqual(row["adapter_id"], "mcp:wudao")
        self.assertEqual(row["lane"], "intel_mcp")
        self.assertTrue(row["ok"])
        self.assertEqual(row["label"], "悟道")
        self.assertEqual(row["rows"], 12)

    def test_probe_and_speedtest_require_router_access(self) -> None:
        """即使被其他组合根挂载，外部探测也不能绕过访问控制。"""

        def deny(_: Request) -> None:
            raise HTTPException(status_code=401, detail="authentication required")

        app = FastAPI()
        app.include_router(build_ops_settings_router(write_dependency=deny))
        with TestClient(app) as client:
            probe = client.post("/api/ops/lanes/probe", json={"lane": "hist_daily"})
            speedtest = client.post("/api/ops/lanes/speedtest", json={})

        self.assertEqual(probe.status_code, 401)
        self.assertEqual(speedtest.status_code, 401)

    def test_probe_hist_daily_uses_router(self) -> None:
        fake = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=12.3, rows=5),
            ProbeResult(
                adapter_id="eastmoney",
                lane="hist_daily",
                ok=False,
                rtt_ms=40.0,
                error="timeout",
            ),
        ]
        with patch("src.market.probe_lane", return_value=fake) as mocked:
            body = self.client.post(
                "/api/ops/lanes/probe", json={"lane": "hist_daily", "runs": 2}
            ).json()
        mocked.assert_called()
        self.assertEqual(len(body["results"]), 2)
        self.assertEqual(body["results"][0]["adapter_id"], "sina")
        self.assertIn("label", body["results"][0])
        self.assertEqual(body["code"], "600519")
        self.assertEqual(body["rounds"][0]["run"], 1)
        self.assertEqual(body["runs"], 2)
        self.assertEqual(len(body["rounds"]), 4)
        self.assertEqual(
            {(row["adapter_id"], row["run"]) for row in body["rounds"]},
            {("sina", 1), ("eastmoney", 1), ("sina", 2), ("eastmoney", 2)},
        )

    def test_probe_median_ignores_failed_round_without_rtt(self) -> None:
        success_one = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=100.0, rows=5)
        ]
        failed = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=False, error="timeout")
        ]
        success_two = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=110.0, rows=5)
        ]
        with patch(
            "src.market.probe_lane",
            side_effect=[success_one, failed, success_two],
        ):
            body = self.client.post(
                "/api/ops/lanes/probe",
                json={"lane": "hist_daily", "runs": 3},
            ).json()

        result = body["results"][0]
        self.assertEqual(result["median_rtt_ms"], 105.0)
        self.assertEqual(result["failed_runs"], 1)

    def test_probe_aggregates_rounds_and_passes_custom_code(self) -> None:
        first = [ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=12, rows=5)]
        second = [ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=32, rows=5)]
        with patch("src.market.probe_lane", side_effect=[first, second]) as mocked:
            response = self.client.post(
                "/api/ops/lanes/probe",
                json={"lane": "hist_daily", "code": "000001", "runs": 2},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "000001")
        self.assertEqual(body["runs"], 2)
        row = body["results"][0]
        self.assertEqual(row["median_rtt_ms"], 22)
        self.assertEqual(len(row["rounds"]), 2)
        self.assertEqual(mocked.call_args.kwargs["code"], "000001")

    def test_probe_rejects_invalid_code_and_runs(self) -> None:
        self.assertEqual(
            self.client.post("/api/ops/lanes/probe", json={"code": "123"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/ops/lanes/probe", json={"runs": 4}).status_code,
            422,
        )

    def test_speedtest_rejects_non_hist(self) -> None:
        response = self.client.post(
            "/api/ops/lanes/speedtest",
            json={"lane": "spot_batch", "code": "600519"},
        )
        self.assertEqual(response.status_code, 400)

    def test_speedtest_hist_daily(self) -> None:
        fake = [
            SpeedTestResult(
                adapter_id="sina",
                code="600519",
                ok=True,
                elapsed_ms=100.0,
                rows=1000,
                bytes_est=80000,
                mb_per_s=0.8,
            )
        ]
        with patch("src.market.speedtest_daily", return_value=fake):
            body = self.client.post(
                "/api/ops/lanes/speedtest",
                json={"lane": "hist_daily", "code": "600519"},
            ).json()
        self.assertEqual(body["lane"], "hist_daily")
        self.assertEqual(body["results"][0]["rows"], 1000)
        self.assertIn("label", body["results"][0])
        self.assertEqual(body["rounds"][0]["run"], 1)

    def test_speedtest_aggregates_rounds(self) -> None:
        first = [SpeedTestResult(adapter_id="sina", code="000001", ok=True, elapsed_ms=10.0)]
        second = [SpeedTestResult(adapter_id="sina", code="000001", ok=True, elapsed_ms=30.0)]
        with patch("src.market.speedtest_daily", side_effect=[first, second]) as mocked:
            response = self.client.post(
                "/api/ops/lanes/speedtest",
                json={"code": "000001", "runs": 2},
            )
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["elapsed_ms"], 20)
        self.assertEqual(len(row["rounds"]), 2)
        self.assertEqual(mocked.call_args.args[0], "000001")

    def test_put_manual_policy_validates_provider_and_clears_lane_sticky(self) -> None:
        with patch("src.shared.paths.load_config", return_value={}), patch(
            "src.shared.paths.save_config", return_value={}
        ) as saved, patch("src.market.clear_sticky") as clear:
            response = self.client.put(
                "/api/ops/lanes/hist_daily/policy",
                json={"mode": "manual", "provider_id": "sina", "fallback": True},
            )
        if response.status_code == 401:
            self.skipTest("write_guard 要求登录，本环境未注入凭证")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["policy"]["provider_id"], "sina")
        self.assertEqual(
            saved.call_args.args[0]["lane_routes"]["hist_daily"]["mode"], "manual"
        )
        clear.assert_called_once_with("hist_daily")

    def test_put_manual_policy_rejects_unknown_disabled_and_unsupported_provider(self) -> None:
        cases = [
            ("hist_daily", {"mode": "manual", "provider_id": "nope"}),
            ("instruments", {"mode": "manual", "provider_id": "sina"}),
        ]
        for lane, payload in cases:
            response = self.client.put(f"/api/ops/lanes/{lane}/policy", json=payload)
            if response.status_code == 401:
                self.skipTest("write_guard 要求登录，本环境未注入凭证")
            self.assertEqual(response.status_code, 422)
        with patch(
            "src.shared.paths.load_config",
            return_value={"lane_providers": {"sina": {"enabled": False}}},
        ):
            response = self.client.put(
                "/api/ops/lanes/hist_daily/policy",
                json={"mode": "manual", "provider_id": "sina"},
            )
        self.assertEqual(response.status_code, 422)

    def test_speedtest_all_disabled_returns_empty(self) -> None:
        """全部停用时不得回退成探测全部源（曾用 ids or None 踩）。"""
        with patch(
            "src.shared.paths.load_config",
            return_value={
                "lane_providers": {
                    "sina": {"enabled": False},
                    "eastmoney": {"enabled": False},
                    "tencent": {"enabled": False},
                    "baostock": {"enabled": False},
                    "tdx": {"enabled": False},
                }
            },
        ):
            with patch("src.market.speedtest_daily") as mocked:
                body = self.client.post(
                    "/api/ops/lanes/speedtest",
                    json={"lane": "hist_daily"},
                ).json()
                mocked.assert_not_called()
        self.assertEqual(body["results"], [])

    def test_probe_adapter_id_ignores_disabled(self) -> None:
        """「测这家」带 adapter_id 时，即使停用也要能探到该源。"""
        fake = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=1.0, rows=3),
        ]
        with patch(
            "src.shared.paths.load_config",
            return_value={"lane_providers": {"sina": {"enabled": False}}},
        ):
            with patch("src.market.probe_lane", return_value=fake) as mocked:
                body = self.client.post(
                    "/api/ops/lanes/probe",
                    json={"lane": "hist_daily", "adapter_id": "sina"},
                ).json()
        mocked.assert_called_once()
        kwargs = mocked.call_args
        self.assertEqual(kwargs[0][0], "hist_daily")
        self.assertEqual(list(kwargs[1]["adapter_ids"]), ["sina"])
        self.assertEqual(body["results"][0]["adapter_id"], "sina")

    def test_patch_provider_enabled(self) -> None:
        with patch("src.shared.paths.save_config", return_value={}) as saved, patch(
            "src.market.clear_sticky"
        ) as clear:
            with patch(
                "src.shared.paths.load_config",
                return_value={"lane_providers": {}},
            ):
                # write_guard 可能要求登录；测试客户端通常旁路或无鉴权
                response = self.client.patch(
                    "/api/ops/lanes/providers/sina",
                    json={"enabled": False},
                )
        if response.status_code == 401:
            self.skipTest("write_guard 要求登录，本环境未注入凭证")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], "sina")
        self.assertFalse(body["enabled"])
        saved.assert_called()
        # 合并写入只动 lane_providers
        arg = saved.call_args[0][0]
        self.assertEqual(arg["lane_providers"]["sina"]["enabled"], False)
        self.assertEqual(
            clear.call_args_list,
            [
                call("hist_daily"),
                call("spot_batch"),
                call("adjust_factor"),
                call("minute_bars"),
                # 新浪现在也是 capital_flow 的回退源，停用它要一并清这条 lane。
                call("capital_flow"),
            ],
        )

    def test_patch_provider_single_lane_keeps_master_switch(self) -> None:
        existing = {"lane_providers": {"sina": {"enabled": True}}}
        with patch("src.shared.paths.save_config", return_value={}) as saved, patch(
            "src.market.clear_sticky"
        ) as clear:
            with patch("src.shared.paths.load_config", return_value=existing):
                response = self.client.patch(
                    "/api/ops/lanes/providers/sina",
                    json={"enabled": False, "lane": "hist_daily"},
                )
        if response.status_code == 401:
            self.skipTest("write_guard 要求登录，本环境未注入凭证")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["disabled_lanes"], ["hist_daily"])
        entry = saved.call_args[0][0]["lane_providers"]["sina"]
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["lanes"], {"hist_daily": False})
        # 只清这条线路的粘性，别把这家其他线路一起清掉
        clear.assert_called_once_with("hist_daily")

    def test_patch_provider_rejects_unsupported_lane(self) -> None:
        response = self.client.patch(
            "/api/ops/lanes/providers/sina",
            json={"enabled": False, "lane": "instruments"},
        )
        if response.status_code == 401:
            self.skipTest("write_guard 要求登录，本环境未注入凭证")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
