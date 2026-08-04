# 账本（ledger）

## 账户口径（券商同款）

- **现金**：最近资产快照的现金锚点，加上之后的卖出额、出入金，减去买入额（`OPENING` 导入不碰现金）。
- **总资产（盯市）**：`现金 + 持仓市值`；无市值时后端用 `现金 + 成本占用` 作账面估。
- **快照**：可只记总资产；未给现金时自动填 `现金 = 总资产 − 当前成本占用`。
- 买入时若已有现金锚点且余额不足，拒绝成交。
- **本月参考盈亏**（看板）：`month_realized_pnl` + `month_pnl_curve`（月初至 as_of 逐日累计已实现，不含潜龙基线）；比例 = 本月已实现 / 账面总资产。
- **当日卖出**（看板 `today_sells`）：`occurred_on = as_of` 的 SELL 明细，含卖出前成本与盈亏%。

## 职责
成交、候选、预案、复盘记录与持仓投影的单一事实源。对外保留 PalaceStore 类名。

## 边界
写 palace.db。行情/复盘可读本上下文，但不可反向写入账本事实。

## 关键入口
`PalaceStore`（`infrastructure/store.py` 门面）；HTTP：`src.ledger.api.build_ledger_router`（组合根挂载）；CLI：`python -m cli.ledger`

### infrastructure 拆分（Mixin 组合）

| 文件 | 职责 |
|---|---|
| `store.py` | `PalaceStore` 门面：连接、事务、组合 mixin；re-export 公开符号 |
| `store_types.py` | `PalaceError` / `Position` / `normalize_*` / 裁决与战法归一（`精选|落选|观察`、`潜龙`） |
| `schema.py` | DDL、迁移、meta、股票登记；连接时幂等把「隔日写入的 `api:screen*`」改标为 `api:screen_backfill`（不碰 manual / job:screen） |
| `trades.py` | 成交、账户事件、日盈亏、持仓/交割投影 |
| `candidates.py` | 候选写入/删除/列表；`delete_candidates_for_pool` 按日+池清空（选股重选替换）；裁决仅 `精选/落选/观察`；保留展示用 `rule_version`，并显式记录 `strategy_slug`、`strategy_revision`、有效参数；列表战法筛选兼容 slug 与中文名；默认排除 `%backfill%` / `%:history`（`include_backfill` / `live_only` 可放开）；`live_only` 另要求写入日=选股日 |
| `plans_reviews.py` | 预案、复盘、时间线（未入账代码时间线返回空列表，不抛「账本中不存在」） |
| `queries.py` | 看板、评分卡、胜率、analytics |
| `import_qianlong.py` | 潜龙 state 导入 |
| `ai_judgments.py` | AI 判定记录 |
| `tracking.py` | 持仓周期跟踪 |

外部使用包根：`from src.ledger import PalaceStore, PalaceError, normalize_decision`。

## 如何扩展
新账本实体：改对应 mixin 的 DDL（`schema.py`）+ 写入方法，并补 tests/ledger。单文件 ≤600 行。

## 给 Agent 的用法
- 读写账本：`from src.ledger import PalaceStore, PalaceError`
- 跨上下文复用候选裁决归一：`from src.ledger import normalize_decision`；不导入 `ledger.infrastructure`
- 路径：`from src.shared.paths import palace_db`
- 候选裁决只写 **精选 / 落选 / 观察**（禁止「值得做」「持仓」等自造档）；潜龙战法 `rule_version` 写 **潜龙**
- 典型任务：记成交、候选、预案；不要在此算资金曲线（去 review）
- 禁忌：不要让 market/ai 写入 palace.db

## README 维护
改表结构、写入语义、公开导出符号或 infrastructure 文件布局时必须更新本文。

## 相关测试
`tests/ledger/`、`tests/app/test_palace_api.py`
