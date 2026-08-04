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


def _splash_html(message: str = "启动中", *, phase: str = "enter") -> str:
    """原生窗口首屏 / 关闭过渡：印章 + 字标 + 开账线（与 SPA boot-splash 同构）。

    phase: enter | exit | error
    """
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    phase_key = phase if phase in {"enter", "exit", "error"} else "enter"
    kickers = {"enter": "开账", "exit": "落笔", "error": "中断"}
    kicker = kickers[phase_key]
    body_class = f"phase-{phase_key}"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Loci</title>
<style>
html,body{{margin:0;height:100%;color:#142033;
font-family:"IBM Plex Sans","Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif}}
body{{display:grid;place-items:center;
background:radial-gradient(ellipse 55% 40% at 50% 38%,rgba(196,30,58,.05),transparent 70%),#eef2f6}}
.stage{{display:flex;flex-direction:column;align-items:center;gap:15px;
width:min(14rem,72vw);animation:rise .42s ease-out both}}
.mark{{position:relative;width:44px;height:44px;border-radius:6px;background:#c41e3a;
color:#fff;display:grid;place-items:center;font-family:Georgia,"Noto Serif SC","Songti SC",serif;
font-weight:700;letter-spacing:.03em;font-size:15px;
box-shadow:inset 0 -2px 0 rgba(0,0,0,.12);animation:seal .5s ease-out both}}
.mark::after{{content:"";position:absolute;inset:5px;border:1px solid rgba(255,255,255,.28);
border-radius:3px;pointer-events:none}}
.brand-block{{display:flex;flex-direction:column;align-items:center;gap:11px;width:100%}}
.brand{{font-family:Georgia,"Noto Serif SC","Songti SC",serif;font-size:23px;font-weight:700;
letter-spacing:.02em;line-height:1;color:#142033}}
.tape{{position:relative;width:100%;height:1px;background:#d5dce6;overflow:hidden}}
.tape-fill{{position:absolute;inset:0 auto 0 0;width:0;background:#c41e3a;
animation:tape-in .7s cubic-bezier(.22,1,.36,1) .18s forwards}}
.status{{display:flex;align-items:baseline;gap:7px;font-family:Consolas,"Cascadia Mono",
"IBM Plex Mono",monospace;font-size:11px;font-weight:500;letter-spacing:.14em;color:#5b6b7c;
animation:fade .45s ease .28s both}}
.kicker{{color:#8a96a5}}.dot{{color:#c5ced9}}
.phase-exit{{opacity:.92}}
.phase-exit .stage{{animation:sink .5s ease both}}
.phase-exit .tape-fill{{animation:tape-out .55s cubic-bezier(.4,0,.2,1) .05s forwards;width:72%}}
.phase-error .tape-fill{{animation:none;width:42%;background:#5b6b7c}}
.phase-error .status{{animation:none}}
@keyframes rise{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
@keyframes sink{{from{{opacity:1;transform:none}}to{{opacity:.85;transform:translateY(4px)}}}}
@keyframes seal{{from{{opacity:0;transform:scale(.92)}}to{{opacity:1;transform:none}}}}
@keyframes tape-in{{from{{width:0}}to{{width:72%}}}}
@keyframes tape-out{{from{{width:72%}}to{{width:18%}}}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@media (prefers-reduced-motion:reduce){{
.stage,.mark,.status,.tape-fill{{animation:none!important}}
.tape-fill{{width:72%}}.phase-exit .tape-fill{{width:28%}}.phase-error .tape-fill{{width:42%}}
}}
</style></head><body class="{body_class}"><div class="stage">
<div class="mark" aria-hidden="true">LC</div>
<div class="brand-block">
<div class="brand">Loci</div>
<div class="tape" aria-hidden="true"><div class="tape-fill"></div></div>
</div>
<div class="status" role="status">
<span class="kicker">{kicker}</span><span class="dot" aria-hidden="true">·</span>
<span id="h">{safe}</span>
</div></div></body></html>"""


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
    # live 选路已优先 sina/tencent（通常 <1s）；略放宽以扛偶发抖动
    with urllib.request.urlopen(f"{base}/api/market/live-tape", timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_tray_title(tape: dict[str, Any]) -> str:
    """托盘悬停文案：委托 market.live_tape（仓置顶 + 等宽排版）。"""
    from src.market.infrastructure.live_tape import format_tray_title

    return format_tray_title(tape)


def run_server(host: str, port: int) -> None:
    try:
        log(f"server thread start host={host} port={port}")
        # 桌面入口默认开调度器（盘后选股 / 行情同步）；可设 0 关闭
        os.environ.setdefault("PALACE_ENABLE_SCHEDULER", "1")
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
    on_show_peek: Callable[[], None] | None = None,
    tooltip: str = "Loci",
) -> Any:
    """右下角托盘：左键打开行情 Peek；菜单可回工作台；「退出」结束进程。"""
    import pystray

    def peek_item(icon, item):  # noqa: ARG001
        if on_show_peek is not None:
            on_show_peek()
        else:
            on_show()

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
        pystray.MenuItem("行情", peek_item, default=True),
        pystray.MenuItem("打开工作台", show_item),
        pystray.MenuItem("在浏览器中打开", browser_item) if on_open_browser else None,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_item),
    ]
    menu = pystray.Menu(*[i for i in items if i is not None])
    icon = pystray.Icon("Loci", _make_tray_image(), tooltip, menu)

    def refresh_loop() -> None:
        last_ok_title = tooltip
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
                # Windows 托盘 tip ≤128；超长 pystray 会 ValueError
                title = (_format_tray_title(tape) or tooltip)[:128]
                icon.title = title
                last_ok_title = title
            except Exception as exc:
                # 短暂超时/选路失败：保留上次成功文案，避免托盘一直「暂不可用」
                log(f"tray tape refresh failed: {type(exc).__name__}: {exc}")
                if last_ok_title and last_ok_title != tooltip:
                    icon.title = last_ok_title[:128]
                else:
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
                tray_icon.title = "Loci · 正在退出"
        except Exception:
            pass

        def finish() -> None:
            try:
                if tray_icon is not None:
                    tray_icon.stop()
            except Exception:
                pass
            _force_exit(0)

        # 给托盘提示一点可见时间，避免「点退出立刻消失」
        threading.Timer(0.45, finish).start()

    def show_again() -> None:
        open_path()

    def show_peek() -> None:
        open_path("/peek")

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
                on_show_peek=show_peek,
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
    parser.add_argument(
        "--allow-multi",
        action="store_true",
        help="允许同时开多个实例（默认单实例，二次启动会前置已有窗口）",
    )
    args = parser.parse_args(argv)

    log(f"boot frozen={getattr(sys, 'frozen', False)} argv={sys.argv!r}")

    if not args.allow_multi and not args.no_window:
        try:
            from src.shared.single_instance import claim_or_focus

            if not claim_or_focus(_writable_root()):
                log("another instance is running → focused existing window, exit")
                return 0
        except Exception:
            log("single-instance check failed:\n" + traceback.format_exc())

    try:
        port = pick_listen_port(args.host, args.port)
    except OSError as exc:
        alert(str(exc) + "\n请先关掉旧的 Loci 再开，或改用 --port 0。")
        return 2
    log(f"listen {args.host}:{port} (requested={args.port})")
    try:
        from src.shared.single_instance import update_port

        update_port(_writable_root(), port)
    except Exception:
        pass

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

    from src.shared.desktop_shell import DesktopShellHooks, run_desktop_shell

    return run_desktop_shell(
        webview=webview,
        url=url,
        server=server,
        no_tray=args.no_tray,
        hooks=DesktopShellHooks(
            log=log,
            alert=alert,
            force_exit=_force_exit,
            writable_root=_writable_root,
            wait_ready=_wait_ready,
            bootstrap_running=_bootstrap_running,
            splash_html=_splash_html,
            start_tray=start_tray,
            icon_ico=_icon_ico,
            run_browser_shell=run_browser_shell,
        ),
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
