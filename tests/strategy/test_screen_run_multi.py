"""战法级多槽：同一个租户可以同时跑潜龙、三源、杨氏。

这里钉的是**上层进度槽**的并发语义，不是行情库的并发能力——后者早就是
「sync 独占写 / screen 共享读」（``ops/application/jobs/market_gate.py``），
挡住用户的一直是「按租户单槽」的进度状态机。

必须钉死的性质：

1. 不同战法**互不阻塞**：潜龙在跑，三源照样能开。
2. 同一战法**仍然防重**：重复点击返回它自己的快照（``busy_reason='same_strategy'``），
否则同日同池会被两条线程来回覆盖。
3. 进度/日志/取消旗**按槽隔离**：A 战法的停止请求不能让 B 在检查点自尽。
4. 并发有上限：到顶返回 ``busy_reason='tenant_limit'``，而不是无声排队或无限并行。
5. 跨租户仍然完全隔离（老性质，不能被多槽改造搞坏）。
"""
from __future__ import annotations

import pytest

from src.shared.tenancy import tenant_scope
from src.strategy.application import screen_run_state as state
from src.strategy.application.screen_run import (
    MAX_CONCURRENT_RUNS,
    MAX_RUNS_PER_TENANT,
    _STATES,
    screen_run_cancel_requested,
    screen_run_request_cancel,
    screen_run_running_strategies,
    screen_run_slot_scope,
    screen_run_snapshot,
    screen_run_snapshot_all,
    screen_run_try_begin,
    screen_run_update,
)


@pytest.fixture(autouse=True)
def _clean_screen_run_states():
    """进度槽是模块级全局：用例之间必须互不可见，否则断言依赖执行顺序。"""
    saved = dict(_STATES)
    _STATES.clear()
    yield
    _STATES.clear()
    _STATES.update(saved)


def _begin(strategy: str, trade_date: str = "2026-08-27") -> dict | None:
    return screen_run_try_begin(strategy=strategy, trade_date=trade_date)


def test_different_strategies_run_side_by_side() -> None:
    """这就是本次改造要的那件事：潜龙在跑，三源、杨氏照样点得开。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None
        assert _begin("yangshi-tail") is None

        assert screen_run_running_strategies() == [
            "qianlong-close",
            "tail-resonance",
            "yangshi-tail",
        ]


def test_same_strategy_still_deduplicates() -> None:
    """同一战法重复点击必须被挡：否则同日同池两条线程互相覆盖入库。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        busy = _begin("qianlong-close")

        assert busy is not None
        assert busy["busy_reason"] == "same_strategy"
        assert busy["strategy"] == "qianlong-close"
        assert busy["status"] == "running"


def test_progress_and_logs_are_isolated_per_strategy() -> None:
    """每个战法一条独立进度条 + 独立日志队列。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None

        with screen_run_slot_scope("qianlong-close"):
            screen_run_update(percent=40.0, message="潜龙扫描候选", log_line="▷ 潜龙 40%")
        with screen_run_slot_scope("tail-resonance"):
            screen_run_update(percent=80.0, message="三源写入候选池", log_line="▷ 三源 80%")

        qianlong = screen_run_snapshot("qianlong-close")
        resonance = screen_run_snapshot("tail-resonance")

        assert qianlong["percent"] == 40.0
        assert resonance["percent"] == 80.0
        assert qianlong["message"] == "潜龙扫描候选"
        assert any("潜龙" in line for line in qianlong["log"])
        assert not any("三源" in line for line in qianlong["log"])
        assert any("三源" in line for line in resonance["log"])


def test_result_of_one_strategy_never_lands_in_another_slot() -> None:
    """跑完的 picks 只属于自己那个槽——否则前端会把三源的结果标成潜龙的。"""
    picks = [{"code": "600519", "name": "贵州茅台"}]
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None
        with screen_run_slot_scope("qianlong-close"):
            screen_run_update(status="done", phase="done", result={"picks": picks})

        assert screen_run_snapshot("qianlong-close")["result"]["picks"] == picks
        assert screen_run_snapshot("tail-resonance")["result"] is None
        assert screen_run_snapshot("tail-resonance")["status"] == "running"


def test_cancel_only_stops_the_named_strategy() -> None:
    """点名停止：A 的停止请求不能让 B 在下一个检查点自尽。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None

        result = screen_run_request_cancel("qianlong-close")
        assert result["cancelled"] is True
        assert result["cancelled_strategies"] == ["qianlong-close"]

        assert screen_run_cancel_requested("qianlong-close") is True
        assert screen_run_cancel_requested("tail-resonance") is False
        # 受理 ≠ 完成：此刻两个都还在跑。
        assert screen_run_snapshot("qianlong-close")["status"] == "running"
        assert "已取消" not in screen_run_snapshot("qianlong-close")["message"]


