"""写锁的 fd 与锁文件必须成对归还 —— 这组测试守的是一处双重泄漏。

``market_write_lock`` 里 ``os.open(lock_path, O_CREAT | O_EXCL | O_WRONLY)`` 一旦成功,
磁盘上就已经躺着一把锁文件了。老代码紧接着的 ``os.write(descriptor, payload)``
如果抛 OSError(磁盘满 ENOSPC、只读挂载 EROFS、杀软拦截),异常会越过整个外层
``try``,而那层 ``finally`` 里**只有** ``local.release()``:

- ``descriptor`` 从不 ``close`` → 本进程 fd 泄漏,一次抽风一个,攒够就 EMFILE;
- ``lock_path`` 从不 ``unlink`` → 残留锁文件的 holder 前缀不是别人的 pid、
    age 又远不到 ``_LOCK_STALE_SEC``(默认 30 分钟),于是**其它进程被硬挡满 30 分钟**。

第二条才是真正致命的:一次写失败换来半小时的行情库全面瘫痪。
所以这里除了断言 fd 关了、文件删了,还要断言「下一次取锁能立刻成功」。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from src.market.infrastructure import write_lock
from src.market.infrastructure.write_lock import current_write_holder, market_write_lock

#: 把等锁上限压到几秒。默认 600s 是留给「排在一次真实全市场同步后面」的,
#: 但在这组用例里它只会让「残留锁挡住后来者」这个 bug 表现成**整个 pytest
#: 进程挂 10 分钟**,而不是一条读得懂的失败。压短之后同一个 bug 变成
#: 「5 秒后 MarketWriteBusy」,修好之后是毫秒级通过。
_SHORT_WAIT_SEC = 5.0


@pytest.fixture(autouse=True)
def _short_lock_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_lock, "_LOCK_WAIT_SEC", _SHORT_WAIT_SEC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "market.db"


@pytest.fixture
def lock_path(db_path: Path) -> Path:
    return write_lock._lock_path(db_path.resolve())


class _WriteExploder:
    """让写锁自己那个 fd 的 ``os.write`` 抛 OSError,别的 fd 一律放行。

    不能无差别地把 ``os.write`` 换掉:pytest 的输出捕获、logging 都在用它,
    一刀切会把测试自己也打死。所以先在 ``os.open`` 上认出锁文件的 fd,
    只对它抛。

    自己存取原函数而不借 ``monkeypatch``:用例里还要在恢复之后再取一次锁,
    而 ``monkeypatch.undo()`` 会把 autouse fixture 压短的等锁上限一并还原,
    于是「残留锁挡人」重新变成挂 10 分钟。
    """

    def __init__(self, lock_path: Path, *, errno: int = 28, msg: str = "No space left on device"):
        self.lock_path = lock_path
        self.errno = errno
        self.msg = msg
        self.opened: list[int] = []
        self._real_open = os.open
        self._real_write = os.write

    def _fake_open(self, path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = self._real_open(path, flags, *args, **kwargs)
        if str(path) == str(self.lock_path):
            self.opened.append(fd)
        return fd

    def _fake_write(self, fd: int, data: Any) -> int:
        if fd in self.opened:
            raise OSError(self.errno, self.msg)
        return self._real_write(fd, data)

    def __enter__(self) -> "_WriteExploder":
        os.open = self._fake_open  # type: ignore[assignment]
        os.write = self._fake_write  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> None:
        os.open = self._real_open  # type: ignore[assignment]
        os.write = self._real_write  # type: ignore[assignment]


@contextmanager
def _exploding_write(db_path: Path, lock_path: Path) -> Iterator[_WriteExploder]:
    """在「写 holder 必失败」的前提下跑一次取锁;交出记录到的 fd 供泄漏断言。"""
    with _WriteExploder(lock_path) as exploder:
        with pytest.raises(OSError) as caught:
            with market_write_lock(db_path, label="sync"):
                raise AssertionError("os.write 都失败了,不该进临界区")
        assert caught.value.errno == 28, "拦错了别的 OSError,断言等于没做"
        assert exploder.opened, "测试没拦到锁文件的 os.open,断言等于没做"
        yield exploder


def _fd_is_closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


def _assert_acquirable_now(db_path: Path, label: str) -> float:
    """再取一次锁并计时。残留锁在的话这里会一直等到 deadline 才抛 busy。"""
    started = time.monotonic()
    try:
        with market_write_lock(db_path, label=label):
            pass
    except write_lock.MarketWriteBusy as exc:
        raise AssertionError(
            f"残留锁把后来者挡住了(等了 {time.monotonic() - started:.1f}s):{exc}"
        ) from exc
    return time.monotonic() - started


def test_os_write_failure_closes_the_descriptor(db_path: Path, lock_path: Path) -> None:
    """磁盘满导致 os.write 抛错 → fd 必须已经关掉,不能一次抽风攒一个到 EMFILE。"""
    with _exploding_write(db_path, lock_path) as exploder:
        fd = exploder.opened[0]

    assert _fd_is_closed(fd), f"fd {fd} 泄漏了:os.write 失败后从没 close 过"


def test_os_write_failure_removes_the_lock_file(db_path: Path, lock_path: Path) -> None:
    """残留锁文件 = 其它进程被挡满 _LOCK_STALE_SEC,这是泄漏里更贵的一半。"""
    with _exploding_write(db_path, lock_path):
        pass

    assert not lock_path.exists(), (
        f"锁文件残留在 {lock_path}:holder 前缀不是别的进程的 pid、age 又不到 "
        f"{write_lock._LOCK_STALE_SEC / 60:.0f} 分钟,后来者会被硬挡这么久"
    )


def test_next_acquire_succeeds_immediately_after_a_write_failure(
    db_path: Path, lock_path: Path
) -> None:
    """真正的验收:一次写失败之后,下一次取锁还能**立刻**拿到。

    这条比「文件删了没」更贴近事故现场 —— 用户看到的是「行情库正在同步,
    请稍候」连报半小时,而实际上根本没有任何同步在跑。
    """
    with _exploding_write(db_path, lock_path):
        pass

    elapsed = _assert_acquirable_now(db_path, "spot")
    assert elapsed < _SHORT_WAIT_SEC / 2, f"下一次取锁等了 {elapsed:.1f}s,残留锁还在挡人"
    assert not lock_path.exists()


def test_write_failure_does_not_strand_the_in_process_rlock(
    db_path: Path, lock_path: Path
) -> None:
    """进程内那把 RLock 也得还回去,否则同进程另一条线程直接饿死。"""
    with _exploding_write(db_path, lock_path):
        pass

    assert current_write_holder(db_path) is None, "持锁者登记没清,诊断会指向一个幽灵"

    box: dict[str, Any] = {}

    def other_thread() -> None:
        try:
            with market_write_lock(db_path, label="other-thread"):
                box["got"] = True
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=other_thread, daemon=True)
    thread.start()
    thread.join(timeout=_SHORT_WAIT_SEC * 3)
    assert not thread.is_alive(), "另一条线程还卡在锁上"
    assert box.get("got") is True, f"另一条线程拿不到锁:{box.get('error')!r}"


def test_bookkeeping_failure_after_open_also_cleans_up(
    db_path: Path, lock_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.write 只是最容易炸的那一步,不是唯一一步。

    从 ``os.open`` 成功到 ``yield``,中间还夹着 record_lock_wait / event /
    logger.info。任何一处抛错都是同一种双重泄漏,所以清理必须覆盖**整段**,
    而不是只给 os.write 单独打个补丁。
    """

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("observability 后端挂了")

    with monkeypatch.context() as patched:
        patched.setattr(write_lock, "record_lock_wait", boom)
        with pytest.raises(RuntimeError):
            with market_write_lock(db_path, label="sync"):
                pass

    assert not lock_path.exists(), "记账环节抛错同样会留下残留锁文件"
    assert current_write_holder(db_path) is None
    _assert_acquirable_now(db_path, "after")


