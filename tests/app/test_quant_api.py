from __future__ import annotations

import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.app.main import create_app

SKILL_MANIFEST = """---
name: 测试技能
slug: test-skill
version: 0.1.0
description: 用于接口测试
schedule: "0 16 * * 1-5"
---

请按步骤执行。
"""


def _skill_zip(extra: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_MANIFEST)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


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

        with MarketStore(os.environ["PALACE_MARKET_DB"]) as store:
            store.upsert_instruments(
                [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "market": "SH",
                        "instrument_type": "STOCK",
                    }
                ]
            )

        persisted = threading.Event()
        captured: dict[str, object] = {}

        def fake_apply_today_spot(*args, **kwargs) -> int:
            captured.update(kwargs)
            persisted.set()
            return 1

        with (
            patch(
                "src.market.infrastructure.live_tape.fetch_live_quotes",
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
            patch("src.market.api.router.board_spot_persist_gate", return_value=True),
            patch("src.market.apply_today_spot", side_effect=fake_apply_today_spot),
        ):
            response = self.client.get("/api/market/board?live=true&page_size=1")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(persisted.wait(timeout=2), "实时行情返回后未触发当日行情落库")
        live_quotes = captured.get("live_quotes")
        self.assertIsInstance(live_quotes, list)
        self.assertEqual(live_quotes[0]["code"], "600519")

    def test_live_board_does_not_consume_persist_window_for_empty_quotes(self) -> None:
        """首轮空行情不应让下一轮有效行情等待节流窗口才落库。"""
        import os

        from src.market import MarketStore

        with MarketStore(os.environ["PALACE_MARKET_DB"]) as store:
            store.upsert_instruments(
                [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "market": "SH",
                        "instrument_type": "STOCK",
                    }
                ]
            )

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
            patch("src.market.infrastructure.live_tape.fetch_live_quotes", side_effect=[[], [quote]]),
            patch("src.market.apply_today_spot", side_effect=lambda *_a, **_k: persisted.set() or 1),
            patch("src.market.api.router._SPOT_PERSIST_LAST", 0.0),
        ):
            first = self.client.get("/api/market/board?live=true&page_size=1")
            second = self.client.get("/api/market/board?live=true&page_size=1")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(persisted.wait(timeout=2), "有效实时行情被空响应错误节流")

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

        with patch("src.market.api.router.market_store", return_value=FakeStore()):
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

        with patch("src.market.api.router.market_store", return_value=FakeStore()):
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
        self.assertEqual(body["cron"], "*/10 9-14 * * 1-5")
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