def test_execution_body_reads_its_own_cancel_flag() -> None:
    """执行体不传参：靠 ``screen_run_slot_scope`` 找到自己那面旗。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None
        screen_run_request_cancel("tail-resonance")

        with screen_run_slot_scope("qianlong-close"):
            assert screen_run_cancel_requested() is False
        with screen_run_slot_scope("tail-resonance"):
            assert screen_run_cancel_requested() is True


def test_cancel_without_strategy_stops_all_running() -> None:
    """省略 strategy = 老客户端的「停这一个」，多槽下语义是「停全部」。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None

        result = screen_run_request_cancel()
        assert result["cancelled"] is True
        assert sorted(result["cancelled_strategies"]) == [
            "qianlong-close",
            "tail-resonance",
        ]
        assert screen_run_cancel_requested("qianlong-close") is True
        assert screen_run_cancel_requested("tail-resonance") is True


def test_cancel_named_idle_strategy_is_a_noop() -> None:
    """连点两次停止，第二次什么都不该发生——更不该报错。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        screen_run_request_cancel("qianlong-close")
        screen_run_update(status="cancelled", phase="cancelled", strategy="qianlong-close")

        again = screen_run_request_cancel("qianlong-close")
        assert again["cancelled"] is False
        assert again["status"] == "cancelled"
        assert again["cancelled_strategies"] == []


def test_a_new_run_lowers_a_stale_cancel_flag_per_slot() -> None:
    """取消过一次之后再开同一个战法，不能刚进循环就自尽。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        screen_run_request_cancel("qianlong-close")
        screen_run_update(status="cancelled", phase="cancelled", strategy="qianlong-close")
        assert screen_run_cancel_requested("qianlong-close") is True

        assert _begin("qianlong-close") is None
        assert screen_run_cancel_requested("qianlong-close") is False
        assert screen_run_snapshot("qianlong-close")["status"] == "running"


def test_concurrency_cap_reports_tenant_limit(monkeypatch) -> None:
    """到顶时必须说清「是排队，不是坏了」，并给出占位的战法列表。"""
    monkeypatch.setattr(state, "MAX_CONCURRENT_RUNS", 2)
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None

        busy = _begin("yangshi-tail")
        assert busy is not None
        assert busy["busy_reason"] == "tenant_limit"
        assert busy["max_concurrent_runs"] == 2
        assert sorted(busy["running_strategies"]) == ["qianlong-close", "tail-resonance"]
        # 到顶时返回最早开跑的那一个，前端才能说「先停它或等它跑完」。
        assert busy["strategy"] == "qianlong-close"
        # 没占到槽的战法不许留下一个假 running。
        assert screen_run_snapshot("yangshi-tail")["status"] == "idle"


def test_default_cap_covers_three_strategies() -> None:
    """默认上限就是「一次把当日三个战法都点一遍」这个真实用法。"""
    assert MAX_CONCURRENT_RUNS >= 3


