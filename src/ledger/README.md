# 账本（ledger）

## 守护模拟仓（2026-09）

`GuardianStore` 提供每租户独立的20万元现金模拟账户，股数为整数、金额按分记账。
`guardian_account.py` 处理费用、T+1、含费平均成本和盈亏；轮次、成交、现金与持仓同事务提交，按流水复核每笔资金与股数变化。
旧层数账户归档到 `guardian_legacy_accounts`，不伪造成现金成交。新流水存 `guardian_trades`，可分页查询及按股票汇总，清仓后保留。
它是天才交易员独立账户，不恢复已下线的券商导入与通用实盘接口。规则和费率见[守护规则](../../docs/guardian.md)，轮次、风险合同和通知边界见[执行契约](../../docs/guardian-execution.md)。

`GuardianStore.claim/finish`按五分钟槽位和`owner_run_id`防重，成功与失败收口均拒绝错误owner或已终态轮次。落账前回调再次核验取消、配置、时钟、报价和意图有效期；账户、fills、轮次及待发通知原子提交，失败不留下半套现金/股数变更。
`risk_plans`在ops的状态副本内按动作后持仓安装，再随账户提交；null保留、[]撤回，绑定持仓数量及开仓批次，实际成交才消费。ledger不解释自然语言止损计划，也不以风险触发事件代替成交流水。
`guardian_notices.py`保存逐轮待发通知、目标通道ID快照、每目标回执和租约；领取按`attempts, slot`升序，先尝试次数少的、同次数再按轮次，避免旧失败消息长期占满批次而阻塞新告警。确认成功的目标不再重试，通知失败不回滚成交或重跑模型。外部服务接受消息到本地写回执之间仍可能中断，不承诺外部exactly-once。

## 范围（2026-08 持仓下线后）

通用账本保留**候选池 / 股池 / 预案 / 复盘 / AI 判定**；2026-09新增的Guardian模拟账户使用独立表和入口。
原通用持仓、成交、账户资金、券商当日盈亏、潜龙 state 导入、持仓周期跟踪**已整体下线**，
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
- 通用入口用于候选、预案和复盘；模拟成交仅走`GuardianStore`及其专用会计契约，不恢复旧持仓/现金接口，不由AI生成资金曲线
- 禁忌：不要让 market/ai 写入 palace.db

## README 维护
改表结构、写入语义、公开导出符号或 infrastructure 文件布局时必须更新本文。

## 相关测试

`guardian_quantity_error`为计划与成交共用的股数申报校验：普通A股不得从整手拆出零股，已有零股可一次卖出；报告在发布前核验。覆盖`tests/ops/test_guardian_plan_quantity.py`。
`tests/ledger/`、`tests/app/test_palace_api.py`

天才交易员支持止盈/止损动作、持股计划与持久自主观察池；策略外观察不产生交易，现金与 T+1 规则不变。详见 docs/guardian.md。

交易员常态和收盘最多4只、盘中临时最多8只，不要求逐只绑定换仓。临时超额时由模型通过close_keep_codes选择当日收盘留仓并持久化；14:50起按最后有效名单退出其他持仓，14:55续跑，真实报价失败保留已成交结果并标明收敛异常。T+1锁定股票最多4只且必须保留，新增/加仓不能破坏收盘可执行性。成功和异常通知优先展示含费持仓成本。测试 tests/ledger/test_guardian_position_limit.py、tests/ops/test_guardian_close.py。

交易员报告：guardian_reports保存带租约的盘前/日/周报告和通知回执；guardian_history按成交流水重建日期账户。成功收盘估值仅更新匹配账户的价格投影，不写交易。报告与流水按租户隔离。

交易员咨询使用guardian_consultations与guardian_consult_turns两张租户表，保留每轮用户实际背景和多轮消息快照，独立于模拟资金、持仓、成交。请求幂等、同话题串行，回答不会改变账户。

### 交易员决策输入留存

`guardian_cycles.result_json.decision_context` 在研判前记录输入账户、候选及当轮规则；`GuardianStore.finish` 保留该字段，包括模型失败时，不用后来的配置改写历史。无需新增数据表。`guardian_available_quantity` 公开复用现金账户的可卖股数算法，供历史时点查询使用；查询不按成本伪造历史行情估值。

### 交易员通知及数据根（2026-09-15）

GuardianStore公开db_path供同租户研究连接复用实际数据根。新price reference可选字段不改变旧风险合同ID；合同消费仍由ops核验实际价格和成交匹配。guardian_notices保存完整正文，receipt_json内增加逐目标parts、body_sha256和sent_parts，结构兼容已有回执，无需重写历史成交。有效进度续展自有300秒租约，失效owner不能续租；notice_backlog返回pending/sending/total/oldest_slot，不生成第二套财务事实。
