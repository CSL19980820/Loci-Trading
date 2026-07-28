"""创建 Windows 桌面快捷方式（便携 exe / 开发态均可）。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _desktop_dir() -> Path:
    # 优先「桌面」特殊文件夹（含 OneDrive 重定向）
    try:
        import ctypes
        from ctypes import wintypes

        CSIDL_DESKTOP = 0
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(0, CSIDL_DESKTOP, 0, SHGFP_TYPE_CURRENT, buf) == 0:
            path = Path(buf.value)
            if path.is_dir():
                return path
    except Exception:
        pass
    for cand in (
        Path.home() / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
    ):
        if cand.is_dir():
            return cand
    return Path.home() / "Desktop"


def _app_target() -> tuple[Path, Path, list[str]]:
    """返回 (启动目标, 工作目录, 额外参数)。"""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return exe, exe.parent, []
    root = Path(__file__).resolve().parent.parent
    packaged = root / "Loci.exe"
    if packaged.is_file():
        return packaged, root, []
    return Path(sys.executable).resolve(), root, [str(root / "loci.py")]


def _icon_path(workdir: Path) -> Path | None:
    for cand in (
        workdir / "assets" / "loci.ico",
        workdir / "loci.ico",
    ):
        if cand.is_file():
            return cand
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "assets" / "loci.ico"  # type: ignore[attr-defined]
        if bundled.is_file():
            return bundled
    return None


def create_desktop_shortcut(*, name: str = "Loci") -> dict[str, str]:
    """在当前用户桌面创建 .lnk，返回路径信息。"""
    target, workdir, args = _app_target()
    if not target.is_file():
        raise FileNotFoundError(f"找不到启动文件：{target}")

    desktop = _desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    link = desktop / f"{name}.lnk"
    ico = _icon_path(workdir)

    def q(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    lines = [
        "$ws = New-Object -ComObject WScript.Shell",
        f"$s = $ws.CreateShortcut({q(str(link))})",
        f"$s.TargetPath = {q(str(target))}",
        f"$s.WorkingDirectory = {q(str(workdir))}",
        "$s.Description = 'Loci · 多战法账本'",
        "$s.WindowStyle = 1",
    ]
    if args:
        lines.append(f"$s.Arguments = {q(subprocess.list2cmdline(args))}")
    if ico is not None:
        lines.append(f"$s.IconLocation = {q(str(ico) + ',0')}")
    lines.append("$s.Save()")
    script = "; ".join(lines)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not link.is_file():
        err = (completed.stderr or completed.stdout or "未知错误").strip()
        raise RuntimeError(f"创建快捷方式失败：{err}")
    return {
        "shortcut": str(link),
        "target": str(target),
        "workdir": str(workdir),
        "desktop": str(desktop),
    }
