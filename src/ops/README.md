# 运维（ops）

## 职责
定时任务、技能包、通知、调度器、运维配置。

行情日终 `today_refresh` 的定稿阶段仅使用通达信，并绕过当日水位重新取数；通达信失败不会再落回退源并返回 `ok`。定稿失败数计入任务顶层 `failed`，由既有运行器记录失败；近窗重试与热库镜像仍沿用原流水线。
其中 `application/screen/` 负责 formula/Python Screen Skill 包的磁盘存储、历史归档、zip 路径校验与 revision 锁；不负责编译或执行选股。

## 边界
写 ops.db；技能文件在 data/skills。

选股任务在入口解析一次目标交易日，行情门禁、热库选择和策略计算均使用该日期；子租户也只读检查同一目标日。启动补跑将待补交易日传入本次 screen 配置，不修改持久化任务日期；根据执行回执分别记录成功、跳过和失败，失败不会再记成补跑完成。

### 固定时点筛选

普通 `screen` 任务可显式配置 `snapshot_time="14:50"`、`snapshot_grace_minutes=2`、`trading_days_only=true`、`catch_up=false`。`jobs/screen_schedule_guard.py` 在入口、选股前、选股返回后及开始入库前检查上海时区窗口及市场交易日历，只有 [14:50:00,14:52:00) 和明确交易日才允许开始持久化；日历缺失/过期、休市、错过窗口或执行迟到均记录 skipped。不承诺 SQLite 事务完成瞬间仍在窗口内。`catch_up=false` 禁止盘后拿最终日 K 补跑。未设置这些字段的旧任务不改变行为。

“一线定乾坤·首板次日”（`yixian-auction`）已退役。启动自愈会删除其 `screen:` 任务、
任务回执、技能包与版本历史、纸面舱和候选历史，并在安装/导入/活动目录及天才交易员
研究入口拒绝再次启用；模板源码仅作历史研究保留。
原 `impulse-pullback-tail-v1` 的普通及绑定选股任务均下线，历史回执保留。
`snapshot_schedule.checked_at` 是门禁时间，真实抓取起止见 `data_snapshot`。
测试：`tests/ops/test_screen_schedule_guard.py`、`tests/ops/test_retire_yixian_auction.py`。

Skill 清单解析在 `application/skill_manifest.py`；安装/解压/发现仍在 `application/skills.py`。
HTTP：`api/skills.py`（目录/安装/生成）+ `api/skill_runs_api.py`（对话 Run）+ `api/skill_jobs_api.py`（战法配置/定时绑定）。

## 企微推送
- 出站统一经 `notify_dispatch.dispatch_text`（安静时段 + 企微 + Bark）；`send_wecom_text` 仍是企微通道实现。
- **出站队列**：企微 / Bark 的 HTTP 都进进程内 FIFO 队列（`notify_send_queue`）。同一时刻只发一条；失败最多 3 次（间隔 1s），三次仍失败再处理下一条。选股计算仍可并行，避免 15:30 多路同时打 Webhook 超时。
- **长正文按字节分片**（`notify.split_text_for_wecom`）：企微 `text` 官方上限是 2048 **字节**（中文一字三字节 ≈ 680 字），而 `MAX_TEXT_CHARS=2000` 是**字数**闸门——纯中文正文折算 6000 字节，超出部分能不能发出去看服务端心情，且它不会告诉你哪里被吞了。需要发全文的场景（悟道简报）一律先切片：默认 1800 字节一片、优先在空行/换行/句末断开、片头带 `（i/n）`；超过 `max_chunks` 时尾部**明写「已截断」**。`_clip` 那条 2000 字的旧闸门保留给既有短正文，不要拿它当长文方案。
- 选股模板可在系统「推送」联配置（ops.db `wecom_screen_template`）：预设 default / compact / with_date / custom。
- 渲染：`format_screen_picks_text`（`notify_screen_template.py`）；占位符 `{title}` `{kind}` `{date}` `{name}` `{code}` `{pct}` `{n}`；技能另有 `{note}`（≤40 字，取 pick.note/thesis 等）。
- 技能推送行用 `skill_pick` / `skill_pick_no_pct`（有说明才套用；无说明回退量化行）。
- **模板键 = 请求 schema 键**：前端把整份模板原样 `PUT /api/ops/settings/wecom`，`QuantModel` 是 `extra="forbid"`，`WecomScreenTemplateModel` 少一个键就是 422「Extra inputs are not permitted」（2026-09-04 线上 `formal_empty` / `watch_*` 四键就是这么炸的）。给 `DEFAULT_TEMPLATE` 加键必须同批加进 schema，`tests/ops/test_notify_and_sync.py::test_request_schema_accepts_every_template_key` 钉着两边相等。
- 量化任务可同时返回正式 `picks` 与弱市 `watch_picks`。**观察票是否随推送发出由模板配置 `show_watch_picks` 统一控制**（系统「推送」联的「低吸观察」开关，落库 ops.db `wecom_screen_template`，默认**关**）：关＝企微/Bark 不出现「👀 低吸观察」分区、正式为空时显示「暂无符合条件的标的」而非「正式精选 0 只」，对所有战法（潜龙/三源/杨氏）一并生效；开＝恢复分区与「正式精选 0 只」空态。观察票无论开关都照常以 `decision=观察` 写入 `candidate_reviews` 并在前端分区展示。
- `screen` / 绑定战法任务 `push_wecom=true` → 量化标记；`skill` 且结果含 picks → 技能标记。成功推送后写入 `wecom_push_marks`（`job_id:trade_date`）；同日再跑只记 `already_pushed`，不重复发企微。
- `screen` / `skill` 正文已自带中文标题，企微分发不再追加内部任务名；Bark 标题也先解析为战法中文名，用户可见通知不得出现 `screen:` / `skill:` 编码。
- `sync` 且 `push_wecom=true`：仅历史日 K 硬 `failed>0` 或整次任务失败时推企微。当日现价（含整批源忙/断网、单票停牌退市）一律软跳过：`spot_skip_reason` / `spot_gaps`，**永不**累加 `failed`，避免 5000+ 条刷屏；文案用人话。
- `notify` 模板 `alerts`：触价内容经 `context.market_hot()` 读热库，与 `GET /api/alerts/today` 同口径。
- `notify` 模板 `digest`（日终简报）：**只汇总当日候选池**（`candidates_payload` + `candidate_day_summary`）。实盘账本下线后不再有账户/持仓/当日盈亏段，`format_digest` 的入参也从 `dashboard` 换成 `candidates` + `summary`。
- 通知策略：`GET|PUT /api/ops/settings/notify`（`quiet_hours` / Bark）；纸面跟随走同一分发，**永不自动写 palace 成交**。

## 纸面量化（战法舱）
- 决策见 [ADR-008](../../docs/adr/ADR-008-paper-quant-cabin.md)。表：`paper_cabins` / `paper_positions` / `paper_fills` / `paper_rejects` / `nextday_plans` / `monitor_runs` / `alert_rules`（ops.db schema v5+）。
- **龙王战法大成体（纸面舱已退役）**：引擎链仍是 `龙空龙`闸门 → `龙头战法`角色 → `龙回头`可买，但 **不再挂 `dragon-return` 纸面舱、不再盘中 AI 盯盘**。统一池代码仍给其它舱和测试用。
- **统一监察池企微正文**：龙回头只渲染一份池清单，首行固定为“池内共X只，观察X只，持股X只，调整X只”。持股/买入/调仓/卖出/新进在前，普通观察随后，移出记录最后；当前池总数不含已移出票。静态行只显示名称、代码、分数，变化行才带动作图标、层数和简短原因；不再输出龙头角色图标、重复的观察池变更段或“龙头身份合格；龙空龙空仓；龙回头尚未回撤”等静态套话。持仓投影保留当日池评分并叠加账本层数，首页、企微与 `GET .../unified-pool` 同源。
- **次日情景预案**（`application/nextday_plan.py` 门面 + `session_clock.py` / `plan_build.py` / `scenario_gates.py`）：正文按「今日发现·可买/观察」分段；按高/平/低开做**动态调仓与择位**（层数、价位带、暂缓/浅接），不是对错判决；09:15–09:30 竞价/开盘前 `follow/revise/abandon/wait`（默认不落开仓，≥09:30 连续竞价才允许）。`merge_ai_orders_with_gates` 与 `scenario_gated_open_orders` 共用 `allow_open_fill`：观察票与非连续竞价一律拒 open/add/buy_dip。层数键统一 `planned_layers_max → planned_layers → layers`。日终滚动：`ref_close` 取日 K 收盘，**禁止**用持仓成本冒充昨收。正文里 `buy=false` 或 0 层的情景只打「暂缓」，**不再输出价格带与 `0层`**（`0.5%~0.5%·0层` 既是噪音又会被读成「还能接一点」）；上下限相同时收成单值。
- **交易日闸**（`jobs/paper_quant_support.resolve_trading_day_gate`）：`strategy_monitor` / `paper_eod` / **手工 `POST .../orders`** 入口优先读热库/传入的 `market` 日历，避免再 open 全量 `market.db` 与盘后同步抢锁；`strategy_monitor` 经 `market_calendar_store()` 与次日日共用一只连接。周末与法定假日整轮跳过（手工下单 **409**）。行情库日历只含已入库日，覆盖不到的日子（如今天）按交易所公告休市日程判定（`src.market.exchange_is_open`：内置年度公告 + 盘外刷新快照，该年度未公布才按工作日），旧版在此处按工作日粗判，中秋、国庆会被当成交易日；日历缺失时仍**买入 fail-closed**（纯买入请求 **409**；混合单剔除 open/add/buy_dip）。`paper_eod` 算次日必须传入已打开的 market。`monitor_runs.status`：LLM 失败等真实异常记 `failed`，非假绿 `success`。
- **持仓退出**（`application/rules_exit_orders.py`）：由 `position_exit_orders(..., ai_driven=)` 按路径分档，两条路径都不会让亏损仓裸奔。
  - **rules 路径**（无 model 或 `ai_mode=rules`）：全套退出，优先级 ① `stop_cut`（浮盈 ≤ 止损线：预案项 `stop_loss_pct` → 舱 config → 战法 `screen_stop_loss_pct`，默认 -6%）；② `take_profit`（≥ 止盈线，预案项优先于舱 config，未配则跳过）；③ `trim_high`（≥ `trim_high_min_pnl_pct`，默认 3%，减半层）；④ 高开 `revise` 减仓（`rules_exit_on_revise`，默认开，减 0.5 层）。每票每轮至多一笔。
  - **AI 全权路径**：只补 `stop_loss_safety_net` 硬止损兜底，止盈/高抛/减仓仍归模型判断。**这层不能省**——模型失语时本轮 `orders` 会被清空、异常回退路径只产开仓单，没有兜底则亏损仓一直挂着无人处理。AI 已对该票出过卖单（`SELL_LIKE_ACTIONS`）时不重复叠加；只在该票加仓时仍会触发止损。
  - `rules_exit_enabled=false` 两条路径都关（等于自担风险）。
- **战法风格记忆**（`application/paper_style_memory.py` + `paper_style_lessons.py`）：每 slug 独立 `paper_style_profiles` / `paper_lessons`（与全局助手记忆隔离）。**默认日终不写教训、不吸入人设、不播种记忆图**；舱配置 `eod_style_learn=true`（或预案侧 `inject_style_memory`）才评头论足→落库→吸入，并注入预案正文。清空用 `clear_paper_cabin_memory`。给人看的文案统一全中文。学习回执带 `fills_by_decided_by`；fill 教训 `evidence.decided_by`（空串→`unknown`）；不按决定方过滤 absorb。LLM 空返回经 `src.ai.chat_text_with_thinking_fallback` 降 thinking 重试（与盯盘共用）。
- **纸面 LLM 慢推理预算**：盘中 `strategy_monitor`、`skill_watch` 的 AI 摘要与盘后记忆学习共用舱配置 `llm_timeout_sec`；默认 1800 秒，写入和旧值读取均限制在 120–1800 秒。该值是单次 HTTP 调用预算；Job 仍由 `timeout_sec`（若显式配置）负责总生命周期保护。
- **统一池失败保护**：`skill_watch` 合并统一监察池异常时保留上一份完整快照并写入运行 `warnings`，禁止拿当轮残缺候选覆盖首页、企微和后续调度共同消费的名单。
- **盘后复盘企微推送（一条）**：`paper_eod` 把日终持仓/角色/五日回看与次日预案合并为「盘后复盘·战法中文名」一条；正文用监测短名（如龙回头），不露英文 slug。风格记忆与记忆子图只写入 `nextday_plans.body_text` 供监测注入，不进企微。`paper_eod` 只消费统一池并写 `nextday_plans`，不得把统一池日期推进到次日或反向改写名单；分发回执写入 Job result 的 `notify`。盘中 `skill_watch` 与收盘选股/`skill` 只更新统一池和预案，不再各自追加一条企微。
- **日终五交易日回看**（`application/paper_eod_review.py`）：强制回看近 5 个交易日；覆盖买过/错过/今日新入池/卖过 + 完整日 K；聚合量能/涨跌家数/板块；可选资金流（失败标暂无观测）。回看包含 `fills_by_decided_by`（只读成交归因分组，见 `paper_decided_by.py`）。**结论必须配对应口径**，否则会给出与事实相反的建议：
  - **错过** 仅当入池日早于复盘日且未买，收益用 `since_attention_return_pct`（自入池日起）；今日才选出来的票标今日新入池，不把入池前涨幅算踏空。
  - **买过** 用 `trade_return_pct`（自买入均价起，卖出部分按成交价、仍持有部分按窗末盯市；纯窗前老仓平仓返回 `None`）。`window_return_pct` 是**标的行情**，拿它当这笔的盈亏会把「买入前跌过」说成「买入后走弱、检查止损」；推送与「买入后走弱」教训都已改用交易口径，整窗只作括注。
  - **卖过** 用 `post_exit_return_pct`（自最后一次卖出日起），整窗上涨可能全发生在买入之前。
  - 三个口径连同说明一并进 `format_lookback_for_prompt`，避免 LLM 自己拿整窗收益重新推错结论。
  日终滚动次日预案时，**未成交的今日预案票继续带入**（不只滚持仓）。完整回看只喂 LLM；推送用 `format_lookback_digest`。
  日终总结的成交流水按 `created_at` **正序**渲染并带 `HH:MM`：`list_paper_fills` 是 DESC，直接打会把「开仓→止盈→开仓」讲反，持仓成本对不上最后一笔。
- **记忆知识图**（`application/paper_memory_graph.py` + `paper_mem_nodes/edges`）：用法对齐 codegraph explore（种子检索+扩边），存 ops.db 不进 `.codegraph/`；explore 摘要节点种类/边关系中文；`GET .../memory/explore`、`POST .../memory/rebuild`。
- **AI 决策留痕**（`infrastructure/store_ai_decisions.py` + `ai_decisions` 表，schema v12）：每一轮 LLM 盯盘都记「模型看到的**报价数值** + system prompt 原文 + user payload + 模型**原始回复** + 解析出的 orders + 模型名 / 耗时 / 失败原因」。
  - 为什么不塞 `monitor_runs.snapshot_json`：那里只存 codes 列表、不存报价数值，prompt 与原始回复完全没落盘，事后无法判断「AI 当时凭什么这么判」；且单条留痕可达几十 KB，而 `list_monitor_runs` 是前端每次打开都拉 20 条的热查询。
  - **失语轮次同样留痕**（`status=unusable/failed` + 原始片段）——恰恰是这种轮次最需要事后查。
  - 写入经 `jobs/paper_monitor_llm.record_ai_decision`，**任何异常只记日志不外抛**：审计坏了顶多丢复盘能力，不能把这一轮交易带崩。
  - 可整表删除（`purge_ai_decisions`），已登记进 `PERSONAL_TABLES`，分享包会清空。`list_ai_decisions` 默认不返回 prompt/报价，需要时传 `include_prompt=True`。
- **盯盘 LLM 模块**（`jobs/paper_monitor_llm.py`）：`MonitorLLMUnusableError` / `_parse_orders_from_text` / `_call_monitor_llm` / `record_ai_decision`。从 `paper_quant_monitor` 拆出（该文件贴 600 行上限）。**调用点仍留在 monitor**——测试按 `mock.patch("...paper_quant_monitor._call_monitor_llm")` 打桩，依赖模块全局解析，把调用一起搬走会让 patch 失效。
- 引擎：`application/paper_exec.py`（按层动作矩阵）；Job 执行器按阶段拆分（均 ≤600 行，经 `registry` 注册）：
  - `jobs/paper_quant.py` — 注册入口 / 公开 Job（`alert_scan` / `strategy_monitor` / `paper_eod` / `generate_nextday_plan`）
  - `jobs/paper_quant_support.py` — 日期、舱配置、龙空龙闸门（MCP 经 `skill_watch.skill_watch_mcp_call`）；内部 helper 从此模块导入
  - `jobs/paper_quant_plan.py` — `generate_nextday_plan`
  - `jobs/paper_quant_monitor.py` — `strategy_monitor`（跟随推送含持仓层数/浮动盈亏；hold 状态有节流）
  - `jobs/paper_quant_eod.py` — `paper_eod` + 角色留痕消费
  - `ensure_paper_monitor_jobs.py` — 普通纸面舱 `enabled` 时幂等挂 `strategy_monitor`/`paper_eod`；`dragon-return` / `dragon-pool` 只删残留任务，不再创建
