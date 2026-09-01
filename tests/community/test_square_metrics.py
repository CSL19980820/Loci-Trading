"""广场卡片的绩效字段、净值曲线契约、以及「我收藏的」端点。

三件事都是同一个诉求：**卡片要能自己把话说完**——前端不该为了在列表上显示
年化 / 夏普 / 回撤 / 胜率，再去拉两次榜单回来拼。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.community import CommunityStore, build_community_router
from src.community.application import discovery, engagement, leaderboard, publishing
from src.community.domain.models import Actor, normalize_equity_curve
from tests.community.conftest import valid_payload

AS_OF = "2026-08-27"


def _publish(store: CommunityStore, actor: Actor, title: str) -> str:
    result = publishing.publish_strategy(
        store, actor=actor, payload=valid_payload(title=title, slug=title)
    )
    return str(result["strategy"]["publish_id"])


# ----------------------------------------------------------------- 广场卡片带绩效


def test_square_items_carry_the_latest_metrics(store: CommunityStore, author: Actor) -> None:
    """一次请求就够画卡片：不用再拉 /leaderboard 回来拼。"""
    publish_id = _publish(store, author, "carrier")
    leaderboard.record_metrics(
        store,
        publish_id,
        as_of=AS_OF,
        sharpe_1y=1.8,
        annual_return=32.5,
        max_drawdown=-0.18,
        win_rate=0.56,
        trades=44,
        live_days=400,
    )
    item = discovery.list_square(store)["items"][0]
    # 既有字段一个都不许变名——前端已经在用
    assert item["latest_score"] == pytest.approx(1.8)
    assert item["metrics_date"] == AS_OF
    metrics = item["metrics"]
    assert metrics["as_of_date"] == AS_OF
    assert metrics["sharpe_1y"] == pytest.approx(1.8)
    assert metrics["annual_return"] == pytest.approx(32.5)
    assert metrics["max_drawdown"] == pytest.approx(-0.18)
    assert metrics["win_rate"] == pytest.approx(0.56)
    assert metrics["trades"] == 44
    assert metrics["live_days"] == 400
    assert metrics["score"] == pytest.approx(1.8)
    # 中间列不许泄进响应
    assert not [key for key in item if key.startswith("mx_")]


def test_square_item_without_metrics_returns_null_not_an_error(
    store: CommunityStore, author: Actor
) -> None:
    """没跑过绩效的策略：``metrics`` 是 None，不是一堆 0，也不是 500。"""
    _publish(store, author, "fresh")
    item = discovery.list_square(store)["items"][0]
    assert item["metrics"] is None
    assert item["latest_score"] == 0.0
    assert item["metrics_date"] == ""


def test_square_metrics_takes_the_newest_as_of_date(store: CommunityStore, author: Actor) -> None:
    """同一个 publish 有多期切片时，卡片只认 ``as_of_date`` 最大的那一期。"""
    publish_id = _publish(store, author, "history")
    leaderboard.record_metrics(
        store, publish_id, as_of="2026-01-31", sharpe_1y=0.4, annual_return=4.0, trades=31
    )
    leaderboard.record_metrics(
        store, publish_id, as_of="2026-08-27", sharpe_1y=2.2, annual_return=44.0, trades=61
    )
    leaderboard.record_metrics(
        store, publish_id, as_of="2026-05-15", sharpe_1y=1.1, annual_return=11.0, trades=45
    )
    item = discovery.list_square(store)["items"][0]
    assert item["metrics"]["as_of_date"] == "2026-08-27"
    assert item["metrics"]["sharpe_1y"] == pytest.approx(2.2)
    assert item["metrics"]["trades"] == 61
    assert item["metrics_date"] == "2026-08-27"


def test_square_stays_a_single_query_per_page(store: CommunityStore, author: Actor) -> None:
    """绩效是 JOIN 出来的，不是逐条查的：条数涨了查询次数也不涨（防 N+1 回潮）。"""
    for index in range(5):
        publish_id = _publish(store, author, f"s{index}")
        leaderboard.record_metrics(
            store, publish_id, as_of=AS_OF, sharpe_1y=float(index), trades=40, live_days=400
        )
    statements: list[str] = []
    store.conn.set_trace_callback(statements.append)
    try:
        result = discovery.list_square(store, page_size=5)
    finally:
        store.conn.set_trace_callback(None)
    assert len(result["items"]) == 5
    assert all(item["metrics"] is not None for item in result["items"])
    # 一次 COUNT + 一次列表。逐条 latest_metrics() 的话这里会是 7 条。
    assert len(statements) == 2
    assert any("strategy_metrics" in sql for sql in statements)
# ----------------------------------------------------------------- 净值曲线契约


def test_normalize_equity_curve_accepts_every_historical_shape() -> None:
    """四个历史别名 + 二元组点 + 金额序列，统一归一到起点 1.0 的契约形状。"""
    contract = normalize_equity_curve(
        {"equity_curve": [{"d": "2024-01-02", "v": 1.0}, {"d": "2024-01-03", "v": 1.1}]}
    )
    assert [point.to_dict() for point in contract] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 1.1},
    ]
    # equity 别名 + {date, value} 键 + 紧凑日期
    equity = normalize_equity_curve(
        {"equity": [{"date": "20240102", "value": 200000}, {"date": "20240103", "value": 210000}]}
    )
    assert [point.to_dict() for point in equity] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 1.05},
    ]
    # nav 别名 + [date, value] 二元组
    nav = normalize_equity_curve({"nav": [["2024-01-02", 2.0], ["2024-01-03", 1.0]]})
    assert [point.to_dict() for point in nav] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 0.5},
    ]
    # curve 别名 + 乱序 + 同日重复（后写的赢）
    curve = normalize_equity_curve(
        {"curve": [["2024-01-03", 1.2], ["2024-01-02", 1.0], ["2024-01-03", 1.3]]}
    )
    assert [point.to_dict() for point in curve] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 1.3},
    ]
    # 裸列表（没有容器）也认
    assert len(normalize_equity_curve([{"d": "2024-01-02", "v": 1.0}])) == 1


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "净值曲线",
        123,
        {"equity_curve": "not-a-list"},
        {"equity_curve": []},
        {"nav": [{"d": "昨天", "v": 1.0}]},
        {"nav": [["2024-01-02", "涨了"]]},
        {"equity": [["2024-01-02", 0.0], ["2024-01-03", 1.0]]},
        [{"no": "shape"}, 42, object()],
    ],
)
def test_normalize_equity_curve_returns_empty_for_garbage(garbage: Any) -> None:
    """历史数据形状不可控：认不出来一律空列表，**绝不抛**。"""
    assert normalize_equity_curve(garbage) == []


def test_normalize_equity_curve_downsamples_long_curves() -> None:
    """超过 750 点就等距抽稀，首尾必留（曲线是看形状的，不是拿来对账的）。"""
    from datetime import date, timedelta

    first = date(2022, 1, 3)
    raw = [
        {"d": (first + timedelta(days=index)).isoformat(), "v": 1.0 + index / 1000.0}
        for index in range(1200)
    ]
    points = normalize_equity_curve(raw)
    assert 700 <= len(points) <= 750
    assert points[0].to_dict() == {"d": first.isoformat(), "v": 1.0}
    assert points[-1].d == raw[-1]["d"]  # 末点必留：抽掉的是密度，不是区间
    assert [point.d for point in points] == sorted(point.d for point in points)
    # 上限可以调小（详情页给缩略图用）
    assert len(normalize_equity_curve(raw, limit=50)) == 50
def test_written_curve_lands_on_the_contract_key(store: CommunityStore, author: Actor) -> None:
    """写入口归一一次：库里只有 ``equity_curve``，别名不再留第二份真相。"""
    publish_id = _publish(store, author, "curved")
    row = leaderboard.record_metrics(
        store,
        publish_id,
        as_of=AS_OF,
        sharpe_1y=1.0,
        trades=40,
        live_days=400,
        metrics={"nav": [["2024-01-02", 100000], ["2024-01-03", 103000]], "note": "旧格式"},
    )
    assert row["metrics"]["equity_curve"] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 1.03},
    ]
    assert "nav" not in row["metrics"]
    assert row["metrics"]["note"] == "旧格式"  # 其余字段原样保留


def test_broken_curve_does_not_block_the_metrics_row(
    store: CommunityStore, author: Actor
) -> None:
    publish_id = _publish(store, author, "broken")
    row = leaderboard.record_metrics(
        store,
        publish_id,
        as_of=AS_OF,
        sharpe_1y=1.5,
        trades=40,
        live_days=400,
        metrics={"equity": "毁灭吧", "note": "标量还在"},
    )
    assert "equity_curve" not in row["metrics"]
    assert row["metrics"]["note"] == "标量还在"
    assert row["sharpe_1y"] == pytest.approx(1.5)


# ----------------------------------------------------------------- GET /me/stars


class _Auth:
    """可切换当前用户的假鉴权依赖；匿名返回 None（工厂契约要求不抛 401）。"""

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
        test_client.actor_holder = auth
        yield test_client


def _login(client, user_id: str = "u-author", name: str = "老王") -> None:
    client.actor_holder.current = {"user_id": user_id, "display_name": name}


def test_my_stars_requires_login(client) -> None:
    assert client.get("/api/community/me/stars").status_code == 401


def test_my_stars_returns_square_shaped_cards(client) -> None:
    """收藏列表复用广场卡片：字段（含 metrics）必须对得上。"""
    _login(client)
    publish_id = client.post("/api/community/strategies", json=valid_payload()).json()["strategy"][
        "publish_id"
    ]
    client.post(
        f"/api/community/strategies/{publish_id}/metrics",
        json={"as_of": AS_OF, "sharpe_1y": 1.25, "annual_return": 20.0, "trades": 40},
    )
    _login(client, user_id="u-reader", name="小张")
    assert client.get("/api/community/me/stars").json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }
    client.post(f"/api/community/strategies/{publish_id}/star")
    payload = client.get("/api/community/me/stars", params={"limit": 10}).json()
    assert payload["total"] == 1
    assert payload["limit"] == 10
    card = payload["items"][0]
    square_card = client.get("/api/community/strategies").json()["items"][0]
    assert set(square_card) <= set(card)
    assert card["publish_id"] == publish_id
    assert card["starred"] is True
    assert card["starred_at"]
    assert card["metrics"]["sharpe_1y"] == pytest.approx(1.25)
    assert card["metrics"]["as_of_date"] == AS_OF


def test_my_stars_paginates_and_hides_what_went_private(
    store: CommunityStore, author: Actor, reader: Actor
) -> None:
    first = _publish(store, author, "one")
    second = _publish(store, author, "two")
    engagement.star(store, first, actor=reader)
    engagement.star(store, second, actor=reader)
    page = discovery.list_starred(store, actor=reader, limit=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["publish_id"] == second# 最近收藏的在前
    second_page = discovery.list_starred(store, actor=reader, limit=1, offset=1)
    assert second_page["items"][0]["publish_id"] == first
    # 作者改私有后，收藏关系还在，但不再露给收藏者
    publishing.set_visibility(store, second, actor=author, visibility="private")
    remaining = discovery.list_starred(store, actor=reader)
    assert [item["publish_id"] for item in remaining["items"]] == [first]
    assert store.has_starred(second, reader.user_id) is True