class ProductionAuthTests(unittest.TestCase):
    """新增的写接口必须和账本写入走同一道门，不能开旁路。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        app = create_app(
            base / "palace.db", base / "no-static",
            environment="production", allowed_hosts=["testserver"],
            write_token="test-token", auth_username="admin",
            auth_password="pw", session_secret="secret",
        )
        self.client = TestClient(app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_write_endpoints_reject_anonymous_callers(self) -> None:
        for method, path, kwargs in (
            ("post", "/api/jobs", {"json": {"name": "x", "kind": "sync"}}),
            ("post", "/api/skills", {"files": {"file": ("s.zip", _skill_zip(), "application/zip")}}),
            ("post", "/api/market/sync", {"json": {}}),
            ("delete", "/api/providers/x", {}),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 401, f"{path} 未鉴权就放行了")

    def test_sync_screen_candidate_writes_use_write_guard(self) -> None:
        """默认入库的同步选股必须在计算和持久化前经过写守卫。"""
        from src.strategy.api.router import build_strategy_router

        def reject_write() -> None:
            raise HTTPException(status_code=401, detail="write access denied")

        app = FastAPI()
        app.include_router(build_strategy_router(write_dependency=reject_write))
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch(
                "src.strategy.api.router.market_store",
                side_effect=AssertionError("写守卫应在选股前拒绝请求"),
            ),
            patch("src.strategy.api.router.should_sync_today", return_value=False),
        ):
            for method, path, kwargs in (
                ("post", "/api/strategies/screen", {"json": {"strategy": "qianlong-close-v3"}}),
                ("get", "/api/screen/today?strategy=qianlong-close-v3", {}),
            ):
                with self.subTest(path=path):
                    response = getattr(client, method)(path, **kwargs)
                    self.assertEqual(response.status_code, 401, response.text)

    def test_agent_bearer_token_is_accepted(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"name": "x", "kind": "sync"},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_read_endpoints_also_require_auth_in_production(self) -> None:
        self.assertEqual(self.client.get("/api/strategies").status_code, 401)
        self.assertEqual(self.client.get("/api/capabilities").status_code, 401)


if __name__ == "__main__":
    unittest.main()


class AnalysisEndpointTests(unittest.TestCase):
    """横向对比与退出扫描是分钟级任务，必须异步——同步返回会被网关掐断。

    这里只验接口契约，不真跑分析：真跑一轮要几十秒，且后台线程会持着
    SQLite 连接，临时目录清不掉。用 patch 把执行本身换成空操作。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        self.client = TestClient(create_app(base / "palace.db", base / "no-static"))
        self._patch = patch("src.ops.run_job", return_value={"status": "success"})
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.client.close()
        # 后台线程会持着 SQLite 连接；不等它收工，Windows 上删不掉临时目录。
        for thread in threading.enumerate():
            if thread.name.startswith("analysis-"):
                thread.join(timeout=10)
        self.temp.cleanup()

    def test_returns_202_with_a_pollable_job_id(self) -> None:
        response = self.client.post("/api/analysis/compare", json={"holds": [1]})
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertTrue(body["job_id"])
        self.assertIn("job_id=", body["poll"])

    def test_optimize_requires_a_strategy(self) -> None:
        response = self.client.post("/api/analysis/optimize", json={"holds": [1]})
        self.assertEqual(response.status_code, 422)
        self.assertIn("strategy", response.json()["detail"])

    def test_unknown_kind_is_rejected_by_the_path_schema(self) -> None:
        self.assertEqual(self.client.post("/api/analysis/mystery", json={}).status_code, 422)

    def test_extra_field_is_rejected(self) -> None:
        response = self.client.post("/api/analysis/compare", json={"nope": 1})
        self.assertEqual(response.status_code, 422)

    def test_repeated_triggers_reuse_one_job_record(self) -> None:
        """一次性分析不该在任务表里积累一堆同类型僵尸任务。"""
        first = self.client.post("/api/analysis/compare", json={"holds": [1]}).json()
        second = self.client.post("/api/analysis/compare", json={"holds": [3]}).json()
        self.assertEqual(first["job_id"], second["job_id"])

    def test_analysis_job_is_created_disabled(self) -> None:
        """即时分析不该被调度器捡去定时跑。"""
        body = self.client.post("/api/analysis/compare", json={"holds": [1]}).json()
        jobs = {job["id"]: job for job in self.client.get("/api/jobs").json()}
        self.assertFalse(jobs[body["job_id"]]["enabled"])
        self.assertEqual(jobs[body["job_id"]]["cron"], "")

    def test_analysis_uses_a_run_snapshot_and_returns_that_run_id(self) -> None:
        calls: list[tuple[object, str | None]] = []

        def fake_run_job(_store, job, **kwargs):
            calls.append((job, kwargs.get("run_id")))
            return {"status": "success"}

        with patch("src.ops.run_job", side_effect=fake_run_job):
            first = self.client.post(
                "/api/analysis/compare", json={"holds": [1]}
            ).json()
            second = self.client.post(
                "/api/analysis/compare", json={"holds": [3]}
            ).json()
            for thread in list(threading.enumerate()):
                if thread.name.startswith("analysis-"):
                    thread.join(timeout=5)

        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertIn(f"run_id={first['run_id']}", first["poll"])
        self.assertIn(f"run_id={second['run_id']}", second["poll"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(isinstance(job, dict) for job, _ in calls))
        self.assertEqual(
            {int(job["config"]["holds"][0]) for job, _ in calls},
            {1, 3},
        )
        self.assertEqual(
            {run_id for _, run_id in calls},
            {first["run_id"], second["run_id"]},
        )

    def test_analysis_thread_start_failure_marks_run_failed(self) -> None:
        """任务槽已落库后若线程无法启动，不能留下永远 running 的历史。"""
        with patch("src.strategy.api.router.threading.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("no thread slots")
            response = self.client.post("/api/analysis/compare", json={"holds": [1]})

        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("no thread slots", response.json()["detail"])

        from src.ops import OpsStore
        import os

        with OpsStore(os.environ["PALACE_OPS_DB"]) as store:
            job = store.get_job_by_name("[即时] compare")
            self.assertIsNotNone(job)
            runs = store.list_runs(job_id=job["id"], limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("no thread slots", runs[0]["error_text"])


class ShouldSyncTodayTests(unittest.TestCase):
    def test_uses_explicit_market_db_not_default_path(self) -> None:
        """线上 PALACE_MARKET_DB 与默认 data/market.db 不是同一个库。"""
        from src.app.legacy.quant_common import should_sync_today

        with tempfile.TemporaryDirectory() as tmp:
            market_db = Path(tmp) / "prod-market.db"
            seen: list[str | None] = []

            class FakeStore:
                def __init__(self, path: str | None) -> None:
                    seen.append(None if path is None else str(path))

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def list_instruments(self):
                    return []

                def coverage(self):
                    return {"last_date": ""}

            with patch("src.market.MarketStore", FakeStore):
                self.assertTrue(should_sync_today(str(market_db)))
            self.assertEqual(seen, [str(market_db)])