- **监测推送降噪（一段式）**：企微只在**有动作**时出声。龙回头 `skill_watch` 的扫描摘要不推（`push_wecom=False`），出声交给纸面跟随推送——`execute_skill_watch` 据此把 `emit_follow` 置为 `not push_wecom`，由 `paper_quant_monitor` 在成交/拒单/失语/持仓巡检指纹变化时发一条「监测·龙回头」（节流见 `paper_follow_push.should_push_hold_snapshot`）。两者只能有一个出声，否则同一轮发两遍。
  龙头地图/涨停动量 `default_push_wecom=False`，notify 层硬拦截。龙王观察行最多 5 只且全部展示，只报龙王纠偏后的龙头角色，不让普通中军进入统一池。
  正文在闸门一行之外补：`📊盘面`（晋级/封板/炸板/跌停率/宽度/温度/涨跌停/主力净流入/截至时刻）、`🏷最强`（题材涨幅+净流入，含区间象限标签若有）、`🐉龙头`（题材·板数）；缺字段不硬编。
  时效：看悟道 `actualTradeDate`/`dateStatus`/`snapshotTime`；`dateStatus=mismatch` 或实际日早于请求日 → 空仓且**不**再打盘面/题材/龙头行。题材闸门只用 `theme_intraday_capital` 盘中截面，**不开** `includeBoomReason`（boomDate/催化常跨日）；选题材另可叠 `sector_analysis` 区间强度软过滤。
  统一池分流：持股/买入用 `💰`，调仓/卖出用 `🔄`，新进/观察/移出用 `👀`；动作只更新该票当前状态，不生成第二份名单。
- 选股/`skill` 成功且 `paper_quant.enabled` → `_maybe_seed_nextday_plan` 写情景预案；
  **`skill_watch` 不参与种子**（盘中只推监测）。
  候选固定带 `validation=unverified`。普通题材候选仍由龙空龙决定能否开仓；`market_gate_policy=strategy_specific + entry_confirmed` 的候选改用战法自身的宽度确认，不再被全局闸门二次否决。
- **纸面介入一行**（`actionable_line.py`）：真正该买时推 `💰名称 · N层 · 买价 · -20%`；盈亏比例**只有一个**（无斜杠双值），优先 `pnl_pct`，否则止损/止盈里取一个；层数按形态分，买价取扫描收盘/标记价（不编造）。
- **战法监测扫描链**（`application/skill_watch/`）：`payload`（悟道载荷解析）+ `kline_stats`（日线派生指标）
  为共用底座；`market_regime` 出龙空龙闸门；`leader_map` 出龙头地图（leader/secondary/follower/weakened/failed）；
  选题材时可选叠 `theme_interval`（开盘啦 `sector_analysis` 四象限软过滤：偏好持续强势、走弱出
  `theme_interval_weak`；调用失败/题材名未对齐出 `theme_interval_degraded` 并写入 `theme_interval` 状态，
  **不**改闸门盘中 strength）；
  `auction_confirm` 在 09:15–09:30 用集合竞价复核**龙头与中军**，**竞价放弃会就地把角色改写成 failed**，
  下游拿不到过期龙头/中军；跨链路开仓过滤已迁 `application/paper_policy/`（`eligibility` + `auction_gap` +
  `stances`）：扫描 stance=`abandoned|downgraded|confirmed|pending`，纸面=`follow|revise|abandon|wait`；
  只认 `auction_stance`/`open_blocked`，**禁止**中文 reason 启发式。旧路径 `skill_watch.paper_eligibility` /
  `auction_gap` 为兼容壳。downgraded 保留但半层+高开不追；`dragon_return` 只消费
  leader/secondary 找回头；空仓日仍扫地图角色供一段式推送（`skip_when_empty=False`），
  `picks` 仍为空不种子开仓；`limit_up_momentum` 同样走 `confirm_leaders` + 闸门/调参。
  扫描热路径默认**不**重探测 `tape_readiness`（`probe_tape_readiness=true` 才开）；日 K 走
  `history_many` 批量最近 N 根，缺票限流 routed。
  MCP/闸门软失败时 runner 标 `skipped`/`degraded`，不得假绿。引擎名 → 扫描函数与能力声明
  走 `skill_watch/engine_registry.py`（`needs_market_store` / `uses_market_gate` /
  `emits_observe` / `eod_rescan`；`theme_rotation` / `theme-leader-rotation` 并入 `leader_map`）。
  观察池粘性以 picks 含 `intent=observe` 为准；纸面闸门看 `uses_market_gate`。
  引擎自己维护跨轮状态时声明 `needs_ops_store=True`，runner 注入 **`store` + `persist`**
  （不是 `ops_store`，参数名写错只会在真调度时炸成 TypeError）。
  新增战法：注册表加一条 + 能力字段，勿再散写 slug 字面量。
- **无信号不推企微**（`EngineSpec.push_only_when_actionable`）：置 True 的引擎在
  `status=success` 且没有可执行候选时直接 `push_skipped=no_actionable_picks`。
  空 `picks` 与 **仅观察**（`intent`/`action` 为 observe）都不算可执行——只出观察票的引擎不该刷屏，
  统一池缺 action 时还会默认成 observe，旧逻辑只要名单非空就刷「👀观察 N：…仅观察」。
  **不能指望 notify 里那条 `not summary` 兜底**——runner 给 `summary` 配了 `"无新信号"`
  默认值、`signals` 里还常年躺着 `watch_only`/`gate_empty`，那条分支永远进不去，
  盘中每 10 分钟就会推一条「无新信号」。失败/跳过仍推中文原因，不受此开关影响。
- **龙回头纸面舱已退役（2026-08，勿重建）**：`dragon-return` 舱、`监测·龙回头` / `盘后复盘·龙回头` 任务与技能包由 `application/retire_dragon_return.py` 在启动时幂等清掉。盘面 GET 与 `ensure_dragon_cabin_policy` **不再隐式建舱**（这是上次删了又回来的原因）。`sync_skills_from_templates` 跳过该 slug。同族的二波监测也已在 2026-08 退役（见下条）。
- **龙池已退役（2026-08，勿重建）**：引擎、技能包、`监测·龙池` 任务与生命周期状态已整体移除；`application/retire_dragon_pool.py` 在启动时幂等清理存量安装（删任务、卸技能、清 `dragon_pool_state*`、清 `unified_monitor_pool:dragon-pool` 快照，并摘掉其它池里 `candidate_feed=skill_watch:dragon-pool` 的候选）。**只删源码不清库会更糟**：调度器照样按 cron 触发那条任务，执行器找不到引擎就每 5 分钟推一条失败。
  - 退役依据（300 个交易日 / 199 笔成交样本，防前视口径同下）：扣 0.26% 成本后相对**同信号日全市场等权基准**的配对超额 T+3 仅 **+0.53%（t=1.00，95% 区间 [-0.50%, +1.56%] 跨 0）**、T+5 +0.36%、T+10 −0.59%；超额胜率 T+3 只有 43.7%，最赚的 3 笔贡献 38% 盈利；入池分数按三等分无区分度（低 +1.00% / 中 −0.26% / 高 +0.83%）。要把该超额证成显著约需 764 笔 ≈ 46 个月。
  - 同期它还高度顺周期：`ready` 需全市场站上 MA20 ≥50%，而 2026-06-02~08-12 只有 18% 的交易日达标，2026 年 3/6/7 月整月零信号——赚的那点绝对收益基本是 beta。
  - 明细见 `2026-08-dragon-pool-forward-validation.md`（已从仓库移除，可在提交 d05e02d 中查看）。想重做这类「曾大涨 + 回撤到位」的战法，请先复现这份对照再动手，别直接把参数抄回来。
  闸门质量警告分硬/软：错日/`tool_error`/必填缺失 → 空仓；tape `degraded` 等软警告 → 最多观察不开仓。
  纸面舱 `_resolve_market_gate` 对同日闸门短 TTL（约 90s）复用，减轻与 `skill_watch` 叠打配额。
  观察池文案/规则在 `observe_format.py`（`observe_alert_records` 结构化预警），粘性合并仍在 `observe_pool.py`；
  `collect_observe_alerts` 禁止解析中文行。
- **二波监测已退役（2026-08，勿重建）**：引擎 `second_wave`、技能包 `dragon-second-wave`、托管任务 `监测·二波监测`、首页二波监测条、`GET /api/skills/{slug}/second-wave` 与留痕表 `second_wave_signals` 已整体移除；`application/retire_second_wave.py` 在启动时幂等清理存量安装（删任务、卸技能、清 `second_wave_latest` / `watch_tuning:` / `unified_monitor_pool:` 三个键，并摘掉别的池里 `candidate_feed=skill_watch:dragon-second-wave` 的候选），留痕表由 `_MIGRATIONS` 的 `DROP TABLE` 收走。
  - **它是唯一一条系统托管的 `skill_watch`**，所以只删源码最糟：用户 `ops.db` 里那条 `*/5 9-14` 照样触发，执行器找不到技能就每 5 分钟推一条「未安装技能：dragon-second-wave」——2026-08 容器化部署后这条就是这么炸的（镜像没带 `templates/`，新卷里也没有技能包）。
  - 退役原因是用户停用，不是证伪。当时的规格、阈值与实测分档留在 `2026-08-dragon-second-wave-live-alert-spec.md`（已从仓库移除，可在提交 d05e02d 中查看），想重做同类「曾大涨 + 回踩均线」的战法请先复现那份再动手。
- **人工单门闩**：`POST .../manual-orders` 默认过情景/竞价/市场闸门；`bypass_gates=true` 仅本地默认可；**`PALACE_ENV=production` 拒绝**，临时开闸需 `LOCI_PAPER_ALLOW_BYPASS_GATES=1`（并打 warning 日志）。
- **次日日期**：`_next_trade_date` 优先读 `market.db` 交易日历（长假不错位），无日历时退回跳周末。
- **每段可启停、每档可调**（`application/skill_watch/tuning.py`）：存 ops.db `meta` 键 `watch_tuning:{slug}`。
  段开关 `market_gate` / `theme_interval` / `auction_confirm` / `role_history` / `paper_candidates`；阈值分 `gate` / `roles` /
  `scan` / `auction` 四段。**关掉的段真的不跑**（闸门关 → `data_status=disabled` 且不做择时；竞价关 → 不打
  `auction_opening_snapshot`；区间强度关 → 只按盘中 strength 选题材）。未知键丢弃、越界值钳到边界，值域表只在 `tuning._RANGES` 维护一份。
  默认闸门/角色阈值在 `defaults.py`（叶模块），`tuning` 不再顶层 import `leader_map`/`market_regime`，打断软环。
  **字段清单也由后端出**：`tuning_schema()` 给出每个阈值的中文名/步长/值域与三套命名预设
  （`aggressive` 偏进攻 / `balanced` 中性 / `defensive` 偏防守），前端照着渲染；
  新增阈值必须在 `FIELD_META` 登记（`tests/ops/test_tuning_schema.py` 会卡住漏登记）。
  HTTP：`GET|PUT|DELETE /api/skills/{slug}/watch-tuning`；PUT 传 `preset` 整档套用（段开关保留）。
  响应含 `tuning` / `defaults` / `schema` / `presets`。
- **龙头角色留痕**（`infrastructure/store_watch.py` + `leader_role_snapshots`）：**只追加**，一次扫描写一批。
  `intel_snapshots` 是按 `(交易日, 工具)` 覆盖的缓存，同日多次扫描只剩最后一次，角色演进会被抹掉；这张表
  专门留住「谁从龙头掉成走弱」。可整表清空重建（重扫即生）。
  **表里只存观测事实**；存活天数、转移矩阵、走弱预警提前量都能推导，按仓规不入库，
  统一在 `application/skill_watch/role_stats.py` 即时算（`role_transitions` /
  `summarize_role_history` / `position_role_alerts` / `suggest_tuning_adjustments`）。
  **`suggest_tuning_adjustments` 只产出建议文案，绝不写入 `watch_tuning`**。
  HTTP：`GET /api/skills/{slug}/leader-roles` 返回 `history` + `transitions` + `summary` + `suggestions`。
- **留痕的消费端是日终**（`jobs/paper_quant_eod._eod_role_review`）：日终正文追加「角色演进」段
  （龙头存活榜、角色转移、走弱预警提前量）与「调参建议·仅参考」短段（来自 `suggest_tuning_adjustments`），
  并把**持仓里已判 weakened/failed 的票**落成
  `kind=role_alert` 教训供风格记忆吸收。只进不出的归档等于只占磁盘，这里是它唯一出口。
  **保留窗由 `prune` 任务收口**：`config.leader_role_keep_days`（默认 60 天，设 0 关闭该段清理），
  避免只追加的观测流变成第二个无限增长源。
- **闸门只有一套阈值**：纸面舱 `strategy_monitor` 的 `_resolve_market_gate`（`paper_quant_support`）
  复用该战法的 `watch_tuning:{slug}`（含 `market_gate` 段开关）；`emotion/ladder/themes` 三件套经
  `fetch_market_snapshot` **按日短缓存 ~90s**，与扫描器共享，避免叠跑重复扣配额。闸门评估结果另有
  纸面侧 TTL 缓存。**关闭 `market_gate` 段 = fail-closed**（共用 `disabled_market_gate`），不得静默放行。
  竞价低开带（放弃/降级）走 `auction_gap.classify_low_open_band`，扫描确认与纸面预案对齐。
  人工 `POST .../paper-cabins/{slug}/orders` 默认过情景/竞价/市场闸门；`bypass_gates` 见上「人工单门闩」。
  AI follow 后层数钳制到情景 `decision.layers`；高开超舒适带用 `layers_if_stretched`；深低开按 `abandon_gap_pct`（默认 -5%）放弃。
- **悟道未装配即软跳过（不拖垮主体）**：`intel_fetch` / `run_skill_watch` 先查 `wudao_availability`，不可用时返回
  `skipped/reason=mcp_unavailable`（Job 记 `skipped` 而非 failed），不发请求、不扣配额；盘面/账本/本地选股不受影响。
  纸面舱市场闸门同源提前降级（空仓拦截开仓，不抛）；底层 `call_mcp_tool` 对悟道统一软失败。
  `get_strategy_config` 返回 `watch_available` / `watch_unavailable_reason` 供前端置灰。
- **skill_watch**：默认可只跑 MCP/量化；仅 `watch_use_ai=true` 时强制配置 LLM 供应商。
- **intel_fetch**：`stats.failed>0` 时 Job 记 `failed`（部分失败不假绿）；`strategy_monitor` / `paper_eod` 非交易日主动 `skipped`；监测 LLM 失败等记 `monitor_runs.status=failed`。
- **intel_fetch 的配额自检**：开跑前用 `estimate_daily_calls` 按**调度器实况**（ops.db 里三条托管任务的 cron 与 config）算一遍全天扇出，超出本池预算就写一条中文告警到日志和 job payload（`quota_alert` + `summary`），明说超了多少、该拧哪个旋钮（盘中 cron / `intraday_theme_top_n` / 盘后 `theme_top_n`·`stock_flow_top_n`·`screener_count` / 改记 skill 池）。**只报警、不静默截断**：这一轮照原配方跑完，少拿数据必须是人显式调旋钮，否则下游会把「只扫了前 N 只」当成「全市场就这些」。悟道不可用时先软跳过，不做自检、不建调用清单。
- **盘中题材扇出上限**：intraday 档的 `theme_stocks` 只按 `intraday_theme_top_n`（默认 40）扇出，open / close 仍用完整 `theme_top_n`。盘中一天 24 轮，题材数是唯一被轮次放大的旋钮；盘中榜十几分钟不会翻天，而 120→40 一天省 1920 次 structured 配额。
- **intel_fetch 的池可参数化**：Job 配置键 `pool`（默认 `structured`，只认 structured/skill，写错回落并 WARNING）。盯盘那条链路的池在 `market/infrastructure/tape/wudao_provider.py`（默认 `skill`，可经 `TapeRequest.context["quota_pool"]` 指定）。
- **intel_fetch 的缓存 TTL 必须小于采集间隔**：盘中 cron 是 `*/15`，TTL ≥ 15 分钟时下一轮 run 整轮命中缓存、一次真调用都不发，
  Job 却记绿——一半的 run 空转、数据还是上一轮的。默认 12 分钟，盘中档即使用户配得更大也会被钳回（`jobs/intel_fetch.py`）；
  收盘档保留长 TTL（默认 120 分钟）是对的，收盘后数据已定稿。实际生效值还要与 `intel` 侧盘中 10 分钟上限取小。
