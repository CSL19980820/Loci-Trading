"""Loci 本地 HTTP 接口。

组合根：鉴权、Session、健康检查、静态 SPA，并挂载各上下文路由。
"""
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from hmac import compare_digest
from ipaddress import ip_address
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

from src.app.login_throttle import LoginThrottle  # noqa: F401 — 测试/兼容 re-export
from src.app.write_token_policy import apply_write_token_policy
from src.ledger import PalaceError, PalaceStore
from src.ledger.api.router import build_ledger_router
from src.shared.observability import (
    current as current_observation,
    event as observation_event,
    header_values as observation_header_values,
    metric as observation_metric,
    span as observation_span,
)
from src.shared.paths import PROJECT_ROOT, ensure_data_dir, palace_db
from src.shared.webview_cache import purge_webview_http_cache_on_boot

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


def _is_loopback_client(request: Request) -> bool:
    """首启豁免只给直接本机请求；经代理转发的一律要求认证。"""
    if request.headers.get("forwarded") or request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _spawn_eod_catchup(
    *,
    ops_db: str | None,
    market_db: str | None,
    context_factory: Any,
) -> None:
    """后台补跑错过的盘后定点任务（不阻塞 API 启动）。"""
    import threading

    def _worker() -> None:
        try:
            from src.market import MarketStore
            from src.market.application.session import build_session_status
            from src.ops import OpsStore
            from src.ops.application.eod_catchup import run_eod_catchup

            with MarketStore(market_db) as market:
                session = build_session_status(
                    coverage=market.coverage(),
                    trading_days=market.trading_days(),
                )
            last_day = str(session.get("last_trading_day") or "").strip()
            if not last_day:
                return
            result = run_eod_catchup(
                ops_store_factory=lambda: OpsStore(ops_db),
                context_factory=context_factory,
                last_trading_day=last_day,
            )
            if result.get("ran") or result.get("errors"):
                logger.info(
                    "盘后补跑 @%s：due=%s ran=%s errors=%s",
                    last_day,
                    result.get("due"),
                    result.get("ran"),
                    result.get("errors"),
                )
        except Exception as exc:  # noqa: BLE001 — 补跑失败不拖垮服务
            logger.warning("盘后补跑跳过：%s", exc)

    threading.Thread(target=_worker, name="eod-catchup", daemon=True).start()


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
    try:
        from src.ai import migrate_encrypted_llm_keys

        purged_llm = migrate_encrypted_llm_keys()
        if purged_llm:
            logger.info("已清除 %s 条 LLM 旧加密凭据（请在运维页重录）", purged_llm)
    except Exception:
        logger.exception("清理 LLM 旧加密凭据失败（已忽略）")
    try:
        from src.intel import migrate_encrypted_mcp_tokens

        purged_mcp = migrate_encrypted_mcp_tokens()
        if purged_mcp:
            logger.info("已清除 %s 条 MCP 旧加密凭据（请在运维页重录）", purged_mcp)
    except Exception:
        logger.exception("清理 MCP 旧加密凭据失败（已忽略）")
    try:
        from src.strategy.application.screen_skills import refresh_screen_strategy_catalog

        refresh_screen_strategy_catalog()
    except Exception:
        logger.exception("刷新 Screen Skill 战法目录失败（已忽略）")
    # 打包桌面：uvicorn 拉起 app 时清 WebView HTTP 缓存（早于 load_url）
    try:
        purge_webview_http_cache_on_boot()
    except Exception:
        logger.exception("启动时清理 WebView 缓存失败（已忽略）")
    resolved_db = Path(db_path or os.environ.get("PALACE_DB") or DEFAULT_DB)
    runtime_environment = (environment or os.environ.get("PALACE_ENV") or "local").strip().lower()
    is_production = runtime_environment == "production"
    # 本地桌面默认可写；对网/共享主机可设 PALACE_REQUIRE_WRITE_AUTH=1 强制会话/Bearer
    require_write_auth = is_production or _env_flag("PALACE_REQUIRE_WRITE_AUTH")
    if not require_write_auth:
        logger.warning(
            "写鉴权开放（非 production）：浏览器会话恒真。"
            "对网暴露请设 PALACE_ENV=production 或 PALACE_REQUIRE_WRITE_AUTH=1"
        )
    resolved_hosts = allowed_hosts or _split_hosts(os.environ.get("PALACE_ALLOWED_HOSTS", ""))
    if is_production and not resolved_hosts:
        raise RuntimeError("生产环境必须配置 PALACE_ALLOWED_HOSTS")
    if not resolved_hosts:
        resolved_hosts = ["localhost", "127.0.0.1", "testserver"]
    resolved_write_token = write_token if write_token is not None else os.environ.get("PALACE_WRITE_TOKEN", "")
    apply_write_token_policy(
        write_token=resolved_write_token,
        is_production=is_production,
        require_write_auth=require_write_auth,
        issued_at_raw=os.environ.get("PALACE_WRITE_TOKEN_ISSUED_AT", ""),
        log=logger,
    )
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

    def reload_scheduler() -> None:
        scheduler = scheduler_box.get("instance")
        if scheduler is not None:
            scheduler.reload()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """进程内定时调度的启停。

        由入口显式开启（``loci.py`` / ``cli.serve`` 会 ``setdefault`` 为 1）；
        pytest 与一次性脚本不设该变量，避免半夜多份重复同步。生产 compose
        也可设 ``PALACE_ENABLE_SCHEDULER=1``。
        """
        def _ensure_managed_jobs() -> None:
            from src.ops import OpsStore
            from src.ops.application.ensure_managed_jobs import ensure_all_managed_jobs

            with OpsStore(os.environ.get("PALACE_OPS_DB") or None) as ops:
                ensure_all_managed_jobs(ops)

        if _env_flag("PALACE_ENABLE_SCHEDULER"):
            try:
                from src.ops import JobContext
                from src.ops import JobScheduler

                market_db = os.environ.get("PALACE_MARKET_DB") or None
                market_hot = os.environ.get("PALACE_MARKET_HOT_DB") or None
                scheduler = JobScheduler(
                    db_path=os.environ.get("PALACE_OPS_DB") or None,
                    context_factory=lambda: JobContext(
                        market_db=market_db, market_hot_db=market_hot
                    ),
                )
                scheduler.start()
                scheduler_box["instance"] = scheduler
                try:
                    _ensure_managed_jobs()
                except Exception as exc:  # noqa: BLE001 — 启动期兜底，不挡调度器
                    logger.warning("托管任务确保失败：%s", exc)
                plan = scheduler.reload()
                logger.info("调度器已启动，装载 %s 个任务", plan["count"])
                for rejected in plan["rejected"]:
                    logger.error(
                        "任务 %s 的 cron 非法：%s", rejected["name"], rejected["reason"]
                    )
                _spawn_eod_catchup(
                    ops_db=os.environ.get("PALACE_OPS_DB") or None,
                    market_db=market_db,
                    context_factory=lambda: JobContext(
                        market_db=market_db, market_hot_db=market_hot
                    ),
                )
            except ImportError as exc:
                logger.warning("调度器依赖缺失（%s），定时任务未启动", exc.name)
        else:
            # 未开调度器时仍写入托管绑定，避免桌面端首次只开 API 时任务表为空
            try:
                _ensure_managed_jobs()
            except Exception as jobs_exc:  # noqa: BLE001
                logger.debug("托管任务预写跳过：%s", jobs_exc)
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

    @app.middleware("http")
    async def observe_request(request: Request, call_next: Any) -> Any:
        """为 HTTP 请求建立本地相关性；默认不加响应头、不发外部数据。"""
        incoming = observation_header_values(request.headers)
        started = time.perf_counter()
        span_kwargs = {
            key: incoming.get(key)
            for key in ("trace_id", "run_id", "job_id", "source_id", "tool_receipt_id")
        }
        with observation_span(
            "http.request",
            **span_kwargs,
            labels={"component": "http", "operation": request.method.lower()},
        ) as correlation:
            try:
                response = await call_next(request)
            except Exception:
                elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
                observation_metric(
                    "loci.http.requests",
                    labels={"component": "http", "operation": request.method.lower(), "status": "error"},
                )
                observation_event(
                    logger,
                    logging.ERROR,
                    "http_request",
                    fields={
                        "method": request.method,
                        "status": "error",
                        "duration_ms": elapsed_ms,
                    },
                )
                raise
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            status = str(getattr(response, "status_code", 500))
            outcome = "success" if status.startswith("2") else "error"
            observation_metric(
                "loci.http.requests",
                labels={
                    "component": "http",
                    "operation": request.method.lower(),
                    "status": status[:3],
                    "outcome": outcome,
                },
            )
            route = getattr(request.scope.get("route"), "path", "") or "unmatched"
            observation_event(
                logger,
                logging.INFO if outcome == "success" else logging.WARNING,
                "http_request",
                fields={
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "duration_ms": elapsed_ms,
                },
            )
            if _env_flag("LOCI_OBSERVABILITY_EXPOSE"):
                response.headers["X-Loci-Trace-ID"] = correlation.trace_id or current_observation().trace_id
            return response

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
        if not require_write_auth:
            return True
        if not resolved_auth_username:
            return False
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
        }
        if path.startswith("/api/"):
            is_public_api = path in public_api_paths
            if path == "/api/ops/data-location":
                # 首次向导需要在登录前读取并选择数据目录；配置完成后该响应
                # 含本机安装、配置及数据库路径。仅本机首启可匿名，远端仍须认证。
                from src.shared.paths import needs_setup

                is_public_api = needs_setup() and _is_loopback_client(request)
            if not is_public_api and not (
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
        return JSONResponse(
            status_code=503,
            content={"detail": "账本繁忙或文件被占用，请稍后重试"},
        )

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        payload = {"status": "ok"}
        if not is_production:
            payload["db"] = str(resolved_db)
        return payload

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
            market_db=os.environ.get("PALACE_MARKET_DB") or None,
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
            setup_access_allowed=_is_loopback_client,
        )
    )

    # 全局助手独立挂载：会话与后台运行使用 ops.db，业务工具仍只经各域公开 API。
    from src.ai.api.assistant import build_assistant_router

    app.include_router(
        build_assistant_router(
            write_dependency=require_write_access,
            ops_db=os.environ.get("PALACE_OPS_DB") or None,
            palace_db=str(resolved_db),
            market_db=os.environ.get("PALACE_MARKET_DB") or None,
            scheduler_reloader=reload_scheduler,
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
    return app


app = create_app()
