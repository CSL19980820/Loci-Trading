"""把 src/shared/boot_splash_assets.py 的 _CSS 对齐到 frontend/index.html 里那份。

背景：`boot_splash.py` 同时喂两处启动图——`loci.py` 的原生预览窗（webview 起来
之前那一屏）和 `frontend/index.html` 的 SPA 内联启动图。两份 CSS 一旦漂移，
开 App 就会看到「原生图一个配色 → 交接给 SPA 图换一个配色」的跳变。

2026-08 前端把启动图改掉了（去 webfont、去衬线、圆角收到 3px、品牌字换等宽），
但没回写 Python 侧，于是 `tests/shared/test_boot_splash.py` 红，原生图也还是旧样式。
这个脚本以 **index.html 为准**回灌 Python，方向与 `sync_boot_splash_index.py` 相反。

2026-09 `boot_splash.py` 超 600 行拆成三块，`_CSS` 落到 `boot_splash_assets.py`，
回灌目标随之改到该文件——门面 `boot_splash.py` 里已经没有 `_CSS` 三引号块了。
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "index.html"
MODULE = ROOT / "src" / "shared" / "boot_splash_assets.py"


def main() -> None:
    index_html = INDEX.read_text(encoding="utf-8")
    match = re.search(r"<style>(.*?)</style>", index_html, re.DOTALL)
    if not match:
        raise SystemExit("frontend/index.html 里找不到内联 <style>")
    css = match.group(1).strip("\n")

    source = MODULE.read_text(encoding="utf-8")
    # _CSS = """....."""  —— 非贪婪匹配到第一个收尾三引号
    pattern = re.compile(r'(_CSS = """\n)(.*?)(""")', re.DOTALL)
    if not pattern.search(source):
        raise SystemExit(f"{MODULE.name} 里找不到 _CSS 三引号块")

    def _sub(m: re.Match[str]) -> str:
        return f"{m.group(1)}{css}\n{m.group(3)}"

    MODULE.write_text(pattern.sub(_sub, source, count=1), encoding="utf-8")
    print(f"已把 {len(css.splitlines())} 行 CSS 从 index.html 回灌到 {MODULE.name}")


if __name__ == "__main__":
    main()
