"""进程级选股容量许可：容量、排队、取消与 FIFO 公平性。

用真线程跑，不 mock 信号量——这道闸门要挡的是「三档选股同时加载全市场面板把
容器 OOM 掉」，mock 掉并发就等于什么都没测。
"""
from __future__ import annotations

import threading
import time

import pytest

from src.shared.screen_capacity import (
        ScreenCapacityBusy,
        screen_capacity_permit,
        screen_capacity_status,
)


@pytest.fixture(autouse=True)
def _default_capacity(monkeypatch: pytest.MonkeyPatch):
    """容量按默认 1 跑，并在收尾处确认许可没泄漏。

    `LOCI_SCREEN_JOB_CONCURRENCY` 经 `_env_int` 间接读取，conftest 的 `_ENV_KEYS`
    正则扫不到它——开发机导出过就会让整套用例在另一档容量上跑绿。
    """
    monkeypatch.delenv("LOCI_SCREEN_JOB_CONCURRENCY", raising=False)
    monkeypatch.delenv("LOCI_SCREEN_QUEUE_WAIT_SEC", raising=False)
    yield
    assert _wait_until(lambda: screen_capacity_status()["in_use"] == 0), "许可没还回来"
    assert screen_capacity_status()["waiting"] == 0, "队列里还有残留的等待者"


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _Holder:
    """在后台线程里占住许可，直到主线程放行。"""

    def __init__(self, label: str = "holder") -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(label,), daemon=True)

    def _run(self, label: str) -> None:
        try:
            with screen_capacity_permit(label=label, wait_sec=None):
                self.entered.set()
                self.release.wait(timeout=10)
        except BaseException as exc:  # noqa: BLE001 — 交回主线程断言
            self.error = exc
            self.entered.set()

    def __enter__(self) -> "_Holder":
        self._thread.start()
        assert self.entered.wait(timeout=3), "后台持有者没能拿到许可"
        assert self.error is None
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        self._thread.join(timeout=5)
        assert not self._thread.is_alive()


def test_second_request_is_refused_when_capacity_is_taken() -> None:
    with _Holder():
        started = time.monotonic()
        with pytest.raises(ScreenCapacityBusy) as caught:
            with screen_capacity_permit(label="第二档", wait_sec=None):
                pytest.fail("容量已满时不该放行第二个请求")
        assert caught.value.reason == "no_wait"
        assert time.monotonic() - started < 0.5, "wait_sec=None 必须立刻返回"


def test_wait_sec_gives_up_with_busy_after_the_deadline() -> None:
    with _Holder():
        started = time.monotonic()
        with pytest.raises(ScreenCapacityBusy) as caught:
            with screen_capacity_permit(label="等不到的", wait_sec=0.4):
                pytest.fail("前面那档还没放手，这里不该进来")
        waited = time.monotonic() - started
    assert caught.value.reason == "deadline"
    assert caught.value.waited_sec >= 0.4
    assert waited < 5.0, "超时后必须立刻收场，不能一直等下去"


def test_cancelled_callback_breaks_out_of_the_queue() -> None:
    """排队中点「停止」要能退出，而不是干等到 20 分钟排队上限。"""
    calls = {"n": 0}

    def cancelled() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    with _Holder():
        started = time.monotonic()
        with pytest.raises(ScreenCapacityBusy) as caught:
            with screen_capacity_permit(label="被取消的", wait_sec=600, cancelled=cancelled):
                pytest.fail("取消之后不该拿到许可")
        waited = time.monotonic() - started
    assert caught.value.reason == "cancelled"
    assert waited < 5.0, f"取消没能打断排队（等了 {waited:.1f}s）"


def test_permit_is_available_again_after_release() -> None:
    with _Holder():
        pass
    started = time.monotonic()
    with screen_capacity_permit(label="后来的", wait_sec=None):
        assert screen_capacity_status()["in_use"] == 1
    assert time.monotonic() - started < 0.5, "前面放手后不该再等"


def test_waiters_are_served_in_arrival_order() -> None:
    """FIFO：先到先得。信号量按唤醒顺序放行，倒霉的等待者会被反复插队到超时。"""
    order: list[str] = []
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    def grab(name: str) -> None:
        with screen_capacity_permit(label=name, wait_sec=10):
            with lock:
                order.append(name)

    with screen_capacity_permit(label="队头占位", wait_sec=None):
        for name in ("先到", "次到", "后到"):
            thread = threading.Thread(target=grab, args=(name,), daemon=True)
            thread.start()
            threads.append(thread)
            # 逐个确认已入队再放下一个，否则「到达顺序」本身就是随机的。
            assert _wait_until(
                lambda n=name: n in screen_capacity_status()["waiters"]
            ), f"{name} 没能进入等待队列"
        assert screen_capacity_status()["waiters"] == ["先到", "次到", "后到"]
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert order == ["先到", "次到", "后到"]


def test_same_thread_reentry_passes_through() -> None:
    """执行器内部再要一次许可必须直接放行，否则容量 1 时自锁。"""
    with screen_capacity_permit(label="外层", wait_sec=None):
        with screen_capacity_permit(label="内层", wait_sec=None):
            assert screen_capacity_status()["in_use"] == 1
        assert screen_capacity_status()["in_use"] == 1, "内层退出不该把外层的许可还掉"


def test_capacity_follows_the_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCI_SCREEN_JOB_CONCURRENCY", "2")
    # 两档都得在**别的线程**里占：同线程重入是直接放行的，占不出真容量。
    with _Holder("第一档"), _Holder("第二档"):
        status = screen_capacity_status()
        assert status["limit"] == 2
        assert status["in_use"] == 2
        assert status["holders"] == ["第一档", "第二档"]
        with pytest.raises(ScreenCapacityBusy):
            with screen_capacity_permit(label="第三档", wait_sec=None):
                pytest.fail("容量 2 时第三档必须被挡住")
