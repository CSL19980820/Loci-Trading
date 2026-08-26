# ADR-009：盘口情报 provider lanes 与可选悟道

- 状态：Accepted（Step 1 + Step 2）
- 日期：2026-08-08

## 背景

龙王战法的日 K 属于 market 的 OHLCV 数据，不应因为悟道 MCP 未配置就
失效，也不能让 AI 或情报 provider 成为日 K 真相。另一方面，情绪、涨停、
题材和竞价等盘口情报需要统一的数据源聚集出口，避免各战法各自调用和各自
解释同一份信息。

## 决策

1. 龙头地图日 K 先读注入的 `MarketStore`/`market_hot.db`，单票缺失时通过
   `src.market.fetch_daily_routed`（排除 `wudao` provider）取不复权日 K；不再
   在 `leader_map` 调 MCP `kline`。
2. market 增加六条 tape lane：
   `market_emotion`、`limit_up_pool`、`broken_limit_up`、
   `theme_board`、`theme_members`、`auction_snapshot`。
3. tape 使用冻结 slots dataclass 作为请求、结果和 provenance 契约；一份
   结果只有一个 `provider_id`，所有尝试和警告显式留在 provenance，不做跨
   provider 猜测式合并。
4. router 采用 first-healthy-wins。provider 失败或缺数时短暂进程内冷却；
   全部不可用返回 `degraded` 结果，不把业务异常传给调用方。
5. provider 启停和手选回退复用既有 `lane_providers` / `lane_routes` 配置；
   `intel_snapshots` 是可删除重建的缓存，tape 不创建新 SQLite 表。
6. 悟道只是可选 provider，延迟从 `src.intel` 包根调用；缺悟道时 cleanly
   unavailable，不复制 token、配额或连接逻辑。

## 本轮范围

本轮只落地日 K 解耦与 tape DTO/provider/router/cache 骨架，并保留
`skill_watch/payload.py` 作为兼容解析入口。现有 `runner.py` 的悟道硬闸门、
`market_regime` 和 `dragon_return` 的盘口调用不变。

## 后续

Step 3+ 再把盘口情报采集、缓存消费和战法调用迁移到 tape router，补齐非悟道
provider 与 typed DTO 的完整字段归一；迁移期间不得把 `strength_norm` 等
provider 负责的归一化下沉到 router，也不得跨来源拼接结果。
