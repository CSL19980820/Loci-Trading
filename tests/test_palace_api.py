from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from src.palace_api import LoginThrottle, create_app


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
        app = create_app(Path(self.temp.name) / "fallback.db", static_dir)
        with TestClient(app) as client:
            response = client.get("/archive/000722")
        self.assertEqual(response.status_code, 200)
        self.assertIn("palace-ui", response.text)

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
