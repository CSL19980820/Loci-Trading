# 行情（market）

## 职责
标的、日 K、同步编排、数据线路适配器、股票池。

## 边界
只写 market.db；禁止写 palace.db。

## 关键入口
`MarketStore` / `sync_quotes`；HTTP：`/api/market/*` `/api/universe/*`（现由 app.legacy.quant_router 挂载）；CLI：`python -m cli.market`

## 如何扩展
新行情源：在 infrastructure/adapters 实现并注册到 lane。

## 存储层拆分（infrastructure）
对外符号不变：`from src.market import MarketStore, normalize_code, …` 与
`from src.market.infrastructure.store import MarketStore, normalize_code, …`。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_codes.py` | `MarketError` / `normalize_code` / `guess_market` / `to_sina_symbol` |
| `store_schema.py` | DDL、字段常量、`DEFAULT_DB` |
| `store_rw.py` | 写入与基础读取 mixin |
| `store_panel.py` | 全市场面板与 `_consolidate` |
| `duckdb_panel.py` | 可选 DuckDB 只读旁路（`LOCI_MARKET_DUCKDB=1`；失败回退 pandas） |
| `store.py` | `MarketStore` 组合 + 连接生命周期 + re-export |

## 给 Agent 的用法
- 仓：`from src.market import MarketStore, sync_quotes, apply_today_spot`
- 健康门禁：`guard_market_health` / `check_market_health`
- 线路：`fetch_daily_routed` / `fetch_live_quotes_routed` / `fetch_instruments_routed` / `enabled_adapter_ids` / `ALL_LANES`
- 新源：在 `infrastructure/adapters` 实现并注册 lane
- HTTP 前缀见 `api/README.md`（现多由 `app.legacy.quant_router` 挂载）
- 禁忌：写 palace.db；在 adapter 外写死厂商 if-else；跨上下文深掏 `infrastructure`

## README 维护
改同步语义、适配器契约、公开导出或 store 拆分边界时必须更新本文。

## 相关测试
`tests/market/`（含 `test_duckdb_panel.py`：未装 duckdb 则 skip；装了则同夹具经典 vs `LOCI_MARKET_DUCKDB=1` 行数/关键价对齐）
