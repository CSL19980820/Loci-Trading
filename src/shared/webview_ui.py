"""WinForms / WebView2 UI 线程辅助（托盘与后台线程勿直接碰 native）。"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Win32：工具窗样式，避免行情 Peek 占用任务栏按钮。
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000


def run_on_ui_thread(window: Any, action: Callable[[], T], *, wait: bool = True) -> T | None:
    """在 WinForms UI 线程执行；无 native / 已在 UI 线程则直接调用。

    ``wait=False`` 用 ``BeginInvoke`` 投递，避免后台线程同步 ``Invoke`` 死锁。
    """
    native = getattr(window, "native", None) if window is not None else None
    if native is None:
        result = action()
        return result if wait else None
    try:
        needs_invoke = bool(getattr(native, "InvokeRequired", False))
    except Exception:
        needs_invoke = False
    if not needs_invoke:
        result = action()
        return result if wait else None

    box: list[tuple[str, Any]] = []

    def _boxed() -> None:
        try:
            box.append(("ok", action()))
        except Exception as exc:
            box.append(("err", exc))

    try:
        from System import Action as NetAction

        net_action = NetAction(_boxed)
    except Exception:
        net_action = _boxed

    if not wait:
        begin = getattr(native, "BeginInvoke", None)
        if callable(begin):
            try:
                begin(net_action)
                return None
            except Exception:
                pass

    invoke = getattr(native, "Invoke", None)
    if not callable(invoke):
        result = action()
        return result if wait else None
    try:
        invoke(net_action)
    except Exception:
        try:
            invoke(_boxed)
        except Exception:
            result = action()
            return result if wait else None

    if not wait:
        return None
    if not box:
        return action()
    kind, payload = box[0]
    if kind == "err":
        raise payload
    return payload  # type: ignore[no-any-return]


def hide_peek_from_taskbar(window: Any) -> bool:
    """把 Peek 标成工具窗并从任务栏移除。Windows / pywebview native 可用时生效。"""
    native = getattr(window, "native", None)
    if native is None:
        return False

    def _apply() -> bool:
        changed = False
        try:
            native.ShowInTaskbar = False
            changed = True
        except Exception:
            pass
        hwnd = 0
        try:
            handle = native.Handle
            hwnd = int(handle.ToInt32()) if hasattr(handle, "ToInt32") else int(handle)
        except Exception:
            hwnd = 0
        if hwnd:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                style = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
                new_style = (style | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
                if new_style != style:
                    user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, new_style)
                    changed = True
            except Exception:
                pass
        return changed

    try:
        return bool(run_on_ui_thread(window, _apply))
    except Exception:
        return False
