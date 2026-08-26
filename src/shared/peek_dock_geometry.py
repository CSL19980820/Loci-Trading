"""行情小窗贴边几何：工作区、吸附边、缩进/展开矩形。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Edge = Literal["left", "right", "top", "bottom"]

PEEK_W = 340
PEEK_H = 340
GHOST_SIZE = 40
GHOST_PEEK_LR = 36
GHOST_PEEK_TB = 36
SNAP_PX = 24
STICK_PX = 48
UNDOCK_PX = 40


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
    """贴边时完整浮窗矩形 (x, y, w, h)。"""
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
    """缩进探头矩形 (x, y, w, h)。"""
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