- **skill_watch 的工具入参照悟道 schema 写**：`broken_limit_up` 不收 `limit`（多传一个键 → `INVALID_ARGUMENTS` 整条拒 →
  炸板池空手回来、「弱转强」候选恒为空），要几行在本地 `rows_by_code(limit=…)` 截。键名对照表见 `intel/README.md`。
- **mcp_quota**：DDL 在 ops `store_schema`；`intel.quota` 只读写 ops.db 该表。
- 预览：`POST /api/skills/{slug}/watch-preview` 用实时数据试跑一次同一套扫描，只读——不写纸面舱、不推送、不调 LLM；
  响应可带 `suggestions`（留痕频率建议，不改参）。
- 龙回头纸面舱每次 `strategy_monitor` 都重判 `short_term_emotion` / `limit_up_ladder` /
  `theme_intraday_capital`；闸门为“空/观察”时拦截新增纸面仓位，但不拦截已有仓位退出。
- Live 快照：`src.market.application.live_cache`（TTL，不写 market 权威库）。
- HTTP：`/api/ops/paper-cabins*`、`/api/ops/alert-rules*`（见 `api/README.md`）。
  `GET /api/ops/alert-hits` 的 `limit` 与 `/api/jobs/runs` 同口径钳到 **1..500**（越界 422）：它直接进 SQL 的 `LIMIT ?`，裸 int 等于放任全表扫 + 无界响应，`-1` 在 SQLite 里更是「不限行数」。
  `insert_alert_hit` 的空返回是**幂等跳过**（同桶重扫），不是「写失败」：真失败会抛出，`scan_alert_rules` 的 `if not hit: skipped += 1` 只吃前者。

## 盘中留存采集（intraday_capture）

托管任务「托管盘中留存采集」，工作日 **15:35**（让开 15:10 的行情日终重刷与 15:30 起的
选股时段）。执行器 `jobs/intraday_capture.py`，落点在 `<data_dir>/intraday/`，
**不写任何一个库**。

- **为什么必须托管**：上游没有历史（AkShare 21 个接口只有当天快照），漏一天永久缺一天，
  靠人记得每天点一次等于一定会漏。见
  [ADR-014](../../docs/adr/ADR-014-encrypted-intraday-tape-retention.md)。
- **部分失败不算任务失败**：一轮六个上游，AkShare 打的是公开网页接口，
  `RemoteDisconnected` 是常态。一个源挂掉就判整轮失败会让运维页天天飘红，最后没人看它。
  所以**一个都没采到才抛 `JobError`**，部分成功记 `status="partial"` 并把失败清单原样
  写进 payload。
- config：`datasets`（只采这几个）、`trade_date`（补采历史目录用）。缺省采
  `default_specs()` 全部。
- **过期删除挂在 `prune` 任务里**（不新建任务类型）：`intraday_keep_days` 默认 60、
`intraday_max_delete` 默认 30。留存带删不掉只记进 payload 不抛——那是磁盘问题，不该让
  整条运维清理红掉。

## 一键分享打包
- 用例：`application/share_pack.py` — 仅打包已编译 onedir（`Loci.exe` + `_internal`），可选附带行情/运维骨架/MCP/技能/本机配置/账本。
- **默认脱敏**（`application/share_pack_sanitize.py`）：分享包是数据离开本机的唯一出口，按信任边界处理。
  - `ops.db`：整表清空个人记录（`PERSONAL_TABLES`：job_runs / 纸面舱 / 教训 / 记忆图 / 告警 / 角色留痕 / 回测结果），
    抹掉 LLM 密钥、任务配置里的 Webhook；`meta` 走**白名单** `META_ALLOWLIST`（新增键默认不外发）
  - `mcp.json`：只留 URL / 工具清单 / 备注，抹掉 token 与 headers
  - `loci.config.json`：递归抹掉含 token/secret/key/webhook 等字样的字段；解析失败则整份跳过
  - 勾选 `private` 才关闭脱敏（自己换机器用）；`ledger` 单列且默认不勾
  - 压缩前 `find_forbidden_files` 兜底：出现 `.palace_ai_master_key` / `*.key` / `*.pem` 直接中止打包
- 响应头回执 `X-Loci-Sanitized` / `X-Loci-Sanitize-Count`，前端据此提示"脱敏包"还是"含个人数据"。
- 产出：顶层目录名为 `Loci/` 的 AES 加密 zip；固定解压密码仅在服务端 `SHARE_PACK_PASSWORD`，前端不展示。
- 可选 `algorithms`：是否打入 `_internal/src/strategy` 与 `formula` 内置算法。
- HTTP：`GET /api/ops/version`、`GET /api/ops/share-pack/status`、`POST /api/ops/share-pack`（见 `api/README.md`）。
- 不打包：`.palace_ai_master_key`、webview 缓存、审计截图等噪声。

## 关键入口
`OpsStore` / `run_job` / `discover_skills`；HTTP：`/api/jobs/*` `/api/skills/*` `/api/ops/*`；CLI：`python -m cli.ops`

## 如何扩展
新 Job kind：在 `application/jobs/<kind>.py` 写 `execute_*`，再注册到 `application/jobs/registry.py` 的 `EXECUTORS`，并加入 `JOB_KINDS` 与 `JobCreate.kind`。

托管任务：
- 行情：`MANAGED_SYNC_INTRADAY` / `MANAGED_SYNC_EOD`，由 `ensure_managed_market_sync_jobs` 幂等创建；**首次默认开启**盘中增量 + 日终重刷（默认 15:10，`today_refresh` + `with_factors`，赶在 15:30 选股前）。**`today_refresh` 的三步顺序是硬约束**：复权因子 → 当日 spot → **权威源定稿**（`_finalize_today_with_authoritative`，通达信近窗 20 根，全市场约 2 分钟）。定稿必须排最后：`quotes_daily` 的 upsert 后写覆盖先写，而 `apply_today_spot` 写的 source 恒带 `_spot`，反过来跑就会把刚定稿的正式日 K 重新盖成临时行。**这一步 2026-08-26 之前是缺的**——spot 只要成功，当日就 100% 是临时行（没有回执、`amount` 可能是 `close×volume` 合成假值），正式日 K 要等第二天早上增量近窗回头重写才落，而 15:30 选股、当日回测与复盘全在读它；体检的 `last_day_authoritative` 判据一上线就把这个形态报了出来。定稿失败只写 `finalize.error` 不刷红任务（spot 行还在，有临时行比没数据强）。两条任务每天首次运行前刷新一次证券目录，退市旧票会先退出本轮代码集；盘中增量（`mode=full`）走 watermark：今天没同步过的票只补近窗日 K（见 `src/market` 的「日 K 增量近窗」），不再每天把全市场全历史重拉一遍；只有 `force=true` 才回全量
- **同步作业的运行记录只留证据摘要**：`source_evidence.receipts` 压成失败样本（上限 50 条）+ `receipts_total` / `receipts_failed` / `receipts_source`。逐票回执的权威副本在 `market.db.source_route_receipts`，全量塞进 `ops.db.job_runs.result_json` 会让单条运行涨到数百 MB（实测 257 MB/条，258 条运行 = 1.7 GB 运维库）。**`mode` / `force` / `with_factors` / `refresh_instruments_daily` 是托管键**：启动时确保托管任务会把它们复位成上述语义，只有 `workers` / `push_wecom` / cron / `enabled` 等尊重用户改动——历史遗留的 `force=true` 会让盘中增量每 5 分钟重拉一遍全市场历史
- `sync` 结果字段：历史日 K 硬失败进 `failed`；当日现价软跳过进 `spot_skip_reason` / `spot_gaps`；每日证券目录刷新写 `instrument_refresh`（失败时继续用本地目录）；**尽力而为的子步骤失败也要留痕**——复权因子刷新失败写 `factors_error`，换手率回填失败写 `turnover_repair.error`，热库镜像失败写 `hot_mirror.error`。这些尽力而为项都不改任务状态（不因外部源抖动把日终刷成红），但运维页看得见，避免「除权后 qfq 长期失真却一直绿灯」
- 行情热库重建：`MANAGED_HOT_REBUILD`（`kind=hot_rebuild`，默认 cron `10 16 * * mon-fri`），由 `ensure_managed_hot_rebuild_job` 幂等创建；把全量库近 700 交易日窗口全量重灌进滚动热读库（`market_hot.db`，重建时裁窗外旧行），热库损坏/启动兜底时手动触发。见 [ADR-007](../../docs/adr/ADR-007-market-hot-readonly-window.md)
- 行情库体检:`MANAGED_MARKET_QUALITY`(`kind=data_quality`,默认 cron `30 16 * * mon-fri`,排在热库重建之后,看到的是当日终态),由 `ensure_managed_market_quality_job` 幂等创建。**只读、只报、不改库**——修复各有各的入口(`scripts/resync_market_authoritative.py`、`repair/turnover`),体检擅自动手会让「谁改的库」说不清。**七项判据**:全库权威源占比、**最后一个交易日的权威源占比**、合成成交额行数、近窗缺回执、最后交易日覆盖、基准指数量级、非权威源水位。超阈值时 payload 里出 `blocked` / `alert`(中文告警),但**不抛异常**:体检报的是「库需要维护」,不是「这次任务出错了」,刷红运维页会让人开始忽略它。阈值可在 job config 覆盖(键名见 `jobs/data_quality._THRESHOLD_KEYS`,**新增阈值必须同步登记进这份名单**,否则运维页调了也不生效),配置写错只 warn 并回落默认——配置写错就不体检 = 最需要体检的时候正好没体检
  为什么要有它:换源和全量重写都只解决「当下」。之后主源一旦被限流,回退源会安静地把 `close×volume` 合成的假成交额写回来;spot 会落下无回执的临时行;退市票的水位会一直停在老日期。这些都不报错,只会慢慢把库泡坏。见 [ADR-013](../../docs/adr/ADR-013-tdx-primary-daily-source-and-batch-sync.md)
  **「最后一个交易日的权威源占比」是 2026-08-26 补的盲区**:全库口径的分母是十六年历史,一次重灌顶到 96.5% 之后,「今天主源一行没写」要连续退化约 **49 个交易日**才拉得动它。取证是在**开发机**上做的(该机通达信自 07-28 起被限流):全库 96.5% 判绿,而最后一个交易日的 5542 行里 tdx **0 行**。**同一天的生产库是健康的**(全库 97.1%、近 8 个交易日逐日 99.9%~100%)——这条判据补的是算术上必然存在的盲区,不是在修某次生产事故;写证据时务必标清是哪台机器,否则后来人会照着一个不存在的故障排查。口径细节(spot 临时行单独归类、定稿时限、0.90 阈值的日水位依据、为什么是 warn 不是 block)见 `src/market/README.md`
  **托管默认 `push_wecom=true`**:体检报出来的东西如果只落在 `job_runs.result_json` 和本地日志里,就要靠人主动去运维页翻,而这类问题不翻就不会知道、每多一天多一天脏数据。降噪交给 `jobs/notify._maybe_push_wecom` 的 `data_quality` 分支——**全绿一律 `push_skipped=quality_all_green`**,只有 `blocked` 或有 `alert` 才推,正文直接用 `build_alert` 写好的中文告警;`status!=success` 也推(体检自己不抛异常,能失败的是打不开行情库这类真故障)。已存在的任务照旧**只补缺失键**(`{**DEFAULT, **prev}`),用户在页面上关掉的推送、改过的 cron 都不会被 ensure 顶回去
  **推送异常不许拖垮体检**:`_maybe_push_wecom` 里的 `dispatch_text` 现在整段包了 try——`run_job` 调它的那一行**不在**任何 try 里,漏一个异常出去会让这次运行卡在 `running` 上收不了尾,等于一条推送把它本该通知的那次体检记录也毁了
