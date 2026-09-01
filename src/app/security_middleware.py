"""浏览器安全响应头中间件，外加组合根用到的几个环境/来源判定小工具。

`secure_response_headers` 给静态 SPA 与 JSON API 共用一套响应头（CSP、nosniff、
frame-ancestors…），是**兜底**层：它只 `setdefault`，不覆盖路由自己显式设过的头。

`_split_hosts` / `_env_flag` / `_is_loopback_client` 一起放这里，是因为它们全都
在回答同一类问题——「这次部署/这个请求处在什么安全语境里」：允许哪些 Host、
某个开关有没有打开、请求是不是真的来自本机（而不是代理转发来的）。组合根
`src/app/main.py` 仍 re-export 这三个名字，历史导入与 monkeypatch 继续成立。
"""
from base64 import b64encode
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
import os
import re
from typing import Any

from fastapi import FastAPI, Request

from src.shared.paths import PROJECT_ROOT

_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)


def _index_html_path() -> Path:
    """与 `mount_spa` 用同一套解析顺序，否则算出来的哈希对不上真正发出去的那份。"""
    raw = os.environ.get("PALACE_STATIC_DIR") or (PROJECT_ROOT / "frontend" / "dist")
    return Path(raw) / "index.html"


def _boot_script_hashes() -> list[str]:
    """index.html 里内联 `<script>` 的 CSP sha256 源表达式。

    首屏启动图必须在 JS 分片下载之前就铺满窗口，所以那段脚本只能内联。
    但 `script-src 'self'` 会把它拦掉——实测后果是 `#boot-splash` 退化成
    `position:static` 的裸 div，比视口还高，每次开 App 都先闪一坨没样式的东西。

    这里按**实际发出去的那份 index.html** 现算哈希：改了启动图不用手改白名单，
    也就不会出现「白名单过期 → 又被悄悄拦掉」的第二次事故。
    算不出来（纯 API 部署 / 产物缺失）就返回空表，CSP 退回最严格档。
    """
    try:
        html = _index_html_path().read_text(encoding="utf-8")
    except OSError:
        return []
    hashes = []
    for body in _INLINE_SCRIPT_RE.findall(html):
        digest = b64encode(sha256(body.encode("utf-8")).digest()).decode("ascii")
        hashes.append(f"'sha256-{digest}'")
    return hashes


def _split_hosts(raw: str) -> list[str]:
    return [host.strip() for host in raw.split(",") if host.strip()]


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_client(request: Request) -> bool:
    """首启豁免只给直接本机请求；经代理转发的一律要求认证。"""
    if request.headers.get("forwarded") or request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _build_csp() -> str:
    """组装 CSP。

    两处刻意的放宽，都写清了理由，别随手收紧或放大：

    * `script-src` 加的是**启动图内联脚本的 sha256**，不是 `'unsafe-inline'`——
      注入型脚本仍然进不来，只有 index.html 里那段字节完全一致的启动图能跑。
    * `style-src` 必须带 `'unsafe-inline'`：CSP 的 `style-src` 同时管 `<style>`
      元素和元素上的 `style="..."` 属性，而 Vue 的过渡、Element Plus 的弹层
      z-index 与表格列宽全靠运行时写 style 属性。不给就是满屏控制台报错加弹层错位。
          样式注入的危害远低于脚本注入，且本进程只监听回环地址。
    * `font-src` 要放 `data:`：Monaco 把 codicon 图标字体内联成 base64 data URL，
      不放行的话策稿台代码编辑器的折叠箭头、告警角标全变成豆腐块。字体不可执行，风险极低。
    """
    script_src = " ".join(["'self'", *_boot_script_hashes()])
    return (
        f"default-src 'self'; script-src {script_src}; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )


def install_secure_response_headers(app: FastAPI) -> None:
    """注册安全响应头中间件。

    **注册顺序有意义**：Starlette 后加的中间件先跑，组合根里这一行的位置决定了
    它相对 observe_request / 生产鉴权闸门 / TenantResolverMiddleware 的层次。
    搬动调用点前先读 `create_app` 里那几处顺序注释。
    """
    # CSP 只在装配时算一次：index.html 在进程生命周期内不会变，逐请求重读磁盘不值当。
    csp = _build_csp()

    @app.middleware("http")
    async def secure_response_headers(request: Request, call_next: Any) -> Any:
        """静态 SPA 与 JSON API 共用的浏览器安全响应头。"""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", csp)
        return response
