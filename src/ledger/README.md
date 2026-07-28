# 账本（ledger）

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
| `store_types.py` | `PalaceError` / `Position` / `normalize_*` / `_dumps` `_loads` |
| `schema.py` | DDL、迁移、meta、股票登记 |
| `trades.py` | 成交、账户事件、日盈亏、持仓/交割投影 |
| `candidates.py` | 候选写入/删除/列表、精选口径、池日汇总 |
| `plans_reviews.py` | 预案、复盘、时间线 |
| `queries.py` | 看板、评分卡、胜率、analytics |
| `import_qianlong.py` | 潜龙 state 导入 |
| `ai_judgments.py` | AI 判定记录 |
| `tracking.py` | 持仓周期跟踪 |

外部仍：`from src.ledger import PalaceStore, PalaceError`（或 `from src.ledger.infrastructure.store import ...`）。

## 如何扩展
新账本实体：改对应 mixin 的 DDL（`schema.py`）+ 写入方法，并补 tests/ledger。单文件 ≤600 行。

## 给 Agent 的用法
- 读写账本：`from src.ledger import PalaceStore, PalaceError`
- 路径：`from src.shared.paths import palace_db`
- 典型任务：记成交、候选、预案；不要在此算资金曲线（去 review）
- 禁忌：不要让 market/ai 写入 palace.db

## README 维护
改表结构、写入语义、公开导出符号或 infrastructure 文件布局时必须更新本文。

## 相关测试
`tests/ledger/`、`tests/app/test_palace_api.py`
