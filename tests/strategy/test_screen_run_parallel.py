"""两条真线程并跑：执行体是否各写各的槽（多槽改造的端到端验证）。

与 ``test_screen_run_multi.py`` 的区别：那边钉的是状态机的契约（try_begin /
cancel / 快照），这边真的起 ``start_screen_run_thread`` 两次，让两条
``execute_screen_run`` 同时在跑，验证：

1. ``screen_run_slot_scope`` 的 ContextVar 真的跨线程隔离——线程体里那二十来处
无参 ``screen_run_update(...)`` 各自落进自己的槽，不互相盖；
2. 日志不串台；
3. 点名取消只停一个，另一条照样跑完并落 ``done``；
4. 结果 ``picks`` 落在正确的槽里。

这条用例专门防「进度看着对，其实是两条线程轮流盖同一个槽」——那种 bug 在单线程

**容量前提**：进程级选股许可（``src.shared.screen_capacity``）默认只放行一个，
两条线程真并跑需要显式把容量抬到 2。这不是绕过闸门——槽隔离与闸门是两件事，
把它们搅在一起会让「槽会不会串」永远测不到。闸门本身的行为另有用例钉。
测试里 100% 观察不到。
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.shared import screen_capacity
from src.shared.tenancy import tenant_scope
from src.strategy.application.screen_run import (
    _STATES,
    screen_run_request_cancel,
    screen_run_snapshot,
    screen_run_snapshot_all,
    start_screen_run_thread,
)

QIANLONG = "qianlong-close-v3"
SANYUAN = "sanyuan-tail-v1"


@pytest.fixture(autouse=True)
def _capacity_for_two(monkeypatch):
    """本文件要的是两条线程真并跑，显式把进程级许可抬到 2 并清干净状态。"""
    monkeypatch.setenv("LOCI_SCREEN_JOB_CONCURRENCY", "2")
    screen_capacity._HOLDERS.clear()
    screen_capacity._WAITING.clear()
    yield
    screen_capacity._HOLDERS.clear()
    screen_capacity._WAITING.clear()


@pytest.fixture(autouse=True)
def _clean_screen_run_states():
    saved = dict(_STATES)
    _STATES.clear()
    yield
    _STATES.clear()
    _STATES.update(saved)


class FakeMarketStore:
    """够 execute_screen_run 用的最小行情仓：两个交易日，不碰磁盘。"""

    def __enter__(self) -> "FakeMarketStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def trading_days(self, *, start: str = "", end: str = "") -> list[str]:
        return ["2026-08-26", "2026-08-27"]

    def list_instruments(self, *, status: str = "") -> list[dict[str, str]]:
        return []

    def coverage(self) -> dict[str, str]:
        return {"last_date": "2026-08-27"}

    def data_snapshot(self) -> dict[str, str]:
        return {"market_revision": "fixed"}


def _result(slug: str, trade_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_slug=slug,
        strategy_revision="rev1",
        trade_date=trade_date,
        entry_timing="next_open",
        universe_size=1,
        elapsed_seconds=0.01,
        params={},
        effective_params={},
        picks=[{"code": "600519" if slug == QIANLONG else "000001", "factors": {}}],
        watch_picks=[],
        health=None,
        universe={},
        universe_funnel={},
        data_snapshot={},
    )


def _spawn(slug: str) -> dict[str, Any]:
    return start_screen_run_thread(
        {
            "strategy": slug,
            "start": "2026-08-26",
            "end": "2026-08-27",
            "record_candidates": False,
            "skip_health_check": True,
            "refresh_spot": False,
        },
        market_factory=FakeMarketStore,
        palace_db=None,
    )


def test_two_strategies_really_run_at_the_same_time(monkeypatch) -> None:
    """两条线程同时卡在选股中间，各自的槽都必须是 running 且互不覆盖。"""
    import src.strategy as strategy_pkg

    entered = threading.Barrier(3, timeout=20)
    release = threading.Event()

    def fake_screen(_store, slug: str, **kwargs: Any) -> SimpleNamespace:
        day = str(kwargs.get("trade_date") or "")
        if day == "2026-08-26":
            # 两条线程都停在第一个交易日：主线程借 barrier 在「真并跑」那一刻断言
            entered.wait()
            release.wait(timeout=20)
        return _result(slug, day)

    monkeypatch.setattr(strategy_pkg, "screen", fake_screen)

    with tenant_scope("u_a"):
        assert _spawn(QIANLONG).get("status") == "running"
        assert _spawn(SANYUAN).get("status") == "running"

        entered.wait()
        try:
            snap = screen_run_snapshot_all()
            running = set(snap["running_strategies"])
            assert running == {QIANLONG, SANYUAN}, snap["running_strategies"]

            # 日志不串台：各自只有自己的战法名开头那一行 + 自己的交易日进度
            qianlong_log = "\n".join(snap["runs"][QIANLONG]["log"])
            sanyuan_log = "\n".join(snap["runs"][SANYUAN]["log"])
            assert "潜龙" in qianlong_log, qianlong_log
            assert "潜龙" not in sanyuan_log, sanyuan_log

            # 取消只停被点名的那一个
            assert screen_run_request_cancel(QIANLONG)["cancelled_strategies"] == [QIANLONG]
            assert snap["runs"][SANYUAN]["status"] == "running"
        finally:
            release.set()

        _wait_until_settled(QIANLONG)
        _wait_until_settled(SANYUAN)

        # 潜龙在第二个交易日的检查点退出；三源不受影响，跑完两天
        assert screen_run_snapshot(QIANLONG)["status"] == "cancelled"
        assert screen_run_snapshot(SANYUAN)["status"] == "done"

        done = screen_run_snapshot(SANYUAN)["result"]
        assert done["strategy"] == SANYUAN
        assert [pick["code"] for pick in done["picks"]] == ["000001"]
        # 被取消的那个没有把自己的结果写进别人的槽
        assert screen_run_snapshot(QIANLONG)["result"] is None


def _wait_until_settled(slug: str, timeout: float = 20.0) -> None:
    """等某个战法的槽落到终态。线程是 daemon，不等就会在断言里读到中间态。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        status = screen_run_snapshot(slug)["status"]
        if status in {"done", "error", "cancelled"}:
            return
        time.sleep(0.05)
    raise AssertionError(f"{slug} 没能在 {timeout}s 内跑完：{screen_run_snapshot(slug)}")


