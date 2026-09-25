"""Loci 本地 HTTP 接口。

组合根：鉴权、Session、健康检查、静态 SPA，并挂载各上下文路由。
"""
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import os
import sqlite3
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.app.auth_guards import (
    build_auth_guards,
    current_context,  # noqa: F401 - 测试/兼容 re-export
)
from src.app.logging_setup import configure_logging
from src.app.login_throttle import LoginThrottle  # noqa: F401 — 测试/兼容 re-export
from src.app.security_middleware import (  # noqa: F401 - 下划线名同为兼容 re-export
    _env_flag,
    _is_loopback_client,
    _split_hosts,
    install_secure_response_headers,
)
from src.app.spa_mount import install_spa_cache_control, mount_spa
from src.app.startup_migrations import run_startup_self_heal
from src.app.tenant_middleware import TenantResolverMiddleware
from src.app.write_token_policy import apply_write_token_policy
from src.identity import (
    IdentityStore,
    build_admin_router,
    build_auth_dependency,
    build_auth_router,
    seed_default_admin,
)
from src.ledger import PalaceError, PalaceStore
from src.ledger.api.router import build_ledger_router
from src.shared.observability import (
    current as current_observation,
    event as observation_event,
    header_values as observation_header_values,
    metric as observation_metric,
    span as observation_span,
)
from src.shared.paths import ensure_data_dir, palace_db

# 必须在任何 logger 取用前执行：容器绕过 cli/serve.py 直起 uvicorn，没这一行应用自己的 INFO 在生产上一条都不输出（见 logging_setup）。
configure_logging()
logger = logging.getLogger(__name__)

DEFAULT_DB = palace_db()