- 候选兑现：`MANAGED_OUTCOME_TRACK`（`kind=outcome`，默认 cron `45 15 * * mon-fri`），由 `ensure_managed_outcome_job` 幂等创建；lifespan 启动（含未开调度器时预写）确保存在。已存在时**只补齐缺失的配置键**（`limit` / `max_age_trading_days` / `benchmark`），不整体覆盖、不改 enabled / cron
- 运维清理：`MANAGED_PRUNE`（`kind=prune`，默认 cron `30 2 * * mon-fri`），由 `ensure_managed_prune_job` 幂等创建；工作日凌晨清理 `job_runs`（每任务保留最近 200 条）与 `leader_role_snapshots`（保留 60 天），避免运维库无限涨库。`prune_runs` **不删 `status=running` 的记录**（清掉执行中的运行槽会让 `finish_run` 当场报「任务运行不存在」），`keep_per_job` 下限钳到 1（配 0 会连「最近一次跑没跑过」都查不到）
- 悟道情报采集：`情报·开盘/盘中/盘后`（`kind=intel_fetch`），由 `ensure_managed_intel_jobs` 幂等创建；走 **structured 池**（默认 3000/天），Agent/Skill 临机与**战法盯盘 / tape lane** 走 skill 池（默认 2000/天）。**这三条任务的 cron 就是配额估算的真相来源**：`intel_fetch` 自检会读 ops.db 里它们的真实 cron 与 config 反推日耗（`*/15 9-14` = 24 轮/日，不是拍脑袋的 20），改 cron 就等于改预算。默认配置下 structured 预估 **1755 次/日**（开盘 190 + 盘中 53×24 + 盘后 293），压在 3000 以内。`enabled` 参数**只是首次创建的默认值**：已存在的任务只补齐缺失的托管配置键，不回写 enabled / cron / 用户调过的 `theme_top_n` 等参数——否则用户在运维页关掉的情报任务会在下次启动自己复活
- 悟道 AI 简报推送：`简报·开盘/午间/收盘/晚间`（`kind=intel_brief`），由 `ensure_intel_brief_jobs.ensure_managed_intel_brief_jobs` 幂等创建，**首次默认开启**且 `push_wecom=true`。cron 分别 `10,25,40 9`、`10,25,40 12`、`40,55 15`、`10,25,40 21`（全 `mon-fri`）——**比悟道出稿时点（09:00/12:00/15:30/21:00）晚 10 分钟**，且一档挂多个触发点兜它的延迟：第一次没出稿记 `skipped/not_published`，下一个点再看一眼；出稿后由防重标记（复用选股那套 `wecom_push_marks`，指纹含悟道 `generatedAt`，所以它重算过一次才允许再推）保证只推一条。正文经 `intel/application/briefing.py` 把 `fullContent`（Markdown）转成纯文本，再由 `notify.split_text_for_wecom` **按字节**切片（企微 text 上限 2048 **字节**，中文一字三字节；`MAX_TEXT_CHARS` 那道 2000 **字**闸门对中文其实是 6000 字节，靠它只会被服务端悄悄吞掉后半篇）。开盘档实测 8.3KB 切 5 条。开关三层：任务启停（四条独立）/ `push_wecom`（只取数不出声）/ `full_text`（只发摘要，少几条消息）。**通用「任务状态」推送对这个 kind 闭嘴**（`jobs/notify._maybe_push_wecom` 的 `intel_brief` 分支）：正文由执行器自己分片推，再来一条状态播报就是一天最多 12 条「已跳过」噪音；只有 `status=failed` 才出声（回执键用 `push_reason`，不占执行器写「为什么跳过」的 `reason`）。而 `failed` 只有两种来路——执行器抛异常，或**简报取回来了却一条都没发出去**（`push_error`，见 `registry` 状态判定，不得假绿）；刻意没发（安静时段/限流/开关关/已推过）一律 `skipped`。**简报是 AI 旁注**：正文首行固定标注来源，不入库、不参与复盘数字、不喂选股引擎。见 [ADR-017](../../docs/adr/ADR-017-wudao-briefing-relay-and-intel-widening.md)
- 价格提醒扫描：`价格提醒扫描`（`kind=alert_scan`，默认 cron `*/5 9-14 * * mon-fri`），由 `ensure_alert_scan_job.ensure_managed_alert_scan_job` 幂等创建，**但只在库里已有启用中的 `alert_rules` 时才创建**。理由两头都要顾：一头是规则的 `cooldown_minutes`（默认 5 分钟）/ `max_triggers_per_day` / `market_hours_mode` 只有「按固定节奏扫」才有意义（[ADR-008](../../docs/adr/ADR-008-paper-quant-cabin.md) 第 7 条把价格提醒的运行时定为 `alert_rules` / `alert_scan`），而在此之前**没有任何代码创建过这条任务**——规则存进去以后只有人手点 `POST /api/ops/alert-rules/scan` 才会命中，提醒不会自己响；另一头是没有规则时 `scan_alert_rules` 直接返回 `total_rules=0`，无条件托管等于给每台机器每天塞 48 条空 run。**cron 窗口就是唯一的时段闸门**：`_can_trigger` 并不校验 `market_hours_mode`，所以这条任务不能挪到盘后或改成全天。已存在的任务只补齐缺失配置键，不改 enabled / cron，规则被删光也不停用不删除（用户调过的 cron 删了找不回来）
- 专属战法：`skill:{slug}`（`kind=skill`，盘后 AI 选股）+ `监测·{slug}`（`kind=skill_watch`，盘中确定性信号）。两者由 `skill_strategy_config.save_strategy_config` 成对写入，**不自动创建**；仅开启盘后 AI 或盘中 AI 解读时要求 LLM 供应商。`SKILL.md` 只声明战法能力、工具、信号与取数窗口，不声明 cron/时段；运行时间、频率、启停和推送由系统配置（见 `DEFAULT_SCREEN_SCHEDULE` / `DEFAULT_WATCH_SCHEDULE`）。
- 盘后选股：每个引擎战法绑定 `screen:{slug}`，默认 cron `30 15 * * mon-fri`（工作日 15:30），由 `ensure_managed_screen_jobs` 幂等创建/对齐；战法可声明自己的托管时点与输出上限。三源 / 杨氏收盘档：`sanyuan-tail-v1` / `yangshi-tail-v1` 固定 15:30（最多 2 / 1 只）。14:50 两档（`sanyuan-tail-1450` / `yangshi-tail-1450`）已连代码删除；启动时活动目录收缩会清掉旧库残留的 `screen:*-1450`。`qianlong-tail-v1` 已下线，启动时 `ensure_managed_screen_jobs` 会删掉旧的 `screen:qianlong-tail-v1`；用户在详情页保存的 `universe`（行情范围）会保留，手动选股未传 universe 时也回落该配置（见 `screen_job_config.resolve_screen_universe`）；无 `screen_schedule` 声明的战法还会保留用户自定义定时；**盘中选今天**（含用户保留的 14:50 cron）走 `screen_live`：自己拉实时日 K 叠内存面板，不写 `market.db`、不镜像热库、不占 `market_heavy_slot`。**收盘后**才走 `ensure_today_quotes_for_screen`：当日覆盖率已达标则跳过 spot（不与盘后同步抢写），不足才刷现价；库忙但覆盖已够则软放行。**多租户**：子账号盘后选股恒不刷 spot、不镜像热库（行情由主账号的系统级同步统一写；当日行情未就绪时落 `skipped`）；盘中选股各租户各自拉实时、互不抢写锁。首次创建的 cron 按租户错峰到 15:30~15:44，主账号仍是 15:30——见「并发与配额」
- 活动目录收缩：`ensure_managed_screen_jobs` 会删除 `screen:*` 前缀下不再托管的旧 `screen` 任务（未注册，或声明 `screen_managed_job=False`），避免废弃/不定时战法继续调度或推送；其它同名前缀任务和非 `screen` 任务不受影响
- 调度器：`loci.py` / `cli.serve` 默认 `PALACE_ENABLE_SCHEDULER=1`（pytest 不设）；启动时确保上述托管任务并 `reload`
- **工作日 cron**：一律写 `mon-fri`（或经 `validate_cron` 把历史 `1-5` 归一化）。APScheduler 的数字星期是 **0=周一**，Unix 习惯的 `1-5` 会被当成周二–周六，**整周跳过周一**（龙王盘中监测/纸面盯盘会在周一静默不跑）。
- **启动补跑**：调度器起来后后台执行 `eod_catchup`——对 `screen` / 日终 `sync` / `outcome` 等「工作日定点」cron，若最近交易日触发点已过且尚未跑过，则 `trigger=catchup` 补跑一次。多时点 cron（换行 / 分号分隔）逐时点判定：只要有一个时点「已到、`last_run_at` 未覆盖」就进名单，补的是最晚那个时点。`last_run_at` 无时区时按 UTC/上海本地**任一覆盖**即跳过；「当日已成功」的判定精确到时点——成功 run 的 `started_at` 必须不早于要补的触发点，早一档成功不能替晚一档失败顶账。选股企微另有 `wecom_push_marks` 防连推。
- `GET /api/jobs/schedule`：未启调度器时仍用 `preview_upcoming_jobs` / `next_cron_fire_at` 按 cron 推算 `next_run_at`，供详情页展示
- **执行互斥与生命周期**：`run_job` 通过 ops.db 原子认领同一任务的执行槽；调度、API、CLI 和助手重叠触发时，后到者返回 `skipped` 和当前 `run_id`，不重复执行副作用。可传 `idempotency_key` 做跨重试幂等；`JobContext.check_cancelled()` 在安全检查点收敛 API 的取消请求或 `timeout_sec`，终态为 `cancelled` / `timed_out`，`finish_run` 不允许覆盖既有终态。`heartbeat_at` 与 `owner_pid` 一起用于 stale recovery。`sync`/`screen` 另有进程内行情闸门（`jobs/market_gate.py`）：**sync=独占写、screen=共享读**（多路选股可并行；不再互相假互斥等 90s）。holder 标签去重（`screen:qianlong-…` 不再变成 `screen:screen:…`）。**14:35–15:00 盘中增量（`mode=full`）占锁前直接 skipped**，避免新开一轮写库和 14:50 选股叠内存；盘中选股自己拉实时 overlay，不再等这次增量写完。日终 `today_refresh` 不跳过。`execute_sync` 持锁后仍会再判一次窗口，判到就 `JobSkipped` 放锁。选股等锁 360s、同步等锁 20 分钟（`LOCI_MARKET_GATE_SCREEN_WAIT_SEC` / `LOCI_MARKET_GATE_SYNC_WAIT_SEC` 可覆盖；旧的 90s 与 45 分钟租期完全失配，正常排队天天被当故障报）。**写者优先**：有 sync 在排队时不再放新 screen 进来，否则一波接一波的选股能把同步无限期饿死。**读槽有租约**（`MARKET_SCREEN_HOLD_LEASE_SEC`，45 分钟，与 screen stale 回收窗同口径）：到点仍不放槽的选股按已废弃处理并放行同步——ops.db 那条 run 此时也已被判 failed，闸门不该继续替一个判死的任务挡路。**同线程重入按 kind 判**：同 kind 直接放行（`run_job` 外层 + `execute_sync` 内层是同一批写入，再抢一次只会自锁），`sync` 写槽里再要 `screen` 读槽也放行（写槽本就涵盖读，排队等于等自己）；但 **`screen` 读槽里再要 `sync` 写槽不算重入**——那是跨 kind，正是本模块要防的「一边扫 market.db、一边写 WAL」组合，旧判据「持有任意 kind 即重入」会把它静默放行、独占写锁形同虚设。现在内层会真去抢写槽：先把**自家**那把读槽临时让出（否则 `_acquire_writer` 会等自己），写完在同一临界区里降级取回；别人的读槽照样挡路，抢不到就按常规排队/超时收场。等锁超时用人话了断，不硬刚挂死同步：**同步排在另一条健康同步后面等不到 → `JobSkipped` → 终态 `skipped`**（两条同步写的是同一批当日行情，先到的写完就够了；判 failed 只会每天刷一次假故障 + 企微「同步失败」）；持锁超过 `MARKET_SYNC_STUCK_SEC`（45 分钟，与 sync stale 回收窗同口径）才算卡死，仍明确 failed 并点名占锁任务；被租约内的选股挡住仍是 failed，但文案改为「选股仍在正常执行」，不再让用户去「停掉卡住的选股」（它们通常是受害者而非元凶）。`LOCI_OBSERVABILITY=1` 时记 `loci.lock.wait_ms` / `market_gate_lock_timeout`（`outcome=skipped|timeout`）。读写双库：`sync`/`screen` 写全量库后把最近交易日增量镜像进热库（`mirror_recent_to_hot`）；`sync` 镜像失败只记 warning、不阻断任务。`screen` 默认只读热库；镜像失败、`hot_unusable_reason` 判定不可用（窗口偏浅或落后于全量）、或策略 `requires_full_history` 时回退全量库选股——`jobs/screen`、`screen_run`、`POST /api/screen` 三条路径共用同一判定函数，不再各写一份；选股前准备当日行情见 `market.application.screen_spot`（覆盖达标跳过 / 库忙复检覆盖）。超时 / 僵尸 running 回收：认领时优先按 `owner_pid` **探活**——进程已死立刻腾槽（不再干等）；**同一 PID 但 `started_at` 早于本进程启动**也立刻腾槽（容器 Recreate 后 uvicorn 经常还是 PID 1，`pid_alive(1)` 为真会把上一世的 running 当成还活着，2026-09-01 重启后三条槽被假占用）。时间兜底 `sync`/`screen` **45 分钟**，其它 kind **24 小时**。调度器启动与每次 `claim_run` 都会扫。跨进程行情写锁见 `market.infrastructure.write_lock`（sync/spot 互斥，同线程可重入，**跨线程等待有 deadline**）。**`execute_sync` 自己也占 sync 写槽**：HTTP `/api/market/sync`、首启 bootstrap 回填、CLI 都不走 `run_job`，只在 `run_job` 上挂闸门等于留了后门——2026-08-24 正是 bootstrap 同步在闸门视野之外占着写锁，把 15:30 三只选股拖死，进而让盘后同步与日终重刷连续两次假故障。即时分析预先分配独立运行槽，因此不同请求仍可并行。
- **执行期心跳（2026-08-25 修）**：`run_job` 在执行器外面套一层 `HeartbeatPump`（`jobs/context.py`），执行期间每 **30s**（`HEARTBEAT_INTERVAL_SECONDS`）推进一次 `job_runs.heartbeat_at`。此前 `ctx.heartbeat()` 全仓只在执行器**启动前**和**返回后**各调一次，中间从不刷新：一次 914s 的日终同步心跳全程冻在起始值，于是（1）耗时超过 `STALE_RUN_SECONDS_BY_KIND["sync"]`（45 分钟）的**合法**长任务会在还在跑的时候被 `claim_run` / `reclaim_stale_runs` 判死腾槽；（2）运维看着冻结的心跳，把正常但慢的同步当成挂死处理，还错杀了旁边正在跑的选股。**不去改 16 个执行器**——它们都是同步函数，逐个改不现实、新写的一定会忘，所以统一在 registry 这一层兜住。几条硬约束（理由都写在代码注释里）：泵套在 `market_heavy_slot` **外面**（等写槽本身最长 20 分钟，排队期间这条 run 已经是 running，心跳一样不能冻）；30s 是「远快于最紧的 15 分钟 / 45 分钟回收窗」和「别拿单行 UPDATE 去持续抢 ops.db 写锁」之间的折中；心跳线程**自带 sqlite 连接**（`store_runs.RunHeartbeatWriter`）——`OpsStore.conn` 是 `check_same_thread=True` 建的，跨线程直接用会当场抛 ProgrammingError，共用连接还会和执行线程的事务互踩，连接懒开懒关且都在心跳线程内完成；`stop()` = 置事件 + `join()`，成功 / 异常 / 超时 / 取消四条路径都经 `with` 收口，线程不泄漏（另标 daemon 兜底）；心跳写库失败只累加 `errors` 并记一条 warning，绝不反过来把任务本身弄失败。`finish_run` 随之改用 `BEGIN IMMEDIATE`：WAL 下「先 SELECT 状态、再 UPDATE 终态」的 deferred 事务，若心跳线程在中间提交过，升级写锁会立刻拿到 `SQLITE_BUSY_SNAPSHOT`（`busy_timeout` 对这种冲突不生效），收尾会平白失败。**注意心跳的含义也随之变了**：它现在证明的是「进程还活着、这条 run 还没收尾」，**不**证明业务在推进——真卡死（例如攥着 market.db 不放）要靠 `timeout_sec`、人工取消或 `market_gate` 的持锁判据兜底，时间窗只剩下抓「进程没了 / 根本没心跳」。回归测试见 `tests/ops/test_job_heartbeat_liveness.py`

### 回测进程边界（2026-09）

`compare` / `optimize` 的即时分析默认用 `execution_mode=process`，由
`src.backtest` 的 `spawn` worker 承担大面板计算；单次 `backtest` Job 也可在配置中
启用同一模式。父进程仍负责 `job_runs` 认领、心跳、取消、超时与最终落库，worker
只读显式 `market_db`，在当前租户上下文中加载策略，结果通过 16 MiB 上限的 JSON
IPC 返回。worker 被终止后内存随操作系统回收，避免线程异常把 API 进程拖进高水位。
进程槽默认 1 个，`LOCI_BACKTEST_PROCESS_SLOTS` 可调到 1–4；结果的 `execution`
字段记录 worker PID 与可选 RSS。旧 CLI 或小样本可将 `execution_mode` 设为 `thread`。

### Job kind × 托管 cron 判定（2026-08 审计）

`EXECUTORS` 里 16 种 kind，逐个判过「该不该有系统托管的 cron」。**没有托管 cron 不等于漏**——
`notify` / `backtest` / `compare` / `optimize` 的 config 必须点名 template / strategy / 区间，
没有能替用户拍板的默认值；`skill` / `skill_watch` 由 `save_strategy_config` 成对写入；
`strategy_monitor` / `paper_eod` 按纸面舱走 API。

| kind | 托管 cron | 判定 | 代码证据 |
| --- | --- | --- | --- |
| `sync` | `*/5 9-14`（盘中）/ `10 15`（日终） | 该有 ✓ | `ensure_market_sync_jobs.ensure_managed_market_sync_jobs` |
| `screen` | `30 15`（每个引擎战法一条） | 该有 ✓ | `ensure_screen_jobs.ensure_managed_screen_jobs` |
| `outcome` | `45 15` | 该有 ✓ | `store_jobs.ensure_managed_outcome_job` |
| `prune` | `30 2` | 该有 ✓ | `ensure_managed_prune_job` |
| `hot_rebuild` | `10 16` | 该有 ✓ | `ensure_hot_rebuild_job` |
| `data_quality` | `30 16` | 该有 ✓ | `ensure_market_quality_job` |
| `intel_fetch` | `26 9` / `*/15 9-14` / `40 15` | 该有 ✓ | `ensure_intel_jobs`（三档） |
| `intel_brief` | `10,25,40 9` / `10,25,40 12` / `40,55 15` / `10,25,40 21` | 该有 ✓ | `ensure_intel_brief_jobs`（四档；比悟道出稿晚 10 分钟，多触发点兜延迟） |
| `skill_watch` | 无 | 不该托管 | 二波监测退役后不再有托管的 `skill_watch`；`监测·{slug}` 由 `save_strategy_config` 成对写入 |
| `alert_scan` | `*/5 9-14`，**有启用规则才建** | 原先漏了，已补 ✓ | `ensure_alert_scan_job`；ADR-008 第 7 条 + `alert_rules.cooldown_minutes` 默认 5 分钟 |
| `strategy_monitor` | 无（按舱） | 不该托管 | `ensure_paper_monitor_jobs` 由 `PUT /api/ops/paper-cabins/{slug}/config` 调；执行器 `paper_quant_monitor` 第一行就要 `config["slug"]`，没有舱就没有任务 |
| `paper_eod` | 无（按舱） | 不该托管 | 同上；`retire_dragon_return` 模块头明写「启动时 reconcile 会把监测/日终挂回来，删舱等于白删」 |
| `skill` | 无 | 不该托管 | `skill_strategy_config.save_strategy_config` 成对写入；`execute_skill` 缺 provider 直接 `JobError` |
| `notify` | 无 | 不该托管 | `execute_notify` 按 `config.template` 分支，托管挑哪个模板都是替用户拍板 |
| `backtest` | 无 | 不该托管 | `execute_backtest`：`config.strategy` 缺失即 `JobError`；跑的是历史区间，天天重跑同一段没有新信息 |
| `compare` | 无 | 不该托管 | `execute_compare`：全战法 × 多持有期笛卡尔积，一次几十轮回测，研究用 |
| `optimize` | 无 | 不该托管 | `execute_optimize` 自己在 docstring 里写「参数扫描天生会生产漂亮数字」，定时跑等于定时过拟合 |

**纸面舱这三种为什么生产上一条都没有，是对的**：唯二存在过的舱 `dragon-return` / `dragon-pool`
已在 2026-08 退役（`retire_dragon_return` / `retire_dragon_pool` 启动时幂等清任务、卸技能、删舱），
`is_retired_paper_cabin` 会拦住重建；新舱只有用户在盘面 `PUT .../config` 时才连带挂任务。
**绝不要**在 `ensure_all_managed_jobs` 里按舱重挂——那正是上次「删了又回来」的原因。

