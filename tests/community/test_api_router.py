"""社区路由冒烟测试：工厂契约、401/403/422 映射、鸭子类型的 auth_dependency。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.community import build_community_router
from tests.community.conftest import valid_payload


class _Auth:
    """可切换当前用户的假鉴权依赖。匿名时返回 None（工厂契约要求不抛 401）。"""

    def __init__(self) -> None:
        self.current: Any = None

    def __call__(self) -> Any:
        return self.current


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    auth = _Auth()
    app.include_router(
        build_community_router(
            write_dependency=lambda: None,
            auth_dependency=auth,
            community_db=str(tmp_path / "community.db"),
        )
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.actor_holder = auth  # httpx 的 .auth 是鉴权流，别占用
        yield test_client


def _login(client, user_id: str = "u-author", name: str = "老王", admin: bool = False) -> None:
    client.actor_holder.current = {"user_id": user_id, "display_name": name, "is_admin": admin}


def test_square_is_readable_anonymously(client) -> None:
    response = client.get("/api/community/strategies")
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "pages": 0,
        "sort": "hot",
    }


def test_write_endpoints_require_a_current_user(client) -> None:
    assert client.post("/api/community/strategies", json=valid_payload()).status_code == 401
    assert client.get("/api/community/subscriptions").status_code == 401


def test_publish_flow_over_http(client) -> None:
    _login(client)
    created = client.post("/api/community/strategies", json=valid_payload())
    assert created.status_code == 201, created.text
    publish_id = created.json()["strategy"]["publish_id"]

    detail = client.get(f"/api/community/strategies/{publish_id}")
    assert detail.status_code == 200
    assert detail.json()["strategy"]["title"] == "潜龙尾盘打板"

    versions = client.get(f"/api/community/strategies/{publish_id}/versions")
    assert [item["version"] for item in versions.json()] == [1]

    new_version = client.post(
        f"/api/community/strategies/{publish_id}/versions",
        json={
            "source_text": "v2",
            "release_notes": "调参",
            "backtest": valid_payload()["backtest"],
        },
    )
    assert new_version.status_code == 201
    assert new_version.json()["version"]["version"] == 2

    delisted = client.post(f"/api/community/strategies/{publish_id}/delist")
    assert delisted.status_code == 200
    assert delisted.json()["strategy"]["status"] == "delisted"


def test_publish_rule_failure_returns_422_with_violations(client) -> None:
    """schema 过得去、上架清单过不去的 payload，走领域错误映射（含逐条 violations）。"""
    _login(client)
    weak = valid_payload(
        backtest={
            "trades": 5,
            "start": "2024-01-01",
            "end": "2024-03-01",
            "commission_bps": 0,
            "stamp_duty_bps": 10,
            "slippage_bps": 5,
        }
    )
    response = client.post("/api/community/strategies", json=weak)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "publish_rules_failed"
    codes = {item["code"] for item in detail["violations"]}
    assert {"trades_too_few", "backtest_window_too_short", "cost_zero_commission_bps"} <= codes


def test_missing_backtest_is_rejected_by_the_schema(client) -> None:
    """回测证据是必填字段，连 body 校验都过不去。"""
    _login(client)
    payload = valid_payload()
    payload.pop("backtest")
    assert client.post("/api/community/strategies", json=payload).status_code == 422


def test_unknown_body_field_is_rejected(client) -> None:
    _login(client)
    response = client.post("/api/community/strategies", json=valid_payload(mode="auto_trade"))
    assert response.status_code == 422


def test_star_clone_and_comment_endpoints(client) -> None:
    _login(client)
    publish_id = client.post("/api/community/strategies", json=valid_payload()).json()["strategy"][
        "publish_id"
    ]
    _login(client, user_id="u-reader", name="小张")

    assert client.post(f"/api/community/strategies/{publish_id}/star").json()["stars"] == 1
    assert client.delete(f"/api/community/strategies/{publish_id}/star").json()["stars"] == 0

    clone = client.post(f"/api/community/strategies/{publish_id}/clone", json={})
    assert clone.status_code == 200
    assert clone.json()["bundle"]["imported_from"] == "community"

    comment = client.post(
        f"/api/community/strategies/{publish_id}/comments", json={"body": "学习了"}
    )
    assert comment.status_code == 201
    comment_id = comment.json()["id"]
    assert len(client.get(f"/api/community/strategies/{publish_id}/comments").json()) == 1
    assert client.delete(f"/api/community/comments/{comment_id}").json()["deleted"] is True


def test_subscribe_and_pull_signals(client) -> None:
    _login(client)
    publish_id = client.post("/api/community/strategies", json=valid_payload()).json()["strategy"][
        "publish_id"
    ]
    client.post(
        f"/api/community/strategies/{publish_id}/signals",
        json={"trade_date": "2026-08-27", "payload": {"codes": ["600519"]}},
    )
    _login(client, user_id="u-reader", name="小张")
    subscribed = client.post(
        f"/api/community/strategies/{publish_id}/subscribe", json={"notify_channels": ["inapp"]}
    )
    assert subscribed.status_code == 201
    assert subscribed.json()["mode"] == "signal_only"
    assert subscribed.json()["notice"] == "只推信号，不自动下单"

    signals = client.get("/api/community/subscriptions/signals")
    assert signals.json()["items"][0]["payload"]["codes"] == ["600519"]
    assert (
        client.delete(f"/api/community/strategies/{publish_id}/subscribe").json()["changed"] is True
    )


def test_subscription_mode_cannot_be_overridden(client) -> None:
    """合规红线：请求体里塞 mode 也不行——schema 根本没有这个字段。"""
    _login(client)
    publish_id = client.post("/api/community/strategies", json=valid_payload()).json()["strategy"][
        "publish_id"
    ]
    response = client.post(
        f"/api/community/strategies/{publish_id}/subscribe", json={"mode": "auto_trade"}
    )
    assert response.status_code == 422


def test_leaderboard_endpoints(client) -> None:
    _login(client)
    publish_id = client.post("/api/community/strategies", json=valid_payload()).json()["strategy"][
        "publish_id"
    ]
    metrics = client.post(
        f"/api/community/strategies/{publish_id}/metrics",
        json={"as_of": "2026-08-27", "sharpe_1y": 2.0, "live_days": 400, "trades": 55},
    )
    assert metrics.status_code == 201
    assert metrics.json()["score"] == 2.0

    # 普通用户不能重算榜单
    assert (
        client.post("/api/community/leaderboard/rebuild", json={"board": "overall"}).status_code
        == 403
    )
    _login(client, user_id="u-admin", name="管理员", admin=True)
    rebuilt = client.post(
        "/api/community/leaderboard/rebuild", json={"board": "overall", "as_of": "2026-08-27"}
    )
    assert rebuilt.json()["written"] == 1

    board = client.get("/api/community/leaderboard", params={"board": "overall", "limit": 10})
    assert board.json()["entries"][0]["publish_id"] == publish_id
    assert client.get("/api/community/leaderboard/boards").status_code == 200
    assert client.get("/api/community/leaderboard", params={"board": "乱来"}).status_code == 422


def test_feed_profile_and_follow(client) -> None:
    _login(client)
    client.post("/api/community/strategies", json=valid_payload())
    _login(client, user_id="u-reader", name="小张")
    assert client.post("/api/community/users/u-author/follow").json()["followers"] == 1
    profile = client.get("/api/community/users/u-author/profile")
    assert profile.json()["counts"]["strategies"] == 1
    assert profile.json()["viewer"]["following"] is True
    assert {item["verb"] for item in client.get("/api/community/feed").json()} == {
        "published",
        "followed",
    }
    assert client.delete("/api/community/users/u-author/follow").json()["followers"] == 0


def test_auth_context_objects_are_accepted(client) -> None:
    """``auth_dependency`` 可以返回 identity 的 AuthContext 形状，社区不与之绑死。"""
    client.actor_holder.current = SimpleNamespace(
        user=SimpleNamespace(id="u-ctx", display_name="上下文用户", role="admin")
    )
    created = client.post("/api/community/strategies", json=valid_payload())
    assert created.status_code == 201
    assert created.json()["strategy"]["owner_user_id"] == "u-ctx"
    assert created.json()["strategy"]["owner_name"] == "上下文用户"
    # 匿名上下文（user=None）等价于未登录
    client.actor_holder.current = SimpleNamespace(user=None)
    assert client.post("/api/community/strategies", json=valid_payload()).status_code == 401


def test_write_dependency_still_guards_writes(tmp_path) -> None:
    """组合根的写依赖被拒时，写接口一律 401，不看当前用户。"""

    def deny() -> None:
        raise HTTPException(status_code=401, detail="需要写权限")

    app = FastAPI()
    app.include_router(
        build_community_router(
            write_dependency=deny,
            auth_dependency=lambda: {"user_id": "u-author"},
            community_db=str(tmp_path / "community.db"),
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/community/strategies", json=valid_payload()).status_code == 401
        assert client.get("/api/community/strategies").status_code == 200


def test_missing_strategy_is_404(client) -> None:
    response = client.get("/api/community/strategies/PUB-nope")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
