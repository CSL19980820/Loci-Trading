# 组合根（app）

## 职责
装配 FastAPI：鉴权、Session、健康检查、静态 SPA、挂载各上下文 HTTP。不含领域计算。

## 边界
- 账本路由：`src.ledger.api.router.build_ledger_router`（组合根注入 `write_dependency` + `get_store`）
- 量化路由由 `src.app.legacy.quant_router.build_quant_router` **薄聚合** include 各上下文 `api/`（URL 不变）；请求模型在各上下文自己的 `api/schemas.py`（**不再**放组合根，`legacy.quant_common` 已清空）；依赖打开器与「缺依赖 503」映射在 `src.shared.api_deps`；前缀归属见各上下文 `api/README.md`
- Screen Skill 已**整块搬出组合根**（2026-08）：编排在 `src.strategy.application.screen_skills`，HTTP 契约在 `src.strategy.api.screen_skills_router`，包读写经 `src.ops` 包根。组合根只负责 include 路由，不再持有任何业务编排
- 可观测性：HTTP middleware 经 `src.shared.observability` 建 request span 与相关性字段；默认关闭。`LOCI_OBSERVABILITY=1` 才写本地 JSON/metrics；`LOCI_OBSERVABILITY_OTEL=1` 才桥接宿主 OTel（不配置 exporter）；`LOCI_OBSERVABILITY_EXPOSE=1` 才回 `X-Loci-Trace-ID`（见 [ADR-010](../../docs/adr/ADR-010-2026-08-baseline-observability-virtual-table.md)）

## 文件清单

`create_app()` 曾经一个函数就 500 多行。2026-08 按「同一类失败/同一类关注点」切开，**装配顺序仍然全部由 `main.py` 决定**——下面这些模块只提供步骤，不决定何时执行：

| 文件 | 职责 | 边界 |
|---|---|---|
| `main.py` | 组合根本体：解析配置、建 `FastAPI`、按序装中间件、`include_router`、`lifespan` 调度器 | 唯一决定**顺序**的地方 |
| `startup_migrations.py` | `run_startup_self_heal()`：LLM/MCP 旧加密凭据迁移、刷 Screen Skill 战法目录、清 WebView 缓存 | 每步 `try/except` + `logger.exception`，**失败一律不拖垮进程**。要「失败就拒绝启动」的校验请写进 `main.py` 正文 |
| `security_middleware.py` | `install_secure_response_headers()` + `_split_hosts` / `_env_flag` / `_is_loopback_client` | 都在回答「这次部署/这个请求处在什么安全语境里」 |
| `auth_guards.py` | `build_auth_guards()` → `has_browser_session` / `has_agent_token` / `require_write_access`；无状态的 `current_context` | **必须保持工厂返回闭包**：它们捕获每个 app 实例自己的 `require_write_auth` 与 `write_token`，改成全局变量会让同进程里两个 app 互相覆盖对方的令牌 |
| `spa_mount.py` | `install_spa_cache_control()` + `mount_spa()` | `mount_spa` 是 catch-all，**必须在所有 API 路由 include 完之后**调用 |
| `logging_setup.py` / `login_throttle.py` / `write_token_policy.py` / `tenant_middleware.py` | 原有拆分，未动 | |

**搬走的名字一律在 `main.py` re-export**（含 `_split_hosts` / `_env_flag` / `_is_loopback_client` 这类下划线名与 `LoginThrottle`）。`tests/app/**` 有大量用例直接 `from src.app.main import ...` 并 monkeypatch `src.app.main` 上的名字；re-export 掉一个，monkeypatch 就会静默打到空处——测试照样绿，线上不生效。


## 对外入口
- `src.app.main:create_app` / `app`
- `python -m cli.serve` 或 `uvicorn src.app.main:app`

## 如何扩展
新 HTTP：优先写入对应上下文的 `api/`，再在组合根 `include_router`；过渡期可先挂进 `legacy.quant_router`。


## 给 Agent 的用法
- 应用工厂：`from src.app.main import create_app, app`
- 账本路由：`src.ledger.api.build_ledger_router`
- 量化聚合路由：`src.app.legacy.quant_router.build_quant_router`
- Screen Skill：契约与编排已搬到 `src.strategy`（见上）。对外契约仍包含 runtime/dialect、执行源、manifest.logic/data/references 与 revisions；试跑 `run_result` 分开返回正式 `picks` 与弱市 `watch_picks`，两者分别截断并回显总数
- 工坊能力目录：`GET /api/screen-skills/catalog` 返回两种 runtime、方言、26 个公式函数、日线字段与片段；预览成功会返回 compiler/manifest 生成的 `explanation`
- `POST /api/screen-skills/generate` 的 description 模式要求逐条 citation，并以请求携带的 references 覆盖模型输出；TDX/THS 仅作为导入方言，不是完整厂商公式产品模式
- 新路由优先下沉到各上下文 `api/`，再在此挂载
- SPA：`index.html`/路由壳 `Cache-Control: no-store`；`/assets/*` 长期 `immutable`；打包启动时清 WebView HTTP 缓存
- 生产环境的 API 默认要求浏览器会话或 Agent Bearer；仅未完成首启时，`/api/ops/data-location` 的直接本机回环请求可免登录，远端或经代理转发的访问仍须认证
- **本地桌面默认可写**（非 `production` 且未设 `PALACE_REQUIRE_WRITE_AUTH=1`）：写鉴权对浏览器会话恒真，便于单机开发
- **Agent Bearer（`PALACE_WRITE_TOKEN`）**：长期静态密钥，无内置 TTL（`write_token_policy.py`）。生产若配置则长度须 ≥32，否则拒绝启动；优先浏览器会话，Agent 仅无头自动化。轮换：换新随机串 → 更新环境变量 → 设/刷新 `PALACE_WRITE_TOKEN_ISSUED_AT=YYYY-MM-DD` → 重启；超 90 天启动告警。本地桌面不配也可写。**不要**用收紧 AI ExecutionGrant 代替轮换
- Screen Skill slug 冲突检测用 `strategy.is_builtin_registered`，勿 import `_REGISTRY`

## README 维护
改鉴权、挂载方式、静态资源策略时必须更新本文。

## 相关测试
`tests/app/`、`tests/ledger/`