**`ensure_*.py` 与 `ensure_all_managed_jobs` 对账**：9 个 ensure 模块里 8 个已挂（行情同步 / 热库重建 /
库体检 / 运维清理 / 盘中留存采集 / 盘后选股 / 情报采集 / 价格提醒扫描）+ store 侧的候选跟踪；
唯一没挂的 `ensure_paper_monitor_jobs` 是**故意**的（见上）。候选跟踪原先裸调在 `_ensure_step`
保护之外，它一抛异常后面全部托管任务与三条退役清理都会被跳过，现已并入受保护的循环。

### 盘后时点余量（2026-08 实测）

日终重刷 15:10 起、实测 914s（15 分 14 秒）→ 收在 **15:25:14**，离 15:30 三条选股只剩 **286 秒**。
所以「选股开始时同步还没跑完」在当前实测下**还没有发生**，但余量薄：

- 选股是共享读者，撞上仍在写的同步会等锁，上限 `MARKET_SCREEN_LOCK_WAIT_SEC=360s`。
  合计容忍到同步耗时 **1560s（26 分钟）**；再超，三条选股会一起抛 `JobError`（红，且要人处理）。
- 不对称要注意：同步排在选股后面拿不到锁是 `JobSkipped`（下轮再跑，静默），
  **选股排在同步后面超时却是 `JobError`**——同样是排队，一边算正常一边算故障。
- 三条选股（`qianlong-close-v3` / `sanyuan-tail-v1` / `yangshi-tail-v1`）同在 15:30，
  彼此是共享读者不互斥，但 `run_job` 在读槽外还套一道 `screen_memory_slot`——它现在只是
  `src.shared.screen_capacity` 的 ops 适配器（记 `component="screen_queue"` 的等待 metrics、
  把 `ScreenCapacityBusy` 翻成 `JobError`），闸门本体是**进程级**的：同时执行的选股数
  `LOCI_SCREEN_JOB_CONCURRENCY`（默认 1），排队上限 `LOCI_SCREEN_QUEUE_WAIT_SEC`
  （默认 20 分钟，超时 `JobError`），FIFO 先到先得、排队可取消。排队在读槽之外，不挡同步写者。
  串行后单条实测 30~100s，尾巴一般在 15:35 前；极端单条 984s 时会推到 15:46 前后，
  与 `40 15` 情报盘后、`45 15` 候选跟踪重叠。
- **闸门覆盖面（2026-09 已补齐五类入口）**：许可本体在 `src/shared/screen_capacity.py`，
  下列入口全部占同一道闸门，`LOCI_SCREEN_JOB_CONCURRENCY` 就是全进程的真实上界：

  | 入口 | 位置 | 排队策略 |
  |---|---|---|
  | Job 执行器 | `ops/application/jobs/market_gate.py:477` | 等 `LOCI_SCREEN_QUEUE_WAIT_SEC` |
  | HTTP 异步选股 | `strategy/application/screen_run.py:191` | 等满，可取消（点「停止」即出队） |
  | HTTP 同步选股 | `strategy/api/router.py:150` | `wait_sec=0`，满则 429 |
  | `/api/screen/today` | `strategy/api/screen_today_router.py:105` | `wait_sec=0`，满则 429 |
  | AI 助手选股工具 | `ai/application/system_toolbus_strategy.py:67` | `wait_sec=0`，不堵模型回合 |

  两档策略的分界是**调用方能不能等**：后台任务与异步执行体有进度条可以排队，
  同步 HTTP 与模型回合不能——让它们排 20 分钟只会换来一个超时的连接。
- 建议（按性价比排序，均不改战法声明）：① 把 `LOCI_MARKET_GATE_SCREEN_WAIT_SEC` 提到 900s，
  零改动把容忍窗从 26 分钟推到 34 分钟；② 日终重刷维持 15:10，**不要提前**——
  提前到 15:05 换来的 5 分钟余量，代价是可能拿到未定稿的收盘 spot。
- `hot_rebuild`（16:10）/ `data_quality`（16:30）不在 `MARKET_HEAVY_KINDS` 里，不受行情闸门管；
  选股读槽租约是 45 分钟（15:30 起最晚到 16:15），极端拖堂时热库重建会在选股仍在读时重灌热库。

### 全局助手调度

全局助手可管理 `sync`、`screen`、`backtest`、`compare`、`optimize`、`prune`、`outcome` 任务，并在创建、更新、删除后请求组合根重载调度器。它不能创建、修改或触发 `skill`、`notify` 等可扩展任务，避免经助手间接取得 CLI、文件或外部 MCP 执行面。助手立即触发任务时必须传入当前工作台的 `JobContext(market_db, palace_db)`。

## 包结构（jobs）
`application/jobs/`：`context`（JobContext/JobError）· 各 kind 执行器（含 `outcome`）· `registry`（EXECUTORS + `run_job`）。对外仍从 `src.ops` / `src.ops.application.jobs` 导入。

