from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app.main import LoginThrottle, create_app


class PalaceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        app = create_app(Path(self.temp.name) / "palace.db", Path(self.temp.name) / "no-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_trade_candidate_plan_and_dashboard_flow(self) -> None:
        trade = self.client.post(
            "/api/trades",
            json={"action": "BUY", "code": "300358", "name": "楚天科技", "shares": 3200, "price": 8.3},
        )
        self.assertEqual(trade.status_code, 201)
        candidate = self.client.post(
            "/api/candidates",
            json={
                "code": "300358", "name": "楚天科技", "decision": "重点", "reason": "结构回踩后确认",
                "score": 82, "timing": "D-low", "pool_id": "POOL-2026-07-24", "occurred_on": "2026-07-24",
            },
        )
        self.assertEqual(candidate.status_code, 201)
        plan = self.client.post(
            "/api/plans",
            json={
                "code": "300358", "title": "回踩首仓", "scenario": "缩量止跌", "entry_zone": "8.10-8.30",
                "stop_price": 7.76, "target_price": 9.1, "layers": 1, "invalidation": "破位", "occurred_on": "2026-07-24",
            },
        )
        self.assertEqual(plan.status_code, 201)
        dashboard = self.client.get("/api/dashboard?date=2026-07-24")
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.json()
        self.assertEqual(payload["positions"][0]["code"], "300358")
        self.assertEqual(payload["candidates"][0]["id"], candidate.json()["id"])
        self.assertEqual(payload["plans"][0]["id"], plan.json()["id"])
        self.assertIn("candidate_summary", payload)
        self.assertGreaterEqual(payload["candidate_summary"]["selected_count"], 1)
        self.assertIn("picks", payload["candidate_summary"])
        self.assertTrue(isinstance(payload["candidate_summary"]["picks"][0], dict))
        self.assertIn("reason", payload["candidate_summary"]["picks"][0])

    def test_batch_delete_candidates(self) -> None:
        ids: list[str] = []
        for code, name in (("600000", "浦发银行"), ("600519", "贵州茅台")):
            created = self.client.post(
                "/api/candidates",
                json={
                    "code": code,
                    "name": name,
                    "decision": "观察",
                    "reason": "批量删除测",
                    "occurred_on": "2026-07-27",
                },
            )
            self.assertEqual(created.status_code, 201)
            ids.append(created.json()["id"])

        deleted = self.client.post("/api/candidates/batch-delete", json={"ids": ids})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["removed"], 2)
        listed = self.client.get("/api/candidates/list")
        self.assertEqual(listed.status_code, 200)
        remaining = {item["id"] for item in listed.json()}
        self.assertTrue(remaining.isdisjoint(ids))

    def test_journal_pool_review_and_analytics_endpoints(self) -> None:
        self.client.post(
            "/api/trades",
            json={"action": "BUY", "code": "300358", "name": "楚天科技", "shares": 100, "price": 8.3, "occurred_on": "2026-07-20"},
        )
        self.client.post(
            "/api/trades",
            json={"action": "SELL", "code": "300358", "shares": 40, "price": 8.8, "occurred_on": "2026-07-22"},
        )
        self.client.post(
            "/api/candidates",
            json={
                "code": "300358", "name": "楚天科技", "decision": "重点", "reason": "结构回踩",
                "score": 82, "pool_id": "POOL-2026-07-24", "occurred_on": "2026-07-24",
            },
        )
        self.client.post(
            "/api/candidates",
            json={
                "code": "000722", "name": "湖南发展", "decision": "落选", "reason": "量能不足",
                "score": 50, "pool_id": "POOL-2026-07-24", "occurred_on": "2026-07-24",
            },
        )
        created = self.client.post(
            "/api/reviews",
            json={
                "entity_type": "trade",
                "entity_id": "TX-TEST",
                "outcome": "减仓节奏正确",
                "return_pct": 2.1,
                "lesson": "按预案减",
                "next_rule": "保留分批",
                "reviewed_on": "2026-07-23",
            },
        )
        self.assertEqual(created.status_code, 201)

        trades = self.client.get("/api/trades")
        pools = self.client.get("/api/pools")
        day = self.client.get("/api/pools/day?date=2026-07-24")
        reviews = self.client.get("/api/reviews")
        analytics = self.client.get("/api/analytics")

        self.assertEqual(trades.status_code, 200)
        self.assertEqual(len(trades.json()), 2)
        self.assertEqual(pools.status_code, 200)
        self.assertEqual(pools.json()[0]["selected"], 1)
        self.assertEqual(day.status_code, 200)
        self.assertEqual(day.json()["filtered_count"], 1)
        self.assertEqual(reviews.status_code, 200)
        self.assertEqual(reviews.json()[0]["outcome"], "减仓节奏正确")
        self.assertEqual(analytics.status_code, 200)
        self.assertIn("equity_curve", analytics.json())

    def test_today_alerts_and_csv_export(self) -> None:
        import os

        import numpy as np
        import pandas as pd

        from src.market.infrastructure.store import MarketStore

        market_path = Path(self.temp.name) / "market.db"
        market = MarketStore(market_path)
        dates = ["2026-07-20", "2026-07-21", "2026-07-22"]
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": np.full(3, 8.0),
                "high": np.full(3, 8.5),
                "low": np.full(3, 7.4),
                "close": [8.2, 8.0, 7.5],
                "volume": np.full(3, 1_000_000.0),
                "amount": np.full(3, 8_000_000.0),
                "outstanding_share": np.full(3, 1e9),
                "turnover": np.full(3, 0.001),
            }
        )
        market.upsert_quotes("300358", frame, source="test")
        market.close()

        prev_market = os.environ.get("PALACE_MARKET_DB")
        os.environ["PALACE_MARKET_DB"] = str(market_path)
        try:
            # market_db 是构造期注入的：环境变量要先于 create_app 就位
            self.client.close()
            app = create_app(
                Path(self.temp.name) / "palace.db",
                Path(self.temp.name) / "no-static",
            )
            self.client = TestClient(app)
            self.client.post(
                "/api/plans",
                json={
                    "code": "300358",
                    "title": "回踩首仓",
                    "scenario": "缩量止跌",
                    "stop_price": 7.76,
                    "target_price": 9.1,
                    "occurred_on": "2026-07-20",
                },
            )
            alerts = self.client.get("/api/alerts/today")
            self.assertEqual(alerts.status_code, 200)
            payload = alerts.json()
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["status"], "stop_hit")
            self.assertAlmostEqual(payload[0]["last_close"], 7.5)

            trade = self.client.post(
                "/api/trades",
                json={
                    "action": "BUY",
                    "code": "300358",
                    "name": "楚天科技",
                    "shares": 100,
                    "price": 8.3,
                    "reason": "试仓",
                },
            )
            self.assertEqual(trade.status_code, 201)
            csv_resp = self.client.get("/api/trades/export.csv")
            self.assertEqual(csv_resp.status_code, 200)
            self.assertIn("text/csv", csv_resp.headers["content-type"])
            body = csv_resp.content.decode("utf-8-sig")
            self.assertIn("日期", body)
            self.assertIn("300358", body)
            self.assertIn("试仓", body)
        finally:
            if prev_market is None:
                os.environ.pop("PALACE_MARKET_DB", None)
            else:
                os.environ["PALACE_MARKET_DB"] = prev_market

    def test_qianlong_import_preview_confirm_flow(self) -> None:
        import io
        import json

        state = {
            "updatedAt": "2026-07-24",
            "totalAssets": 206400,
            "realizedPnlCumulative": -11104,
            "holdings": [{"name": "楚天科技", "code": "300358", "cost": 8.3, "shares": 3200}],
        }
        payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
        preview = self.client.post(
            "/api/import/qianlong/preview",
            files={"file": ("state.json", io.BytesIO(payload), "application/json")},
        )
        self.assertEqual(preview.status_code, 200)
        preview_body = preview.json()
        self.assertTrue(preview_body["can_import"])
        self.assertEqual(preview_body["holdings_count"], 1)

        confirm = self.client.post(
            "/api/import/qianlong/confirm",
            files={"file": ("state.json", io.BytesIO(payload), "application/json")},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(len(confirm.json()["position_events"]), 1)

        trades = self.client.get("/api/trades")
        self.assertEqual(trades.status_code, 200)
        self.assertEqual(len(trades.json()), 1)
        self.assertEqual(trades.json()[0]["action"], "OPENING")

        preview_again = self.client.post(
            "/api/import/qianlong/preview",
            files={"file": ("state.json", io.BytesIO(payload), "application/json")},
        )
        self.assertEqual(preview_again.status_code, 200)
        self.assertFalse(preview_again.json()["can_import"])

    def test_rejects_invalid_position_change(self) -> None:
        response = self.client.post(
            "/api/trades", json={"action": "SELL", "code": "300358", "shares": 100, "price": 8.3}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("没有可卖出的仓位", response.json()["detail"])

    def test_static_ui_falls_back_to_index_for_client_side_route(self) -> None:
        static_dir = Path(self.temp.name) / "dist"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html><body>palace-ui</body></html>", encoding="utf-8")
        assets = static_dir / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
        app = create_app(Path(self.temp.name) / "fallback.db", static_dir)
        with TestClient(app) as client:
            response = client.get("/archive/000722")
            asset = client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("palace-ui", response.text)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        self.assertEqual(asset.status_code, 200)
        self.assertIn("immutable", asset.headers.get("cache-control", ""))

    def test_production_login_or_agent_token_protects_the_ledger(self) -> None:
        app = create_app(
            Path(self.temp.name) / "production.db",
            Path(self.temp.name) / "no-static",
            environment="production",
            allowed_hosts=["testserver"],
            write_token="test-agent-token",
            auth_username="admin",
            auth_password="test-password",
            session_secret="test-session-secret",
        )
        payload = {"action": "BUY", "code": "300358", "name": "楚天科技", "shares": 100, "price": 8.3}
        # 生产形态是 HTTPS：会话 Cookie 带 Secure，只会经加密信道回传。
        # 用 http:// 跑这个用例的话客户端不会带回 Cookie，那是正确行为。
        with TestClient(app, base_url="https://testserver") as client:
            blocked_read = client.get("/api/dashboard")
            bad_login = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            login = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
            readable = client.get("/api/dashboard")
            allowed_by_session = client.post("/api/trades", json=payload)
            session = client.get("/api/auth/session")
            logout = client.post("/api/auth/logout")
            blocked_after_logout = client.get("/api/dashboard")
            allowed_by_agent = client.post(
                "/api/trades",
                json={**payload, "code": "300359"},
                headers={"Authorization": "Bearer test-agent-token"},
            )
            extra = client.post(
                "/api/trades",
                json={**payload, "unknown_field": "not accepted"},
                headers={"Authorization": "Bearer test-agent-token"},
            )
        self.assertEqual(blocked_read.status_code, 401)
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(login.status_code, 200)
        self.assertIn("max-age=2592000", login.headers["set-cookie"].lower())
        self.assertIn("httponly", login.headers["set-cookie"].lower())
        self.assertIn("samesite=lax", login.headers["set-cookie"].lower())
        self.assertIn("secure", login.headers["set-cookie"].lower())
        self.assertEqual(readable.status_code, 200)
        self.assertEqual(allowed_by_session.status_code, 201)
        self.assertTrue(session.json()["authenticated"])
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(blocked_after_logout.status_code, 401)
        self.assertEqual(allowed_by_agent.status_code, 201)
        self.assertEqual(extra.status_code, 422)
        self.assertEqual(allowed_by_session.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", allowed_by_session.headers["content-security-policy"])

    def test_production_data_location_requires_auth_after_setup(self) -> None:
        """首次向导完成后，数据与配置路径不能再匿名暴露。"""
        app = self._production_app("data-location.db")
        with patch("src.shared.paths.needs_setup", return_value=False):
            with TestClient(app, base_url="https://testserver") as client:
                response = client.get("/api/ops/data-location")
                authenticated = client.get(
                    "/api/ops/data-location",
                    headers={"Authorization": "Bearer test-agent-token"},
                )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)

    def test_production_health_does_not_expose_database_path(self) -> None:
        app = self._production_app("health.db")
        with TestClient(app, base_url="https://testserver") as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_production_data_location_stays_public_during_initial_setup(self) -> None:
        app = self._production_app("data-location-setup.db")
        with patch("src.shared.paths.needs_setup", return_value=True):
            with TestClient(
                app,
                base_url="https://testserver",
                client=("127.0.0.1", 50000),
            ) as client:
                response = client.get("/api/ops/data-location")
                proxied = client.get(
                    "/api/ops/data-location",
                    headers={"X-Forwarded-For": "198.51.100.19"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(proxied.status_code, 401)

    def test_production_data_location_rejects_remote_initial_setup(self) -> None:
        """远端首次请求既不能读路径，也不能借首启写入目录。"""
        app = self._production_app("data-location-remote.db")
        target = Path(self.temp.name) / "remote-initial-data"
        with patch("src.shared.paths.needs_setup", return_value=True):
            with TestClient(
                app,
                base_url="https://testserver",
                client=("198.51.100.19", 50000),
            ) as client:
                anonymous_read = client.get("/api/ops/data-location")
                anonymous_write = client.post(
                    "/api/ops/data-location",
                    json={"data_dir": str(target), "setup_done": True},
                )
                authenticated_read = client.get(
                    "/api/ops/data-location",
                    headers={"Authorization": "Bearer test-agent-token"},
                )

        self.assertEqual(anonymous_read.status_code, 401)
        self.assertEqual(anonymous_write.status_code, 401)
        self.assertEqual(authenticated_read.status_code, 200)
        self.assertFalse(target.exists())

    def _production_app(self, name: str, **overrides: object):
        kwargs: dict[str, object] = {
            "environment": "production",
            "allowed_hosts": ["testserver"],
            "write_token": "test-agent-token",
            "auth_username": "admin",
            "auth_password": "test-password",
            "session_secret": "test-session-secret",
        }
        kwargs.update(overrides)
        return create_app(
            Path(self.temp.name) / name, Path(self.temp.name) / "no-static", **kwargs
        )

    def test_insecure_http_mode_drops_the_secure_flag(self) -> None:
        """HTTP 临时排障模式必须显式声明，才允许 Cookie 不带 Secure。"""
        app = self._production_app("insecure.db", insecure_http=True)
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login", json={"username": "admin", "password": "test-password"}
            )
            readable = client.get("/api/dashboard")
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("secure", login.headers["set-cookie"].lower())
        self.assertEqual(readable.status_code, 200)

    def test_login_throttles_after_repeated_failures(self) -> None:
        """连续失败达到阈值后锁定，且锁定期内正确口令同样被拒。"""
        app = self._production_app("throttle.db")
        with TestClient(app, base_url="https://testserver") as client:
            failures = [
                client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
                for _ in range(5)
            ]
            blocked = client.post(
                "/api/auth/login", json={"username": "admin", "password": "wrong"}
            )
            blocked_even_with_right_password = client.post(
                "/api/auth/login", json={"username": "admin", "password": "test-password"}
            )
        self.assertTrue(all(item.status_code == 401 for item in failures))
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)
        self.assertEqual(blocked_even_with_right_password.status_code, 429)

    def test_successful_login_clears_the_failure_counter(self) -> None:
        """登录成功要把计数清零，否则零星手滑会累积成误锁。"""
        app = self._production_app("throttle-reset.db")
        with TestClient(app, base_url="https://testserver") as client:
            for _ in range(4):
                client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            ok = client.post(
                "/api/auth/login", json={"username": "admin", "password": "test-password"}
            )
            for _ in range(4):
                client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            still_allowed = client.post(
                "/api/auth/login", json={"username": "admin", "password": "test-password"}
            )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(still_allowed.status_code, 200)


class LoginThrottleTests(unittest.TestCase):
    def test_failures_expire_out_of_the_window(self) -> None:
        """窗口滑过后自动解锁，不需要重启进程。"""
        throttle = LoginThrottle(max_failures=2, window_seconds=0)
        throttle.record_failure("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        self.assertEqual(throttle.retry_after("1.2.3.4"), 0)

    def test_counts_are_per_source(self) -> None:
        """一个来源被锁不应连坐其他来源。"""
        throttle = LoginThrottle(max_failures=2)
        throttle.record_failure("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        self.assertGreater(throttle.retry_after("1.2.3.4"), 0)
        self.assertEqual(throttle.retry_after("5.6.7.8"), 0)


if __name__ == "__main__":
    unittest.main()