def _wait_for_capacity(*, in_use: int, waiting: int, timeout: float = 20.0) -> dict:
    """等许可状态到达期望值。裸读会撞上「第二条线程刚 spawn 还没排到队」。"""
    deadline = time.monotonic() + timeout
    status = screen_capacity.screen_capacity_status()
    while time.monotonic() < deadline:
        status = screen_capacity.screen_capacity_status()
        if status["in_use"] == in_use and status["waiting"] == waiting:
            return status
        time.sleep(0.02)
    raise AssertionError(f"许可状态没到 in_use={in_use}/waiting={waiting}：{status}")


def test_second_strategy_queues_instead_of_doubling_memory(monkeypatch) -> None:
    """容量=1 时第二个战法**排队**而不是并行开面板。

    生产实测：三档并发的全市场面板（4400 只票 x 60 日）在 3.7G 机器上触发
    memcg OOM 打掉整个容器。槽仍然是两个（进度条各显各的），但真正开面板的
    同时只有一个。这条用例钉的就是「槽数 != 并发数」。
    """
    import src.strategy as strategy_pkg

    monkeypatch.setenv("LOCI_SCREEN_JOB_CONCURRENCY", "1")
    screen_capacity._HOLDERS.clear()
    screen_capacity._WAITING.clear()
    inside = threading.Event()
    release = threading.Event()
    concurrent: list[int] = []

    def fake_screen(_store, slug: str, **kwargs: Any) -> SimpleNamespace:
        day = str(kwargs.get("trade_date") or "")
        concurrent.append(len(screen_capacity.screen_capacity_status()["holders"]))
        if day == "2026-08-26" and not inside.is_set():
            inside.set()
            release.wait(timeout=20)
        return _result(slug, day)

    monkeypatch.setattr(strategy_pkg, "screen", fake_screen)

    with tenant_scope("u_a"):
        assert _spawn(QIANLONG).get("status") == "running"
        assert _spawn(SANYUAN).get("status") == "running"
        assert inside.wait(timeout=20)

        # 第一个占着唯一的许可；第二个已认领自己的槽（进度条在转）但还没开面板。
        # 轮询而不是裸读：第二条线程刚被 spawn 时可能还没走到排队那一步。
        status = _wait_for_capacity(in_use=1, waiting=1)
        assert status["holders"] and status["waiters"], status
        assert set(screen_run_snapshot_all()["running_strategies"]) == {QIANLONG, SANYUAN}

        release.set()
        _wait_until_settled(QIANLONG)
        _wait_until_settled(SANYUAN)

        # 两个都跑完，且从没有过两份面板同时在内存里。
        assert screen_run_snapshot(QIANLONG)["status"] == "done"
        assert screen_run_snapshot(SANYUAN)["status"] == "done"
        assert max(concurrent) == 1, concurrent
