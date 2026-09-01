"""社区上下文测试夹具：临时库 + 三种身份 + 合规的发布 payload。

全部用 ``tmp_path`` 下的临时库，绝不碰真实 ``data/community.db``
（全局隔离另见 ``tests/conftest.py``）。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.community import Actor, CommunityStore


@pytest.fixture
def store(tmp_path) -> CommunityStore:
    opened = CommunityStore(tmp_path / "community.db")
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def author() -> Actor:
    return Actor(user_id="u-author", display_name="老王")


@pytest.fixture
def reader() -> Actor:
    return Actor(user_id="u-reader", display_name="小张")


@pytest.fixture
def admin() -> Actor:
    return Actor(user_id="u-admin", display_name="管理员", is_admin=True)


def valid_backtest(**over: Any) -> dict[str, Any]:
    """一份能过上架清单的回测证据。"""
    payload: dict[str, Any] = {
        "trades": 42,
        "start": "2023-01-01",
        "end": "2024-06-30",
        "commission_bps": 3,
        "stamp_duty_bps": 10,
        "slippage_bps": 5,
        "metrics": {"win_rate": 0.52},
    }
    payload.update(over)
    return payload


def valid_payload(**over: Any) -> dict[str, Any]:
    """一份能过上架清单的发布 payload。"""
    payload: dict[str, Any] = {
        "title": "潜龙尾盘打板",
        "summary": "尾盘 14:50 选出次日高开概率大的票，次日开盘买入。",
        "kind": "screen",
        "entry_timing": "next_open",
        "tags": ["打板", "龙头"],
        "source_text": "def screen(panel):\n    return panel.head(5)\n",
        "params": {"top_n": 5},
        "release_notes": "首次发布",
        "backtest": valid_backtest(),
    }
    payload.update(over)
    return payload


@pytest.fixture
def published(store: CommunityStore, author: Actor) -> dict[str, Any]:
    """已上架一条策略，返回 ``detail()`` 结构。"""
    from src.community.application import publishing

    return publishing.publish_strategy(store, actor=author, payload=valid_payload())
