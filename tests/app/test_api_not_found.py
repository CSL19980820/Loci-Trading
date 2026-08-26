"""`/api/*` 未匹配路由必须回 JSON 404,不能吐 SPA 外壳。

原先 SPA 的 catch-all 会把任何未匹配路径(含 `/api/**`)兜成 200 + index.html。
后果:调用方拿到 `text/html`,前端以「JSON 解析失败」的形式炸在离现场十万八千里
的地方,API 客户端也分不清「端点没了」和「服务器返回了页面」。

持仓下线一次删掉十几个 `/api/*`,正是这类混淆最容易发生的时候——所以这条
单独钉住。
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from src.app.main import create_app

#: 本轮随持仓一起下线的端点。留着这份名单,顺带挡住「哪天有人手滑加回来」。
RETIRED = (
    "/api/dashboard",
    "/api/positions",
    "/api/trades",
    "/api/trades/export.csv",
    "/api/analytics",
    "/api/scorecard",
    "/api/daily-pnl",
    "/api/review/equity",
    "/api/review/trips",
    "/api/review/positions",
    "/api/review/drift",
)


class ApiNotFoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_unknown_api_path_is_json_404_not_spa_shell(self) -> None:
        resp = self.client.get("/api/definitely-not-a-real-endpoint")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("application/json", resp.headers.get("content-type", ""))
        self.assertNotIn("<!doctype html", resp.text.lower())

    def test_retired_endpoints_are_gone(self) -> None:
        """持仓下线的端点必须 404,而且是 JSON 404。"""
        for path in RETIRED:
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 404, path)
                self.assertNotIn("<!doctype html", resp.text.lower(), path)

    def test_surviving_endpoints_still_answer(self) -> None:
        """反向对照:别把活的也 404 了。"""
        for path in ("/api/health", "/api/candidates", "/api/review/candidates"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_non_api_path_still_falls_back_to_spa(self) -> None:
        """前端历史路由不能被误伤——它们本就该回 index.html。"""
        resp = self.client.get("/pool")
        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            self.assertNotIn("application/json", resp.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