class LoginInput(BaseModel):
    """固定管理员登录，仅用于浏览器会话，不建立用户体系。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)



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
    run_startup_self_heal()
    # 只有**显式传参**才钉死账本路径（测试与单库桌面部署依赖这个语义）。
    # PALACE_DB 环境变量刻意不参与钉死：它表达的是「这台机器主租户的那一份库」，
    # 由 paths.palace_db() 自己按租户判断——子租户仍要落到自己的目录，
    # 否则所有人共用一个账本，多租户当场失效。
    pinned_palace_db = bool(db_path)
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
    # v2 起这两个变量不再是「唯一的固定管理员」，而只是首启种子的入参。
    # 不配也能起：identity 会种出默认管理员 lociAdmin / Asdf!234（带强制改密）。
    # 但生产上用文档里写死的口令是高危状态，必须喊得足够大声。
    if is_production and not (resolved_auth_username and resolved_auth_password):
        logger.warning(
            "生产环境未配置 PALACE_AUTH_USERNAME/PASSWORD，将使用默认管理员账号。"
            "该口令是公开文档里的默认值，请立刻登录并修改，或配置这两个环境变量后重启。"
        )
    # 会话 Cookie 默认带 Secure；只有显式声明的 HTTP 临时排障模式才放开。
    resolved_insecure_http = (
        insecure_http if insecure_http is not None else _env_flag("PALACE_INSECURE_HTTP")
    )
    if is_production and resolved_insecure_http:
        logger.warning(
            "PALACE_INSECURE_HTTP 已开启：会话 Cookie 不带 Secure 标记，"
            "登录凭证会以明文经网络传输。仅限短期排障，勿长期对公网运行。"
        )
    # ---- 身份体系（v2 群龙）--------------------------------------
    # 老部署只有 PALACE_AUTH_USERNAME/PASSWORD 一对固定凭据；v2 把它们种成
    # identity.db 里的管理员账号，租户绑到 __primary__，也就是原来的 data/
    # 目录本身。升级即用：老用户登录后看到的还是自己那套账本，零迁移。
    identity_db_path = os.environ.get("LOCI_IDENTITY_DB") or None
    try:
        with IdentityStore(identity_db_path) as identity_store:
            seeded = seed_default_admin(
                identity_store,
                # 显式把部署声明的凭据交给种子函数，而不是塞进 os.environ——
                # 后者会跨测试/跨 app 实例泄漏，且没人清理。
                username=resolved_auth_username or None,
                password=resolved_auth_password or None,
            )
            if seeded is not None:
                logger.info("身份库已就绪，管理员：%s", seeded.username)
    except Exception:
        # 身份库建不起来不该让整个应用起不来：Agent Bearer 通道仍可用，
        # 运维还有机会进容器排查。
        logger.exception("初始化身份库失败（登录功能将不可用）")
    auth_dependency = build_auth_dependency(
        identity_db_path,
        # 桌面/本地形态自动以主租户管理员身份运行，保持单机零登录体验。
        auto_login_primary=not require_write_auth,
    )
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
        from src.research.infrastructure.backtest_jobs import recover_research_jobs
        from src.research.api.backtest_router import _BACKTEST_EXECUTOR
        from src.research.api.factor_router import _FACTOR_EXECUTOR
        from src.ops.api.guardian_consult import _CONSULT_EXECUTOR
        from fastapi.concurrency import run_in_threadpool
        executors = (_BACKTEST_EXECUTOR, _FACTOR_EXECUTOR, _CONSULT_EXECUTOR)
        await run_in_threadpool(recover_research_jobs)
        for executor in executors:
            executor.start()
        gateway = None
        if os.getenv("LOCI_GRPC_LISTEN"):
            from src.ai.infrastructure.grpc_gateway import start_from_env
            gateway = await start_from_env()
        try:
            yield
        finally:
            for executor in executors:
                await run_in_threadpool(executor.shutdown)
            if gateway is not None:
                await gateway.stop(5)
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
        """每请求解析一次账本路径：多租户下它随当前用户变。

        ``resolved_db`` 只在显式传参 / PALACE_DB 指定时是权威值；否则交给
        ``palace_db()`` 按 ContextVar 里的租户解析（见 src/shared/tenancy.py）。
        """
        store = PalaceStore(resolved_db if pinned_palace_db else palace_db())
        try:
            yield store
        finally:
            store.close()

    guards = build_auth_guards(
        require_write_auth=require_write_auth, write_token=resolved_write_token
    )
    has_browser_session = guards.has_browser_session
    has_agent_token = guards.has_agent_token
    require_write_access = guards.require_write_access

    install_secure_response_headers(app)

    install_spa_cache_control(app)

    from src.ops.api.guardian_share import PUBLIC_REPORT_PATH, build_report_share_router
    app.include_router(build_report_share_router())

    @app.middleware("http")
    async def require_authenticated_access(request: Request, call_next: Any) -> Any:
        """线上仅开放登录页、健康检查及 Agent API；工作台路由需浏览器会话。"""
        if not is_production:
            return await call_next(request)

        path = request.url.path
        if request.method in {"GET", "HEAD"} and PUBLIC_REPORT_PATH.fullmatch(path):
            return await call_next(request)
        # /api/auth/** 整个前缀公开：注册、找回密码、扫码轮询本来就是给未登录的人
        # 用的。只放行 /api/auth/login 会让注册页把自己挡在门外。
        public_api_prefixes = ("/api/auth/",)
        # 这几条虽在 /api/auth/ 下，但只有登录后才有意义，必须重新挡上。
        private_auth_prefixes = (
            "/api/auth/me",
            "/api/auth/api-keys",
            "/api/auth/notifications",
        )
        public_api_paths = {
            "/api/health",
        }
        if path.startswith("/api/"):
            is_public_api = path in public_api_paths or (
                path.startswith(public_api_prefixes)
                and not path.startswith(private_auth_prefixes)
            )
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

    if is_production and resolved_session_secret:
        # v2 之后已经**没有任何代码读 request.session**：身份走 identity 的
        # loci_session（服务端 sessions 表 + 不透明 token）。这一段只为兼容回滚——
        # 万一要退回 v1，palace_session 还能被认出来。没配 secret 就不装，
        # 于是「零环境变量也能起生产」成立。
        app.add_middleware(
            SessionMiddleware,
            secret_key=resolved_session_secret,
            session_cookie="palace_session",
            max_age=60 * 60 * 24 * 30,
            same_site="lax",
            https_only=not resolved_insecure_http,
        )

    # 必须是最外层中间件：后加的先跑。生产鉴权闸门 require_authenticated_access
    # 读的是 request.state.loci_auth，晚一层注册它就永远读不到（真踩过：登录 200
    # 但下一个请求仍然 401）。
    from src.app.visitor_access import VisitorAccessMiddleware

    app.add_middleware(VisitorAccessMiddleware)
    app.add_middleware(TenantResolverMiddleware, resolver=auth_dependency)

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

    # 身份与治理路由先挂：登录页在任何业务能力缺失时都必须可用。
    app.include_router(
        build_auth_router(
            auth_dependency=auth_dependency,
            identity_db=identity_db_path,
            # 本地 http 调试若带 Secure，浏览器根本不会回传 Cookie。
            cookie_secure=is_production and not resolved_insecure_http,
        )
    )
    app.include_router(
        build_admin_router(auth_dependency=auth_dependency, identity_db=identity_db_path)
    )
    try:
        from src.community import build_community_router

        app.include_router(
            build_community_router(
                write_dependency=require_write_access,
                auth_dependency=auth_dependency,
            )
        )
    except ImportError:
        # 社区上下文是可选能力：缺依赖时工作台照常可用。
        logger.warning("社区上下文未装载（community 依赖缺失）")

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
            palace_db=str(resolved_db) if pinned_palace_db else None,
            scheduler_getter=lambda: scheduler_box["instance"],
            setup_access_allowed=_is_loopback_client,
            # 装 / 卸技能包要管理员：技能包 = 代码，见 ops/api/skills._require_skill_admin
            auth_dependency=auth_dependency,
        )
    )

    # 全局助手独立挂载：会话与后台运行使用 ops.db，业务工具仍只经各域公开 API。
    from src.ai.api.assistant import build_assistant_router

    app.include_router(
        build_assistant_router(
            write_dependency=require_write_access,
            # 一律传 None：助手会话与 LLM 供应商都在租户自己的 ops.db 里，
            # 把 PALACE_OPS_DB 钉进去等于让所有人共用一套密钥与对话。
            ops_db=None,
            palace_db=str(resolved_db) if pinned_palace_db else None,
            market_db=os.environ.get("PALACE_MARKET_DB") or None,
            scheduler_reloader=reload_scheduler,
        )
    )

    mount_spa(app, static_dir)
    return app


app = create_app()
