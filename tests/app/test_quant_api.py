"""组合根 HTTP 契约：路由挂载、技能上传与写权限。

鉴权 / 分析端点用例在 `test_quant_api_auth_analysis.py`；夹具在 `quant_api_fixtures.py`。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app.main import create_app

from tests.app.quant_api_fixtures import _skill_zip


class QuantApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        # 让 router 用临时库，不碰工作区里的真实数据。
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ["PALACE_SKILL_ROOT"] = str(base / "skills")
        (base / "skills").mkdir(parents=True, exist_ok=True)
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        app = create_app(base / "palace.db", base / "no-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    # ---- 能力探测 -------------------------------------------------

    def test_capabilities_reports_what_is_available(self) -> None:
        body = self.client.get("/api/capabilities").json()
        for key in ("market", "strategies", "backtest", "skills", "scheduler", "llm"):
            self.assertIn(key, body)
        self.assertIsInstance(body["missing"], list)

    def test_live_board_persists_snapshot_after_returning_quotes(self) -> None:
        """行情台实时列表返回后仍应启动节流的当日行情落库。"""
        import os

        from src.market import MarketStore

        instrument = {
            "code": "600519",
            "name": "贵州茅台",
            "market": "SH",
            "instrument_type": "STOCK",
        }
        # board 读热库；spot 落盘写全量库——两端都要有标的。
        for key in ("PALACE_MARKET_HOT_DB", "PALACE_MARKET_DB"):
            path = os.environ.get(key) or os.environ["PALACE_MARKET_DB"]
            with MarketStore(path) as store:
                store.upsert_instruments([instrument])

        persisted = threading.Event()
        captured: dict[str, object] = {}

        def fake_apply_today_spot(*args, **kwargs) -> int:
            captured.update(kwargs)
            persisted.set()
            return 1

        with (
            patch(
                "src.market.application.live.fetch_live_quotes",
                return_value=[
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "price": 1500.0,
                        "pct": 1.2,
                        "change": 18.0,
                        "prev_close": 1482.0,
                    }
                ],
            ),
            patch("src.market.api.board_router.board_spot_persist_gate", return_value=True),
            patch(
                "src.market.api.board_router.apply_spot_and_mirror",
                side_effect=fake_apply_today_spot,
            ),
        ):
            response = self.client.get(
                "/api/market/board?live=true&persist=true&page_size=1"
            )
            # 落库在后台线程；须在 patch 仍生效时等待，否则线程会打到真实 apply。
            self.assertTrue(persisted.wait(timeout=2), "实时行情返回后未触发当日行情落库")

        self.assertEqual(response.status_code, 200, response.text)
        live_quotes = captured.get("live_quotes")
        self.assertIsInstance(live_quotes, list)
        self.assertEqual(live_quotes[0]["code"], "600519")

    def test_live_board_does_not_consume_persist_window_for_empty_quotes(self) -> None:
        """首轮空行情不应让下一轮有效行情等待节流窗口才落库。"""
        import os

        from src.market import MarketStore

        instrument = {
            "code": "600519",
            "name": "贵州茅台",
            "market": "SH",
            "instrument_type": "STOCK",
        }
        for key in ("PALACE_MARKET_HOT_DB", "PALACE_MARKET_DB"):
            path = os.environ.get(key) or os.environ["PALACE_MARKET_DB"]
            with MarketStore(path) as store:
                store.upsert_instruments([instrument])

        persisted = threading.Event()
        quote = {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1500.0,
            "pct": 1.2,
            "change": 18.0,
            "prev_close": 1482.0,
        }
        with (
            patch(
                "src.market.application.live.fetch_live_quotes",
                side_effect=[[], [quote]],
            ),
            patch(
                "src.market.api.board_router.apply_spot_and_mirror",
                side_effect=lambda *_a, **_k: persisted.set() or {"written": 1},
            ),
            patch("src.market.api.board_router._SPOT_PERSIST_LAST", 0.0),
        ):
            first = self.client.get(
                "/api/market/board?live=true&persist=true&page_size=1"
            )
            second = self.client.get(
                "/api/market/board?live=true&persist=true&page_size=1"
            )
            self.assertTrue(persisted.wait(timeout=2), "有效实时行情被空响应错误节流")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

    def test_market_search_uses_database_pagination(self) -> None:
        """搜索不能把全量证券列表搬到 API 进程后再过滤。"""
        calls: list[dict[str, object]] = []

        class FakeStore:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def list_instruments(self, **kwargs):
                raise AssertionError("search must not load all instruments")

            def page_instruments(self, **kwargs):
                calls.append(kwargs)
                return 1, [{"code": "600519", "name": "贵州茅台"}]

        with patch("src.market.api.router.market_hot_store", return_value=FakeStore()):
            response = self.client.get("/api/market/search?q=茅台&limit=1")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [{"code": "600519", "name": "贵州茅台"}])
        self.assertEqual(calls, [{"q": "茅台", "instrument_type": None, "status": "", "offset": 0, "limit": 1}])

    def test_market_search_does_not_treat_whitespace_as_empty_query(self) -> None:
        class FakeStore:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def page_instruments(self, **kwargs):
                return 1, [{"code": "600519", "name": "贵州茅台"}]

        with patch("src.market.api.router.market_hot_store", return_value=FakeStore()):
            response = self.client.get("/api/market/search?q=%20%20")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_minute_rejects_invalid_code_as_client_error(self) -> None:
        response = self.client.get("/api/market/minute/not-a-code")

        self.assertEqual(response.status_code, 422, response.text)

    def test_minute_reports_actual_trade_date_when_query_date_is_omitted(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            {
                "datetime": ["2026-07-31 09:30:00"],
                "close": [10.5],
                "volume": [100],
            }
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_minute_routed",
            return_value=(frame, "test"),
        ), patch(
            "src.market.application.minute.unadjusted_prev_close",
            return_value=10.0,
        ):
            response = self.client.get("/api/market/minute/600519")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["trade_date"], "2026-07-31")
        self.assertEqual(body["prev_close"], 10.0)
        self.assertEqual(body["adjust"], "none")

    # ---- 策略 -----------------------------------------------------

    def test_lists_registered_strategies_with_entry_timing(self) -> None:
        """入场时点必须出现在接口里：前端和回测都要靠它才知道怎么用信号。"""
        items = self.client.get("/api/strategies").json()
        slugs = {item["slug"] for item in items}
        self.assertIn("qianlong-close-v3", slugs)
        for item in items:
            self.assertIn(item["entry_timing"], ("open", "close", "next_open", "next_dip"))
            self.assertIn("params", item)

    def test_strategy_job_upsert_persists_schedule_and_universe(self) -> None:
        """工坊详情保存：结构化定时 + 行情范围写入 ops job，并回传完整时间预览。"""
        unbound = self.client.get("/api/strategies/qianlong-close-v3/job").json()
        self.assertFalse(unbound["bound"])

        response = self.client.put(
            "/api/strategies/qianlong-close-v3/job",
            json={
                "schedule_mode": "interval",
                "interval_minutes": 10,
                "window_start_hour": 9,
                "window_start_minute": 30,
                "window_end_hour": 14,
                "window_end_minute": 50,
                "auto_review": True,
                "enabled": True,
                "universe": {
                    "preset": "custom",
                    "boards": ["main", "chi_next", "star"],
                    "exclude_st": True,
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["bound"])
        self.assertEqual(body["cron"], "*/10 9-14 * * mon-fri")
        self.assertTrue(body["enabled"])
        self.assertEqual(body["config"]["schedule"]["mode"], "interval")
        self.assertEqual(body["config"]["universe"]["boards"], ["main", "chi_next", "star"])
        self.assertTrue(body["config"]["universe"]["exclude_st"])
        self.assertTrue(body["config"]["push_wecom"])
        self.assertEqual(len(body["next_runs"]), 5)
        self.assertRegex(body["next_runs"][0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

        again = self.client.get("/api/strategies/qianlong-close-v3/job").json()
        self.assertTrue(again["bound"])
        self.assertEqual(again["config"]["schedule"]["interval_minutes"], 10)

        push_off = self.client.put(
            "/api/strategies/qianlong-close-v3/job",
            json={
                "schedule_mode": "once",
                "run_hour": 15,
                "run_minute": 30,
                "push_wecom": False,
                "universe": {"boards": ["main"], "exclude_st": True},
            },
        )
        self.assertEqual(push_off.status_code, 200, push_off.text)
        self.assertFalse(push_off.json()["config"]["push_wecom"])

        off = self.client.put(
            "/api/strategies/qianlong-close-v3/job",
            json={"schedule_mode": "off", "universe": {"boards": ["main"], "exclude_st": False}},
        )
        self.assertEqual(off.status_code, 200, off.text)
        self.assertFalse(off.json()["bound"])
        self.assertEqual(off.json()["next_runs"], [])
        gone = self.client.get("/api/strategies/qianlong-close-v3/job").json()
        self.assertFalse(gone["bound"])

    def test_skill_job_upsert_persists_push_wecom(self) -> None:
        """技能详情保存定时 + 推送开关，写入 skill:{slug}。"""
        install = self.client.post(
            "/api/skills",
            files={"file": ("test-skill.zip", _skill_zip(), "application/zip")},
        )
        self.assertEqual(install.status_code, 201, install.text)

        unbound = self.client.get("/api/skills/test-skill/job").json()
        self.assertFalse(unbound["bound"])

        bad = self.client.put(
            "/api/skills/test-skill/job",
            json={"schedule_mode": "once", "run_hour": 15, "run_minute": 30},
        )
        self.assertEqual(bad.status_code, 422)

        response = self.client.put(
            "/api/skills/test-skill/job",
            json={
                "schedule_mode": "once",
                "run_hour": 15,
                "run_minute": 30,
                "provider": "demo-llm",
                "push_wecom": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["bound"])
        self.assertEqual(body["name"], "skill:test-skill")
        self.assertEqual(body["kind"], "skill")
        self.assertTrue(body["config"]["push_wecom"])
        self.assertEqual(body["config"]["provider"], "demo-llm")

        off = self.client.put(
            "/api/skills/test-skill/job",
            json={"schedule_mode": "off", "provider": "demo-llm"},
        )
        self.assertEqual(off.status_code, 200, off.text)
        self.assertFalse(off.json()["bound"])

    def test_screen_on_empty_market_reports_clearly(self) -> None:
        """行情仓是空的时候要给可读的 422，而不是 500。"""
        response = self.client.post(
            "/api/strategies/screen", json={"strategy": "qianlong-close-v3"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("行情", response.json()["detail"])

    def test_unknown_strategy_is_422(self) -> None:
        response = self.client.post("/api/strategies/screen", json={"strategy": "nope"})
        self.assertEqual(response.status_code, 422)

    def test_extra_field_is_rejected(self) -> None:
        """与账本写入同样的严格校验：多字段就 422，不静默忽略。"""
        response = self.client.post(
            "/api/strategies/screen",
            json={"strategy": "qianlong-close-v3", "unknown": 1},
        )
        self.assertEqual(response.status_code, 422)

    def test_universe_accepts_bse_board_explicitly(self) -> None:
        response = self.client.post(
            "/api/universe/preview",
            json={
                "preset": "custom",
                "boards": ["main", "bse"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["universe"]["boards"], ["main", "bse"])

    def test_universe_presets_endpoint(self) -> None:
        response = self.client.get("/api/universe/presets")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body)
        self.assertTrue(any("bse" in item["boards"] for item in body))
        default = next(item for item in body if item["id"] == "default_a_share")
        self.assertNotIn("bse", default["boards"])
        self.assertTrue(default["exclude_st"])
