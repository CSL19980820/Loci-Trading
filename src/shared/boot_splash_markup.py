"""把 CSS / JS / 文案拼成原生首屏 HTML 与 SPA 内联片段。

为什么单独成文件：这里全是纯函数——给定 phase 出字符串，无 IO、无线程，
测试只需断言子串。与 500 行字面量、与会死锁的交接逻辑混在一起时，
`tests/shared/test_boot_splash.py` 里「enter 不许出现回撤动画」这类断言
到底在防哪一层，读的人分不出来。
"""

from __future__ import annotations

from src.shared.boot_splash_assets import (
    BOOT_SPLASH_REV,
    _CSS,
    _ERROR_TIP,
    _EXIT_TIP,
    _JS,
)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _body_enter(*, tip: str = "本地服务启动中") -> str:
    return f"""<svg class="loci-boot-map" viewBox="0 0 960 640" width="100%" height="100%" preserveAspectRatio="none" aria-hidden="true"></svg>
<div class="loci-boot-brand">
  <div class="loci-boot-mark" aria-hidden="true">LC</div>
  <div class="loci-boot-name">Loci</div>
</div>
<div class="loci-boot-copy loci-tip-blink">
  <div class="loci-boot-kicker"><span class="loci-boot-phase">启动中</span></div>
  <div class="loci-boot-tip">{_escape(tip)}</div>
</div>"""


def _body_quiet(*, kicker: str, message: str, tip: str) -> str:
    """收市 / 中断：印章 + 落笔线，无分时图。"""
    status = (
        f'<span class="loci-boot-phase">{_escape(kicker)}</span>'
        f' · <span class="loci-boot-msg">{_escape(message)}</span>'
    )
    return f"""<div class="loci-boot-close">
  <div class="loci-boot-brand">
    <div class="loci-boot-mark" aria-hidden="true">LC</div>
    <div class="loci-boot-name">Loci</div>
  </div>
  <div class="loci-boot-close-rail" aria-hidden="true"></div>
  <div class="loci-boot-copy">
    <div class="loci-boot-kicker">{status}</div>
    <div class="loci-boot-tip">{_escape(tip)}</div>
  </div>
</div>"""


def render_splash_html(message: str = "启动中", *, phase: str = "enter") -> str:
    """原生窗口首屏 / 关闭 / 错误：完整 HTML 文档。"""
    phase_key = phase if phase in {"enter", "exit", "error"} else "enter"
    if phase_key == "enter":
        body = _body_enter()
    elif phase_key == "exit":
        body = _body_quiet(kicker="落笔", message=message, tip=_EXIT_TIP)
    else:
        body = _body_quiet(kicker="中断", message=message, tip=_ERROR_TIP)
    js = _JS.replace("__PHASE__", phase_key)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Loci</title>
<style>{_CSS}</style></head>
<body class="phase-{phase_key}">
<div id="boot-splash" class="loci-boot-root" data-rev="{BOOT_SPLASH_REV}" aria-busy="true" aria-live="polite">
{body}
</div>
<script>{js}</script>
</body></html>"""


def spa_boot_splash_markup() -> tuple[str, str, str]:
    """返回 (css, body_inner, js) 供 SPA index 同构嵌入；phase 固定 enter。"""
    body = _body_enter()
    js = _JS.replace("__PHASE__", "enter")
    return _CSS, body, js
