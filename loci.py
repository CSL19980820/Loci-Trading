#!/usr/bin/env python
"""Loci 桌面入口：本机 FastAPI + 系统窗口 + 系统托盘。"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_stdio() -> None:
    """windowed exe 下 stdout/stderr 为 None，uvicorn 日志初始化会直接崩。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


_ensure_stdio()


def _writable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    path = _writable_root() / "data" / "loci-startup.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(msg, flush=True)


def alert(msg: str, title: str = "Loci") -> None:
    log(f"ALERT: {msg}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)
    except Exception:
        pass


def info_box(msg: str, title: str = "Loci") -> None:
    log(f"INFO: {msg}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40)
    except Exception:
        pass


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_listen_port(host: str, preferred: int = 0) -> int:
    """preferred>0 且空闲则用之，否则交给系统分配实际端口。"""
    if preferred > 0:
        if _port_free(host, preferred):
            return preferred
        raise OSError(f"端口 {preferred} 已被占用")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _splash_html(message: str = "Loci 启动中") -> str:
    """原生窗口首屏：不等服务就绪也能先看见转圈。"""
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Loci</title>
<style>
html,body{{margin:0;height:100%;background:#f6f3ee;color:#1c1917;
font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{height:100%;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:14px}}
.mark{{width:40px;height:40px;border-radius:6px;background:#c41e3a;color:#fff;
display:grid;place-items:center;font-weight:700;letter-spacing:.04em}}
.spin{{width:22px;height:22px;border:2px solid #e7e0d6;border-top-color:#c41e3a;
border-radius:50%;animation:r .75s linear infinite}}
.hint{{font-size:13px;color:#78716c;letter-spacing:.06em}}
@keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body><div class="wrap">
<div class="mark">LC</div><div class="spin"></div>
<div class="hint" id="h">{safe}</div></div></body></html>"""


def _bootstrap_running(base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/api/market/bootstrap", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("status") or "") == "running"
    except Exception:
        return False


def _wait_ready(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= getattr(resp, "status", 200) < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(0.35)
    raise RuntimeError(f"服务未能在 {timeout:.0f}s 内就绪：{url}（{last_err}）")

    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= getattr(resp, "status", 200) < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(0.35)
    raise RuntimeError(f"服务未能在 {timeout:.0f}s 内就绪：{url}（{last_err}）")


def _fetch_tape(base: str) -> dict:
    with urllib.request.urlopen(f"{base}/api/market/live-tape", timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_pct(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.1f}%"


def _format_tray_title(tape: dict[str, Any]) -> str:
    """托盘悬停文案：指数一行 + 持仓多行（系统气泡不支持着色）。"""
    indices = tape.get("indices") or []
    positions = tape.get("positions") or []
    bits: list[str] = []
    for item in indices[:4]:
        label = str(item.get("label") or item.get("name") or item.get("code") or "")
        bits.append(f"{label}{_fmt_pct(item.get('pct'))}")
    pos_ok = [p for p in positions if p.get("ok") and p.get("pnl_pct") is not None]
    bag = ""
    if pos_ok:
        avg = sum(float(p["pnl_pct"]) for p in pos_ok) / len(pos_ok)
        bag = _fmt_pct(avg)
        bits.append(f"仓{bag}")
    lines = [f"指数：{'，'.join(bits) if bits else '暂无'}"]
    if pos_ok:
        lines.append(f"持仓：总 {bag}")
        for p in pos_ok[:8]:
            name = str(p.get("name") or p.get("label") or p.get("code") or "")
            if len(name) > 6:
                name = name[:6]
            lines.append(f"  {name} {_fmt_pct(p.get('pnl_pct'))}")
    elif positions:
        lines.append("持仓：行情暂不可用")
    else:
        lines.append("持仓：空仓")
    return "\n".join(lines)[:500]


def run_server(host: str, port: int) -> None:
    try:
        log(f"server thread start host={host} port={port}")
        from src.shared.paths import ensure_data_dir, market_db, writable_root

        root = ensure_data_dir()
        # 便携说明：放到 exe 旁（仅当还不存在）
        try:
            src = ROOT / "使用说明.txt"
            dst = writable_root() / "使用说明.txt"
            if src.is_file() and not dst.is_file():
                import shutil

                shutil.copy2(src, dst)
        except OSError:
            pass
        log(
            f"data_dir={root} market_db={market_db()} "
            f"size={market_db().stat().st_size if market_db().is_file() else 0}"
        )
        import uvicorn
        from src.app.main import app

        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            log_level="warning",
            log_config=None,
        )
    except Exception:
        log("server thread crashed:\n" + traceback.format_exc())


def _icon_png() -> Path:
    return ROOT / "assets" / "loci-icon.png"


def _icon_ico() -> Path:
    return ROOT / "assets" / "loci.ico"


def _make_tray_image():
    from PIL import Image

    png = _icon_png()
    if png.is_file():
        image = Image.open(png).convert("RGBA")
        return image.resize((64, 64), Image.Resampling.LANCZOS)

    # fallback if asset missing
    from PIL import ImageDraw

    image = Image.new("RGBA", (64, 64), (208, 18, 42, 255))
    draw = ImageDraw.Draw(image)
    draw.text((16, 18), "LC", fill=(255, 255, 255, 255))
    return image


def start_tray(
    *,
    base_url: str,
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
    on_open_browser: Callable[[], None] | None = None,
    tooltip: str = "Loci",
) -> Any:
    """右下角托盘：左键/「打开 Loci」唤回窗口；「退出」结束进程。"""
    import pystray

    def show_item(icon, item):  # noqa: ARG001
        on_show()

    def quit_item(icon, item):  # noqa: ARG001
        on_quit()
        try:
            icon.stop()
        except Exception:
            pass

    def browser_item(icon, item):  # noqa: ARG001
        if on_open_browser:
            on_open_browser()

    items = [
        pystray.MenuItem("打开 Loci", show_item, default=True),
        pystray.MenuItem("在浏览器中打开", browser_item) if on_open_browser else None,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_item),
    ]
    menu = pystray.Menu(*[i for i in items if i is not None])
    icon = pystray.Icon("Loci", _make_tray_image(), tooltip, menu)

    def refresh_loop() -> None:
        while True:
            try:
                # 非交易日 / 盘后库已最新：不刷实时，只保留静态提示
                with urllib.request.urlopen(f"{base_url}/api/market/session", timeout=4) as resp:
                    session = json.loads(resp.read().decode("utf-8"))
                if not session.get("live_allowed"):
                    reason = session.get("live_reason") or "off"
                    if reason == "non_trading_day":
                        icon.title = "Loci · 非交易日"
                    elif str(reason).startswith("after_close"):
                        icon.title = "Loci · 已收盘"
                    else:
                        icon.title = "Loci"
                    time.sleep(30)
                    continue
                tape = _fetch_tape(base_url)
                icon.title = _format_tray_title(tape) or tooltip
            except Exception:
                icon.title = "Loci · 行情暂不可用"
            time.sleep(5)

    threading.Thread(target=refresh_loop, name="loci-tray-tape", daemon=True).start()
    try:
        icon.run_detached()
        log("tray started (detached)")
    except Exception:
        threading.Thread(target=icon.run, name="loci-tray", daemon=True).start()
        log("tray started (thread)")
    return icon


def _force_exit(code: int = 0) -> None:
    """托盘/浏览器模式下干净退出，避免只剩无头 uvicorn 线程。"""
    log(f"force exit code={code}")
    os._exit(code)


def run_browser_shell(
    *,
    url: str,
    server: threading.Thread,
    no_tray: bool = False,
    reason: str = "",
) -> int:
    """浏览器回退：必须挂托盘，才能「退出」关掉进程。"""
    import webbrowser

    def open_path(path: str = "") -> None:
        webbrowser.open(f"{url}{path}")

    open_path()

    quit_flag = threading.Event()
    tray_icon: Any = None

    def quit_app() -> None:
        log("browser-shell quit requested")
        quit_flag.set()
        try:
            if tray_icon is not None:
                tray_icon.stop()
        except Exception:
            pass
        _force_exit(0)

    def show_again() -> None:
        open_path()

    if not no_tray:
        tip = "Loci · 浏览器模式（右键可退出）"
        if reason:
            tip = f"Loci · {reason}"
        try:
            tray_icon = start_tray(
                base_url=url,
                on_show=show_again,
                on_quit=quit_app,
                on_open_browser=show_again,
                tooltip=tip,
            )
        except Exception:
            log("browser-shell tray failed:\n" + traceback.format_exc())
            alert(
                "浏览器模式已打开，但托盘挂载失败。\n"
                "请关浏览器标签后，在任务管理器结束 Loci。\n\n"
                + traceback.format_exc()[-400:]
            )

    if tray_icon is None and not no_tray:
        # 托盘挂不上时至少弹一个可关的提示窗，避免无头进程
        alert("Loci 正在浏览器中运行。\n点「确定」将结束后台进程。")
        _force_exit(0)

    try:
        while server.is_alive() and not quit_flag.is_set():
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    _force_exit(0)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loci · 本地多战法账本")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="监听端口；0=系统自动分配空闲端口（推荐）",
    )
    parser.add_argument("--browser", action="store_true", help="只用系统浏览器")
    parser.add_argument("--no-window", action="store_true", help="只起服务")
    parser.add_argument("--no-tray", action="store_true", help="不启用托盘挂载")
    args = parser.parse_args(argv)

    log(f"boot frozen={getattr(sys, 'frozen', False)} argv={sys.argv!r}")

    try:
        port = pick_listen_port(args.host, args.port)
    except OSError as exc:
        alert(str(exc) + "\n请先关掉旧的 Loci 再开，或改用 --port 0。")
        return 2
    log(f"listen {args.host}:{port} (requested={args.port})")

    server = threading.Thread(
        target=run_server,
        args=(args.host, port),
        name="loci-uvicorn",
        daemon=True,
    )
    server.start()

    url = f"http://{args.host}:{port}"

    if args.no_window:
        try:
            _wait_ready(f"{url}/api/health")
            log(f"server ready {url}")
        except Exception as exc:
            alert(f"后台服务启动失败：\n{exc}\n\n详情见 data/loci-startup.log")
            return 1
        log(f"headless {url}")
        try:
            while server.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0

    def open_in_browser(path: str = "") -> None:
        import webbrowser

        webbrowser.open(f"{url}{path}")

    if args.browser:
        try:
            _wait_ready(f"{url}/api/health")
        except Exception as exc:
            alert(f"后台服务启动失败：\n{exc}")
            return 1
        return run_browser_shell(
            url=url,
            server=server,
            no_tray=args.no_tray,
            reason="浏览器模式",
        )

    try:
        import webview
    except ImportError:
        log("webview missing → browser fallback")
        try:
            _wait_ready(f"{url}/api/health")
        except Exception as exc:
            alert(f"后台服务启动失败：\n{exc}")
            return 1
        return run_browser_shell(
            url=url,
            server=server,
            no_tray=args.no_tray,
            reason="无桌面组件，浏览器模式",
        )

    state: dict[str, Any] = {
        "quitting": False,
        "tray_ok": False,
        "window": None,
        "icon": None,
        "ready": False,
    }

    def show_main() -> None:
        window = state.get("window")
        if window is None:
            open_in_browser()
            return
        try:
            window.show()
            window.restore()
            log("window restored from tray")
        except Exception:
            log("show_main failed:\n" + traceback.format_exc())
            open_in_browser()

    def quit_app(*, from_window_close: bool = False) -> None:
        """统一退出：关窗/停托盘/强杀进程（×、Alt+F4 与托盘「退出」同路径）。"""
        if state["quitting"]:
            return
        state["quitting"] = True
        origin = "window-close" if from_window_close else "tray-menu"
        log(f"quit requested via {origin}")
        if not from_window_close:
            window = state.get("window")
            try:
                if window is not None:
                    window.destroy()
            except Exception:
                log("destroy failed:\n" + traceback.format_exc())
        try:
            icon = state.get("icon")
            if icon is not None:
                icon.stop()
                log("tray stopped")
        except Exception:
            log("tray stop failed:\n" + traceback.format_exc())
        # webview.start 未必立刻返回；定时强退避免残留 uvicorn
        threading.Timer(0.8, lambda: _force_exit(0)).start()

    def start_tray_once() -> None:
        if args.no_tray or state["tray_ok"]:
            return
        state["tray_ok"] = True
        try:
            state["icon"] = start_tray(
                base_url=url,
                on_show=show_main,
                on_quit=quit_app,
                on_open_browser=lambda: open_in_browser(),
            )
        except Exception:
            log("tray failed:\n" + traceback.format_exc())

    def on_closing() -> bool:
        # 补数进行中：提醒用户，确认后才退出
        if _bootstrap_running(url):
            try:
                import ctypes

                # MB_YESNO | MB_ICONWARNING
                choice = ctypes.windll.user32.MessageBoxW(
                    0,
                    "行情补数还在进行中，现在退出会中断同步。\n确定要退出吗？",
                    "Loci",
                    0x34,
                )
                if choice != 6:  # IDYES
                    log("quit cancelled — bootstrap still running")
                    return False
            except Exception:
                log("bootstrap quit prompt failed:\n" + traceback.format_exc())
        quit_app(from_window_close=True)
        return True

    try:
        storage = _writable_root() / "data" / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(storage))

        # 先开窗转圈，服务就绪后再 load_url —— 体感更快
        window = webview.create_window(
            "Loci",
            html=_splash_html("Loci 启动中"),
            width=1280,
            height=860,
            min_size=(960, 640),
        )
        state["window"] = window

        def navigate_when_ready() -> None:
            try:
                _wait_ready(f"{url}/api/health", timeout=90.0)
                state["ready"] = True
                log(f"server ready {url} → load_url")
                window.load_url(url)
            except Exception as exc:
                log(f"navigate failed: {exc}")
                try:
                    window.load_html(
                        _splash_html(f"启动失败：{exc}")
                    )
                except Exception:
                    pass
                alert(f"后台服务启动失败：\n{exc}\n\n详情见 data/loci-startup.log")

        threading.Thread(
            target=navigate_when_ready,
            name="loci-navigate",
            daemon=True,
        ).start()

        window.events.closing += on_closing
        try:
            window.events.minimized += lambda: log("window minimized → taskbar (tray stays)")
            window.events.restored += lambda: log("window restored from taskbar")
        except Exception:
            pass
        try:
            window.events.shown += lambda: start_tray_once()
        except Exception:
            threading.Timer(1.5, start_tray_once).start()
        start_tray_once()
        log("tray init requested before webview.start()")

        start_kwargs: dict[str, Any] = {"storage_path": str(storage)}
        ico = _icon_ico()
        if ico.is_file():
            start_kwargs["icon"] = str(ico)

        log(f"webview.start() kwargs={list(start_kwargs)}")
        started_at = time.monotonic()
        webview.start(**start_kwargs)
        elapsed = time.monotonic() - started_at
        log(f"webview exited after {elapsed:.1f}s quitting={state['quitting']}")
        if state["quitting"]:
            _force_exit(0)
        if elapsed < 3.0:
            alert(
                "桌面窗口未能保持打开（可能缺少 WebView2）。\n"
                "已改用系统浏览器，并挂到托盘——右键托盘图标选「退出」。"
            )
            try:
                _wait_ready(f"{url}/api/health")
            except Exception:
                pass
            return run_browser_shell(
                url=url,
                server=server,
                no_tray=args.no_tray,
                reason="浏览器模式（托盘可退出）",
            )
        return 0
    except Exception:
        log("webview failed:\n" + traceback.format_exc())
        alert(
            "桌面窗口打开失败，已改用系统浏览器。\n"
            "已挂到托盘——右键托盘图标选「退出」即可关闭，不必开任务管理器。"
        )
        try:
            _wait_ready(f"{url}/api/health")
        except Exception:
            pass
        return run_browser_shell(
            url=url,
            server=server,
            no_tray=args.no_tray,
            reason="浏览器模式（托盘可退出）",
        )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        raise SystemExit(main())
    except Exception:
        text = traceback.format_exc()
        try:
            with _log_path().open("a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass
        alert("Loci 启动崩溃：\n" + text[-800:])
        raise
