# 组合根（app）

## 职责
装配 FastAPI：鉴权、Session、健康检查、静态 SPA、挂载各上下文 HTTP。不含领域计算。

## 边界
- 账本路由：`src.ledger.api.router.build_ledger_router`（组合根注入 `write_dependency` + `get_store`）
- 量化路由由 `src.app.legacy.quant_router.build_quant_router` **薄聚合** include 各上下文 `api/`（URL 不变）；共享模型见 `legacy.quant_common`；前缀归属见各上下文 `api/README.md`
- `src.app.screen_skills*` 只做 Screen Skill HTTP 契约与编排：读取/写入交给 `src.ops.application.screen`，formula/Python runtime 分派与选股交给 `src.strategy`；逻辑说明、数据选择和资料引用是同一严格 DTO 的组成部分

## 对外入口
- `src.app.main:create_app` / `app`
- `python -m cli.serve` 或 `uvicorn src.app.main:app`

## 如何扩展
新 HTTP：优先写入对应上下文的 `api/`，再在组合根 `include_router`；过渡期可先挂进 `legacy.quant_router`。


## 给 Agent 的用法
- 应用工厂：`from src.app.main import create_app, app`
- 账本路由：`src.ledger.api.build_ledger_router`
- 量化聚合路由：`src.app.legacy.quant_router.build_quant_router`
- Screen Skill：`src.app.screen_skills_api` + `src.app.screen_skills`（对外契约包含 runtime/dialect、执行源、manifest.logic/data/references 与 revisions）
- 工坊能力目录：`GET /api/screen-skills/catalog` 返回两种 runtime、方言、26 个公式函数、日线字段与片段；预览成功会返回 compiler/manifest 生成的 `explanation`
- `POST /api/screen-skills/generate` 的 description 模式要求逐条 citation，并以请求携带的 references 覆盖模型输出；TDX/THS 仅作为导入方言，不是完整厂商公式产品模式
- 新路由优先下沉到各上下文 `api/`，再在此挂载
- SPA：`index.html`/路由壳 `Cache-Control: no-store`；`/assets/*` 长期 `immutable`；打包启动时清 WebView HTTP 缓存
- 生产环境的 API 默认要求浏览器会话或 Agent Bearer；仅未完成首启时，`/api/ops/data-location` 的直接本机回环请求可免登录，远端或经代理转发的访问仍须认证

## README 维护
改鉴权、挂载方式、静态资源策略时必须更新本文。

## 相关测试
`tests/app/`、`tests/ledger/`