def test_normal_acquire_release_still_cleans_up(db_path: Path, lock_path: Path) -> None:
    """别为了修泄漏把正常路径改坏:正常出锁也要 close + unlink。"""
    with market_write_lock(db_path, label="sync"):
        assert lock_path.exists()
        assert current_write_holder(db_path) is not None
    assert not lock_path.exists()
    assert current_write_holder(db_path) is None


def test_body_exception_still_releases(db_path: Path, lock_path: Path) -> None:
    """临界区里业务抛错时,锁一样要还。"""
    with pytest.raises(ValueError):
        with market_write_lock(db_path, label="sync"):
            raise ValueError("同步炸了")

    assert not lock_path.exists()
    assert current_write_holder(db_path) is None
    _assert_acquirable_now(db_path, "again")


def test_reentrant_path_unaffected(db_path: Path, lock_path: Path) -> None:
    """同线程重入语义不能变:外层 sync 占着,内层 spot 直接放行。"""
    with market_write_lock(db_path, label="sync"):
        with market_write_lock(db_path, label="spot"):
            assert lock_path.exists()
        # 内层退出不许把外层的锁文件顺手删了
        assert lock_path.exists()
        assert current_write_holder(db_path) is not None
    assert not lock_path.exists()


def test_stale_lock_from_this_pid_is_still_taken_over(
    db_path: Path, lock_path: Path
) -> None:
    """本进程留下的残留锁照旧可以接管 —— 这条老行为不能被清理逻辑改掉。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(f"{os.getpid()}:stale-from-last-run", encoding="ascii")

    elapsed = _assert_acquirable_now(db_path, "sync")
    assert elapsed < _SHORT_WAIT_SEC / 2
    assert not lock_path.exists()


def test_memory_db_is_still_bypassed() -> None:
    """:memory: 没有对应文件,不该被清理逻辑带出 Windows 非法路径。"""
    with market_write_lock(":memory:", label="sync"):
        pass
