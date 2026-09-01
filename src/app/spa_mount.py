"""静态 SPA 的挂载与缓存策略：`/assets` 静态目录 + Vue Router 历史路由 catch-all。

两件事都只跟「前端产物怎么发出去」有关，与任何业务上下文无关，所以整块从
组合根挪出来。`install_spa_cache_control` 是中间件（注册顺序有意义，见下），
`mount_spa` 必须在**所有 API 路由都 include 完之后**再调用：catch-all 会吃掉
一切未匹配路径，先挂它等于把后面注册的接口全部遮住。
"""
from pathlib import Path
from typing import Any
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.shared.paths import PROJECT_ROOT


def install_spa_cache_control(app: FastAPI) -> None:
    """注册 SPA 缓存头中间件；注册位置决定它与其它中间件的层次，勿随手挪。"""

    @app.middleware("http")
    async def spa_cache_control(request: Request, call_next: Any) -> Any:
        """index/路由壳禁止缓存；带 hash 的 /assets 可长期缓存。"""
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            return response
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


def mount_spa(app: FastAPI, static_dir: Path | str | None = None) -> None:
    """挂载前端产物目录；目录不存在时静默跳过（纯 API 部署是合法形态）。

    **务必最后调用**：`serve_spa` 是 catch-all。
    """
    dist_dir = Path(
        static_dir or os.environ.get("PALACE_STATIC_DIR") or (PROJECT_ROOT / "frontend" / "dist")
    )
    if dist_dir.is_dir():
        resolved_dist = dist_dir.resolve()
        assets_dir = resolved_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="palace-assets")

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def serve_spa(frontend_path: str) -> FileResponse:
            """提供产物文件,并为 Vue Router 的历史路由回退到 index.html。

            ``/api/`` 下未匹配到路由的一律回 JSON 404,**不吐 SPA 外壳**。
            否则调用方拿到的是 200 + text/html:前端会以「JSON 解析失败」的形式炸在
            离现场十万八千里的地方,API 客户端也分不清「端点没了」和「服务器返回了页面」。
            持仓下线这一轮删掉十几个 `/api/*`,正是这类混淆最容易发生的时候。
            """
            if frontend_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="接口不存在:/%s" % frontend_path)
            requested = (resolved_dist / frontend_path).resolve()
            if frontend_path and requested.is_relative_to(resolved_dist) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(
                resolved_dist / "index.html",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