## 存储层拆分（infrastructure）
对外仍从 `store` 入口导入：`OpsStore` / `OpsError` / `JOB_KINDS` / `MANAGED_SYNC_*` / `new_id` 等。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_helpers.py` | 常量、`OpsError`、`new_id` / `dumps` / `loads`、**全库时钟 `_now()`**（本地时区 + 偏移 + 微秒 ISO8601，见下「时间戳口径」） |
| `store_schema.py` | DDL、`SCHEMA_VERSION`、迁移清单 |
| `store_jobs.py` | 任务定义(cron / config / 托管确保)与 meta 设置 mixin |
| `store_runs.py` | 执行历史 mixin:占槽 / 回收 / 收尾 / 取消。与 `store_jobs` 拆开——前者是**配置**,后者是**状态机**,读的人和改的原因都不一样;崩溃回收(按 `owner_pid` 探活,时间窗兜底)也集中在这里——**探活实现已收拢到 `src.shared.process_alive.pid_alive`**,`market` 的跨进程写锁要问同一个问题(崩溃留下的锁文件该不该接管),两边各写一份就会让「多久算挂了」在仓里出现两套答案;`ops/infrastructure/process_alive.py` 现在只是保留 `pid_is_alive` 这个名字的转发；时间戳写入走 `_now()`，回收窗与排序走 `RUN_STALE_SQL` / `RUN_ORDER_SQL`（`julianday()` 折算，兼容历史 UTC 行） |
| `store_providers.py` | LLM 供应商 mixin |
| `model_catalog.py` | `models_json` 规范化 / 发现合并 / 启用 id 派生 |
| `store_strategy.py` | 战法档案与策略版本 mixin |
| `store_alerts.py` | 价格提醒规则 / 命中 mixin；`insert_alert_hit` 返回空 dict **只**表示「同一 `(rule_id, trigger_bucket)` 已命中过」的幂等跳过，外键违例 / NOT NULL / schema 漂移一律抛 `OpsError` 或原异常（原先 `except Exception: return {}` 会把没建父规则的整批写入压成「行行成功、一行没落」） |
| `store_paper.py` | 纸面舱 / 持仓 / 成交 / 拒单 / 预案 / monitor mixin；`apply_paper_fill` 把成交流水与仓位快照写在**同一事务**（分两次写会留下「有成交、仓位没动」的半条记录，后续加减仓都在错的基数上算） |
| `store_ai_decisions.py` | AI 决策留痕 mixin（`ai_decisions`）：prompt / 报价数值 / 原始回复 / 解析结果；可整表清空 |
| `store_watch.py` | 龙头角色留痕（只追加）与角色变化推导 mixin |
| `store.py` | `OpsStore` 组合 + 连接/迁移 + re-export；旧库缺列时先迁移再补索引（避免 `idempotency_key` 等 INDEX 抢跑导致桌面 90s 起不来） |

### 时间戳口径：本地时区（2026-08-26 改）

ops.db 所有写入统一走 `store_helpers._now()`——**本地时区 + 偏移 + 微秒 ISO8601**
（`2026-08-26T15:30:00.123456+08:00`），与账本 `ledger/store_types._now()` 同口径
（见 `src/ledger/README.md` 里 `ai_judgments.py` 那一行）。`OpsStore._now()` 只是它的转发。

- **改之前**：`jobs` / `job_runs` / `llm_providers` / `strategy_versions` / `meta` 走 SQLite
  `datetime('now')`——UTC、秒级、空格分隔；而同库的 `paper_*` / `alert_*` /
  `leader_role_snapshots` 早已是本地时间。一个库两套时钟，运维页又不做任何时区换算
  （`JobRecentRunsPanel.vue` 只把 `T` 换成空格再切 19 位），于是 15:30 跑的任务显示 07:30。
- **旧数据不迁移**：库里的 UTC 行原样留着（生产 `job_runs` 706 行、`jobs` 14 行全是旧格式）。
  **不要**写 `UPDATE ... WHERE status='running'` 这类历史重写脚本——本仓已经因此错杀过一个
  正在跑的任务。旧行在页面上仍显示 UTC，可接受；排序与回收由下面两条兜住。
- **读取侧一律折算再比**：`store_runs.py` 的 `RUN_STALE_SQL` / `RUN_ORDER_SQL` 用 `julianday()`
  把两种写法放到同一条 UTC 时间轴（无偏移的旧值按 UTC 解释，正是它当初的含义）。
  **禁止**退回字符串比较：`'T' > ' '`，同日的新行会无条件排到旧行前面；回收窗那边更严重——
  写入本地而基准仍是 UTC，回收窗凭空多 8 小时（真死的任务 8 小时没人收尸）；基准换成本地而行
  是 UTC，则刚启动的任务当场被判死。两个方向都有用例：`tests/ops/test_run_timestamps_local_tz.py`。
- **脏时间戳**：`julianday()` 解析不了就返回 NULL，时间窗谓词整体为 NULL → 该行不被回收
  （与改动前一致，宁可漏收也不能批量错杀）。兜底在 `_reclaim_legacy_no_pid_runs`：
  `owner_pid = 0` 且时间戳不可解析的行照收，槽位不会永久卡在假「正在执行」。
- **下游**：`eod_catchup.last_run_covers_slot` 对带偏移的新值走精确分支；无偏移的旧值仍保留
  「UTC / 上海本地任一覆盖即视为已跑」的双解释兜底（旧行还在，去掉会导致每次启动重复补跑）。
  `wecom_push_mark.shanghai_date_of_timestamp` 与 `market/sentinel_evidence` 读 `jobs.last_run_at`
  时都已经是「带时区就按时区、否则按 UTC」，无需改动。

## 写鉴权 / Agent Bearer（运维部署）
- 组合根写门闩见 `src.app.main` / `src.app.write_token_policy`；ops HTTP 写口经同一 `write_dependency`。
- **本地桌面**默认可写，无需 `PALACE_WRITE_TOKEN`。
- **生产 / 对网**：人类优先登录会话；可选配置 `PALACE_WRITE_TOKEN`（≥32 字符高熵）供无头 Agent。轮换流程：生成新串 → 更新部署环境变量 → 写 `PALACE_WRITE_TOKEN_ISSUED_AT=YYYY-MM-DD` → 滚动重启 → 作废旧串。勿写入分享包或 git。不收紧 AI ExecutionGrant。

## 给 Agent 的用法
- 任务：`from src.ops import run_job, OpsStore, OpsError, new_id`
- 技能：`discover_skills` / `install_skill` / `install_skill_dir` / `sync_skills_from_templates`；根目录每次运行时解析
- 模板战法：`templates/skills/<slug>/` → `POST /api/skills/sync-templates`（或 `sync_skills_from_templates`）批量装到 `data/skills`
- Screen Skill 文件存储：`src.ops.application.screen.*`，**对外经 `src.ops` 包根导出**（`save_screen_package` / `list_screen_packages` / `read_screen_archive` 等 11 个符号）；HTTP 契约与公式编排由 `src.strategy.application.screen_skills` 负责，禁止它深引 `application.screen`
- `runtime=formula` 的执行文件是 `formula.tdx`；`runtime=python` 是 `strategy.py` 与可选包内模块；两者共用原子保存和历史归档
- Screen Skill 上传必须走 `/api/screen-skills/import`；`/api/skills` 只接受普通技能包，并对误投/损坏的 screen 包返回受控 422
- Screen Skill 历史只列出非当前 package revision；恢复归档时会将回滚前的 current 包原子归档，避免当前版本和历史版本重复展示
- 新 Job kind：写执行器后注册到 `application/jobs.EXECUTORS`
- 调度 cron 一律按 `Asia/Shanghai` 解析（`validate_cron(..., timezone=...)`）；工作日字段用 `mon-fri`（`normalize_cron_weekdays` 兼容历史 `1-5`）

## README 维护
改 Job 种类、技能约定、ops.db 语义、企微模板或 store 拆分边界时必须更新本文。

## 相关测试
`tests/ops/`（含 `test_job_lifecycle_contract.py`、`test_jobs_api.py`、`test_paper_quant.py`、`test_sync_skill_templates.py`）

## 多租户调度

`ops.db` 随租户分库（`src/shared/tenancy.py`：多租户不是「每张表加一列 user_id」，
而是「换一个 data 根」），但调度器是**进程内单例**。装载时必须遍历活跃租户，
否则子租户的任务永远不触发——而 UI 上还写着「下次触发 15:30」，不报错、不留痕。

### 系统级 vs 用户级

判据只有一条，写在 `application/tenant_jobs.SYSTEM_JOB_KINDS` 上：
**这个 kind 写的是全局共享的 `market.db` / `market_hot.db`，还是租户私有库？**

| 分组 | kind | 跑几份 |
| --- | --- | --- |
| 系统级 | `sync` / `hot_rebuild` / `data_quality` / `prune` / `intraday_capture` | 只在主租户跑一份 |
| 用户级 | `screen` / `strategy_monitor` / `paper_eod` / `alert_scan` / `intel_fetch` / `intel_brief` / `outcome` / `skill*` / `notify` / 回测类 | 按租户各跑各的 |

系统级任务按租户各跑一份的后果是确定的两条：(1) N 个线程同时写同一个 SQLite
文件，撞写锁，`busy_timeout` 耗尽后整批同步失败，谁都拿不到数据；(2) N 份并发
请求打同一个上游行情源，直接被限频封成 403，连主租户原本能跑通的那一份也一起挂。
行情是**公共事实**，一份就够；选股/盯盘/提醒/情报是**私人事实**，必须各跑各的。

> **`prune` 是唯一的例外，别当笔误改掉。** 它删的既有全局产物（盘中留存带目录，
> ADR-014），也有**租户私有**的 `job_runs` / `leader_roles`。归到系统级是取
> 「不重复删全局目录」这一头，代价是子租户的 `job_runs` 没人清。当前每租户任务量小、
> `keep_per_job` 默认 200，量级可控；等子租户任务多起来，正确做法是把 prune 拆成
> system 段（留存带目录）与 tenant 段（job_runs / leader_roles），而不是简单地
> 把它挪出 `SYSTEM_JOB_KINDS`。

装载层（`tenant_job_rows`）和执行层（`run_tenant_job`）**各挡一次**：库里存在一条
历史遗留的子租户 `sync` 也触发不了，不指望库是干净的。

### 装载规则

- 主租户装**全部**任务，APScheduler job id 保持**裸 job id 不变**——`/api/jobs/schedule`
  与行情同步设置页都拿裸 id 去 `upcoming()` 里查实况，加前缀会让「下次触发」集体变空。
- 其他活跃租户只装**非系统级**任务，job id 形如 `t:<tenant>:<job_id>`。分库之后两个
  租户的主键完全可能重合，不加前缀会被 APScheduler 按 id 去重顶掉一个——表现为
  「B 注册之后 A 的选股就不跑了」，同样没有任何报错。
- 名单 = **identity.db 里 `status='active'` 的 `tenant_id`** ∩ **磁盘上已存在的租户目录**。
  取交集是因为：刚注册还没进过任何页面的用户没有 ops.db，为他建库只为跑一轮空选股，
  纯属给每个新注册用户白送一堆 `job_runs` 噪声。
- **身份库不可用**（文件不存在 / 打不开 / 读不动）时降级为**只跑主租户**，并打 WARNING。
  绝不凭磁盘目录猜名单：谁被停用、谁被删号，只有 identity.db 知道。盘点是只读路径，
  不会顺手把空的 identity.db 建出来。

### 闸门与上限

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `LOCI_TENANT_JOB_CONCURRENCY` | `2` | 租户线程池（APScheduler `tenant` executor）宽度 = 同时执行的**租户级**任务数。`max_instances=1` 只防同一条任务自己叠罗汉，拦不住 50 个租户在同一分钟各跑各的选股 |
| `LOCI_SYSTEM_JOB_CONCURRENCY` | `4` | 系统线程池（`default` executor）宽度。只跑主租户的任务，与租户池**物理隔离** |
| `LOCI_MAX_SCHEDULED_TENANTS` | `50` | 装载的租户总数上限（含主租户）。超过就只装前 N 个并打 WARNING，而不是把几百个 job 硬塞进 web 进程 |
| `LOCI_ENSURE_TENANT_JOBS` | `1` | 启动时是否为子租户确保用户级托管任务；设 `0` 关闭 |

并发上限由**池宽**保证，不再阻塞等信号量。闸门在每次 `reload()` 时按当前环境变量
重建（只会更严不会更松，池宽是进程启动时定的）；拿不到槽位**立刻**落一条 `skipped`
留痕后返回，绝不像旧实现那样 `acquire(timeout=300)` 干等 5 分钟——池子一共才几条
线程，堵在那里就是拿调度线程去等另一个调度线程。详见下方「并发与配额」。

`reload()` 的返回值新增 `tenants` 字段（`count` / `ids` / `jobs` / `total_active` /
`truncated` / `degraded` / `concurrency` / `system_concurrency` / `executors` /
`max_tenants`），`/api/jobs/schedule` 可直接透出。

### ensure_* 的租户语义

`ensure_all_managed_jobs` 拆成两个入口，**别名保留**（`src/app/main.py` 仍在调它，签名不变）：

- `ensure_system_jobs(store)` —— 行情同步 / 热库重建 / 库体检 / 运维清理 / 盘中留存。
  只在**主租户**确保。
- `ensure_tenant_jobs(store)` —— 候选 T+N 跟踪 / 盘后选股 / 情报采集 / 价格提醒扫描
  + 三条退役清理（龙池 / 龙回头 / 二波）。在**当前租户**确保：它们本来就读写
  `OpsStore(None)`（= 当前租户的库），调用方只要包在 `tenant_scope(uid)` 里就是对的。
- `ensure_all_managed_jobs(store)` = 两组都做。主租户上下文里调用，行为与拆分前一致。

子租户的用户级任务由 `JobScheduler.start()` 在进程启动时确保一次（`reload()` 不重复做——
确保会加载整个战法目录，而 reload 每次任务增删都会被调用）。

### 相关测试

`tests/ops/test_tenant_jobs.py`：系统级 kind 不下放子租户、两租户 job id 不撞（用例里
人为把两边主键改成同一个值）、超限截断并告警、身份库缺失降级、`run_tenant_job` 确实
把 `current_tenant()` 切到目标租户（假执行器断言）。

## 告警通道（多通道推送）

企微一家独大的时代结束了：出站变成**可插拔通道注册表**，六个通道一视同仁——
`wecom` / `dingtalk` / `feishu` / `webhook` / `email` / `inbox`（站内信）。

### 分层

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 域 | `domain/notify.py` | `NotifyMessage`（frozen）+ `NotifyChannel` Protocol。**不 import httpx/sqlite3/smtplib**（`domain-no-web-framework` 契约） |
| 基础设施 | `infrastructure/notify_channels.py` | 六个通道实现 + 注册表 `_CHANNELS`。出站 IO 收在 `_http_post_json` / `_smtp_send` 两个私有桩点 |
| 应用 | `application/notify_registry.py` | 配置读写、并行投递、限流。`notify.py` 再导一次，保持「推送的东西从 `application.notify` 拿」的心智 |
| 应用 | `application/notify_subscribers.py` | 社区订阅信号 → 通道分发 |
| HTTP | `api/notifications.py` | `GET /api/ops/notify/channels`、`PUT|POST /api/ops/notify/channels/{name}[/test]` |

加一个通道 = 在 `_CHANNELS` 加一行。**不要**再去别处补 if/elif —— 旧的
`notify_dispatch` 就是那样长成两处需要同步的分支的。

### 硬约束

- **一个通道挂不能带死任务。** `_BaseChannel.send` 吞掉一切异常返回 `False`，
  只记 WARNING。推送是任务的副产品，不是任务本身；`jobs/notify` 那边已经因为
  一条推送异常把整次运行卡在 `running` 上收不了尾过一回。
- **超时统一 8s**，六个通道并行发（`ThreadPoolExecutor`）。串行最坏 48s，会顶到
  调度器心跳窗。
- **企微不重写。** `WecomChannel` 转调 `application.notify.send_wecom_text`，
  payload（`msgtype=text`）、2000 字截断、出站队列串行 + 失败重试 3 次的语义原样
  保留。企微只有一份实现。
- **绝不回显 secret。** `list_channels` / HTTP 只回末 6 位（`mask_secret`）。
  webhook URL 的 key 段就是凭据本身；`headers` 的**值**（常放 `Authorization`）
  也一起打码。库里存的仍是真值——打码只发生在回显路径上。
- **限流按 (租户, 通道, 消息指纹)**，窗口 60s。指纹取 title/level/body，
  **不取 link**：任务重试生成的链接带不同 `run_id`，算进去等于限流白做，而要防的
  正是任务重试风暴。手动「测试」绕过限流（连点两次必须两次都真的发）。

### 配置与兼容

配置落 ops.db `meta`，键 `notify:<name>`。这些键**不在** `META_ALLOWLIST` 里，
分享包默认不外发（fail-closed）。

**旧的 `wecom_webhook` 键仍然生效**：读不到 `notify:wecom` 时回退读旧键
（`notify_registry.get_channel_config`）。这条回退**不许删**——只配过旧键的部署
删掉就静音了，而「告警不响」本身没有告警。回归测试：
`test_legacy_wecom_webhook_key_still_works` / `..._still_reaches_dispatch_text`。

邮件走 stdlib `smtplib`，读 identity 那套 `LOCI_SMTP_*` 环境变量，但**不复用**
它的 `Mailer`：`Mailer` 没从 `src.identity` 包根导出，深引 infrastructure 会撞
`protect-identity-infra` 契约。收件人在通道配置里，SMTP 密码只在环境变量里，不进
ops.db。站内信经 `from src.identity import IdentityStore` 包根导入。

### 接入点

**只有一处**：`notify_dispatch.dispatch_text`。任务完成/失败
（`jobs/notify._maybe_push_wecom`）与价格提醒命中（`alert_rules.scan_alert_rules`）
本来就都走它，所以那两处调用点一行没改就同时拿到了钉钉/飞书/邮件/站内信。

`dispatch_text` 有两条腿，刻意分开：企微/Bark 走**旧腿**（正文 `【标题】\n正文`
的拼法、`prepend_title_to_wecom` 开关一字不动）；其余五个走**新腿**
（`_EXTRA_CHANNELS`，注册表并行发）。企微**不走新腿**——两条腿最终都调
`send_wecom_text`，都走会重复出声。`webhook_override` 或显式 `channel_ids` 表示
调用方点名了发哪儿，此时不外扩。

### 社区订阅信号

`application/notify_subscribers.py` 补上了 community 那条链缺的下半截：
`publish_signals()` 原先写完 `signal_broadcasts` 就收工，谁也不通知，
`CommunityStore.list_subscribers()` 全仓零调用，订阅者只能自己轮询。

`dispatch_subscription_signal(ops_store, community_store, publish_id, ...)` 按订阅者的
`notify_channels` 偏好分桶：`inapp` → 站内信、`email` → 邮件、`desktop` → **本仓没有
传输实现，照实记进 `skipped`，不假装发过**。收件人由本次调用决定，所以走
`dispatch_report(config_overrides=...)`，不落库。

放在 ops 而不是 community：community 不许 import identity/ops（两条 protect 契约 +
`community/api/deps.py` 里刻意的鸭子类型），而站内信在 identity、注册表在 ops。
`community_store` 参数同样是鸭子类型，只要有 `list_subscribers` / `get_subscription`
两个方法就行，测试塞个假的即可。

### 相关测试

`tests/ops/test_notify_channels.py`（38 例）：注册表内容与查找、钉钉/飞书加签**固定
时间戳对拍**（期望值由官方算法独立算出后钉死，且两家算法不同——飞书拿
`f"{ts}\n{secret}"` 当密钥对空串签，照抄钉钉会一直 401）、未配置不发、单通道失败
不影响其他、`errcode!=0` 算失败、限流去重与窗口过期、secret 不回显、旧键回归、
邮件/站内信、社区订阅分发、三个 HTTP 端点。

用例带 `_no_real_network` autouse 夹具：`urlopen` / `SMTP` / `SMTP_SSL` 全部替换成
记账 + 抛错，**并在 teardown 断言没记到账**。为什么要事后清算而不是当场抛——通道
的契约就是吞掉一切异常返回 `False`，当场抛会被通道自己接住翻译成「发送失败」，
用例照样绿。这不是假想：本文件最初有一处 `with patch(...)` 缩进写歪，断言掉到
mock 作用域外，用例真的打到了 open.feishu.cn，靠对端回 19001 才暴露。

## 通知隔离与限流

这一节讲**三件在多租户下会静默出错的事**：配置串户、告警刷屏、出站挂死。
它们的共同点是坏了不报错——没有 500、没有红灯，只有「A 的告警发进了 B 的群」
「用户把企微机器人静音了」「调度线程再也没醒过来」。

### 1. 通知配置一律按租户解析

`ops/api/settings.py` 给 `build_notification_settings_router` 传的是 **`ops_db=None`**，
不是组合根那个 `PALACE_OPS_DB`。

组合根把这个环境变量读成字符串，一路 `app/main.py` → `app/legacy/quant_router.py`
→ `ops/api/settings.py` → `notifications._ops()` → `OpsStore(ops_db)`。
`shared/paths._tenant_scoped` 里「env 只对主租户生效」的护栏**只在不传参时**起作用；
显式传一个字符串会把它整条绕过。运维一旦填了这个变量，全部租户共用一个 ops.db：
A 改 webhook 会改掉 B 的，A 的告警会发进 B 的群。

`market_sync` / `jobs` / `paper_quant` 三个支路仍然收 `ops_db`——它们的语义是
「这台机器的那一份运维库」（调度器、行情同步都是主租户的系统任务），改动它们
需要单独论证，不在这一轮里顺手做。

回归测试 `tests/ops/test_notify_tenant.py`：**刻意把 `ops_db` 钉进组合入口**
（模拟运维填了变量），再用两个租户各 PUT 一个不同的企微 URL，断言互不可见、
落的是两个不同的文件、被钉进来的那个库一个字节都没被写。
用例自带一个纯 ASGI 的 `X-Loci-Tenant` 中间件（与 `app/tenant_middleware.py` 同构，
**不是** `BaseHTTPMiddleware`——那个会把下游放进另一个任务，ContextVar 的绑定
关系随 Starlette 版本漂）。

> 为什么以前没人发现：`tests/conftest.py` 全程设着 `PALACE_OPS_DB`，
> 于是所有 HTTP 用例都跑在「所有人共用一个库」的配置下，而没有一条用例去看
> 两个租户会不会互相覆盖。守卫不存在时，被守的东西默认就是坏的。

### 2. 两条腿都过限流

`notify_dispatch.dispatch_text` 的旧腿（企微 / Bark）以前**直接 send，从不问限流器**，
只有新腿（`_EXTRA_CHANNELS`，不含企微）过 `_allow`。而 `run_job` 的**失败分支**
（`jobs/registry.py`）也推，失败路径又没有 `wecom_push_mark` 那种按交易日去重：
一个 `*/5 9-14` 的 `alert_scan` 持续失败 = 每 5 分钟一条企微、全天 60+ 条。
**告警刷屏就是告警失效**——用户会把机器人静音，然后真正重要的那条也没人看。

现在两条腿共用同一张 `_recent` 表（`notify_registry.allow_send`），口径
`(租户, 通道, 消息指纹)`、窗口 60s。两条腿共用一个指纹是刻意的：否则会出现
「企微被压住、钉钉又冒出来」的半拉子降噪。

- 全部通道都被压住时，`dispatch_text` 返回 `skipped="rate_limited"`（与
  `quiet_hours` 同构），并在 `suppressed` 里列出通道名。
- `jobs/notify` 把它记成 `push_skipped` 而**不是** `push_error`：降噪是成功，
  记成故障会让下一个人来关限流。这条路径也**不写** `wecom_push_mark`——这次压根
  没发出去，同日重跑仍应尝试。
- `bypass_rate_limit=True` **只给「用户刚点了测试按钮」用**
  （`/api/ops/settings/notify/test`、`/api/ops/notify/channels/{name}/test`）：
  那时用户正盯着屏幕等回声，压住等于骗他「通道坏了」。业务推送一律不许传。

限流闸门放在 **URL 解析之后**：配置本身就坏（没填 webhook）时要报错，
不能被限流盖成「已跳过」。

**已知残留**：60s 窗口挡得住「任务重试风暴」（秒级连发），挡不住「每 5 分钟失败
一次」这种节奏——那需要按 `(job_id, 交易日)` 的失败去重，属于 `jobs` 侧的账，
不在通知层。真要治本，失败推送也该有自己的 `push_mark`。

### 3. 企微 20 条/分钟令牌桶，45009 不重试

官方口径：**每个 webhook key 20 条/分钟**，超限回 `errcode=45009`。

- 令牌桶在 `notify_send_queue`，按 **webhook key** 记账（`RATE_LIMIT_PER_MINUTE`）。
  这是全仓唯一与租户无关、和官方口径对齐的位置：被限的对象是 key，它既不属于
  某个租户，也不属于某条业务消息。超限的消息**排队等**，不丢。
  桶用「一次算清等待时长、只睡一次」的写法，不是 `while not allowed: sleep()`——
  后者在 `time.sleep` 被测试换成 no-op 时会变成死循环。
- `notify._post` 收到 `WECOM_NON_RETRYABLE_ERRCODES`（45009 超频、93000 webhook
  非法、93004 已停用、40001 凭证非法）时抛 `NotifyNotRetryable`，它同时是
  `NotifyError`（调用点一行不用改）和 `notify_send_queue.NonRetryableSendError`
  （队列见到就 break）。此前 45009 被当成普通失败又打 2 次，是在超频的伤口上撒盐。
  **表外的错误码保持可重试**：把「网络抖了一下」误判成永久失败等于静音。

为什么标记类放在 `notify_send_queue` 而不是靠错误码字符串猜：`notify` 已经
import 了队列，反向 import 是循环依赖；判定权留在懂协议的那一层，队列只认标记。

### 4. `run_serialized` 有超时（真实挂死路径）

`item.done.wait()` 以前**没有超时**。工人线程因不可捕获错误退出时，`finally` 会把
`_worker_started` 置回 False（下次调用能重启工人），**但已经在队列里等的 item
永远等不到 `done.set()`**——调用线程（很可能是调度线程）就永久阻塞在那里。

现在等待上限 `SEND_WAIT_TIMEOUT_SEC = 90s`，超时抛 `SendQueueTimeout` 并记 WARNING，
调用方按「这条没发出去」处理。同时工人取到**已过期**的 item 时直接丢弃并记账：
调用方早就不等了，几分钟后再把那条告警发出去只会让人更困惑。

代价说清楚：持续 >20 条/分钟的洪峰下，排在 90s 之后的消息会被丢。这是刻意的——
挂死一条调度线程的代价比丢一条重复告警大得多。

### 5. 限流指纹不含 tags：社区信号自己按业务键去重

`domain/notify.NotifyMessage.fingerprint()` = `title\x1flevel\x1fbody`，
**不含 link 和 tags**。这对「任务重试风暴」是对的（重试的 `run_id` 会变，算进去
等于限流白做），但 `publish_id` 恰恰只活在 tags 里：同一作者的两条不同策略，
若模板化正文字节级相同，60s 内第二条会被静默吃掉。

修法选的是**不动 `fingerprint()`**（动它会连带改掉所有通道的既有限流行为），
改在 `notify_subscribers` 层按业务真正的唯一键去重：
`_claim_signal(publish_id, trade_date)`，窗口 24h，键含租户；然后
`dispatch_report(bypass_rate_limit=True)` 把通用限流让开。
两套口径不叠加，「谁压住了这条消息」一目了然。
`dispatch_subscription_signal(..., trade_date=...)`：拿得到交易日就一定要传，
否则同一条策略换一天再发会被当成重复压掉。

### 6. 通道线程池必须带租户上下文

`notify_registry.dispatch_report` 的并行投递走
`shared.tenancy.submit_with_tenant`，**不是**裸 `pool.submit`。
ContextVar 不跨 `ThreadPoolExecutor` 边界，裸 submit 会让通道线程里的
`current_tenant()` 静默落回主租户。今天六个通道恰好都不读租户上下文，所以
「没泄漏」纯属巧合——只要有人给 `inbox` 通道加一句「按当前租户解析 identity.db」，
巧合当场变成串户，而且不报错。回归测试
`test_channels_run_with_the_caller_tenant_bound` 把这个不变量钉住。

### 7. `dispatch_subscription_signal` 怎么接线（community 不得 import ops）

它至今**零生产调用方**：`community.publish_signals()` 写完 `signal_broadcasts`
就收工，谁也不通知。接线不能靠 community 直接 import ops——`.importlinter` 的
protect 契约拦着，而且方向也反了（community 是被依赖方）。

正确做法是**组合根注入回调**：

1. `src/community` 侧给发布流程留一个可选的通知钩子，签名只用内置类型，
   例如 `on_published(publish_id: str, *, title: str, body: str, trade_date: str)`；
   community 自己不知道钩子背后是谁，默认是 `None`（不通知，行为与今天一致）。
2. `src/app/main.py`（组合根）在装配 community router 时把钩子填上，闭包里调
   `src.ops.dispatch_subscription_signal(ops_store, community_store, publish_id, ...)`。
   组合根本来就同时认识两个上下文，这条边是合法的。
3. 钩子必须**吞异常**（推送失败不能让发布失败），并且跑在
   `spawn_tenant_thread` / `submit_with_tenant` 里——发布流程不该等 SMTP。

改 `src/community/**` 不在本轮范围内，所以这里只留接法；`ops` 侧该给的
（去重口径、`config_overrides`、鸭子类型的 `community_store`）都已经就位。

### 相关测试

| 文件 | 守什么 |
| --- | --- |
| `tests/ops/test_notify_tenant.py` | 两个租户的 webhook 互不可见、各写各的库、限流不跨租户顶掉、旧键仍按租户解析 |
| `tests/ops/test_notify_channels.py` | 企微旧腿过限流、测试按钮绕过限流、两条腿共用指纹、45009 不重试且普通失败仍重试 3 次、令牌桶 20/分钟且按 key、`run_serialized` 超时不挂死、过期 item 被丢弃、通道线程带租户 |
| `tests/ops/test_notify_send_queue.py` | 串行、重试、失败后继续下一条（既有契约，不许被限流改坏） |

`tests/ops/conftest.py` 有一条 autouse 夹具清三张进程级表（限流指纹、令牌桶、
信号去重）。不清就会出现「单跑绿、全量跑红」——加了限流之后受影响的用例比以前
多得多，所以放在公共 conftest 里，而不是每个文件各写一遍。

外部 HTTP 一律 mock，守卫用**记账 + teardown 断言**：通道契约是吞掉一切异常返回
`False`，在 `urlopen` 里当场抛 `AssertionError` 会被通道自己接住翻译成「发送失败」，
用例照样绿。上一轮真的抓到过一个打 `open.feishu.cn` 的用例。

## 并发与配额

定时任务是「按时间自动占用整台机器」的权利。多租户之后它有三个失控口子：抢线程、
抢全局行情写锁、无限建任务。这一节把三者的挡法一次讲清。

### 两个 executor 池

`JobScheduler` 用 APScheduler 3.x **原生的多 executor**（不是自己写调度器，也不是
引入 Celery）：

| 池 | 环境变量 | 默认 | 装什么 |
| --- | --- | --- | --- |
| `default`（系统池） | `LOCI_SYSTEM_JOB_CONCURRENCY` | `4` | **主租户**的全部任务：行情同步 / 热库重建 / 库体检 / 运维清理 / 盘中留存 + 主租户自己的用户级任务 |
| `tenant`（租户池） | `LOCI_TENANT_JOB_CONCURRENCY` | `2` | **所有子租户**的任务：选股 / 盯盘 / 情报 / 提醒 / 候选跟踪 |

`reload()` 装载时按 `executor=SYSTEM_EXECUTOR if primary else TENANT_EXECUTOR` 分流。

**为什么必须拆池。** 此前从未覆盖过 APScheduler 的默认配置，也就是全仓共用一个
`ThreadPoolExecutor(max_workers=10)`；而 `_run_tenant` 还用 `gate.acquire(timeout=300)`
阻塞等信号量。50 个租户 15:30 同时到期时，10 条线程全被租户任务堵住 5 分钟，
**行情同步根本排不上队**——代码注释自己都写着「全被堵住等于整个调度器停摆」，
然后紧接着就是那句 300 秒阻塞等待。拆池之后：池宽就是并发上限，租户任务再多也只能
占满自己那一格。`ThreadPoolExecutor` 队列无界，排队不丢任务；陈旧的那些由
`max_instances=1` + `misfire_grace_time`（1 小时）收口。

**拿不到槽位怎么办。** 信号量还在，但改成 `acquire(blocking=False)`：拿不到就经
`record_tenant_job_skipped` 落一条 `skipped` 记录后立刻返回。直接 `return` 会让用户
在「执行历史」里看到那天**什么都没发生**，既不像成功也不像失败；阻塞则是拿调度线程
去等另一个调度线程。

### `job_slots`：自建任务条数配额

`application/job_quota.py`，形状与 `src/ai/application/quota.py` 一致（正数是硬顶、
负数不限、**0 表示「用系统默认」而不是「一条都不给」**）。额度来自 identity
`user_quotas.job_slots`，默认 5。

- **托管任务不占额度。** 判据：任务名在 `managed_job_names()` 里（各 `ensure_*` 模块的
  `MANAGED_*` 常量现取，不抄第二份），**或**以 `screen:` 开头（战法目录会增减，只能
  按前缀判）。子租户开箱就有 7~8 条托管任务，算进额度的话新用户一登录就超额，
  连一条自己的任务都建不了。
- **闸门只放 API 层**（`api/jobs.py` 的 `create_job`，超额 429）。**绝不能下沉到**
  `OpsStore.create_job` / `ensure_job`：托管任务的确保路径也走这两个方法，而
  `ensure_managed_jobs._ensure_step` 对异常只打一行 warning——闸门放存储层会让启动期的
  托管确保在超额租户上**静默失败**，用户的选股任务就这么无声消失了。
- **身份库不可用一律降级**为默认值（文件不存在时连 open 都不做，只读路径不许顺手
建出空的 identity.db）。配额是治理手段，不是业务前提，读不到额度不能把任务 CRUD 卡死。
- `GET /api/jobs/quota` 透出 `{used, limit, unlimited, managed}`；`managed` 必须报出来，
  否则用户看到「上限 5」却在列表里数出 12 条，只会以为额度算错了。

### 系统级 kind 的三道挡板

`sync` / `hot_rebuild` / `data_quality` / `prune` / `intraday_capture` 写的是全局共享的
`market.db` / `market_hot.db`，只该由主租户跑一份（判据见 `SYSTEM_JOB_KINDS`）。三道挡板
各挡各的路，缺一条就漏一条：

| # | 位置 | 挡的是 |
| --- | --- | --- |
| 1 | 装载 `tenant_job_rows` | 子租户库里的历史遗留系统级任务不进调度计划 |
| 2 | 执行 `run_tenant_job` | 绕过装载层直接触发的定时执行 |
| 3 | HTTP `guard_system_job_kind`（create / update / trigger，403） | **手动触发**——`POST /api/jobs/{id}/run` 完全绕开前两道 |

第 3 道是补上的安全缺陷：`JobCreate.kind` 的 Literal 里本来就有 `sync` 与 `prune`，而
`trigger_job` 没有任何守卫，于是**任何普通成员点一下就能跑 `execute_sync`**，独占全局
`market_write_lock` 最长 45 分钟（`MARKET_SYNC_STUCK_SEC`），期间所有人的选股一起排队，
上游还可能被打成限频 403。主租户（= 管理员）行为一个字不变。

同一层还有 **cron 频率下限**：非主租户不得建快于 5 分钟一次的 cron（422）。判据不自己
解析 cron 字段，而是用 `CronTrigger` 算接下来两次触发的间隔（`cron_interval_seconds`），
`< MIN_TENANT_CRON_INTERVAL_SECONDS`（300s）就拒——`* * * * *` 语法完全合法，一条就够
一个人把租户池长期占满。

### 用户任务不碰行情写锁

行情是**全局共享事实**，写它的只有主租户的系统级同步任务；子租户只该读。
`jobs/screen.py` 里按 `is_primary_tenant()` 分流：

- **盘中选今天走 `screen_live`，主/子租户都不写库。** 自己拉 `spot_batch` 叠面板；
  历史只读热库，不镜像、不占行情闸门。拉不到实时就失败，不拿昨日本地日 K 凑数。
- **子租户盘后恒 `refresh_spot=False`**。原链路是 `execute_screen` → `ensure_today_quotes_
  for_screen` → `apply_today_spot` → 全局 `market_write_lock`，而 `refresh_spot` 默认 True：
  50 个租户 15:30 一起抢同一把写锁，谁都跑不完，连主租户的日终重刷也被拖住。
- 当日行情没就绪时落 **`skipped`**（`JobSkipped`，result 里写明「等主账号的行情同步完成」），
  而不是自己去抢锁、也不是刷一条红。就绪判定走 `ensure_today_quotes_for_screen(store, [])`：
  不传 code 就只度量覆盖率、不会调 `apply_today_spot`。
- **子租户不做 `mirror_recent_to_hot`**。镜像是写全局 `market_hot.db`，属于 sync 的职责
  （`jobs/sync.py` 每轮结束时已经做了）；原来每个战法无条件镜像一次、失败还被吞掉。

`jobs/market_gate.py` 的 `_slot_label` 也带上了租户前缀。两个租户的
`screen:qianlong-close-v3` 同名同姓，不加前缀的话 `_READER_SINCE.setdefault` 只记住第一个
进来的时刻，租约一到 `_evict_expired_readers` 就把整个 label 连计数一起 pop 掉，**误杀
刚开跑几秒的后来者**。主租户标签保持原样，日志口径不变。

### cron 错峰

`application/job_stagger.py`：`crc32(tenant_id) % span` 得到分钟偏移，确定性、无状态、可测。
**主租户恒为 0**（存量单机用户的 15:30 一分钟都不许动）。

| 托管任务 | 基准 | 错峰后 |
| --- | --- | --- |
| `screen:<slug>` 盘后选股 | 15:30 | 15:30~15:44 |
| 情报·盘后 | 15:40 | 15:40~15:54 |
| 候选 T+N 跟踪 | 15:45 | 15:45~15:59 |

情报·开盘（9:26）不错峰——往后挪会挪进交易时段；情报·盘中（`*/15`）是区间任务，
本来就摊开了，`staggered_cron` 对非纯数字的分钟字段原样返回。

错峰**只用在首次创建**：托管合并语义是 `{**DEFAULT, **prev}`，只补缺失键，不覆盖用户
改过的 cron。战法显式声明 `screen_schedule` 时每次都会重算 cron，但散列是确定性的，
同一个租户永远落在同一分钟，UI 上的「下次触发」不会每次重启就换一个。

### 为什么不迁 APScheduler 4.x

`requirements.txt` / `deploy/requirements-server.txt` 钉的是 `apscheduler>=3.11,<4`。

- 4.x 至今只有 **4.0.0a6（alpha，16 个月没出 beta）**，官方文档明写 do NOT use in
  production。
- 4.x 把 API 整个重写了（scheduler / executors / `add_job` 签名全变），迁过去等于把本节
  描述的多池方案再写一遍，换来的能力我们一个都不需要（异步调度、外部数据存储、多进程）。
- **上界不是洁癖**：没有 `<4`，4.0 stable 发布当天 `pip install -r requirements.txt` 就会
  解析到 4.x，本仓在 `from apscheduler.schedulers.background import BackgroundScheduler`
  这一行直接 ImportError——服务器起不来，而且是「什么都没改」的那天起不来。

多 executor 是 3.x 就有的能力：**该用开源现成能力的地方用它，而不是自己写一个信号量
调度器**——这次的改动正是把自己写的那个 300 秒阻塞闸门换成 APScheduler 原生的池隔离。

### 相关测试

- `tests/ops/test_job_quota.py`：托管任务不占额度、第 6 条自建被拒、管理员不限、
  `job_slots=0` 是「用默认」不是「零条」、身份库缺失/读坏都降级。
- `tests/ops/test_tenant_jobs.py`：子租户建/改/跑系统级 kind 一律 403（主租户不受影响）、
  cron 频率下限、两个池各自装对任务且池宽独立、槽位满时落 skipped 且不阻塞、
  错峰确定性且主租户不变、托管任务只在首次创建时错峰。

## 保留期与垃圾回收

2026-08 审计结论：全仓 **40 类持续增长的数据里只有 5 类真的有人清**。三个最严重的
盲区都已在本轮补上：

1. `prune` 在 `tenant_jobs.SYSTEM_JOB_KINDS` 里 → **子租户的 `ops.db` 一条都不清**
   （`job_runs` 粗算 **580 MB/年/人**）。→ 拆出租户段 `prune_tenant`。
2. AI 助手八张表**全部无清理**，`ai_agent_events` 是重灾区
   （`StreamEventBuffer` 每 120 字符 flush 一次，工具密集的一次 run = 100-500 行 /
   50 KB-1 MB，活跃用户 **1-20 MB/日**）。→ `src/ai/application/retention.py`。
3. `IdentityStore.purge_expired()` **全仓零调用点**（死代码）；community.db 连清理
   函数都没写。→ 都挂进系统段 `prune`，社区侧新增
   `src/community/application/retention.py`。

### 两段 prune：谁清什么

| kind | 归属 | 删什么 | 挂在哪 | cron |
|---|---|---|---|---|
| `prune` | 主租户一份 | `data/intraday/` 目录 + `identity.db` + `community.db`（外加主租户 `job_runs` / `leader_role_snapshots` 的兜底，见下） | `ensure_system_jobs` → `ensure_managed_prune_job` | `30 2 * * mon-fri` |
| `prune_tenant` | **每租户各跑** | 当前租户 `ops.db` 的全部只追加表 + `skill_runs/` + `research_runs/` | `ensure_tenant_jobs` → `ensure_prune_tenant_job` | 主租户 `30 2`；子租户 `crc32(tenant)%60` 散到 `02:30-03:29` |

`prune_tenant` **不进 `SYSTEM_JOB_KINDS`** —— 默认就是租户级，
`JobScheduler.start()` 已经会为每个活跃子租户跑一遍 `ensure_tenant_jobs`，
零额外装载代码。一旦有人把它加进那个集合，子租户立刻回到「一条都不清」。

错峰用 `zlib.crc32` 而不是随机数，是为了**确定性**：同一租户每次 ensure 算出的
时点必须一样，否则每次应用启动都在改用户的 cron。

`prune` 里的 `job_runs` / `leader_role_snapshots` 两段**故意没有搬走**：它们是主租户
库的兜底，即使用户在运维页把租户段那条任务关掉，主租户也不至于回到一条都不清。

### 三类截断的逐表口径

**① 纯时间（15 天）**——只追加、可重建或只用于近期回看的观测流：

| 表 / 目录 | 时间列 | 库 | 段 |
|---|---|---|---|
| `ai_agent_events` ⭐收益最大 | `created_at` | 租户 ops.db | tenant |
| `ai_execution_grants` | `created_at` | 租户 ops.db | tenant |
| `ai_decisions` | `created_at` | 租户 ops.db | tenant |
| `monitor_runs` | `started_at` | 租户 ops.db | tenant |
| `alert_hits` | `trigger_time` | 租户 ops.db | tenant |
| `leader_role_snapshots`（60 → **15**） | `trade_date` | 租户 ops.db | tenant |
| `mcp_quota` | `trade_date` | 租户 ops.db | tenant |
| `skill_runs/SR-*.json` + `.events.jsonl` | 文件 mtime | 磁盘 | tenant |
| `research_runs/RR-*/` | 目录内最新 mtime | 磁盘 | tenant |
| `activity_feed` | `created_at` | community.db | system |
| `leaderboard_snapshots` | `as_of_date` | community.db | system |
| `signal_broadcasts` | `trade_date`（每 `publish_id` **保底最近 1 条**） | community.db | system |
| `sessions` / `oauth_states` / `email_verifications` | 各自 `expires_at` | identity.db | system（`IdentityStore.purge_expired()`） |

**② 纯条数**——`ai_sessions` 保留**最近 500 个会话**（连同 CASCADE 的
`ai_messages` / `ai_agent_runs` / `ai_agent_events`）。**不能按 15 天砍**：对话是
用户资产；而且按时间删 `ai_messages` 会把一个会话**截成半截**，读起来像模型突然
失忆，比整个删掉更糟。截断单位因此是**整个会话**。正在 `running` / `waiting_user`
的会话永不参与截断（删掉会让那一轮当场卡死在 running）。

**③ 时间 + 条数双闸门**——`job_runs` **必须两者都要**。老的
`keep_per_job=200` 是单参数，而各任务 cron 频率差两个数量级：`*/5 9-14` 的价格提醒
一天 48 条，200 条 = **2.8 天**；日更的候选跟踪一天 1 条，200 条 = **10 个月**。
同一个参数给出 2.8 天到 10 个月的保留期，两头都不对。三参数各管一件事：

- `keep_min=5` —— 保底条数，**永不删**（连「上次跑没跑过、报了什么错」都要留得下）
- `keep_max=200` —— 硬上限，超出一律删（挡住高频任务刷爆库）
- `keep_days=15` —— 中间地带的判据

`status='running'` 的行既不参与排名也永不删除（清掉执行中的运行槽会让 `finish_run`
当场报「任务运行不存在」）。

### 明确**不该**砍的四类

| 不砍的 | 为什么 |
|---|---|
| `identity.audit_log` | 合规用途，**180 天**，且必须是被审计者改不动的 |
| `ai_sessions` / `ai_messages` | 用户资产，只做条数截断（见上） |
| `data/intraday/` | **60 天不要动**（ADR-014）：上游取不到历史，删早了永久没有 |
| `community.published_*` / 评论 / 收藏 / 克隆留痕 / 订阅 / 关注 | 用户作品，删一行 = 抹掉一个人的策略或一段讨论 |
| `palace.db` 全部 | 账本 |

另外 `ai_usage_daily` 也不清：日粒度一天一行，且是月度配额判定的输入。

### `julianday()`：时间比较的唯一写法

**绝不能拿字符串比。** `job_runs` 等表新旧两种时间戳并存——历史行是
`datetime('now')` 的 UTC 裸串 `"YYYY-MM-DD HH:MM:SS"`，新行是 `_now()` 的本地带偏移
`"...T...+08:00"`。字符串比会差 8 小时，而且 `'T' > ' '` 让同日的新行无条件排到旧行
前面，排序也一起错。`store_runs.RUN_STALE_SQL` 已为此踩过坑并写了长注释，本轮照抄
那一招，收拢进 `src/shared/sqlite_retention.py`：

- `age_predicate(col)` → `julianday(col) < julianday('now', ?)`
- 脏值让 `julianday()` 返回 NULL → 谓词为 NULL → 该行**不**被删（宁可漏删一条，
  也不能因一次解析失败清空整张表）
- 纯 `YYYY-MM-DD` 的列（`trade_date` / `as_of_date` / `day` / `period`）不受影响，
  走 `date_only=True` 直接串比

### 为此补的索引

`ai_agent_events(created_at)`、`ai_execution_grants(created_at)`（两条在
`ai/infrastructure/assistant_store_schema.py` 的建表 DDL 里）、`ai_decisions(created_at)`、
`monitor_runs(started_at)`、`leader_role_snapshots(trade_date)`（三条在
`store_schema._MIGRATIONS` 尾部）。identity.db 的四条
（`ix_sessions_absolute` / `ix_ev_expiry` / `ix_notifications_created` /
`ix_usage_period`）在 `identity/infrastructure/schema.py`。

缺索引时 15 天截断就是**全表扫**，而清理跑在 02:30 且整段持写锁——慢下来等于把凌晨
的库锁住，比不清理更糟。已有可用、不重复建的：`alert_hits.idx_alert_hits_time`、
`job_runs.idx_runs_job(job_id, started_at DESC)`、`activity_feed.idx_feed_created`、
`audit_log.ix_audit_time`、`oauth_states.ix_oauth_states_expiry`、
`signal_broadcasts.idx_broadcast_date`、`strategy_metrics.idx_metrics_date_score`。

### `storage_mb` 语义（用户说的「垃圾上限」）

`identity.db` 的 `user_quotas.storage_mb`（默认 **2048**，**0 = 用系统默认**，
**负数 = 不限**）是该用户私有目录的**软上限**。

- 口径由 `application/tenant_storage.tenant_storage_usage(tenant_id)` 定义，**分项**
  返回 `palace.db` + `ops.db` + `skills/` + `skill_runs/` + `research_runs/`。
  刻意**不是** `du -s` 整个目录：主租户的私有目录就是 `data/` 本身，里面还躺着
  全局共享的 `market.db` / `market_hot.db`（GB 级），算进去他会永远显示超配额。
  数据库按 `x.db` + `-wal` + `-shm` 三件套统计（WAL 在大批量删除后能比主库还大）。
- `prune_tenant` 先按常规保留期清一轮；**清完仍超限就进入激进模式**：保留期
  除以 `aggressive_factor`（默认 2 = 减半）再清一轮，payload 报 `over_quota: true`
  与 `bytes_before/after`。
- **永远不拒绝写入**。超配额是「这个人的垃圾比别人多」，把他锁在门外（不让存对话、
  不让跑技能）比留点垃圾糟得多，而且用户当场没有可操作的补救手段。
- 取不到配额（桌面单机没有 `identity.db`、服务端偶发读不动）一律**按不限处理**：
  宁可这一晚不进激进模式，也不能凭一次读失败去更狠地删用户数据。

### payload 口径与 VACUUM

`prune_tenant` 的 payload 报 `{table: {deleted, kept, ms}}` **加上**
`bytes_before` / `bytes_after`。两者缺一不可：**删行不会让 SQLite 文件变小**
（只把页标记为可复用），只报「删了 37 万行」会让人以为库瘦了，只报体积又会让人
以为清理没生效。缩文件要显式 `VACUUM`——它重写整个库、需要等量空闲磁盘、期间独占
写锁，**绝不塞进每晚的清理任务**，payload 里固定写 `vacuum: "not_run"`。

### 四个坑（都有仓内先例）

1. **首次开 15 天会一次删几十万行**，WAL 暴涨 + 长时间持写锁。必须分批：
   SQLite 的 `DELETE ... LIMIT` 需要编译选项 `SQLITE_ENABLE_UPDATE_DELETE_LIMIT`，
   **CPython 自带的没开** → 用 `WHERE rowid IN (SELECT rowid ... LIMIT :batch)` 循环，
   每批 5000 行，**每批一次提交**（提交点就是把写锁交还给别人的地方）。
   用 `rowid` 而不是 `id`：`mcp_quota` / `leaderboard_snapshots` 这种复合主键表根本
   没有 `id` 列。
2. 删了文件不会变小（见上）。
3. **单段失败不能带走整轮** —— 照抄 `jobs/prune.py` 对 intraday 的做法：异常只写进
   payload 不抛（统一经 `sqlite_retention.segment`）。一张表被锁住，不该让另外十张
   也不清。
4. 参数集中在 `ensure_prune_tenant_job.DEFAULT_PRUNE_TENANT_CONFIG`，靠
   `{**DEFAULT, **prev}` 自动给存量库补齐新键，**不用写迁移**；用户在运维页调过的
   值永远优先。所有「天数 / 条数」参数配 `0` 一律解释为**关闭该段**而不是「全部
   删光」——0 在配置里最可能是「忘了填」。

### 为什么**不**加 RotatingFileHandler

日志不是问题，别动它。

- `logging_setup.py` 只有 `StreamHandler` → stderr，**本来就不写文件**。
- 服务端由 `docker-compose.yml` 的 `max-size:20m` / `max-file:5` 兜底（**100 MB 硬
  上限**）；桌面由 `loci.py` 手写轮转（4 MiB）兜底。两条路径都已经有界。
- 在这上面加 `RotatingFileHandler`，只会**在挂载卷里再复制一份 stdout 已有的内容**：
  同样的字节存两遍，还多出一个谁都不会去轮转策略对账的文件。

### 相关测试

- `tests/ops/test_prune_tenant.py`：子租户真的被清、三参数双闸门（保底 / 硬上限 /
  时间闸）、新旧时间戳同轴比较、`running` 槽不删、分批删除（数 DELETE 条数）、
  单段失败不带走整轮、`storage_mb` 激进模式且不拒写、cron 错峰确定性、
  `research_runs/` 下非 `RR-*` 的状态存档一个不动。
- `tests/ai/test_retention.py`：`ai_agent_events` 15 天截断且不伤对话、会话按条数
  截断且**不把会话删成半截**、活跃会话不删、`ai_usage_daily` 不动。
- `tests/community/test_retention.py`：三表清理、`signal_broadcasts` 每
  `publish_id` 保底最近 1 条、**用户作品一行不少**。

跑：`.\.venv\Scripts\python.exe -m pytest tests/ops tests/ai tests/community -q`
## 天才交易员入口（2026-09）

`guardian`任务按交易日51个五分钟时点研判；09:25、11:30、15:00仅分析。策略池是参考，模型可自主交易池外沪深北A股。20万元租户独立模拟账户按分记账，保留T+1、股数、资金和费用规则。
入口为`jobs/guardian.py`，配置为`guardian_config.py`；会计规则经ledger公开API提供。历史迁移、页面及报告见[天才交易员](../../docs/guardian.md)，当前安全边界见[执行契约](../../docs/guardian-execution.md)。

决策完整性由`guardian_completion.py`核验，最多一次无工具修复。买卖必须提供`execution`的价格授权与带时区有效期；最终成交价来自核验后的新鲜报价。`guardian_quotes.py`统一主备报价、估值与执行校验。
`guardian_order_repair.py`仅在尚未落账时有限缩量、撤回或修正留仓名单，保留原拒单；不得新增交易、放宽价限或延长有效期。`withdrawn`、错过成交窗口及其他受阻意图不能伪装为主动无动作。
`guardian_outcome.py`区分主动no_action与rejected/partial_execution。研究预算270秒，提交同时检查墙钟和单调耗时小于300秒，并复核取消、配置和owner；仅分析边界保持静默，执行受阻按failed及通知设置处理。
结构化`risk_plans`按动作后的持仓原子安装，null保留、[]撤回；合同绑定数量/开仓批次，每股每轮止损优先且最多一笔，最终报价与T+1仍有效。只有匹配fills消费合同，旧自然语言计划不自动成为合同。
`guardian_delivery.py`及ledger通知存储按通道ID快照目标；按`attempts, slot`升序领取租约，避免旧失败消息阻塞新告警，仅重试未成功目标。补发不重跑研究或成交，外部投递不承诺exactly-once。

常态和收盘最多4只、盘中临时最多8只；`close_keep_codes`由模型选择并覆盖T+1锁定股票。14:50起执行最后有效名单，14:55续跑；缺价或收盘未收敛保留实际成交并明确失败，不补造卖出。名称迁移沿用原任务ID和账户，自主观察池不改变资金。

`ensure_guardian_review_jobs`维护盘前08:50、日复盘15:45、当周最后交易日15:55的报告；失败可补跑，成功报告防重。财务数字由账本和收盘价计算，模型仅解释与提出条件化计划、待验证经验。
报告、研判、咨询及格式修复使用模型输出额度，未配置时默认328000；共用`REPLY_STYLE`。报告检查结束原因、完整字段和证据引用，保留修复诊断，未通过不得保存成功。
报告正文按1700 UTF-8字节分段，标题加正文不超过2048字节；逐段回执支持续传，补发不重复调用模型。明确计划股数复用账本申报校验，非法数量由模型修复；按同一快照展示“卖出→剩余”，持仓变化后由`premarket_plan_context`使旧数量失效，保留原报告。
报告按账户→全局→逐股→机会→经验展示；策略候选即使未被评价也保留并标明“未评价”。盘前/日/周分别使用上一交易日/当日/当周信号，保留`strategy_slug/rule_version`。
休市日全系统业务通知静默，日历于06:30/18:30更新、07:30补重试。只读咨询保留独立实际背景、幂等请求和多轮历史，不修改模拟账户。
相关测试见`tests/ops/test_guardian*.py`、`tests/ledger/test_guardian_cash_account.py`、`tests/ledger/test_guardian_position_limit.py`；执行契约列出对应回归入口，不以文档记载代替实际验证。

### 交易员决策证据与机会复核

`guardian_evidence.py` 提供 `guardian_decision_history` 只读工具：按日期、股票、时段和分页返回原始逐股理由、条件变化、其他买入意图、成交与拒单。咨询自动带入问题指定日期的首批轮次；不能把最近5轮之外的记录说成不存在。研判前账户优先使用当轮快照，旧记录只按该轮之前的成交流水重建现金和可卖股数，不拿收盘状态代替开盘。

自动研判在调用模型前保存 `decision_context`（账户、实际 `position_policy`、候选输入和盘前计划），成功与失败提交均保留。未记录历史规则时明确缺失，禁止以当前提示词反推历史程序约束。模型理由、程序拒单、事后行情评价分开归因；未记录逐股决策的候选标记 `not_recorded`，不补写主动放弃。每轮优先复核待触发机会，修改等待条件需说明新增事实及其时点，保留自主选择权。

独立智能体（`stock_agent_policy.simulate_stock_agent`）逐笔预检：入选/观察/临时持仓上限只拒绝“使数量越限并继续变大”的那一笔（`reject_code=agent_limit`），卖出、减仓、止损和撤观察照常执行；依赖成交结果的组合约束（锁仓数、临时超配留仓名单、14:50后禁止新增超配、单股仓位上限）先撤回相关买入（单股仓位只撤该股，其余撤回本轮全部买入/加仓，不由程序挑选赢家）后重算，不再整轮失败。账本提交处的数量复核同口径：下调上限后已越限的账户可以收敛。尾盘收敛只执行模型明确给出的留仓名单；名单缺失、未覆盖T+1锁仓，或只是“此前未超配”的空列表（无当日计划日期）时交由模型本轮研判，不再每轮报“禁止凭空替换”，也不会把全部持仓当作名单外清仓。回归：`tests/test_stock_agent_policy_resilience.py`。

天才交易员与独立智能体（含龙头选手）均支持 `common_prompt` 共用身份/风格偏好、`premarket_prompt` 盘前、`prompt` 盘中、`review_prompt` 盘后。每轮只加载共用部分与当前阶段；盘前/盘后留空时回退到盘中，不叠加两份阶段提示词。天才交易员的盘中提示词仍为内置默认时，盘前/日复盘留空改用对应阶段内置提示词，避免盘中任务进入报告；周复盘只用周复盘提示词或其内置默认。竞价与尾盘使用盘中，日/周复盘使用盘后。日/周复盘的计划阶段（产出次日计划与下周重点）加载共用基调和自定义的日/周复盘提示词，不重复注入内置回顾提示词。咨询只加载共用基调与独立咨询任务。内置天才交易员无固定战法偏好；用户风格写在共用基调，系统规则只规定“偏好是默认方向，偏离须写明比较与理由”，不写入具体风格。龙头选手的龙头与起爆点定位放在共用基调中。逐字匹配旧内置提示词的未分阶段配置会按新模板读取，自定义文本及显式留空保留；保存设置后持久化，无需改写历史报告。

达到常态4只不构成盘中禁买：在8只临时上限及资金/T+1约束内可先买新仓，再退出可卖旧仓，收盘最多4只。沿用14:50起收敛及14:55重试，不以提示词绕过收敛期限制。复盘按原始证据区分信号未满足、主动放弃、不可执行与仅因常态名额放弃，收益假设与规则误读分开处理。

复盘分开统计 `failed_cycles` 和 `expired_cycles`，逐股回顾消费原始条件变化与规则证据。回归见 `tests/ops/test_guardian_evidence.py` 及交易员主流程/复盘测试。

历史查询默认提供决策原文和输入摘要，保留每只候选及信号时间；使用 `guardian_decision_history` 的 `code` 与 `include_inputs=true` 获取完整原始信号，避免每次把多轮重复明细全部塞入上下文。摘要与原始查询的股票覆盖和决策内容有等价测试。

### 交易员研究能力与可靠性补全（2026-09-15）

研判、咨询、复盘统一叠加`guardian_research_tools`工作台：原行情工具 + system__系统只读能力 + 账户、实时主备报价、任意决策预演、组合情景、十进制算术和历史证据。研究不设固定轮数/单轮工具总次数，使用实际运行期限；保留用户模型、思考和输出容量，不增加战法、单股资金比例或持有天数限制。报告不再限制20只评价，完整计划覆盖由真实输入决定。

执行边界统一为用户授权的固定基准2%容差（含2%）；9.00上限允许9.01/9.18，拒绝9.19。`bind_execution_references`是唯一市价基准绑定入口；预检、按分成交价和风险回执共用验证器，旧风险合同ID兼容可选字段。首次风险触发仍严格判断，单股缺价不再阻塞全部模型研究。

完整执行通知逐目标/逐分段保存回执；`guardian_delivery`是租户补发任务，工作日08:00—20:55每五分钟运行，不研究、不撮合，失败可续传且成功段不重发。GET guardian返回待发积压。配置部分保存不重置thinking/parallel_tools等已有字段，不复活已停用任务。来源目录展示或成交后通知故障不推翻已核账成交。失败回执保存original_decision、failure_stage和preflight_fills，未提交的预演不计fills。详细语义及局限以[执行契约](../../docs/guardian-execution.md)为准。

盘中通知由 `guardian_notification.py` 生成只读当日基准与账户汇总，`render_digest` 仅展示本轮成交/受阻操作；不再附完整持仓、观察池或模型长文。完整研究仍原样留存，盘前/日周复盘明细不变。今日收益以权威昨收净值为基准，缺数据明确不可用；异常包含阶段/原因/未落账说明，估值或出站故障不覆盖原始错误。通知分段同时满足2000字节和旧通道字符预算，具体口径见 `docs/guardian.md`。
