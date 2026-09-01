"""悟道 MCP 配额：两个租户的在途计数与每分钟名额必须互不影响。

口径依据（详见 ``src/intel/infrastructure/quota.py`` 头部那段注释）：悟道 token 只
来自 ``mcp.json``，而 ``paths.mcp_json_path()`` 是**按租户**的，环境变量覆盖只对主
租户生效。一个租户 = 一个悟道账号 = 服务端各算各的 5000/天、50/分。所以日计数
（ops.db，本来就按租户）、在途占位、每分钟窗口三者必须同口径。

修之前只有日计数按租户，另两个是进程级的：租户 B 的在途调用会把 A 的已用额度
撞高，A 于是收到一条**假的**「配额已用尽」。
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.intel.infrastructure.quota import (
    McpQuotaError,
    acquire_quota,
    clear_quota_reservations,
    quota_snapshot,
    record_quota_call,
)
from src.shared.tenancy import tenant_scope


class QuotaTenantIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "LOCI_MCP_QUOTA_DAILY": "4",
                "LOCI_MCP_QUOTA_STRUCTURED": "2",
                "LOCI_MCP_QUOTA_SKILL": "2",
                "LOCI_MCP_RATE_PER_MIN": "0",
            },
        )
        self.env.start()
        clear_quota_reservations()

    def tearDown(self) -> None:
        clear_quota_reservations()
        self.env.stop()

    def test_inflight_of_one_tenant_never_eats_another_tenants_budget(self) -> None:
        """B 把自己的 structured 池占满，A 必须仍然发得出去。"""
        with tenant_scope("u_b"):
            acquire_quota("structured")
            acquire_quota("structured")
            with self.assertRaisesRegex(McpQuotaError, "结构化采集"):
                acquire_quota("structured")

        with tenant_scope("u_a"):
            # 修之前这里会拿 B 的两次在途去撞 A 的余额，直接抛「配额已用尽」。
            acquire_quota("structured")
            snap = quota_snapshot()
        self.assertEqual(snap["used"]["structured"], 0, "A 还没记账，已用量不该被 B 顶高")

    def test_recorded_calls_land_in_the_callers_own_ledger(self) -> None:
        with tenant_scope("u_a"):
            acquire_quota("skill")
            record_quota_call("skill")
            self.assertEqual(quota_snapshot()["used"]["skill"], 1)

        with tenant_scope("u_b"):
            self.assertEqual(quota_snapshot()["used"]["skill"], 0)
            acquire_quota("skill")
            record_quota_call("skill")
            self.assertEqual(quota_snapshot()["used"]["skill"], 1)

        with tenant_scope("u_a"):
            self.assertEqual(quota_snapshot()["used"]["skill"], 1, "A 的账本被 B 写脏了")

    def test_releasing_an_inflight_slot_only_touches_the_callers_bucket(self) -> None:
        """记账释放占位时，绝不能顺手把别人的占位弹掉。"""
        from src.intel.infrastructure import quota as mod

        with tenant_scope("u_b"):
            acquire_quota("structured")
        with tenant_scope("u_a"):
            acquire_quota("structured")
            record_quota_call("structured")

        self.assertEqual(len(mod._INFLIGHT.get(("u_b", "structured"), [])), 1)
        self.assertNotIn(("u_a", "structured"), mod._INFLIGHT)

    def test_per_minute_window_is_per_tenant_because_the_key_is_per_tenant(self) -> None:
        """每分钟限速保护的是**该租户自己那个悟道账号**，不能被别人吃掉名额。

        凭据在 ``mcp.json``（按租户），所以限速也按租户。若哪天改成全平台共用一个
        悟道账号，这条与日计数要**一起**改回全局——只改一个就又撕裂了。
        """
        from src.intel.infrastructure import quota as mod

        with patch.dict(os.environ, {"LOCI_MCP_RATE_PER_MIN": "1"}):
            with patch.object(mod, "_MINUTE_WAIT_MAX_SECONDS", 0.2):
                with tenant_scope("u_b"):
                    acquire_quota("structured")
                    # B 自己再发一次必须被节流到超时（名额已被自己占掉）。
                    with self.assertRaisesRegex(McpQuotaError, "每分钟名额"):
                        acquire_quota("structured")
                with tenant_scope("u_a"):
                    # A 有自己的窗口，不该被 B 的那一次挤掉。
                    acquire_quota("structured")

        self.assertEqual(len(mod._MINUTE_WINDOW.get("u_a", [])), 1)
        self.assertEqual(len(mod._MINUTE_WINDOW.get("u_b", [])), 1)


if __name__ == "__main__":
    unittest.main()
