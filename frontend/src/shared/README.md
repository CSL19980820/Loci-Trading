# shared

跨页面组件、API 客户端、路由、stores、lib。

- `api/palace.ts` — 候选 / 预案 / 复盘 / 会话 HTTP（持仓与成交端点已于 2026-08 下线，勿再加回）
- `api/quant.ts` — 量化 barrel（实现见 `quant_client` / `quant_market` / `quant_strategy` / `quant_ops` / `quant_review`）；调用方仍 `from '@/shared/api/quant'`
