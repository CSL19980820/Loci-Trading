"""同步引擎的收尾必须是有限时间的 —— 这组测试守的是一条确定性死锁。

## 死锁长什么样

`sync.py` 里的调用形状是固定的三段:

```python
outcomes = sync_engine.make_queue(batch)     # 有界队列,maxsize = batch * 3
pool = sync_engine.fan_out(codes, fetch_one, outcomes, workers=n)
try:
    sync_engine.drain(outcomes, writer, len(codes), progress=...)
finally:
    pool.shutdown(wait=True)
```

`drain` 循环体里任何一处抛异常(progress 回调抛错、写线程 MemoryError、
Ctrl-C 打进来的 KeyboardInterrupt),控制权就跳到 `finally: pool.shutdown(wait=True)`。
此刻队列是**满的**、消费者**已经走了**,而线程池里还有几千个 code 没跑完:
worker 卡在 `outcomes.put()` 上永远醒不过来 → `shutdown(wait=True)` 永远 join 不到
→ 同步线程挂死,连进程退出都跟着挂死(`concurrent.futures` 的 atexit 会 join 这些
非守护线程)。5544 只票配 600 深的队列,这不是概率问题,是必然。

## 这组测试怎么证明

每个用例都在子线程里跑上面那段完整形状,然后 `join(timeout=...)`。
线程没在超时内退出 = 死锁复现。仓里没装 pytest-timeout,子线程 + join 超时
不引入新依赖,而且能精确指到「挂在哪一段」。
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import pytest

from src.market.infrastructure import sync_engine

#: 修好之后每个用例都是亚秒级;给到 15s 纯粹是不想在慢机器上假阳性。
JOIN_TIMEOUT = 15.0


class _StubWriter:
    """`drain` 只用到 `add` / `close` 两个方法,不需要真的 BatchWriter。"""

    def __init__(
        self, *, boom_at: int | None = None, exc: BaseException | None = None
    ) -> None:
        self.added: list[str] = []
        self.closed = 0
        self._boom_at = boom_at
        self._exc = exc

    def add(self, outcome: sync_engine.Outcome) -> None:
        self.added.append(outcome.code)
        if self._boom_at is not None and len(self.added) == self._boom_at:
            assert self._exc is not None
            raise self._exc

    def close(self) -> None:
        self.closed += 1


def _boom_progress(at: int, exc: BaseException) -> Callable[[int, str], None]:
    def progress(done: int, code: str) -> None:  # noqa: ARG001
        if done == at:
            raise exc

    return progress


class _Harness:
    """照抄 `sync.py` 的调用形状,整段丢进子线程跑。"""

    def __init__(
        self,
        *,
        total: int,
        chunk: int,
        workers: int,
        writer: _StubWriter,
        progress: Callable[[int, str], None] | None = None,
    ) -> None:
        self.codes = [f"{i:06d}" for i in range(total)]
        self.writer = writer
        self.progress = progress
        self.outcomes = sync_engine.make_queue(chunk)
        self.fetched: list[str] = []
        self._guard = threading.Lock()
        self.box: dict[str, Any] = {}
        self.pool = sync_engine.fan_out(
            self.codes, self._fetch_one, self.outcomes, workers=workers
        )
        self.thread = threading.Thread(
            target=self._body, name="drain-harness", daemon=True
        )

    def _fetch_one(self, code: str) -> sync_engine.Outcome:
        with self._guard:
            self.fetched.append(code)
        return sync_engine.Outcome(
            code=code, kind="ok", last_date="2026-08-24", source="stub"
        )

    def _body(self) -> None:
        """完整照抄 sync.py:try drain / finally pool.shutdown(wait=True)。"""
        try:
            sync_engine.drain(
                self.outcomes, self.writer, len(self.codes), progress=self.progress
            )
        except BaseException as exc:  # noqa: BLE001 - 要连 KeyboardInterrupt 一起接
            self.box["drain_error"] = exc
        finally:
            started = time.monotonic()
            try:
                self.pool.shutdown(wait=True)
            except BaseException as exc:  # noqa: BLE001
                self.box["shutdown_error"] = exc
            self.box["shutdown_sec"] = time.monotonic() - started
            self.box["done"] = True

    def start(self) -> None:
        self.thread.start()

    def rescue(self, limit: float = 30.0) -> None:
        """把队列抽干,直到子线程退出。

        **只在用例已经判定失败之后调用。** 修复前这一步是必需的:挂死的
        ``ThreadPoolExecutor`` 用的是非守护线程,``concurrent.futures`` 注册的
        atexit 会在解释器退出时 join 它们,于是「一个用例挂死」会升级成「整个
        pytest 进程收不了尾」。断言用的是 rescue 之前抓到的快照,救援不影响判定。
        """
        deadline = time.monotonic() + limit
        while self.thread.is_alive() and time.monotonic() < deadline:
            try:
                while True:
                    self.outcomes.get_nowait()
            except queue.Empty:
                pass
            self.thread.join(timeout=0.05)

    def assert_settled(self, why: str) -> None:
        self.thread.join(timeout=JOIN_TIMEOUT)
        ok = not self.thread.is_alive()
        snapshot = (
            f"drain_error={self.box.get('drain_error')!r} "
            f"done={self.box.get('done')} "
            f"已消费={len(self.writer.added)} 已取数={len(self.fetched)} "
            f"队列积压={self.outcomes.qsize()}"
        )
        if not ok:
            self.rescue()
        assert ok, f"{why}:子线程 {JOIN_TIMEOUT}s 内没退出。{snapshot}"


def test_progress_callback_error_does_not_wedge_shutdown() -> None:
    """progress 回调抛错 → shutdown 必须能返回。

    这是线上最容易踩到的一条:进度回调要往 ops 库写一行、或者刷一次前端,
    库忙就抛,于是整个同步线程连同进程一起挂死。
    """
    writer = _StubWriter()
    harness = _Harness(
        total=400,
        chunk=4,  # maxsize = 12,远小于 400,保证 worker 一定会堵在 put()
        workers=4,
        writer=writer,
        progress=_boom_progress(5, RuntimeError("进度回调炸了")),
    )
    harness.start()
    harness.assert_settled("progress 回调抛错后")

    # 异常要原样抛给调用方,不能被吞成「同步成功」。
    assert isinstance(harness.box.get("drain_error"), RuntimeError)
    assert "进度回调炸了" in str(harness.box["drain_error"])


def test_writer_memory_error_does_not_wedge_shutdown() -> None:
    """写线程 MemoryError(全量回填单票几千行,真会发生)同样不许挂死。"""
    writer = _StubWriter(boom_at=6, exc=MemoryError("落库时内存炸了"))
    harness = _Harness(total=400, chunk=4, workers=4, writer=writer)
    harness.start()
    harness.assert_settled("writer.add 抛 MemoryError 后")

    assert isinstance(harness.box.get("drain_error"), MemoryError)


def test_keyboard_interrupt_does_not_wedge_shutdown() -> None:
    """Ctrl-C / SystemExit 走 BaseException,``except Exception`` 接不住。"""
    writer = _StubWriter()
    harness = _Harness(
        total=400,
        chunk=4,
        workers=4,
        writer=writer,
        progress=_boom_progress(5, KeyboardInterrupt()),
    )
    harness.start()
    harness.assert_settled("KeyboardInterrupt 打断 drain 后")

    assert isinstance(harness.box.get("drain_error"), KeyboardInterrupt)


def test_abort_cancels_pending_work_instead_of_fetching_everything() -> None:
    """abort 之后不该把剩下几千只票全部取完再收工。

    光「把队列抽干、让 worker 各自跑完」也能解开死锁,但那等于在用户已经
    Ctrl-C 之后还老老实实打完 5544 次网络请求。真正的收法是先掀 abort 闸、
    再 cancel 掉尚未起跑的任务。
    """
    writer = _StubWriter()
    harness = _Harness(
        total=600,
        chunk=4,
        workers=4,
        writer=writer,
        progress=_boom_progress(5, RuntimeError("停")),
    )
    harness.start()
    harness.assert_settled("abort 后")

    assert len(harness.fetched) < 600, "未起跑的任务应当被 cancel,而不是照单跑完"


def test_shutdown_returns_quickly_not_just_eventually() -> None:
    """收尾要「立刻」返回,不是「最终」返回 —— 秒级以上说明还在硬等 worker。"""
    writer = _StubWriter()
    harness = _Harness(
        total=400,
        chunk=4,
        workers=4,
        writer=writer,
        progress=_boom_progress(5, RuntimeError("停")),
    )
    harness.start()
    harness.assert_settled("abort 后")

    elapsed = harness.box.get("shutdown_sec")
    assert elapsed is not None
    assert elapsed < 5.0, f"pool.shutdown 花了 {elapsed:.1f}s,说明还在等阻塞的 worker"


def test_happy_path_still_drains_everything() -> None:
    """给 get() 加超时不能把正常路径改坏:每个 code 恰好一个 Outcome。"""
    writer = _StubWriter()
    harness = _Harness(total=200, chunk=8, workers=4, writer=writer)
    harness.start()
    harness.assert_settled("正常路径")

    assert harness.box.get("drain_error") is None
    assert len(writer.added) == 200
    assert sorted(writer.added) == sorted(harness.codes)
    assert writer.closed == 1
    assert len(harness.fetched) == 200


def test_slow_fetch_is_not_mistaken_for_a_stall() -> None:
    """``get(timeout=)`` 只是让 drain 醒过来看一眼,不能把慢源判成结束。

    单票取数几秒钟很正常(TDX 冷启探服务器就要 2s)。超时即放弃会把「慢」
    误判成「完了」,同步报告凭空少票 —— 那是比死锁更难查的静默错误。
    """
    codes = [f"{i:06d}" for i in range(6)]
    outcomes = sync_engine.make_queue(4)
    writer = _StubWriter()

    def fetch_one(code: str) -> sync_engine.Outcome:
        time.sleep(1.2)  # 比 drain 的轮询间隔长
        return sync_engine.Outcome(code=code, kind="ok")

    pool = sync_engine.fan_out(codes, fetch_one, outcomes, workers=6)
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            sync_engine.drain(outcomes, writer, len(codes))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            pool.shutdown(wait=True)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(timeout=JOIN_TIMEOUT)
    assert not thread.is_alive()
    assert box.get("error") is None
    assert len(writer.added) == 6, "慢源被误判成结束,少收了票"


def test_fan_out_does_not_orphan_the_pool_when_submit_explodes() -> None:
    """``submit`` 半途抛错时 pool 引用会丢 —— 丢了就永远没人 shutdown 它。

    ``fan_out`` 是「submit 完全部 codes 才 return pool」,中途抛错(线程耗尽、
    MemoryError)时调用方连 pool 都拿不到,线程池连同它的非守护线程一起变成孤儿。
    """
    outcomes = sync_engine.make_queue(4)
    codes = [f"{i:06d}" for i in range(400)]
    calls = {"n": 0}
    real_submit = ThreadPoolExecutor.submit

    def flaky_submit(self: ThreadPoolExecutor, fn: Any, *a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] > 20:
            raise RuntimeError("can't start new thread")
        return real_submit(self, fn, *a, **kw)

    def fetch_one(code: str) -> sync_engine.Outcome:
        time.sleep(0.01)
        return sync_engine.Outcome(code=code, kind="ok")

    baseline = threading.active_count()
    ThreadPoolExecutor.submit = flaky_submit  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            sync_engine.fan_out(codes, fetch_one, outcomes, workers=4)
    finally:
        ThreadPoolExecutor.submit = real_submit  # type: ignore[method-assign]

    # 已经 submit 出去的 20 个任务还在跑,队列 maxsize 只有 12:它们会填满队列
    # 然后堵死在 put() 上。调用方拿不到 pool,永远不会有人 shutdown 它 ——
    # 除非 fan_out 自己在抛出去之前先把池收干净。
    #
    # 注意这里**不抽队列**:抽了就等于替 fan_out 把 worker 放出来,测不出问题。
    deadline = time.monotonic() + JOIN_TIMEOUT
    while threading.active_count() > baseline and time.monotonic() < deadline:
        time.sleep(0.05)
    leaked = threading.active_count() - baseline

    # 判定完再救援,免得挂着的非守护线程把整个 pytest 进程的退出一起钉死。
    if leaked > 0:
        rescue_until = time.monotonic() + 30.0
        while threading.active_count() > baseline and time.monotonic() < rescue_until:
            try:
                while True:
                    outcomes.get_nowait()
            except queue.Empty:
                pass
            time.sleep(0.05)

    assert leaked <= 0, (
        f"submit 抛错后线程池成了孤儿:{leaked} 条 worker 还堵在 put() 上,"
        f"而调用方连 pool 引用都没拿到,永远等不到 shutdown"
    )
