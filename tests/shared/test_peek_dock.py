from __future__ import annotations

from pathlib import Path
import time

from src.shared.peek_dock import (
    PeekDockController,
    Rect,
    collapsed_bounds,
    docked_bounds,
    edge_distances,
    hide_peek_from_taskbar,
    load_peek_prefs,
    nearest_snap_edge,
    run_on_ui_thread,
    save_peek_prefs,
    should_undock,
)


class _FakeHandle:
    def __init__(self, value: int) -> None:
        self._value = value

    def ToInt32(self) -> int:
        return self._value


class _FakeNative:
    def __init__(self) -> None:
        self.ShowInTaskbar = True
        self.Handle = _FakeHandle(4242)


def test_hide_peek_from_taskbar_clears_show_in_taskbar() -> None:
    native = _FakeNative()
    window = type("W", (), {"native": native})()
    assert hide_peek_from_taskbar(window) is True
    assert native.ShowInTaskbar is False


def test_hide_peek_from_taskbar_noop_without_native() -> None:
    window = type("W", (), {"native": None})()
    assert hide_peek_from_taskbar(window) is False


def test_run_on_ui_thread_direct_without_invoke() -> None:
    native = _FakeNative()
    window = type("W", (), {"native": native})()
    assert run_on_ui_thread(window, lambda: 7) == 7


def test_run_on_ui_thread_begin_invoke_when_not_waiting() -> None:
    calls: list[str] = []

    class Native:
        InvokeRequired = True

        def BeginInvoke(self, action) -> None:  # noqa: N802
            calls.append("begin")
            action()

        def Invoke(self, action) -> None:  # noqa: N802
            calls.append("invoke")
            action()

    window = type("W", (), {"native": Native()})()
    assert run_on_ui_thread(window, lambda: 1, wait=False) is None
    assert calls == ["begin"]


def test_run_on_ui_thread_marshals_when_invoke_required() -> None:
    calls: list[str] = []

    class _InvokeNative:
        InvokeRequired = True

        def Invoke(self, action) -> None:  # noqa: N802 — WinForms API
            calls.append("invoke")
            action()

    window = type("W", (), {"native": _InvokeNative()})()
    assert run_on_ui_thread(window, lambda: 42) == 42
    assert calls == ["invoke"]


def test_hide_peek_from_taskbar_uses_ui_invoke() -> None:
    calls: list[str] = []

    class _InvokeNative(_FakeNative):
        InvokeRequired = True

        def Invoke(self, action) -> None:  # noqa: N802
            calls.append("invoke")
            action()

    native = _InvokeNative()
    window = type("W", (), {"native": native})()
    assert hide_peek_from_taskbar(window) is True
    assert native.ShowInTaskbar is False
    assert calls == ["invoke"]


def test_nearest_snap_edge_right() -> None:
    work = Rect(0, 0, 1920, 1080)
    # 窗右缘贴工作区右
    assert nearest_snap_edge(work, 1920 - 340 - 10, 200, 340, 340) == "right"


def test_nearest_snap_edge_ignores_corners() -> None:
    work = Rect(0, 0, 1920, 1080)
    # 同时贴右上角
    assert nearest_snap_edge(work, 1920 - 340, 5, 340, 340) is None


def test_nearest_snap_edge_free_when_far() -> None:
    work = Rect(0, 0, 1920, 1080)
    assert nearest_snap_edge(work, 800, 400, 340, 340) is None


def test_collapsed_bounds_right_peek_width() -> None:
    work = Rect(0, 0, 1920, 1080)
    x, y, w, h = collapsed_bounds(work, "right", y_hint=400)
    assert w == 36
    assert h == 40
    assert x == 1920 - 36
    assert y == 400


def test_collapsed_bounds_top_shows_face_height() -> None:
    work = Rect(0, 0, 1920, 1080)
    _x, y, w, h = collapsed_bounds(work, "top")
    assert w == 40
    assert h == 36
    assert y == 0


def test_docked_bounds_left() -> None:
    work = Rect(0, 0, 1920, 1080)
    x, y, w, h = docked_bounds(work, "left", y_hint=100)
    assert (x, w, h) == (0, 340, 340)
    assert y == 100


def test_should_undock() -> None:
    work = Rect(0, 0, 1920, 1080)
    assert should_undock(work, "right", 1000, 200, 340, 340) is True
    assert should_undock(work, "right", 1920 - 340, 200, 340, 340) is False


def test_edge_distances() -> None:
    work = Rect(0, 0, 1000, 800)
    d = edge_distances(work, 0, 10, 100, 100)
    assert d["left"] == 0
    assert d["top"] == 10


def test_peek_prefs_round_trip(tmp_path: Path) -> None:
    saved = save_peek_prefs(
        {"peek_edge": "left", "peek_collapsed": False, "peek_y": 120},
        root=tmp_path,
    )
    assert saved["peek_edge"] == "left"
    assert saved["peek_collapsed"] is False
    assert saved["peek_y"] == 120
    again = load_peek_prefs(tmp_path)
    assert again == saved


def test_attach_keeps_free_phase_even_when_prefs_collapsed(tmp_path: Path, monkeypatch) -> None:
    """工厂窗是 340²；attach 不得只改 phase 为 collapsed，否则前端透明白块。"""
    save_peek_prefs(
        {"peek_edge": "right", "peek_collapsed": True, "peek_y": 200},
        root=tmp_path,
    )
    monkeypatch.setattr(
        "src.shared.peek_dock.load_peek_prefs",
        lambda root=None: load_peek_prefs(tmp_path),
    )

    class _Events:
        def __iadd__(self, _cb):  # noqa: ANN001
            return self

    class _Win:
        def __init__(self) -> None:
            self.events = type("E", (), {"moved": _Events(), "loaded": _Events()})()

    ctl = PeekDockController()
    ctl.attach(_Win())
    assert ctl.phase == "free"
    assert ctl.edge == "right"
    assert ctl.y_hint == 200


def test_stick_zone_wider_than_snap() -> None:
    from src.shared.peek_dock import STICK_PX, SNAP_PX

    assert STICK_PX >= SNAP_PX


def test_show_from_tray_marshals_show_on_ui_thread() -> None:
    calls: list[str] = []

    class _InvokeNative(_FakeNative):
        InvokeRequired = True

        def Invoke(self, action) -> None:  # noqa: N802
            calls.append("invoke")
            action()

    class _Win:
        def __init__(self) -> None:
            self.native = _InvokeNative()
            self.x = 1580
            self.y = 400
            self.width = 36
            self.height = 40
            self.events = type("E", (), {"moved": type("H", (), {"__iadd__": lambda s, _h: s})(), "loaded": type("H", (), {"__iadd__": lambda s, _h: s})()})()

        def show(self) -> None:
            calls.append("show")

        def restore(self) -> None:
            calls.append("restore")

        def resize(self, w: int, h: int) -> None:
            self.width, self.height = w, h
            calls.append("resize")

        def move(self, x: int, y: int) -> None:
            self.x, self.y = x, y
            calls.append("move")

        def evaluate_js(self, _js: str) -> None:
            calls.append("js")

    win = _Win()
    ctl = PeekDockController()
    ctl.window = win
    ctl.phase = "collapsed"
    ctl.edge = "right"
    ctl.y_hint = 400
    ctl.show_from_tray()
    assert "show" in calls
    assert "restore" in calls
    assert calls.index("invoke") < calls.index("show")
    # show_from_tray 把 reveal 放到短延迟后台线程，避免与首帧抢 UI。
    deadline = time.monotonic() + 1.0
    while ctl.phase != "free" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ctl.phase == "free"
