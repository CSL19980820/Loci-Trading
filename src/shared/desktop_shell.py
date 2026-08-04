"""PyWebView 桌面窗口与托盘生命周期。

入口 ``loci.py`` 负责进程、单实例和服务启动；本模块只编排已启动服务
对应的窗口、行情 Peek 与托盘。可选 GUI 依赖均在运行路径内延迟导入，
使窗口策略可在无 Windows GUI 的环境中测试。
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class CloseAction(str, Enum):
    """窗口关闭事件的宿主动作。"""

    ALLOW_CLOSE = "allow_close"
    HIDE_TO_TRAY = "hide_to_tray"
    REQUEST_QUIT = "request_quit"
    CANCEL = "cancel"


class MinimizeAction(str, Enum):
    """主窗口最小化事件的宿主动作。"""

    HIDE_TO_TRAY = "hide_to_tray"
    KEEP_IN_TASKBAR = "keep_in_taskbar"
    IGNORE = "ignore"


def decide_main_close(
    *,
    quitting: bool,
    bootstrap_running: bool,
    quit_confirmed: bool,
) -> CloseAction:
    """主窗口关闭只在已进入退出流程时放行真正 destroy。"""
    if quitting:
        return CloseAction.ALLOW_CLOSE
    if bootstrap_running and not quit_confirmed:
        return CloseAction.CANCEL
    return CloseAction.REQUEST_QUIT


def decide_peek_close(*, quitting: bool) -> CloseAction:
    """行情 Peek 关闭前缩回托盘，完整退出时才放行 destroy。"""
    return CloseAction.ALLOW_CLOSE if quitting else CloseAction.HIDE_TO_TRAY


def decide_minimize(
    *,
    quitting: bool,
    tray_requested: bool,
    tray_started: bool,
    has_tray_icon: bool,
    minimize_to_tray: bool | None,
) -> MinimizeAction:
    """按托盘可用性与偏好决定主窗最小化去向。

    ``None`` 表示偏好读取失败，沿用桌面偏好的默认值：仍缩到托盘。
    """
    if quitting:
        return MinimizeAction.IGNORE
    if not tray_requested or not tray_started or not has_tray_icon:
        return MinimizeAction.KEEP_IN_TASKBAR
    if minimize_to_tray is False:
        return MinimizeAction.KEEP_IN_TASKBAR
    return MinimizeAction.HIDE_TO_TRAY


@dataclass(frozen=True)
class DesktopShellHooks:
    """入口提供的进程与 UI 边界，避免共享层反向依赖入口模块。"""

    log: Callable[[str], None]
    alert: Callable[[str], None]
    force_exit: Callable[[int], None]
    writable_root: Callable[[], Path]
    wait_ready: Callable[..., None]
    bootstrap_running: Callable[[str], bool]
    splash_html: Callable[..., str]
    start_tray: Callable[..., Any]
    icon_ico: Callable[[], Path]
    run_browser_shell: Callable[..., int]


def run_desktop_shell(
    *,
    webview: Any,
    url: str,
    server: threading.Thread,
    no_tray: bool,
    hooks: DesktopShellHooks,
) -> int:
    """创建主窗、行情 Peek 和托盘，并保留原有浏览器回退路径。"""
    state: dict[str, Any] = {
        "quitting": False,
        "tray_ok": False,
        "window": None,
        "peek": None,
        "peek_dock": None,
        "icon": None,
        "ready": False,
        "peek_url": None,
        "peek_loaded": False,
        "peek_show_inflight": False,
        "peek_creating": False,
    }

    def open_in_browser(path: str = "") -> None:
        import webbrowser

        webbrowser.open(f"{url}{path}")

    def show_main() -> None:
        window = state.get("window")
        if window is None:
            open_in_browser()
            return
        try:
            window.show()
            window.restore()
            hooks.log("window restored from tray")
        except Exception:
            hooks.log("show_main failed:\n" + traceback.format_exc())
            open_in_browser()

    def show_peek() -> None:
        """托盘「行情」→ 首次按需创建第二 WebView2，之后复用 dock。

        启动期不预建 Peek（双 WebView2 会卡死「启动中」）。创建必须在 GUI 线程；
        UI 线程异常经 Event 回传，失败才回退系统浏览器。
        """
        if state["quitting"] or state.get("peek_show_inflight"):
            return
        state["peek_show_inflight"] = True

        def _finish(ok: bool, detail: str = "") -> None:
            state["peek_show_inflight"] = False
            state["peek_creating"] = False
            if detail:
                hooks.log(detail)

        def _open_browser_fallback(reason: str) -> None:
            try:
                import webbrowser

                target = state.get("peek_url") or f"{url}/peek"
                webbrowser.open(str(target))
                hooks.log(f"peek fallback browser → {target} ({reason})")
                _finish(True, "peek opened via browser fallback")
            except Exception:
                hooks.log("peek browser fallback failed:\n" + traceback.format_exc())
                _finish(False)

        def _reveal_existing() -> None:
            dock = state.get("peek_dock")
            peek = state.get("peek")
            if dock is None or peek is None:
                raise RuntimeError("peek window missing")
            dock.show_from_tray()
            hooks.log("peek shown from tray (dock)")
            _finish(True)

        def _create_and_show() -> None:
            from src.shared.peek_dock import PEEK_H, PEEK_W, PeekDockApi, PeekDockController
            from src.shared.webview_ui import run_on_ui_thread

            main = state.get("window")
            if main is None:
                raise RuntimeError("main window missing")
            target = state.get("peek_url") or f"{url}/peek"
            state["peek_creating"] = True
            done = threading.Event()
            errors: list[BaseException] = []

            def _build() -> None:
                try:
                    dock = state.get("peek_dock")
                    if dock is None:
                        dock = PeekDockController(log=hooks.log)
                        state["peek_dock"] = dock
                    api = PeekDockApi(dock)
                    peek = webview.create_window(
                        "Loci · 行情",
                        url=str(target),
                        js_api=api,
                        width=PEEK_W,
                        height=PEEK_H,
                        on_top=True,
                        focus=False,
                    )
                    state["peek"] = peek
                    state["peek_loaded"] = True
                    dock.attach(peek)
                    try:
                        peek.events.closing += on_peek_closing
                    except Exception:
                        hooks.log("peek closing hook failed:\n" + traceback.format_exc())
                    hooks.log(f"peek window created on demand → {target}")
                    dock.show_from_tray()
                    hooks.log("peek shown from tray (dock)")
                except BaseException as exc:
                    errors.append(exc)
                    hooks.log("peek UI create failed:\n" + traceback.format_exc())
                finally:
                    done.set()

            # wait=False 避免托盘线程同步 Invoke 死锁；用 Event 收回成功/失败。
            run_on_ui_thread(main, _build, wait=False)
            if not done.wait(timeout=20.0):
                raise TimeoutError("peek window create timed out on UI thread")
            if errors:
                state["peek"] = None
                raise errors[0]
            _finish(True)

        def _run() -> None:
            try:
                if state.get("peek") is not None and state.get("peek_dock") is not None:
                    _reveal_existing()
                    return
                _create_and_show()
            except Exception:
                hooks.log("peek native open failed:\n" + traceback.format_exc())
                _open_browser_fallback("native create failed")

        threading.Thread(target=_run, name="loci-show-peek", daemon=True).start()

    def quit_app(*, from_window_close: bool = False) -> None:
        """统一退出：先显示过渡页，再关窗、停托盘并退出进程。"""
        if state["quitting"]:
            return
        state["quitting"] = True
        origin = "window-close" if from_window_close else "tray-menu"
        hooks.log(f"quit requested via {origin}")

        window = state.get("window")
        icon = state.get("icon")
        try:
            if icon is not None:
                icon.title = "Loci · 正在退出"
        except Exception:
            pass

        if window is not None:
            try:
                window.load_html(hooks.splash_html("正在关闭", phase="exit"))
                if not from_window_close:
                    window.show()
                    try:
                        window.restore()
                    except Exception:
                        pass
            except Exception:
                hooks.log("closing splash failed:\n" + traceback.format_exc())

        def finish_quit() -> None:
            try:
                if icon is not None:
                    icon.stop()
                    hooks.log("tray stopped")
            except Exception:
                hooks.log("tray stop failed:\n" + traceback.format_exc())
            for key in ("peek", "window"):
                win = state.get(key)
                try:
                    if win is not None:
                        win.destroy()
                except Exception:
                    hooks.log(f"destroy {key} failed:\n" + traceback.format_exc())
            # webview.start 未必立刻返回；定时强退避免残留 uvicorn。
            threading.Timer(0.8, lambda: hooks.force_exit(0)).start()

        delay = 0.55 if window is not None else 0.05
        threading.Timer(delay, finish_quit).start()

    def start_tray_once() -> None:
        if no_tray or state["tray_ok"]:
            return
        state["tray_ok"] = True
        try:
            # 桌面窗不暴露浏览器入口，避免本机 API URL 被其它浏览器页面复用。
            state["icon"] = hooks.start_tray(
                base_url=url,
                on_show=show_main,
                on_show_peek=show_peek,
                on_quit=quit_app,
            )
        except Exception:
            hooks.log("tray failed:\n" + traceback.format_exc())

    def confirm_bootstrap_exit() -> bool:
        try:
            import ctypes

            # MB_YESNO | MB_ICONWARNING
            choice = ctypes.windll.user32.MessageBoxW(
                0,
                "行情补数还在进行中，现在退出会中断同步。\n确定要退出吗？",
                "Loci",
                0x34,
            )
            if choice == 6:  # IDYES
                return True
            hooks.log("quit cancelled — bootstrap still running")
            return False
        except Exception:
            hooks.log("bootstrap quit prompt failed:\n" + traceback.format_exc())
            return True

    def on_closing() -> bool:
        running = False if state["quitting"] else hooks.bootstrap_running(url)
        confirmed = confirm_bootstrap_exit() if running else True
        action = decide_main_close(
            quitting=bool(state["quitting"]),
            bootstrap_running=running,
            quit_confirmed=confirmed,
        )
        if action is CloseAction.ALLOW_CLOSE:
            return True
        if action is CloseAction.CANCEL:
            return False
        quit_app(from_window_close=True)
        # 先取消本次关闭，让过渡页完成绘制，再由 quit_app 定时 destroy。
        return False

    def on_peek_closing() -> bool:
        if decide_peek_close(quitting=bool(state["quitting"])) is CloseAction.ALLOW_CLOSE:
            return True
        dock = state.get("peek_dock")
        if dock is not None:
            try:
                dock.hide()
                hooks.log("peek hidden (close → hide via dock)")
                return False
            except Exception:
                hooks.log("peek dock hide failed:\n" + traceback.format_exc())
        peek = state.get("peek")
        try:
            if peek is not None:
                peek.hide()
                hooks.log("peek hidden (close → hide)")
        except Exception:
            hooks.log("peek hide failed:\n" + traceback.format_exc())
        return False

    def on_minimized() -> None:
        preference: bool | None = None
        tray_requested = not no_tray
        tray_started = bool(state["tray_ok"])
        has_tray_icon = state.get("icon") is not None
        if (
            not state["quitting"]
            and tray_requested
            and tray_started
            and has_tray_icon
        ):
            try:
                from src.shared.desktop_prefs import minimize_to_tray_enabled

                preference = minimize_to_tray_enabled()
            except Exception:
                hooks.log("desktop prefs read failed:\n" + traceback.format_exc())

        action = decide_minimize(
            quitting=bool(state["quitting"]),
            tray_requested=tray_requested,
            tray_started=tray_started,
            has_tray_icon=has_tray_icon,
            minimize_to_tray=preference,
        )
        if action is MinimizeAction.IGNORE:
            return
        if action is MinimizeAction.KEEP_IN_TASKBAR:
            reason = "no tray" if not (tray_requested and tray_started and has_tray_icon) else "pref"
            hooks.log(f"window minimized → taskbar ({reason})")
            return
        window = state.get("window")
        if window is None:
            return
        try:
            window.hide()
            hooks.log("window minimized → tray (hidden)")
        except Exception:
            hooks.log("minimize→hide failed:\n" + traceback.format_exc())

    try:
        storage = hooks.writable_root() / "data" / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(storage))
        # 开发态也清缓存，避免改前端后仍吃旧 SPA（打包端 create_app 会再清一次）。
        os.environ.setdefault("LOCI_PURGE_WEBVIEW_CACHE", "1")
        try:
            from src.shared.webview_cache import purge_webview_http_cache

            cleared = purge_webview_http_cache(storage)
            if cleared:
                hooks.log(f"webview cache purged before window: {cleared}")
        except Exception:
            hooks.log("webview cache purge failed:\n" + traceback.format_exc())

        window = webview.create_window(
            "Loci",
            html=hooks.splash_html("启动中", phase="enter"),
            width=1280,
            height=860,
            min_size=(960, 640),
        )
        state["window"] = window

        peek_dock = None
        try:
            from src.shared.peek_dock import PeekDockController

            peek_dock = PeekDockController(log=hooks.log)
            state["peek_dock"] = peek_dock
        except Exception:
            hooks.log("peek dock init failed:\n" + traceback.format_exc())

        # 启动期只建主窗；Peek 延到首次托盘「行情」（见 show_peek）。
        state["peek"] = None

        def navigate_when_ready() -> None:
            from src.shared.webview_ui import run_on_ui_thread

            def _wait_native(win: Any, *, timeout: float = 30.0) -> bool:
                """webview.start 后才有 native；后台线程须等就绪再投递。"""
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if getattr(win, "native", None) is not None:
                        return True
                    time.sleep(0.05)
                return False

            try:
                hooks.wait_ready(f"{url}/api/health", timeout=90.0)
                state["ready"] = True
                boot = int(time.time())
                target = f"{url}/?_boot={boot}"
                state["peek_url"] = f"{url}/peek?_boot={boot}"
                state["peek_loaded"] = False
                if not _wait_native(window):
                    raise RuntimeError("main window native not ready for load_url")
                hooks.log(f"server ready {url} → load_url {target} (peek on-demand)")
                run_on_ui_thread(window, lambda: window.load_url(target), wait=False)
                hooks.log("main load_url scheduled")
            except Exception as exc:
                hooks.log(f"navigate failed: {exc}")
                try:
                    if _wait_native(window, timeout=5.0):
                        err_html = hooks.splash_html(f"启动失败：{exc}", phase="error")
                        run_on_ui_thread(
                            window, lambda: window.load_html(err_html), wait=False
                        )
                except Exception:
                    pass
                hooks.alert(f"后台服务启动失败：\n{exc}\n\n详情见 data/loci-startup.log")
        threading.Thread(
            target=navigate_when_ready,
            name="loci-navigate",
            daemon=True,
        ).start()

        window.events.closing += on_closing
        try:
            window.events.minimized += on_minimized
            window.events.restored += lambda: hooks.log("window restored")
        except Exception:
            pass
        try:
            window.events.shown += lambda: start_tray_once()
        except Exception:
            threading.Timer(1.5, start_tray_once).start()
        start_tray_once()
        hooks.log("tray init requested before webview.start()")

        start_kwargs: dict[str, Any] = {"storage_path": str(storage)}
        ico = hooks.icon_ico()
        if ico.is_file():
            start_kwargs["icon"] = str(ico)

        hooks.log(f"webview.start() kwargs={list(start_kwargs)}")
        started_at = time.monotonic()
        webview.start(**start_kwargs)
        elapsed = time.monotonic() - started_at
        hooks.log(f"webview exited after {elapsed:.1f}s quitting={state['quitting']}")
        if state["quitting"]:
            hooks.force_exit(0)
        if elapsed < 3.0:
            hooks.alert(
                "桌面窗口未能保持打开（可能缺少 WebView2）。\n"
                "已改用系统浏览器，并挂到托盘——右键托盘图标选「退出」。"
            )
            try:
                hooks.wait_ready(f"{url}/api/health")
            except Exception:
                pass
            return hooks.run_browser_shell(
                url=url,
                server=server,
                no_tray=no_tray,
                reason="浏览器模式（托盘可退出）",
            )
        return 0
    except Exception:
        hooks.log("webview failed:\n" + traceback.format_exc())
        hooks.alert(
            "桌面窗口打开失败，已改用系统浏览器。\n"
            "已挂到托盘——右键托盘图标选「退出」即可关闭，不必开任务管理器。"
        )
        try:
            hooks.wait_ready(f"{url}/api/health")
        except Exception:
            pass
        return hooks.run_browser_shell(
            url=url,
            server=server,
            no_tray=no_tray,
            reason="浏览器模式（托盘可退出）",
        )
