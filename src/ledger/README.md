# 账本（ledger）

## 范围（2026-08 持仓下线后）

本上下文只保留**候选池 / 股池 / 预案 / 复盘 / AI 判定**。
持仓、成交、账户资金、券商当日盈亏、潜龙 state 导入、持仓周期跟踪**已整体下线**，
对应的七张表由 schema 迁移 `DROP TABLE IF EXISTS` 掉：

| 已删表 | 原用途 |
|---|---|
| `position_events` | 成交事件（买/卖/开仓导入） |
| `holdings` | 当前持仓投影 |
| `account_events` | 出入金 / 已实现盈亏导入 |
| `account_snapshots` | 账户总资产快照 |
| `daily_pnl_ledger` | 券商市值法当日盈亏 |
| `position_tracking` | 候选 T+N 跟踪（唯一读取方 review drift 已删，纯写入孤儿） |
| `ledger_write_receipts` | 成交/出入金幂等回执 |

同时删掉的模块：`trades.py`、`account_events.py`、`tracking.py`、`equity_basis.py`、
`import_qianlong.py`、`write_receipts.py`。

下线的 HTTP 端点：`/api/dashboard` `/api/positions` `/api/trades`（GET/POST）
`/api/trades/export.csv` `/api/import/qianlong/*` `/api/analytics` `/api/scorecard`
`/api/snapshots` `/api/cashflows` `/api/daily-pnl`（GET/POST）。
`/api/timeline/{code}` 保留，但只剩候选裁决 + 预案（+ 关联复盘）两类事件。

**别把它们加回来**：金额精度、成交幂等、余票成本可为负这些老约束连同代码一起走了，
重新引入等于从零再走一遍那些坑。

## schema 版本号（踩过的坑）

`store_types.SCHEMA_VERSION` 现为 **10**。`init_schema` 在 `meta.schema_version` 与它一致时
**直接返回、一条 DDL 都不跑**——所以**加 DDL 和删 DDL 都必须同步 bump 这个数**，否则已有库
永远走不到新的建表/迁移语句，只有全新空库看起来是对的。迁移入口是 `schema._run_migrations`，
下线表的清理在 `schema._drop_retired_tables`（`RETIRED_TABLES` 常量，幂等）。

参考同款机制：`src/market/infrastructure/store_schema.py` 的 `SCHEMA_VERSION`。

## review 只读缓存指纹

`PalaceStore.review_read_fingerprint() -> str`（`queries.py`，原在已删的 `tracking.py`）。
`src/review` 的结果缓存拿它当失效键，口径只看 `candidate_reviews` / `plans` / `reviews`。

`candidate_reviews` 那条**必须是 GROUP_CONCAT 逐行摘要**，不能简化成 `COUNT(*)`：
`record_candidate` 命中同日同池同标的时走原地 UPDATE，不刷新 `created_at`、不改 rowid、
不改条数，「精选→落选」这种**等长改判**只有逐行摘要看得出来，否则缓存喂陈数据。
钉住这条的测试：`tests/ledger/test_candidate_pool_store.py::CandidatePoolStoreTests::test_review_read_fingerprint_changes_on_any_write`。

也**不要**换成 `PRAGMA data_version`：跨连接读是常数，要它有意义得常驻探针连接，
而常驻连接会占住 palace.db 句柄，Windows 上临时库 rmtree 直接 PermissionError。

## 职责
候选裁决、预案、复盘记录与 AI 判定的单一事实源。对外保留 PalaceStore 类名。

## 边界
写 palace.db。行情/复盘可读本上下文，但不可反向写入账本事实。

## 关键入口
`PalaceStore`（`infrastructure/store.py` 门面）；HTTP：`src.ledger.api.build_ledger_router`（组合根挂载）；CLI：`python -m cli.ledger`

### infrastructure 拆分（Mixin 组合）

| 文件 | 职责 |
|---|---|
| `store.py` | `PalaceStore` 门面：连接、事务、组合 mixin；re-export 公开符号 |
| `store_types.py` | `SCHEMA_VERSION` / `PalaceError` / `normalize_*` / 裁决与战法归一（`精选\|落选\|观察`、`潜龙`） |
| `schema.py` | DDL、迁移、下线表 DROP、meta、股票登记；连接时幂等把「隔日写入的 `api:screen*`」改标为 `api:screen_backfill`（不碰 manual / job:screen） |
| `candidates.py` / `candidates_query.py` / `candidates_sql.py` | 候选写入/删除 + 查询汇总 + 可见性 SQL；`candidate_outcome_rows` 供 review T+N；`delete_candidates_for_pool` 按日+池清空（选股重选替换）；裁决仅 `精选/落选/观察`；保留展示用 `rule_version`，并显式记录 `strategy_slug`、`strategy_revision`、有效参数；列表战法筛选兼容 slug 与中文名；默认排除 `%backfill%` / `%:history`（`include_backfill` / `live_only` 可放开）；`live_only` 另要求写入日=选股日 |
| `plans_reviews.py` | 预案、复盘、时间线（未入账代码时间线返回空列表，不抛「账本中不存在」）；`review_returns_for_tag` / `review_strategy_tags_with_returns` 供 review decay |
| `queries.py` | 战法胜率（`winrate_trend` / `strategy_winrates`，只读 `reviews`）+ `review_read_fingerprint` |
| `ai_judgments.py` | AI 判定记录。`created_at` 与全库统一走 `store_types._now()`（本地时区 + 偏移 + 微秒 ISO8601）；旧行是 `datetime('now')` 留下的 UTC `'YYYY-MM-DD HH:MM:SS'`，**不重写**，读取侧 `ai_judgment_payload` 用 `julianday()` 把两种格式折算到同一条时间轴再排序（脏值沉底、不抛错） |

外部使用包根：`from src.ledger import PalaceStore, PalaceError, normalize_decision`。

## 如何扩展
新账本实体：改对应 mixin 的 DDL（`schema.py`）**并 bump `SCHEMA_VERSION`** + 写入方法，并补 tests/ledger。单文件 ≤600 行。

## 给 Agent 的用法
- 读写账本：`from src.ledger import PalaceStore, PalaceError`
- 跨上下文复用候选裁决归一：`from src.ledger import normalize_decision`；不导入 `ledger.infrastructure`
- 路径：`from src.shared.paths import palace_db`
- 候选裁决只写 **精选 / 落选 / 观察**（禁止「值得做」「持仓」等自造档）；潜龙战法 `rule_version` 写 **潜龙**
- 典型任务：记候选、预案、复盘；**不要**在此记成交/持仓/现金（已下线），也不要在此算资金曲线
- 禁忌：不要让 market/ai 写入 palace.db

## README 维护
改表结构、写入语义、公开导出符号或 infrastructure 文件布局时必须更新本文。

## 相关测试
`tests/ledger/`、`tests/app/test_palace_api.py`
