# ADR-008 · 战法纸面量化舱（次日预案 + AI 执行环）

- Status: Accepted
- Date: 2026-08-06
- Updated: 2026-08-06（情景预案 v1）

## Context

需要把「选股 → 次日预案 → 盘中调仓 → 跟随推送 → 日终归因」落成可调度的纸面量化环，同时守住本仓红线：`palace.db` 是真实账本权威，AI 不得编造行情数字，Live 行情不得污染回测/研究权威。

## Decision

1. **每战法一纸面舱**（`ops.db`：`paper_cabins` / `paper_positions` / `paper_fills` / `paper_rejects`）。仓位只谈「层」（最小步进 0.5），**不计佣金**；标记价来自 Live TTL 快照。
2. **执行引擎一等公民动作**：`open/add/reduce/close/take_profit/stop_cut/trim_high/buy_dip/hold`。非法层数/无仓止盈等高抛低吸门槛失败 → 拒单落库，不改仓。
3. **次日情景预案**（`nextday_plans`，语义 `scenario_v1`）：每只票必须写清**想法**，不是选股池直开仓。
   - 相对昨收划分 **高开 / 平开 / 低开**（默认平开带 ±0.5%）
   - 各情景：`buy`（本情景是否接）、`entry_pct_min/max`（价位带）、`layers`（仓位）；语义是**动态调仓/择位**，不是对错判决
   - 默认（`entry_mode=scenario`）：平开按计划接；过高可暂缓/浅接/等回踩；低开低吸带内接
   - 战法 `entry_timing=next_open`（如潜龙）自动 `entry_mode=next_open`：基线开盘接，过高可减层或等回踩舒适带，一字/近涨停放弃
   - **09:15–09:25 竞价窗**：持续对照实时价输出 `follow` / `revise` / `abandon` / `wait`；默认**只纠偏不落开仓成交**（`auction_allow_open=false`）
   - 开盘后仅当 stance=`follow`；scenario 模式还要求价格落在买点区间，next_open 不强制窄区间
4. **战法风格记忆 + 知识图**（与全局 `ai_memories` / 代码 codegraph 隔离，但**用法对齐**）：
   - 文档层：`paper_style_profiles` + `paper_lessons`（该怎么买 / 该看哪些 / 教训）
   - 图层：`paper_mem_nodes` / `paper_mem_edges`（strategy/rule/watch/lesson/scenario + has_rule/watches/learned_from/absorbed_into/about…）
   - `explore_memory(slug, query)` ≈ codegraph_explore：种子检索 + 一跳扩边，返回子图与摘要
   - 日终 **评头论足** 必须带 **近 5 个交易日回看包**：买过 / 错过（入池日早于复盘日）/ 今日新入池 / 卖过 + 完整日 K；池内量能与板块环境；可选资金流（失败不编造）。**禁止**把今日才选的票的入池前涨幅算成踏空；miss 收益自 `first_attention` 起算。
   - 从回看提炼 miss/卖飞/逆势买等教训 → **吸入**风格与记忆图（`new_pick` 不写 miss 教训）
5. **盘中环** Job `strategy_monitor`：TTL → 情景/竞价门闩 →（可选 LLM，仍须过门闩且遵守风格/图）→ `PaperExecEngine` → 可选 `follow_wecom`（仅推送，不写 palace）。
     - `PUT .../paper-cabins/{slug}/config` 且 `enabled=true` 时幂等挂上 `strategy_monitor` + `paper_eod`（`ensure_paper_monitor_jobs`）；关舱停用对应 Job。
     - 对外企微监测以龙回头为主推送；龙头地图为上游角色源、涨停动量为并行接力线，二者新建监测默认 `push_wecom=false`。
     - 龙回头空仓日仍扫地图角色（一段式带龙头/走弱），`picks` 为空不种子开仓。
     - `dragon-return` 额外先过龙空龙市场闸门：`short_term_emotion` + `limit_up_ladder` +
     `theme_intraday_capital`；闸门为“空/观察”时只允许已有仓位退出，不允许新增纸面仓位。
     - `skill_watch` 的龙回头结果带 `market_gate`、`picks` 和 `validation=unverified`；
     开启 `paper_quant.enabled` 后由 registry 自动写入次日情景预案，不自动下券商单。
6. **Live TTL**（`market.application.live_cache`）为进程内 ephemeral 缓存；**不写** `market.db` 权威表，不进 research run card。
7. **通知**：`notify_dispatch` 统一安静时段 + 企微 + Bark；价格提醒走 `alert_rules` / `alert_scan`。

## Consequences

- 纸面盈亏与真实账本并行，UI 必须明确「纸面」语义，禁止一键同步成 palace 成交。
- **禁止**「预案有票就 open」的盲目兜底；无 LLM 时走 `scenario_gated_open_orders`。
- 风格记忆是舱级可编辑文档，不是第二账本；教训吸入有字符上限，防 prompt 膨胀。
- 记忆图是 **ops.db 内的领域图**，不是把交易记忆塞进 `.codegraph/` AST 索引；查询接口刻意对齐 explore 心智。
- 节假日日历简化（跳过周末），精确交易日历可后补。

## Alternatives considered

- TradingAgents 多 Agent 投票：否决（权威外溢、难审计）。
- 自动写真仓成交：否决（账本红线）。
- TTL 写入 market 权威库：否决（污染可重建缓存与研究证据）。
- 选股结果直接当次日市价单：否决（与「高/低/平开想法 + 竞价纠偏」不符）。
- 复用全局助手 `ai_memories`：否决（战法风格应随舱隔离，避免污染聊天人格）。
- 直接复用 codegraph AST 索引存交易记忆：否决（codegraph 面向源码符号；交易记忆是事件/规则图，落 ops.db）。