def test_aggregate_snapshot_carries_every_slot() -> None:
    """前端一条轮询要能画出全部并行进度。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
        assert _begin("tail-resonance") is None
        with screen_run_slot_scope("qianlong-close"):
            screen_run_update(status="done", phase="done", percent=100.0)

        snap = screen_run_snapshot_all()

        assert set(snap["runs"]) == {"qianlong-close", "tail-resonance"}
        assert snap["runs"]["qianlong-close"]["status"] == "done"
        assert snap["running_strategies"] == ["tail-resonance"]
        # 顶层仍是一份自洽的单槽快照（老前端/老客户端滚动升级期间照旧能读）。
        assert snap["status"] == "running"
        assert snap["strategy"] == "tail-resonance"
        assert snap["max_concurrent_runs"] == MAX_CONCURRENT_RUNS


def test_aggregate_snapshot_never_leaks_across_tenants() -> None:
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None

    with tenant_scope("u_b"):
        snap = screen_run_snapshot_all()
        assert snap["runs"] == {}
        assert snap["running_strategies"] == []
        assert snap["status"] == "idle"
        assert snap["result"] is None


def test_tenants_do_not_share_the_strategy_mutex() -> None:
    """老性质：A 在跑同一个战法，B 照样能跑它。"""
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is None
    with tenant_scope("u_b"):
        assert _begin("qianlong-close") is None
        assert screen_run_snapshot("qianlong-close")["status"] == "running"
    with tenant_scope("u_a"):
        assert _begin("qianlong-close") is not None


def test_slot_table_is_bounded_per_tenant_and_keeps_running_slots() -> None:
    """战法槽也要有上限：一个人点过十几个战法之后，最早那几条 result 没人看了。"""
    with tenant_scope("u_a"):
        assert _begin("keep-running") is None
        for index in range(MAX_RUNS_PER_TENANT + 5):
            slug = f"done-{index}"
            assert _begin(slug) is None
            screen_run_update(status="done", phase="done", strategy=slug)

        slots = _STATES["u_a"]
        assert len(slots) <= MAX_RUNS_PER_TENANT, sorted(slots)
        assert screen_run_snapshot("keep-running")["status"] == "running"


def test_named_snapshot_does_not_allocate_a_slot() -> None:
    """轮询一个从没跑过的战法，不该在内存里给它建槽。"""
    with tenant_scope("u_a"):
        snap = screen_run_snapshot("never-ran")
        assert snap["status"] == "idle"
        assert snap["result"] is None
        assert "never-ran" not in _STATES.get("u_a", {})


def test_total_slot_table_is_bounded_across_tenants(monkeypatch) -> None:
    """两个上限相乘不等于有界：64 租户 × 6 战法的槽全留着能吃掉几十上百 MB。

    服务器只有 1.1 GB（ADR-016），所以除了「每租户 6 个」还有一道全局总闸；
    正在跑的槽依旧不许丢。
    """
    monkeypatch.setattr(state, "MAX_TOTAL_RUN_SLOTS", 8)

    with tenant_scope("u_running"):
        assert _begin("keep-running") is None

    for tenant_index in range(6):
        with tenant_scope(f"u_bulk_{tenant_index}"):
            for slug_index in range(3):
                slug = f"done-{slug_index}"
                assert _begin(slug) is None
                screen_run_update(status="done", phase="done", strategy=slug)

    total = sum(len(slots) for slots in _STATES.values())
    assert total <= 8, {name: sorted(slots) for name, slots in _STATES.items()}
    with tenant_scope("u_running"):
        assert screen_run_snapshot("keep-running")["status"] == "running"


def test_total_cap_never_drops_the_slot_being_written(monkeypatch) -> None:
    """刚建的槽不能被同一轮总闸摘走——否则调用方写进真空，进度凭空消失。"""
    monkeypatch.setattr(state, "MAX_TOTAL_RUN_SLOTS", 2)

    with tenant_scope("u_a"):
        assert _begin("first") is None
        screen_run_update(status="done", phase="done", strategy="first")
        assert _begin("second") is None
        screen_run_update(status="done", phase="done", strategy="second")

        # 总数已达上限，此刻再建一个：新槽必须活着并且写得进去
        screen_run_update(status="error", error="boom", strategy="third")
        assert screen_run_snapshot("third")["error"] == "boom"
