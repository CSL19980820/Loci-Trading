"""行情小窗贴边吸附：几何计算 + 桌面窗控制器。

两态：``collapsed``（小圆形应用图标）/ ``free``（完整浮窗）。
滑过图标 → 自由浮窗；鼠标移开且仍贴边 → 自动缩回；拖出贴边范围 → 保持自由不缩。
偏好落在 ``data/desktop.json``（可重建）。
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.shared.desktop_prefs import load_desktop_prefs, save_desktop_prefs
from src.shared.webview_ui import hide_peek_from_taskbar, run_on_ui_thread

Edge = Literal["left", "right", "top", "bottom"]
Phase = Literal["free", "collapsed"]

PEEK_W = 340
PEEK_H = 340
# collapsed 探头要够大才能拖；过小（22×28）几乎抓不住。
GHOST_SIZE = 40
GHOST_PEEK_LR = 36
GHOST_PEEK_TB = 36
SNAP_PX = 24
# 移开鼠标时：仍在此距离内视为「贴边」，自动缩回
STICK_PX = 48
UNDOCK_PX = 40
SNAP_DEBOUNCE_MS = 280

LogFn = Callable[[str], None]

__all__ = [
    "PEEK_H",
    "PEEK_W",
    "SNAP_PX",
    "STICK_PX",
    "PeekDockApi",
    "PeekDockController",
    "Rect",
    "hide_peek_from_taskbar",
    "run_on_ui_thread",
]


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def default_peek_prefs() -> dict[str, Any]:
    return {
        "peek_edge": "right",
        "peek_collapsed": True,
        "peek_y": None,
    }


def load_peek_prefs(root: Any = None) -> dict[str, Any]:
    prefs = load_desktop_prefs(root)
    out = default_peek_prefs()
    edge = prefs.get("peek_edge", out["peek_edge"])
    if edge in {"left", "right", "top", "bottom"}:
        out["peek_edge"] = edge
    out["peek_collapsed"] = bool(prefs.get("peek_collapsed", out["peek_collapsed"]))
    y = prefs.get("peek_y", out["peek_y"])
    if y is None or isinstance(y, (int, float)):
        out["peek_y"] = int(y) if y is not None else None
    return out


def save_peek_prefs(
    updates: dict[str, Any],
    *,
    root: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if "peek_edge" in updates and updates["peek_edge"] in {
        "left",
        "right",
        "top",
        "bottom",
    }:
        payload["peek_edge"] = updates["peek_edge"]
    if "peek_collapsed" in updates:
        payload["peek_collapsed"] = bool(updates["peek_collapsed"])
    if "peek_y" in updates:
        y = updates["peek_y"]
        payload["peek_y"] = int(y) if y is not None else None
    if payload:
        save_desktop_prefs(payload, root=root)
    return load_peek_prefs(root)


def work_area_for_point(x: int, y: int) -> Rect:
    """Windows 多屏工作区；其它平台退回主屏近似。"""
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        monitor = user32.MonitorFromPoint(
            wintypes.POINT(int(x), int(y)),
            2,  # MONITOR_DEFAULTTONEAREST
        )
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        pass
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return Rect(0, 0, int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))
    except Exception:
        return Rect(0, 0, 1920, 1080)


def edge_distances(work: Rect, x: int, y: int, w: int, h: int) -> dict[Edge, int]:
    return {
        "left": abs(x - work.left),
        "right": abs((x + w) - work.right),
        "top": abs(y - work.top),
        "bottom": abs((y + h) - work.bottom),
    }


def nearest_snap_edge(
    work: Rect, x: int, y: int, w: int, h: int, *, threshold: int = SNAP_PX
) -> Edge | None:
    """四角死区：同时贴近两边时不吸附，避免抢边。"""
    d = edge_distances(work, x, y, w, h)
    near = {edge: dist for edge, dist in d.items() if dist <= threshold}
    if not near:
        return None
    lr = "left" in near or "right" in near
    tb = "top" in near or "bottom" in near
    if lr and tb:
        return None
    return min(near.items(), key=lambda item: item[1])[0]


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def docked_bounds(work: Rect, edge: Edge, *, y_hint: int | None = None) -> tuple[int, int, int, int]:
    """贴边时完整浮窗矩形 (x, y, w, h) —— 用于滑出/吸附对齐。"""
    w, h = PEEK_W, PEEK_H
    if edge == "right":
        x = work.right - w
        y = clamp(
            y_hint if y_hint is not None else work.top + (work.height - h) // 2,
            work.top,
            work.bottom - h,
        )
    elif edge == "left":
        x = work.left
        y = clamp(
            y_hint if y_hint is not None else work.top + (work.height - h) // 2,
            work.top,
            work.bottom - h,
        )
    elif edge == "top":
        x = clamp(
            y_hint if y_hint is not None else work.left + (work.width - w) // 2,
            work.left,
            work.right - w,
        )
        y = work.top
    else:
        x = clamp(
            y_hint if y_hint is not None else work.left + (work.width - w) // 2,
            work.left,
            work.right - w,
        )
        y = work.bottom - h
    return x, y, w, h


def collapsed_bounds(work: Rect, edge: Edge, *, y_hint: int | None = None) -> tuple[int, int, int, int]:
    """缩进探头矩形 (x, y, w, h)——小圆图标嵌边露出。"""
    if edge in {"left", "right"}:
        w, h = GHOST_PEEK_LR, GHOST_SIZE
        y = clamp(
            y_hint if y_hint is not None else work.top + (work.height - h) // 2,
            work.top,
            work.bottom - h,
        )
        x = work.right - w if edge == "right" else work.left
    else:
        w, h = GHOST_SIZE, GHOST_PEEK_TB
        x = clamp(
            y_hint if y_hint is not None else work.left + (work.width - w) // 2,
            work.left,
            work.right - w,
        )
        y = work.top if edge == "top" else work.bottom - h
    return x, y, w, h


def should_undock(work: Rect, edge: Edge, x: int, y: int, w: int, h: int) -> bool:
    d = edge_distances(work, x, y, w, h)
    return d[edge] > UNDOCK_PX


class PeekDockController:
    """绑定 pywebview Window：仅 collapsed ↔ free。"""

    def __init__(self, *, log: LogFn | None = None) -> None:
        self._log = log or (lambda _m: None)
        self.window: Any = None
        self.phase: Phase = "collapsed"
        self.edge: Edge = "right"
        self.y_hint: int | None = None
        self._programmatic = False
        self._snap_timer: threading.Timer | None = None
        self._hidden = True

    def attach(self, window: Any) -> None:
        self.window = window
        prefs = load_peek_prefs()
        self.edge = prefs["peek_edge"]  # type: ignore[assignment]
        self.y_hint = prefs["peek_y"]
        # 窗体工厂以 free 尺寸创建。若按 prefs 把 phase 标成 collapsed 却不改几何，
        # 前端会画透明缩进壳填满 340² → 托盘打开只见白块。
        # 贴边缩进只在可见态 collapse() 时发生；托盘打开走 reveal → free。
        self.phase = "free"
        try:
            window.events.moved += self._on_moved
        except Exception:
            self._log("peek dock: moved hook failed\n" + traceback.format_exc())
        try:
            window.events.loaded += self._on_loaded
        except Exception:
            self._log("peek dock: loaded hook failed\n" + traceback.format_exc())

    def _on_loaded(self) -> None:
        self._push_phase()
        # SPA 挂载晚于 loaded：再推几次，避免前端卡在 collapsed 透明空白壳。
        self._schedule_phase_push_retries()

    def show_from_tray(self) -> None:
        win = self.window
        if win is None:
            return
        self._cancel_snap()
        self._hidden = False

        def _show() -> None:
            win.show()
            win.restore()

        try:
            # wait=False：托盘/后台线程勿同步 Invoke（Peek 预加载时会卡十几秒白块）。
            run_on_ui_thread(win, _show, wait=False)
        except Exception:
            self._log("peek show failed\n" + traceback.format_exc())
            return
        # 延后一拍再改工具窗样式，避免与 WebView2 首帧抢同一 UI 线程导致卡死。
        def _apply_tool_chrome() -> None:
            time.sleep(0.35)
            try:
                hide_peek_from_taskbar(win)
            except Exception:
                self._log("peek taskbar hide failed\n" + traceback.format_exc())

        threading.Thread(target=_apply_tool_chrome, daemon=True).start()

        def _reveal_soon() -> None:
            time.sleep(0.05)
            try:
                # persist=True：与 free 几何对齐，避免 desktop.json 长期 peek_collapsed=true。
                self.reveal(persist=True)
                self._schedule_phase_push_retries()
            except Exception:
                self._log("peek reveal after show failed\n" + traceback.format_exc())

        threading.Thread(target=_reveal_soon, daemon=True).start()
    def hide(self) -> None:
        self._cancel_snap()
        self._hidden = True
        win = self.window
        if win is None:
            return
        try:
            win.hide()
        except Exception:
            self._log("peek hide failed\n" + traceback.format_exc())

    def pointer_enter(self) -> None:
        if self._hidden:
            return
        if self.phase == "collapsed":
            self.reveal()

    def pointer_leave(self) -> None:
        """移开鼠标：仍贴边则缩回；已拖出范围则保持自由。"""
        if self._hidden or self.phase == "collapsed":
            return
        if self._near_edge() is not None:
            self.collapse()

    def request_close(self) -> None:
        self.hide()

    def _cancel_snap(self) -> None:
        if self._snap_timer is not None:
            self._snap_timer.cancel()
            self._snap_timer = None

    def _window_box(self) -> tuple[int, int, int, int] | None:
        win = self.window
        if win is None:
            return None

        def read() -> tuple[int, int, int, int] | None:
            try:
                return int(win.x), int(win.y), int(win.width), int(win.height)
            except Exception:
                return None

        try:
            return run_on_ui_thread(win, read)
        except Exception:
            return None

    def _near_edge(self) -> Edge | None:
        box = self._window_box()
        if box is None:
            return None
        x, y, w, h = box
        work = work_area_for_point(x + w // 2, y + h // 2)
        return nearest_snap_edge(work, x, y, w, h, threshold=STICK_PX)

    def _on_moved(self, *args: Any) -> None:  # noqa: ANN401
        if self._programmatic or self._hidden:
            return
        self._cancel_snap()

        def after_drag() -> None:
            if self._programmatic or self._hidden:
                return
            self._resolve_after_drag()

        self._snap_timer = threading.Timer(SNAP_DEBOUNCE_MS / 1000.0, after_drag)
        self._snap_timer.daemon = True
        self._snap_timer.start()

    def _resolve_after_drag(self) -> None:
        box = self._window_box()
        if box is None:
            return
        x, y, w, h = box
        work = work_area_for_point(x + w // 2, y + h // 2)

        if self.phase == "collapsed":
            if should_undock(work, self.edge, x, y, w, h):
                self.phase = "free"
                self._apply_geometry(x, y, PEEK_W, PEEK_H)
                self._push_phase()
                self._persist()
                return
            self.collapse(y_hint=y if self.edge in {"left", "right"} else x)
            return

        edge = nearest_snap_edge(work, x, y, w, h)
        if edge is None:
            self.phase = "free"
            if w < PEEK_W or h < PEEK_H:
                self._apply_geometry(x, y, PEEK_W, PEEK_H)
            self._push_phase()
            self._persist()
            return
        self.snap_align(edge, y_hint=y if edge in {"left", "right"} else x)

    def snap_align(self, edge: Edge, *, y_hint: int | None = None) -> None:
        """贴边对齐，保持 free（完整浮窗）；移开鼠标才会缩。"""
        self.edge = edge
        if y_hint is not None:
            self.y_hint = y_hint
        self.phase = "free"
        box = self._window_box()
        if box is None:
            return
        x, y, w, h = box
        work = work_area_for_point(x + w // 2, y + h // 2)
        nx, ny, nw, nh = docked_bounds(work, edge, y_hint=self.y_hint)
        self._apply_geometry(nx, ny, nw, nh)
        self._push_phase()
        self._persist()

    def reveal(self, *, persist: bool = True) -> None:
        """从缩进滑出 → 自由完整浮窗（贴边对齐）。"""
        box = self._window_box()
        if box is None:
            cx, cy = 100, 100
        else:
            x, y, w, h = box
            cx, cy = x + max(1, w) // 2, y + max(1, h) // 2
        work = work_area_for_point(cx, cy)
        self.phase = "free"
        nx, ny, nw, nh = docked_bounds(work, self.edge, y_hint=self.y_hint)
        self._apply_geometry(nx, ny, nw, nh)
        self._push_phase()
        if persist:
            self._persist()

    def collapse(self, *, edge: Edge | None = None, y_hint: int | None = None) -> None:
        if edge is not None:
            self.edge = edge
        if y_hint is not None:
            self.y_hint = y_hint
        near = self._near_edge()
        if near is not None:
            self.edge = near
        box = self._window_box()
        if box is None:
            cx, cy = 100, 100
        else:
            x, y, w, h = box
            cx, cy = x + max(1, w) // 2, y + max(1, h) // 2
            if self.edge in {"left", "right"}:
                self.y_hint = y
            else:
                self.y_hint = x
        work = work_area_for_point(cx, cy)
        self.phase = "collapsed"
        nx, ny, nw, nh = collapsed_bounds(work, self.edge, y_hint=self.y_hint)
        self._apply_geometry(nx, ny, nw, nh)
        self._push_phase()
        self._persist()

    def _apply_geometry(self, x: int, y: int, w: int, h: int) -> None:
        win = self.window
        if win is None:
            return

        def apply() -> None:
            self._programmatic = True
            try:
                win.resize(max(w, GHOST_PEEK_LR), max(h, GHOST_PEEK_TB))
                win.move(int(x), int(y))
            except Exception:
                self._log("peek geometry failed\n" + traceback.format_exc())
            finally:

                def clear() -> None:
                    time.sleep(0.05)
                    self._programmatic = False

                threading.Thread(target=clear, daemon=True).start()

        try:
            run_on_ui_thread(win, apply)
        except Exception:
            self._log("peek geometry invoke failed\n" + traceback.format_exc())

    def _schedule_phase_push_retries(self) -> None:
        """前端桥接未就绪时 evaluate_js 为空操作；短窗重推与 PeekView 重同步互补。"""

        def retry(delay: float) -> None:
            time.sleep(delay)
            if self._hidden:
                return
            self._push_phase()

        for delay in (0.15, 0.45, 1.0):
            threading.Thread(target=retry, args=(delay,), daemon=True).start()

    def _push_phase(self) -> None:
        win = self.window
        if win is None:
            return
        phase = self.phase
        edge = self.edge
        js = (
            "window.__lociPeekSetPhase && window.__lociPeekSetPhase("
            f"{phase!r}, {edge!r})"
        )

        def push() -> None:
            try:
                win.evaluate_js(js)
            except Exception:
                pass

        try:
            run_on_ui_thread(win, push)
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            save_peek_prefs(
                {
                    "peek_edge": self.edge,
                    "peek_collapsed": self.phase == "collapsed",
                    "peek_y": self.y_hint,
                }
            )
        except Exception:
            self._log("peek prefs save failed\n" + traceback.format_exc())


class PeekDockApi:
    """暴露给 PeekView 的 pywebview js_api。"""

    def __init__(self, controller: PeekDockController) -> None:
        self._ctl = controller

    def peek_pointer_enter(self) -> None:
        self._ctl.pointer_enter()

    def peek_pointer_leave(self) -> None:
        self._ctl.pointer_leave()

    def peek_close(self) -> None:
        self._ctl.request_close()

    def peek_get_state(self) -> dict[str, str]:
        return {"phase": self._ctl.phase, "edge": self._ctl.edge}
