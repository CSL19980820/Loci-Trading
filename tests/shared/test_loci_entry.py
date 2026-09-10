"""Loci 桌面入口（根 `loci.py`）的可靠性回归。

两处旧伤：

1. 端口探测设了 SO_REUSEADDR。Windows 下两个都带 SO_REUSEADDR 的 socket 可以绑
   同一个 addr:port —— 而 uvicorn 正是这么绑的，于是「上一个 Loci 还开着」时
   `--port` 指定的端口被判成空闲，失败推迟到 uvicorn 自己 bind，再被 run_server
   的 except 吞掉。占用端口必须被判为占用。
2. 启动日志没有轮转。托盘线程 5s 一轮、失败即写一行，长期挂机会把文件写爆。
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import loci  # noqa: E402  仓根入口，不是包

HOST = "127.0.0.1"


@pytest.fixture
def occupied_port():
    """返回一个「真的被人 listen 着」的端口，测完关掉。

    reuse=True 那一档是关键回归：uvicorn 就是带着 SO_REUSEADDR 绑的，
    旧探测在 Windows 上会把这种端口判成空闲。
    """
    held = []

    def _open(reuse: bool) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if reuse:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, 0))
        sock.listen(1)
        held.append(sock)
        return int(sock.getsockname()[1])

    yield _open
    for sock in held:
        sock.close()


@pytest.mark.parametrize("reuse", [False, True])
def test_busy_port_is_reported_busy(occupied_port, reuse: bool) -> None:
    """占用端口必须被判为占用 —— 两种占用姿势都要认。"""
    port = occupied_port(reuse)
    assert loci._port_free(HOST, port) is False


@pytest.mark.parametrize("reuse", [False, True])
def test_pick_listen_port_refuses_busy_preferred(occupied_port, reuse: bool) -> None:
    """--port 指定了被占端口：当场 OSError，而不是放行给 uvicorn 去炸。"""
    port = occupied_port(reuse)
    with pytest.raises(OSError) as excinfo:
        loci.pick_listen_port(HOST, port)
    assert str(port) in str(excinfo.value)


def test_pick_listen_port_zero_returns_usable_port(occupied_port) -> None:
    """--port 0：系统分配的端口必须真的能绑。"""
    busy = occupied_port(True)
    port = loci.pick_listen_port(HOST, 0)
    assert port != busy
    assert loci._port_free(HOST, port) is True


def test_probe_sockopts_never_sets_reuseaddr_on_windows() -> None:
    """Windows：不设 SO_REUSEADDR，改要独占；这正是误判的根因。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        loci._probe_sockopts(sock, os_name="nt")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            assert sock.getsockopt(socket.SOL_SOCKET, exclusive) == 1


def test_probe_sockopts_keeps_reuseaddr_on_posix() -> None:
    """POSIX：SO_REUSEADDR 只放行 TIME_WAIT 残留，去掉反而会误判成占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        loci._probe_sockopts(sock, os_name="posix")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0


def _redirect_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "loci-startup.log"
    monkeypatch.setattr(loci, "_log_path", lambda: path)
    return path


def test_log_rotation_caps_total_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """长期挂机不能把日志写到没边：主文件 + N 份历史就是硬上限。"""
    _redirect_log(monkeypatch, tmp_path)
    monkeypatch.setattr(loci, "LOG_MAX_BYTES", 2048)
    monkeypatch.setattr(loci, "LOG_BACKUP_COUNT", 2)

    for idx in range(600):
        loci.log("tray tape refresh failed: URLError: timed out #" + str(idx))

    produced = sorted(tmp_path.glob("loci-startup.log*"))
    assert len(produced) <= 3, [p.name for p in produced]
    assert not (tmp_path / "loci-startup.log.3").exists()
    total = sum(p.stat().st_size for p in produced)
    # 每份最多写到超过阈值的那一行为止：3 * (2048 + 一行) 足够宽松又能证明有上限
    assert total <= 3 * (2048 + 512), total
    # 不轮转的话这 600 行本身就远超上限
    assert total < 600 * 60


def test_log_rotation_keeps_the_newest_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """轮转不能把「刚发生的事」转丢：最新一行永远在主文件里。"""
    path = _redirect_log(monkeypatch, tmp_path)
    monkeypatch.setattr(loci, "LOG_MAX_BYTES", 512)
    monkeypatch.setattr(loci, "LOG_BACKUP_COUNT", 1)

    for idx in range(200):
        loci.log("line " + str(idx))
    loci.log("最后一句话")

    assert "最后一句话" in path.read_text(encoding="utf-8")
    assert (tmp_path / "loci-startup.log.1").exists()


def test_log_survives_unwritable_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """日志写不下去也不能把启动流程带走。"""
    target = tmp_path / "nope" / "loci-startup.log"
    monkeypatch.setattr(loci, "_log_path", lambda: target)
    loci.log("still alive")


def test_wait_ready_fails_fast_when_server_thread_crashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uvicorn 线程炸了就别再空等 60s —— 直接把真正的原因抛出来。"""
    crash = "Traceback (most recent call last):\nOSError: [Errno 10048] 端口被占用"
    monkeypatch.setitem(loci.SERVER_ERROR, "traceback", crash)

    started = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        loci._wait_ready("http://127.0.0.1:1/api/health", timeout=30.0)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, elapsed
    assert "10048" in str(excinfo.value)
