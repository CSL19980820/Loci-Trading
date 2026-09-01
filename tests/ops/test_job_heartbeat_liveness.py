"""执行期心跳：任务跑着的时候 heartbeat_at 必须在推进，且心跳线程不许泄漏。

背景（2026-08-25 生产事故）：``ctx.heartbeat()`` 全仓只在执行器**启动前**和
**返回后**各调一次，执行期间从不刷新。一次 914s 的日终同步，heartbeat_at 全程
冻在起始值，于是有两个真实后果：

1. 误回收：``store_runs.STALE_RUN_SECONDS_BY_KIND["sync"] = 45*60``，回收按
        心跳/时间窗判活，一次合法的超 45 分钟同步会在**还在跑**的时候被判死腾槽；
2. 误导运维：心跳冻结 15 分钟，正常但慢的同步被当成挂死，还连累了旁边正在跑
        的选股任务被错杀。

所以这里测的不是"心跳这个函数能不能写库"，而是"任务执行期间它到底有没有在跳"。
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time

import pytest

from src.ops.application.jobs import JobContext, registry, run_job
from src.ops.application.jobs import context as context_mod
from src.ops.application.jobs.context import HeartbeatPump
from src.ops.infrastructure import store_runs
from src.ops.infrastructure.store import OpsStore

#: 用例里的心跳节拍。生产默认是 30s（``HEARTBEAT_INTERVAL_SECONDS``，理由见那里），
#: 用例压到亚秒级，才能在几秒的执行窗口里观察到"推进过"。压的是节拍，不是机制：
#: 线程、独立连接、停泵路径跑的都是生产同一套代码。
TEST_INTERVAL = 0.2
#: heartbeat_at 落库是 ``datetime('now')``，**秒级**精度：执行窗口必须跨过整秒才可比。
SLOW_SECONDS = 3.0


def _heartbeat_threads() -> list[threading.Thread]:
    prefix = context_mod.HEARTBEAT_THREAD_PREFIX
    return [t for t in threading.enumerate() if t.name.startswith(prefix)]


@pytest.fixture()
def fast_heartbeat(monkeypatch: pytest.MonkeyPatch) -> float:
    """把心跳节拍压到亚秒级；``HeartbeatPump`` 在构造时才读这个模块全局。"""
    monkeypatch.setattr(context_mod, "HEARTBEAT_INTERVAL_SECONDS", TEST_INTERVAL)
    return TEST_INTERVAL


def test_heartbeat_advances_while_executor_is_still_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fast_heartbeat: float,
) -> None:
    """执行器还没返回，heartbeat_at 就必须已经变新。修复前这条必红。"""
    seen: dict[str, str] = dict()
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="慢同步", kind="sync")

        def slow_executor(_config: dict, ctx: JobContext) -> dict:
            seen["begin"] = str(store.get_run(ctx.run_id)["heartbeat_at"])
            time.sleep(SLOW_SECONDS)
            #: 仍在执行器内部（还没 finish_run）：这时读到的心跳必须比进来时新。
            seen["during"] = str(store.get_run(ctx.run_id)["heartbeat_at"])
            return dict(ok=True)

        monkeypatch.setitem(registry.EXECUTORS, "sync", slow_executor)
        outcome = run_job(
            store, job_id, context=JobContext(ops_store=store), trigger="test"
        )

    assert outcome["status"] == "success"
    assert seen["begin"], "起跑时应已有一次心跳"
    assert seen["during"] > seen["begin"], (
        "执行期间 heartbeat_at 没有推进："
        + seen["begin"]
        + " -> "
        + seen["during"]
    )


def test_live_heartbeat_keeps_an_over_window_run_from_being_reclaimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fast_heartbeat: float,
) -> None:
    """生产后果 1：合法的长任务不该在还跑着的时候被回收腾槽。

    把 sync 的回收窗从 45 分钟压到 2 秒，用几秒的用例复现那次 914s 同步的处境：
    执行时长早已超窗，唯一能证明它还活着的就是心跳。
    """
    db_path = tmp_path / "ops.db"
    monkeypatch.setitem(store_runs.STALE_RUN_SECONDS_BY_KIND, "sync", 2)
    observed: dict[str, str] = dict()
    with OpsStore(db_path) as store:
        job_id = store.create_job(name="超窗同步", kind="sync")

        def slow_executor(_config: dict, ctx: JobContext) -> dict:
            time.sleep(SLOW_SECONDS)
            #: 另一个连接（调度器 / 别的触发方）此刻来收尸。
            with OpsStore(db_path) as watcher:
                watcher.reclaim_stale_runs()
                observed["status"] = str(watcher.get_run(ctx.run_id)["status"])
                observed["error"] = str(watcher.get_run(ctx.run_id)["error_text"])
            return dict(ok=True)

        monkeypatch.setitem(registry.EXECUTORS, "sync", slow_executor)
        outcome = run_job(
            store, job_id, context=JobContext(ops_store=store), trigger="test"
        )

    assert observed["status"] == "running", (
        "正在跑的任务被判死回收了：" + observed.get("error", "")
    )
    assert outcome["status"] == "success"


def test_heartbeat_thread_exits_after_a_successful_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fast_heartbeat: float,
) -> None:
    """成功路径：执行期间恰有一条心跳线程，任务结束后线程数必须回落。"""
    baseline = threading.active_count()
    seen: dict[str, int] = dict()
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="收尾-成功", kind="sync")

        def executor(_config: dict, _ctx: JobContext) -> dict:
            time.sleep(TEST_INTERVAL * 2)
            seen["threads"] = len(_heartbeat_threads())
            return dict(ok=True)

        monkeypatch.setitem(registry.EXECUTORS, "sync", executor)
        outcome = run_job(
            store, job_id, context=JobContext(ops_store=store), trigger="test"
        )

    assert outcome["status"] == "success"
    assert seen["threads"] == 1, "执行期间应当正好有一条心跳线程"
    assert _heartbeat_threads() == [], "任务结束后心跳线程仍在"
    assert threading.active_count() == baseline


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("boom", "failed"),
        ("timeout", "timed_out"),
        ("cancel", "cancelled"),
    ],
)
def test_heartbeat_thread_exits_on_abnormal_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fast_heartbeat: float,
    mode: str,
    expected: str,
) -> None:
    """异常 / 超时 / 取消三条路径同样不许漏线程——本会话刚修过一轮线程泄漏。"""
    db_path = tmp_path / "ops.db"
    baseline = threading.active_count()
    with OpsStore(db_path) as store:
        config = dict(timeout_sec=0.5) if mode == "timeout" else dict()
        job_id = store.create_job(name="收尾-" + mode, kind="sync", config=config)

        def executor(_config: dict, ctx: JobContext) -> dict:
            #: 先让心跳真的跳起来，再走各自的收场。
            time.sleep(TEST_INTERVAL * 4)
            if mode == "boom":
                raise RuntimeError("执行器炸了")
            if mode == "cancel":
                with OpsStore(db_path) as other:
                    other.request_cancel(ctx.run_id, reason="测试取消")
            ctx.check_cancelled()
            return dict(unexpected=True)

        monkeypatch.setitem(registry.EXECUTORS, "sync", executor)
        outcome = run_job(
            store, job_id, context=JobContext(ops_store=store), trigger="test"
        )

        assert outcome["status"] == expected
        assert str(store.get_run(outcome["run_id"])["status"]) == expected

    assert _heartbeat_threads() == [], "异常路径漏了心跳线程"
    assert threading.active_count() == baseline


def test_heartbeat_write_failure_does_not_fail_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fast_heartbeat: float,
) -> None:
    """心跳写库失败只是可见性受损，不能把任务本身拖垮；连接照样要还。"""
    closed: list[bool] = []

    class ExplodingWriter:
        def beat(self, run_id: str) -> bool:
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        store_runs.OpsRunsMixin,
        "run_heartbeat_writer",
        lambda self: ExplodingWriter(),
    )
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="心跳写不进去", kind="sync")

        def executor(_config: dict, _ctx: JobContext) -> dict:
            time.sleep(TEST_INTERVAL * 3)
            return dict(ok=True)

        monkeypatch.setitem(registry.EXECUTORS, "sync", executor)
        outcome = run_job(
            store, job_id, context=JobContext(ops_store=store), trigger="test"
        )

    assert outcome["status"] == "success"
    assert closed == [True], "心跳写入器没被关掉"
    assert _heartbeat_threads() == []


def test_pump_joins_its_thread_even_when_the_body_raises() -> None:
    """泵本身的契约：``with`` 体抛异常也要停泵 + join，不留线程。"""
    ctx = JobContext(run_id="RUN-unit-raise")
    beats: list[int] = []
    pump = HeartbeatPump(ctx, interval=0.05, beat=lambda: beats.append(1))
    with pytest.raises(RuntimeError):
        with pump:
            time.sleep(0.2)
            raise RuntimeError("boom")
    assert beats, "泵一拍都没跳"
    assert pump.thread is None
    assert _heartbeat_threads() == []


def test_pump_swallows_beat_failures_and_keeps_running() -> None:
    """一次写不进去不等于放弃：继续跳，只记错误数。"""

    def boom() -> None:
        raise sqlite3.OperationalError("database is locked")

    ctx = JobContext(run_id="RUN-unit-boom")
    pump = HeartbeatPump(ctx, interval=0.05, beat=boom)
    with pump:
        time.sleep(0.2)
    assert pump.beats == 0
    assert pump.errors >= 2, "失败一次就不再重试了"
    assert _heartbeat_threads() == []


def test_pump_does_not_start_a_thread_without_a_run_to_write() -> None:
    """没有 store / 没绑定 run：不起线程，别白占一个。"""
    pump = HeartbeatPump(JobContext(), interval=0.05)
    with pump:
        time.sleep(0.1)
    assert pump.thread is None
    assert _heartbeat_threads() == []
