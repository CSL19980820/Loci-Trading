"""Loci 本地 HTTP 接口。

组合根：鉴权、Session、健康检查、静态 SPA，并挂载各上下文路由。
"""
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from hmac import compare_digest
from pathlib import Path
import logging
import os
import sqlite3
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.ledger import PalaceError, PalaceStore
from src.ledger.api.router import build_ledger_router
from src.shared.paths import PROJECT_ROOT, ensure_data_dir, palace_db

logger = logging.getLogger(__name__)

DEFAULT_DB = palace_db()


class LoginInput(BaseModel):
    """固定管理员登录，仅用于浏览器会话，不建立用户体系。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


def _split_hosts(raw: str) -> list[str]:
    return [host.strip() for host in raw.split(",") if host.strip()]


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class LoginThrottle:
    """登录失败限流，防止固定口令被暴力枚举。

    单容器单进程部署，用内存计数就够；进程重启计数清零，这是已知取舍。
    它只是下限保护，真正的边界仍是 PALACE_AUTH_PASSWORD 的熵值，
    以及 HTTPS 部署下 Nginx 那层 Basic Auth。
    """

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        recent = [stamp for stamp in self._failures.get(key, []) if stamp > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, key: str) -> int:
        """仍在锁定期内返回剩余秒数；未锁定返回 0。"""
        now = time.monotonic()
        recent = self._recent(key, now)
        if len(recent) < self.max_failures:
            return 0
        return max(1, int(self.window_seconds - (now - recent[0])))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        recent = self._recent(key, now)
        recent.append(now)
        self._failures[key] = recent
        self._prune(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def _prune(self, now: float) -> None:
        """伪造来源 IP 可以刷出大量条目，超阈值时清掉已过期的键。"""
        if len(self._failures) <= 1024:
            return
        cutoff = now - self.window_seconds
        for key in [
            key
            for key, stamps in self._failures.items()
            if not any(stamp > cutoff for stamp in stamps)
        ]:
            self._failures.pop(key, None)


def create_app(
    db_path: Path | str | None = None,
    static_dir: Path | str | None = None,
    *,
    environment: str | None = None,
    allowed_hosts: list[str] | None = None,
    write_token: str | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    session_secret: str | None = None,
    insecure_http: bool | None = None,
) -> FastAPI:
    """创建可测试的 FastAPI 实例；每个请求独立持有 SQLite 连接。"""
    ensure_data_dir()
    resolved_db = Path(db_path or os.environ.get("PALACE_DB") or DEFAULT_DB)
    runtime_environment = (environment or os.environ.get("PALACE_ENV") or "local").strip().lower()
    is_production = runtime_environment == "production"
    resolved_hosts = allowed_hosts or _split_hosts(os.environ.get("PALACE_ALLOWED_HOSTS", ""))
    if is_production and not resolved_hosts:
        raise RuntimeError("生产环境必须配置 PALACE_ALLOWED_HOSTS")
    if not resolved_hosts:
        resolved_hosts = ["localhost", "127.0.0.1", "testserver"]
    resolved_write_token = write_token if write_token is not None else os.environ.get("PALACE_WRITE_TOKEN", "")
    resolved_auth_username = auth_username if auth_username is not None else os.environ.get("PALACE_AUTH_USERNAME", "")
    resolved_auth_password = auth_password if auth_password is not None else os.environ.get("PALACE_AUTH_PASSWORD", "")
    resolved_session_secret = session_secret if session_secret is not None else os.environ.get("PALACE_SESSION_SECRET", "")
    if is_production and not resolved_auth_username:
        raise RuntimeError("生产环境必须配置 PALACE_AUTH_USERNAME")
    if is_production and not resolved_auth_password:
        raise RuntimeError("生产环境必须配置 PALACE_AUTH_PASSWORD")
    if is_production and not resolved_session_secret:
        raise RuntimeError("生产环境必须配置 PALACE_SESSION_SECRET")
    # 会话 Cookie 默认带 Secure；只有显式声明的 HTTP 临时排障模式才放开。
    resolved_insecure_http = (
        insecure_http if insecure_http is not None else _env_flag("PALACE_INSECURE_HTTP")
    )
    if is_production and resolved_insecure_http:
        logger.warning(
            "PALACE_INSECURE_HTTP 已开启：会话 Cookie 不带 Secure 标记，"
            "登录凭证会以明文经网络传输。仅限短期排障，勿长期对公网运行。"
        )
    login_throttle = LoginThrottle()
    # 调度器实例存在这里，供关闭钩子与 /api/jobs/schedule 取用。
    scheduler_box: dict[str, Any] = {"instance": None}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """进程内定时调度的启停。

        显式开关而非默认开启：本地开发、跑测试、执行一次性脚本时都会创建
        app，不该顺手把定时任务也跑起来——半夜多份重复的行情同步就是这么
        来的。生产环境在 compose 里设 PALACE_ENABLE_SCHEDULER=1。
        """
        if _env_flag("PALACE_ENABLE_SCHEDULER"):
            try:
                from src.ops import JobContext
                from src.ops import JobScheduler

                market_db = os.environ.get("PALACE_MARKET_DB") or None
                scheduler = JobScheduler(
                    db_path=os.environ.get("PALACE_OPS_DB") or None,
                    context_factory=lambda: JobContext(market_db=market_db),
                )
                scheduler.start()
                scheduler_box["instance"] = scheduler
                plan = scheduler.reload()
                logger.info("调度器已启动，装载 %s 个任务", plan["count"])
                for rejected in plan["rejected"]:
                    logger.error(
                        "任务 %s 的 cron 非法：%s", rejected["name"], rejected["reason"]
                    )
            except ImportError as exc:
                logger.warning("调度器依赖缺失（%s），定时任务未启动", exc.name)
        try:
            yield
        finally:
            scheduler = scheduler_box.get("instance")
            if scheduler is not None:
                scheduler.shutdown()
                scheduler_box["instance"] = None

    app = FastAPI(
        lifespan=lifespan,
        title="Loci API",
        version="1.0.0",
        description="Loci 本地研究账本 API。所有读写均可追溯；不执行自动交易。",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_hosts)

    # 启动时跑一遍 schema/去重迁移，避免线上仍吃旧脏数据。
    with PalaceStore(resolved_db):
        pass

    def get_store() -> Generator[PalaceStore, None, None]:
        store = PalaceStore(resolved_db)
        try:
            yield store
        finally:
            store.close()

    def has_browser_session(request: Request) -> bool:
        """只认当前固定账号签发的、未被篡改的会话 Cookie。"""
        if not is_production:
            return True
        return compare_digest(str(request.session.get("username", "")), resolved_auth_username)

    def has_agent_token(request: Request) -> bool:
        """Agent 无浏览器会话时可用的服务器端 Bearer 令牌。"""
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        return bool(
            resolved_write_token
            and scheme.lower() == "bearer"
            and token
            and compare_digest(token, resolved_write_token)
        )

    def require_write_access(request: Request) -> None:
        """浏览器会话或 Agent Bearer 令牌均可写入不可变账本。"""
        if has_browser_session(request) or has_agent_token(request):
            return
        raise HTTPException(status_code=401, detail="请先登录或提供有效的 Bearer 令牌")

    @app.middleware("http")
    async def secure_response_headers(request: Request, call_next: Any) -> Any:
        """静态 SPA 与 JSON API 共用的浏览器安全响应头。"""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        return response

    @app.middleware("http")
    async def require_authenticated_access(request: Request, call_next: Any) -> Any:
        """线上仅开放登录页、健康检查及 Agent API；工作台路由需浏览器会话。"""
        if not is_production:
            return await call_next(request)

        path = request.url.path
        public_api_paths = {
            "/api/health",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/session",
            "/api/ops/data-location",
        }
        if path.startswith("/api/"):
            if path not in public_api_paths and not (
                has_browser_session(request) or has_agent_token(request)
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "请先登录或提供有效的 Bearer 令牌"},
                )
            return await call_next(request)

        # 只让未登录浏览器加载登录入口及其构建资源；工作台首页和档案路由被重定向。
        if path == "/login" or path.startswith("/assets/"):
            return await call_next(request)
        if not has_browser_session(request):
            return RedirectResponse(url="/login", status_code=307)
        return await call_next(request)

    if is_production:
        # FastAPI 中后添加的中间件位于外层，确保鉴权前可读取 request.session。
        app.add_middleware(
            SessionMiddleware,
            secret_key=resolved_session_secret,
            session_cookie="palace_session",
            max_age=60 * 60 * 24 * 30,
            same_site="lax",
            https_only=not resolved_insecure_http,
        )

    @app.exception_handler(PalaceError)
    async def palace_error_handler(_: Request, exc: PalaceError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.OperationalError)
    async def sqlite_operational_error_handler(
        _: Request, exc: sqlite3.OperationalError
    ) -> JSONResponse:
        """锁竞争/短暂不可用 → 503，前端可安全重试，而不是裸 500。"""
        logger.warning("sqlite operational error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "账本繁忙，请稍后重试"})

    @app.exception_handler(sqlite3.DatabaseError)
    async def sqlite_database_error_handler(
        _: Request, exc: sqlite3.DatabaseError
    ) -> JSONResponse:
        logger.exception("sqlite database error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "账本暂时不可用，请稍后重试"})

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "db": str(resolved_db)}

    def _throttle_key(request: Request) -> str:
        """限流按来源 IP 计。uvicorn 以 --proxy-headers 启动，
        经 Nginx 转发后 request.client.host 已是真实来源。"""
        return request.client.host if request.client else "unknown"

    @app.post("/api/auth/login", tags=["auth"])
    def login(payload: LoginInput, request: Request) -> dict[str, str | bool]:
        if not is_production:
            return {"authenticated": True, "username": "local"}
        throttle_key = _throttle_key(request)
        blocked_for = login_throttle.retry_after(throttle_key)
        if blocked_for:
            logger.warning("登录失败次数过多，暂时拒绝来源 %s", throttle_key)
            raise HTTPException(
                status_code=429,
                detail="登录失败次数过多，请稍后再试",
                headers={"Retry-After": str(blocked_for)},
            )
        if not (
            compare_digest(payload.username, resolved_auth_username)
            and compare_digest(payload.password, resolved_auth_password)
        ):
            login_throttle.record_failure(throttle_key)
            raise HTTPException(status_code=401, detail="账号或密码错误")
        login_throttle.reset(throttle_key)
        request.session.clear()
        request.session["username"] = resolved_auth_username
        return {"authenticated": True, "username": resolved_auth_username}

    @app.post("/api/auth/logout", tags=["auth"])
    def logout(request: Request) -> dict[str, bool]:
        if is_production:
            request.session.clear()
        return {"authenticated": False}

    @app.get("/api/auth/session", tags=["auth"])
    def session(request: Request) -> dict[str, str | bool]:
        if not is_production:
            return {"authenticated": True, "username": "local"}
        authenticated = has_browser_session(request)
        return {
            "authenticated": authenticated,
            "username": resolved_auth_username if authenticated else "",
        }

    app.include_router(
        build_ledger_router(
            write_dependency=require_write_access,
            get_store=get_store,
        )
    )

    # ---- 行情 / 策略 / 回测 / 技能 / 任务 / 供应商 -----------------
    # 这些能力依赖 pandas、akshare、apscheduler 等可选重量级库。router 内部
    # 全部懒导入：即便线上镜像只装了最小依赖，账本 API 也照常可用，
    # 对应接口返回 503 并说清缺什么。GET /api/capabilities 可一次看清。
    from src.app.legacy import build_quant_router

    app.include_router(
        build_quant_router(
            write_dependency=require_write_access,
            market_db=os.environ.get("PALACE_MARKET_DB") or None,
            ops_db=os.environ.get("PALACE_OPS_DB") or None,
            palace_db=str(resolved_db),
            scheduler_getter=lambda: scheduler_box["instance"],
        )
    )

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
            """提供产物文件，并为 Vue Router 的历史路由回退到 index.html。"""
            requested = (resolved_dist / frontend_path).resolve()
            if frontend_path and requested.is_relative_to(resolved_dist) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(resolved_dist / "index.html")
    return app


app = create_app()
