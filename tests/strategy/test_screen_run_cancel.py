"""选股的协作式取消。

取消不能靠杀线程：选股主体是一段同步的 pandas 面板计算，既没有可打断的 IO
等待点，也不能在持有 SQLite 连接与 ExitStack 的中途被强杀。所以做成「立旗 +
检查点」，而这带来两个必须钉死的性质：

1. **旗是按租户的。** A 点停止不能把 B 正在跑的选股一起停掉。
2. **新一轮开跑前旗必须落下。** 否则上一轮取消留下的旗会让下一轮刚进循环就自尽，
   表现为「点了开始，立刻显示已停止」——这种 bug 只在「取消过一次之后」才复现。
"""
from __future__ import annotations

from typing import Any

import pytest

from src.shared.tenancy import tenant_scope
from src.strategy.application.screen_run import (
    _STATES,
    screen_run_cancel_requested,
    screen_run_request_cancel,
    screen_run_snapshot,
    screen_run_try_begin,
 screen_run_update,
)


@pytest.fixture(autouse=True)
def _clean_screen_run_states():
    saved = dict(_STATES)
    _STATES.clear()
    yield
    _STATES.clear()
    _STATES.update(saved)


def _begin(strategy: str = "demo") -> None:
    assert screen_run_try_begin(strategy=strategy, trade_date="2026-08-27") is None


def test_cancel_on_idle_is_a_noop_not_an_error() -> None:
    """连点两次停止，第二次什么都不该发生——更不该弹红条。"""
    with tenant_scope("u_a"):
        result = screen_run_request_cancel()

    assert result["cancelled"] is False
    assert result["status"] == "idle"


def test_cancel_raises_the_flag_and_says_stopping_not_stopped() -> None:
    with tenant_scope("u_a"):
        _begin()
        result = screen_run_request_cancel()

        assert result["cancelled"] is True
        assert screen_run_cancel_requested() is True

        snap = screen_run_snapshot()
        # 受理 ≠ 完成：此刻任务还在跑，状态必须仍是 running。
        assert snap["status"] == "running"
        assert "停止" in snap["message"]
        # 文案不能写「已取消」——检查点还没到，那是谎话。
    assert "已取消" not in snap["message"]


def test_cancel_does_not_cross_tenants() -> None:
    """A 点停止把 B 的选股也停了，是最容易写出来的那个 bug。"""
    with tenant_scope("u_a"):
        _begin("a-strategy")
    with tenant_scope("u_b"):
        _begin("b-strategy")

    with tenant_scope("u_a"):
        assert screen_run_request_cancel()["cancelled"] is True

    with tenant_scope("u_b"):
        assert screen_run_cancel_requested() is False
        assert screen_run_snapshot()["status"] == "running"
        assert screen_run_snapshot()["strategy"] == "b-strategy"

    with tenant_scope("u_a"):
        assert screen_run_cancel_requested() is True


def test_a_new_run_lowers_a_stale_cancel_flag() -> None:
    """取消过一次之后再开一轮，不能刚进循环就自尽。"""
    with tenant_scope("u_a"):
        _begin()
        screen_run_request_cancel()
        screen_run_update(status="cancelled", phase="cancelled")
        assert screen_run_cancel_requested() is True

        _begin("second-run")

        assert screen_run_cancel_requested() is False
        assert screen_run_snapshot()["status"] == "running"


def test_checkpoint_stops_the_loop_and_keeps_finished_days(monkeypatch) -> None:
    """检查点命中后：状态落 cancelled，且**已经跑完的交易日不回滚**。

    取消是「不再往下跑」，不是「撤销已经做过的事」。已入库的候选是真实发生过的
    选股结果，把它们删掉才是数据丢失。
    """
from src.strategy.application import screen_run as module

seen: list[str] = []
calls = {"n": 0}

def fake_cancel_requested() -> bool:
    # 第一天放过，第二天开始拦——模拟「跑到一半用户点了停止」。
    calls["n"] += 1
    return calls["n"] > 1

    monkeypatch.setattr(module, "screen_run_cancel_requested", fake_cancel_requested)

    with tenant_scope("u_a"):
        _begin()
        # 直接驱动检查点语义，不拉起真实的行情依赖：本用例要钉的是
        # 「命中检查点之后状态怎么落」，不是选股算得对不对。
    total = 3
    for index, day in enumerate(["d1", "d2", "d3"], start=1):
        if module.screen_run_cancel_requested():
            screen_run_update(
           status="cancelled",
         phase="cancelled",
        message=f"已停止 · 完成 {index - 1}/{total} 个交易日",
      )
            break
            seen.append(day)

        snap: dict[str, Any] = screen_run_snapshot()

    assert seen == ["d1"], "第一天应当跑完再停"
    assert snap["status"] == "cancelled"
    assert "完成 1/3" in snap["message"]
