"""全屏分时启动页（原生 webview 与 SPA #boot-splash 同构）。

enter：分时从 0 缓爬；开市前约 1s 从当前位拉到 100% 再淡出（不回撤）。
exit / error：安静收市页——印章 + 落笔线，不用分时、不倒退涨幅。

原文件 703 行超了仓库 600 行硬规则，按职责拆成三块；本模块只做对外门面，
`loci.py` / `desktop_shell.py` / `scripts/sync_boot_splash_index.py` / 测试都从这里进：

- `boot_splash_assets` —— CSS / JS / 文案字面量，被同步脚本机器读写
- `boot_splash_markup` —— 纯函数：拼原生 HTML 与 SPA 内联片段
- `boot_splash_handoff` —— 唯一有副作用的一段：注入 JS 跑完动画再导航
"""

from __future__ import annotations

from src.shared.boot_splash_assets import BOOT_SPLASH_REV
from src.shared.boot_splash_handoff import handoff_to_spa
from src.shared.boot_splash_markup import render_splash_html, spa_boot_splash_markup

__all__ = [
    "BOOT_SPLASH_REV",
    "handoff_to_spa",
    "render_splash_html",
    "spa_boot_splash_markup",
]
