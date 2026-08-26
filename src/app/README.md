# 组合根（app）

## 职责
装配 FastAPI：鉴权、Session、健康检查、静态 SPA、挂载各上下文 HTTP。不含领域计算。

## 边界
- 账本路由：`src.ledger.api.router.build_ledger_router`（组合根注入 `write_dependency` + `get_store`）
- 量化路由由 `src.app.legacy.quant_router.build_quant_router` **薄聚合** include 各上下文 `api/`（URL 不变）；请求模型在各上下文自己的 `api/schemas.py`（**不再**放组合根，`legacy.quant_common` 已清空）；依赖打开器与「缺依赖 503」映射在 `src.shared.api_deps`；前缀归属见各上下文 `api/README.md`
- Screen Skill 已**整块搬出组合根**（2026-08）：编排在 `src.strategy.application.screen_skills`，HTTP 契约在 `src.strategy.api.screen_skills_router`，包读写经 `src.ops` 包根。组合根只负责 include 路由，不再持有任何业务编排
- 可观测性：HTTP middleware 经 `src.shared.observability` 建 request span 与相关性字段；默认关闭。`LOCI_OBSERVABILITY=1` 才写本地 JSON/metrics；`LOCI_OBSERVABILITY_OTEL=1` 才桥接宿主 OTel（不配置 exporter）；`LOCI_OBSERVABILITY_EXPOSE=1` 才回 `X-Loci-Trace-ID`（见 [ADR-010](../../docs/adr/ADR-010-2026-08-baseline-observability-virtual-table.md)）

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

