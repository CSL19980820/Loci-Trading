# 组合根（app）

## 职责
装配 FastAPI：鉴权、Session、健康检查、静态 SPA、挂载各上下文 HTTP。不含领域计算。

## 边界
- 账本路由：`src.ledger.api.router.build_ledger_router`（组合根注入 `write_dependency` + `get_store`）
- 量化路由由 `src.app.legacy.quant_router.build_quant_router` **薄聚合** include 各上下文 `api/`（URL 不变）；共享模型见 `legacy.quant_common`；前缀归属见各上下文 `api/README.md`

## 对外入口
- `src.app.main:create_app` / `app`
- `python -m cli.serve` 或 `uvicorn src.app.main:app`

## 如何扩展
新 HTTP：优先写入对应上下文的 `api/`，再在组合根 `include_router`；过渡期可先挂进 `legacy.quant_router`。


## 给 Agent 的用法
- 应用工厂：`from src.app.main import create_app, app`
- 账本路由：`src.ledger.api.build_ledger_router`
- 量化聚合路由：`src.app.legacy.quant_router.build_quant_router`
- 新路由优先下沉到各上下文 `api/`，再在此挂载

## README 维护
改鉴权、挂载方式、静态资源策略时必须更新本文。

## 相关测试
`tests/app/`、`tests/ledger/`

