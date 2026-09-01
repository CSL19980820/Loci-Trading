"""选股运行态的跨租户隔离（进度快照 + running 互斥）。

``_STATE`` 曾是一个进程级 dict，``GET /api/screen/run`` 不做任何过滤直接返回它：
B 轮询就能看到 A 的 ``result.picks``；而 ``screen_run_try_begin`` 的 running 判定
同样全局，A 在跑的时候 B 会被判 busy（跨租户 DoS）。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.shared.tenancy import current_tenant, tenant_scope
from src.strategy.application.screen_run import (
    MAX_TENANT_STATES,
    _STATES,
    screen_run_snapshot,
    screen_run_try_begin,
    screen_run_update,
    start_screen_run_thread,
)

PICKS = [{"code": "600519", "name": "贵州茅台", "factors": {"score": 88.0}}]


@pytest.fixture(autouse=True)
def _clean_screen_run_states():
    """进度槽是模块级全局：用例之间必须互不可见，否则断言依赖执行顺序。"""
    saved = dict(_STATES)
    _STATES.clear()
    yield
    _STATES.clear()
    _STATES.update(saved)


def test_running_tenant_does_not_block_another_tenant() -> None:
    with tenant_scope("u_a"):
        assert screen_run_try_begin(strategy="demo", trade_date="2026-08-27") is None
        assert screen_run_snapshot()["status"] == "running"

    with tenant_scope("u_b"):
        busy = screen_run_try_begin(strategy="other", trade_date="2026-08-27")
        assert busy is None, f"A 在跑把 B 也判成 busy 了：{busy}"
        assert screen_run_snapshot()["strategy"] == "other"

    with tenant_scope("u_a"):
        # A 自己**同一个战法**的第二次请求仍然要被挡住（防重复入库）。
        mine = screen_run_try_begin(strategy="demo", trade_date="")
        assert mine is not None
        assert mine["strategy"] == "demo"
        assert mine["busy_reason"] == "same_strategy"
        # 但**换一个战法**必须放行：进度槽已经是「租户 × 战法」双层，
        # 「潜龙在跑就什么都点不了」那套全局单槽语义已经废掉。完整的并发
        # 契约见 tests/strategy/test_screen_run_multi.py。
        assert screen_run_try_begin(strategy="again", trade_date="") is None


def test_screen_run_picks_never_leak_across_tenants() -> None:
    with tenant_scope("u_a"):
        screen_run_update(
            status="done",
            phase="done",
            strategy="demo",
            trade_date="2026-08-27",
            result={"strategy": "demo", "picks": PICKS},
            log_line="✓ A 的选股完成",
        )

    with tenant_scope("u_b"):
        snap = screen_run_snapshot()
        assert snap["status"] == "idle", snap
        assert snap["result"] is None, f"B 看到了 A 的选股结果：{snap['result']}"
        assert snap["strategy"] == ""
        assert snap["log"] == []

    with tenant_scope("u_a"):
        mine = screen_run_snapshot()
        assert mine["result"]["picks"] == PICKS
        assert any("A 的选股完成" in line for line in mine["log"])


def test_background_thread_keeps_the_callers_tenant() -> None:
    """裸 ``threading.Thread`` 会把 B 的候选写进管理员的 palace.db。"""
    seen: list[str] = []

    def fake_spawn(target, *, kwargs=None, name=None, **_ignored):
        # spawn_tenant_thread 的语义：线程体跑在**调用时刻**的 Context 副本里。
        seen.append(current_tenant())
        return None

    with tenant_scope("u_b"):
        with patch(
            "src.strategy.application.screen_run.spawn_tenant_thread",
            fake_spawn,
        ):
            start_screen_run_thread(
                {"strategy": "demo", "date": "2026-08-27"},
                market_factory=lambda: None,
                palace_db=None,
            )

    assert seen == ["u_b"], seen


def test_state_table_is_bounded_and_keeps_running_slots() -> None:
    with tenant_scope("u_keep"):
        assert screen_run_try_begin(strategy="demo", trade_date="") is None

    for index in range(MAX_TENANT_STATES + 8):
        with tenant_scope(f"u_bulk_{index}"):
            screen_run_snapshot()

    assert len(_STATES) <= MAX_TENANT_STATES, len(_STATES)
    with tenant_scope("u_keep"):
        assert screen_run_snapshot()["status"] == "running"
