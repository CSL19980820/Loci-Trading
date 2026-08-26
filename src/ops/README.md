# 运维（ops）

## 职责
定时任务、技能包、通知、调度器、运维配置。
其中 `application/screen/` 负责 formula/Python Screen Skill 包的磁盘存储、历史归档、zip 路径校验与 revision 锁；不负责编译或执行选股。

## 边界
写 ops.db；技能文件在 data/skills。
Skill 清单解析在 `application/skill_manifest.py`；安装/解压/发现仍在 `application/skills.py`。
HTTP：`api/skills.py`（目录/安装/生成）+ `api/skill_runs_api.py`（对话 Run）+ `api/skill_jobs_api.py`（战法配置/定时绑定）。

## 企微推送
- 出站统一经 `notify_dispatch.dispatch_text`（安静时段 + 企微 + Bark）；`send_wecom_text` 仍是企微通道实现。
- **出站队列**：企微 / Bark 的 HTTP 都进进程内 FIFO 队列（`notify_send_queue`）。同一时刻只发一条；失败最多 3 次（间隔 1s），三次仍失败再处理下一条。选股计算仍可并行，避免 15:30 多路同时打 Webhook 超时。
- 选股模板可在系统「推送」联配置（ops.db `wecom_screen_template`）：预设 default / compact / with_date / custom。
- 渲染：`format_screen_picks_text`（`notify_screen_template.py`）；占位符 `{title}` `{kind}` `{date}` `{name}` `{code}` `{pct}` `{n}`；技能另有 `{note}`（≤40 字，取 pick.note/thesis 等）。
- 技能推送行用 `skill_pick` / `skill_pick_no_pct`（有说明才套用；无说明回退量化行）。
- 量化任务可同时返回正式 `picks` 与弱市 `watch_picks`；企微把后者独立显示为“低吸观察（不计正式胜率）”。正式为空但有观察时显示“正式精选 0 只”，不再误报“暂无符合条件的标的”。
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
- **交易日闸**（`jobs/paper_quant_support.resolve_trading_day_gate`）：`strategy_monitor` / `paper_eod` / **手工 `POST .../orders`** 入口优先读热库/传入的 `market` 日历，避免再 open 全量 `market.db` 与盘后同步抢锁；`strategy_monitor` 经 `market_calendar_store()` 与次日日共用一只连接。周末与法定假日整轮跳过（手工下单 **409**）；日历缺失时 weekday 粗判 `is_trading_day`，但**买入 fail-closed**（纯买入请求 **409**；混合单剔除 open/add/buy_dip）。`paper_eod` 算次日必须传入已打开的 market。`monitor_runs.status`：LLM 失败等真实异常记 `failed`，非假绿 `success`。
- **持仓退出**（`application/rules_exit_orders.py`）：由 `position_exit_orders(..., ai_driven=)` 按路径分档，两条路径都不会让亏损仓裸奔。
  - **rules 路径**（无 model 或 `ai_mode=rules`）：全套退出，优先级 ① `stop_cut`（浮盈 ≤ 止损线：预案项 `stop_loss_pct` → 舱 config → 战法 `screen_stop_loss_pct`，默认 -6%）；② `take_profit`（≥ 止盈线，预案项优先于舱 config，未配则跳过）；③ `trim_high`（≥ `trim_high_min_pnl_pct`，默认 3%，减半层）；④ 高开 `revise` 减仓（`rules_exit_on_revise`，默认开，减 0.5 层）。每票每轮至多一笔。
  - **AI 全权路径**：只补 `stop_loss_safety_net` 硬止损兜底，止盈/高抛/减仓仍归模型判断。**这层不能省**——模型失语时本轮 `orders` 会被清空、异常回退路径只产开仓单，没有兜底则亏损仓一直挂着无人处理。AI 已对该票出过卖单（`SELL_LIKE_ACTIONS`）时不重复叠加；只在该票加仓时仍会触发止损。
  - `rules_exit_enabled=false` 两条路径都关（等于自担风险）。
- **战法风格记忆**（`application/paper_style_memory.py` + `paper_style_lessons.py`）：每 slug 独立 `paper_style_profiles` / `paper_lessons`（与全局助手记忆隔离）。**默认日终不写教训、不吸入人设、不播种记忆图**；舱配置 `eod_style_learn=true`（或预案侧 `inject_style_memory`）才评头论足→落库→吸入，并注入预案正文。清空用 `clear_paper_cabin_memory`。给人看的文案统一全中文。学习回执带 `fills_by_decided_by`；fill 教训 `evidence.decided_by`（空串→`unknown`）；不按决定方过滤 absorb。LLM 空返回经 `src.ai.chat_text_with_thinking_fallback` 降 thinking 重试（与盯盘共用）。
- **纸面 LLM 慢推理预算**：盘中 `strategy_monitor`、`skill_watch` 的 AI 摘要与盘后记忆学习共用舱配置 `llm_timeout_sec`；默认 1800 秒，写入和旧值读取均限制在 120–1800 秒。该值是单次 HTTP 调用预算；Job 仍由 `timeout_sec`（若显式配置）负责总生命周期保护。
- **统一池失败保护**：`skill_watch` 合并统一监察池异常时保留上一份完整快照并写入运行 `warnings`，禁止拿当轮残缺候选覆盖首页、企微和后续调度共同消费的名单。
- **盘中时段**：二波监测 `skill_watch` 每 5 分钟扫一轮（`*/5 9-14 * * mon-fri`），用当日现价/最高最低，不吃昨收。首页监控带挂同一份快照。
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
  空 `picks` 与 **仅观察**（`intent`/`action` 为 observe）都不算可执行——二波引擎只出观察票，
  统一池缺 action 时还会默认成 observe，旧逻辑只要名单非空就刷「👀观察 N：…仅观察」。
  **不能指望 notify 里那条 `not summary` 兜底**——runner 给 `summary` 配了 `"无新信号"`
  默认值、`signals` 里还常年躺着 `watch_only`/`gate_empty`，那条分支永远进不去，
  盘中每 10 分钟就会推一条「无新信号」。失败/跳过仍推中文原因，不受此开关影响。
  首页二波快照仍每轮更新，只是不再刷企微。
- **龙回头纸面舱已退役（2026-08，勿重建）**：`dragon-return` 舱、`监测·龙回头` / `盘后复盘·龙回头` 任务与技能包由 `application/retire_dragon_return.py` 在启动时幂等清掉。盘面 GET 与 `ensure_dragon_cabin_policy` **不再隐式建舱**（这是上次删了又回来的原因）。`sync_skills_from_templates` 跳过该 slug。替代监控是 **龙回头·二波监测**（`dragon-second-wave`）。
- **龙池已退役（2026-08，勿重建）**：引擎、技能包、`监测·龙池` 任务与生命周期状态已整体移除；`application/retire_dragon_pool.py` 在启动时幂等清理存量安装（删任务、卸技能、清 `dragon_pool_state*`、清 `unified_monitor_pool:dragon-pool` 快照，并摘掉其它池里 `candidate_feed=skill_watch:dragon-pool` 的候选）。**只删源码不清库会更糟**：调度器照样按 cron 触发那条任务，执行器找不到引擎就每 5 分钟推一条失败。
  - 退役依据（300 个交易日 / 199 笔成交样本，防前视口径同下）：扣 0.26% 成本后相对**同信号日全市场等权基准**的配对超额 T+3 仅 **+0.53%（t=1.00，95% 区间 [-0.50%, +1.56%] 跨 0）**、T+5 +0.36%、T+10 −0.59%；超额胜率 T+3 只有 43.7%，最赚的 3 笔贡献 38% 盈利；入池分数按三等分无区分度（低 +1.00% / 中 −0.26% / 高 +0.83%）。要把该超额证成显著约需 764 笔 ≈ 46 个月。
  - 同期它还高度顺周期：`ready` 需全市场站上 MA20 ≥50%，而 2026-06-02~08-12 只有 18% 的交易日达标，2026 年 3/6/7 月整月零信号——赚的那点绝对收益基本是 beta。
  - 明细见 [2026-08-dragon-pool-forward-validation](../../docs/research/2026-08-dragon-pool-forward-validation.md)。想重做这类「曾大涨 + 回撤到位」的战法，请先复现这份对照再动手，别直接把参数抄回来。
  闸门质量警告分硬/软：错日/`tool_error`/必填缺失 → 空仓；tape `degraded` 等软警告 → 最多观察不开仓。
  纸面舱 `_resolve_market_gate` 对同日闸门短 TTL（约 90s）复用，减轻与 `skill_watch` 叠打配额。
  观察池文案/规则在 `observe_format.py`（`observe_alert_records` 结构化预警），粘性合并仍在 `observe_pool.py`；
  `collect_observe_alerts` 禁止解析中文行。
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
- **二波监测**（`application/skill_watch/second_wave.py`，引擎名 `second_wave`）：龙回头的盘中版。
  入池 = 20 日涨幅进过全市场前 10；入池后盯 20 个交易日；触发 = 当日最低打到 MA10 又收复
  （`low ≤ MA10 < 现价`）且距 20 日最高不超过 3 天。**不用 MCP**，全市场日 K 建池 + 快照判触发，
  没有悟道 Key 也能跑；`call_tool` 只为对齐 runner 契约。宽度闸走本地全市场涨家数占比（≥55%），
  不复用龙空龙那套。调参在 `tuning` 的 `second_wave` 段。
  - **强度分 0–100 与 45 分线**：四项权重（20 日涨幅 / 距高点天数 / 回撤 / 筹码宽度）全部来自回测分档。
    实测分档均净 00-44 **−0.962%**、45-59 +2.533%、60-69 −0.026%、70-79 +3.344%、80-100 +5.213%，
    45 是唯一「以下全负、以上整体为正」的线，故默认 `min_strength=45`。
    注意 20 日涨幅与收益是 **W 形非单调**（50~100% 最好、20~50% 最差、≥100% 转负），
    别把它改成「涨得越多分越高」，`tests/ops/test_second_wave.py` 钉了这条。
  - **筹码宽度必须先补停牌行再递推**：全市场面板的 index 是并集，停牌日是 NaN。直接喂 NaN 会让
    COST 分位脱离价格区间（实测某票 close=56.35 而 COST15/85 算成 14.9/25.2，宽度 18.25% vs
    正确值 32.26%，刚好跨过 25% 分档线白送 12 分）。停牌 = 无换手 = 筹码不转移，所以价格 `ffill`、
    换手补 0。这是 `chips.py` 警告的「看着正常、实则毫无意义」那类静默错误，有回归测试。
  - **`load_panel` 必须传 `start`**：不传会把全市场全部历史读进内存，实测单轮 230s；限到 400 个自然日后降到 8s 级。
  - **快照代表的那一天要从面板剔掉**（`_snapshot_day`）：判据不是「日历今天」。盘中快照是今天的实时价，
    而盘中增量同步可能已把今天那根未完成 K 线写进库，留着会让 MA 变成「含今天的 N-1 根 + 现价」；
    盘后快照返回的是最后一根的收盘价，此时该剔的是最后一根，用「今天」当分界反而把它叠加一次
    （方向相反的同一个错，实测让 20 日涨幅从 +51.76% 错算成 +27.98%、距高点从 1 天变 2 天，
    强度 80 → 40 直接跌破 45 线）。两个方向都有回归测试。
  - **调度器不注入行情仓时引擎自己开默认库**：`execute_skill_watch` 只在
    `PALACE_MARKET_DB` / `PALACE_MARKET_HOT_DB` 有值时才建 store，而桌面端启动这两个环境变量都是空的。
    别的引擎有 MCP 兜底，本引擎只吃本地行情——不自己开就会每轮静默降级成「无法建池」，
    自动监控看着在跑其实什么都没扫。
  - **筹码宽度的分母用现价**，不是最后一根收盘价：分档线在 15%/25%，用隔了一天的收盘价当分母会让临界票跳档。
    递推本身只到上一根已完成 K 线（当日换手盘中不是终值），与研究脚本会有约 3pp 的差，不影响分档。
  - **继承龙池退役那条警告**：它同属「曾大涨 + 回撤到位」家族。与龙池不同的是它靠盘中触发而非收盘选股、
    带宽度闸与强度分档。但**逐笔口径可信、组合口径不可信**——`analyze_portfolio` 的 `slot_capital`
    是固定名义额，信号微调会让总收益非线性剧变，见
    [2026-08-dragon-survivorship-and-portfolio-fragility](../../docs/research/2026-08-dragon-survivorship-and-portfolio-fragility.md)。
    因此提醒里**只给信号与依据，不给预期收益**，`validation=unverified` 全程带着。
  - **技能包与托管任务**：`templates/skills/dragon-second-wave/`（slug 必须叫这个——
    `default_watch_push_wecom` / `push_only_when_actionable` 都按 slug 查引擎注册表）。
    经 `save_strategy_config` 成对写入时把 `screen_schedule_mode="off"`（本战法只做盘中，
    盘后 AI 选股要 LLM 供应商），`watch_schedule_mode="interval"` → cron `*/5 9-14 * * mon-fri`。
    启动 `ensure_second_wave_watch_job` 会把已有 `*/10` 任务改成 5 分钟。
    每轮把最新快照写入 `meta.second_wave_latest`；首页 `GET /api/skills/dragon-second-wave/second-wave`
    只读这份快照并给列表票叠当日现价，不重跑全市场扫描。达标 picks 标 `intent=observe`，
    **不刷企微**（`push_only_when_actionable` 把仅观察当无信号）；任务失败仍推原因。
- **二波触发留痕**（`second_wave_signals`）：**只追加**，一轮扫描写一批。
  **未达 45 分线、未过宽度闸的触发也写**，用 `alerted` 标记当时是否真的推送了——观察期要回答
  「强度高的后续是不是真的更好」，只留最终提醒等于把反例扔掉，那个问题就永远验不了。
  可整表清空重建（重扫即生），保留天数由 `prune_second_wave` 控制。
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
- 行情：`MANAGED_SYNC_INTRADAY` / `MANAGED_SYNC_EOD`，由 `ensure_managed_market_sync_jobs` 幂等创建；**首次默认开启**盘中增量 + 日终重刷（默认 15:10，`today_refresh` + `with_factors`，赶在 15:30 选股前）。两条任务每天首次运行前刷新一次证券目录，退市旧票会先退出本轮代码集；盘中增量（`mode=full`）走 watermark：今天没同步过的票只补近窗日 K（见 `src/market` 的「日 K 增量近窗」），不再每天把全市场全历史重拉一遍；只有 `force=true` 才回全量
- **同步作业的运行记录只留证据摘要**：`source_evidence.receipts` 压成失败样本（上限 50 条）+ `receipts_total` / `receipts_failed` / `receipts_source`。逐票回执的权威副本在 `market.db.source_route_receipts`，全量塞进 `ops.db.job_runs.result_json` 会让单条运行涨到数百 MB（实测 257 MB/条，258 条运行 = 1.7 GB 运维库）。**`mode` / `force` / `with_factors` / `refresh_instruments_daily` 是托管键**：启动时确保托管任务会把它们复位成上述语义，只有 `workers` / `push_wecom` / cron / `enabled` 等尊重用户改动——历史遗留的 `force=true` 会让盘中增量每 5 分钟重拉一遍全市场历史
- `sync` 结果字段：历史日 K 硬失败进 `failed`；当日现价软跳过进 `spot_skip_reason` / `spot_gaps`；每日证券目录刷新写 `instrument_refresh`（失败时继续用本地目录）；**尽力而为的子步骤失败也要留痕**——复权因子刷新失败写 `factors_error`，换手率回填失败写 `turnover_repair.error`，热库镜像失败写 `hot_mirror.error`。这些尽力而为项都不改任务状态（不因外部源抖动把日终刷成红），但运维页看得见，避免「除权后 qfq 长期失真却一直绿灯」
- 行情热库重建：`MANAGED_HOT_REBUILD`（`kind=hot_rebuild`，默认 cron `10 16 * * mon-fri`），由 `ensure_managed_hot_rebuild_job` 幂等创建；把全量库近 700 交易日窗口全量重灌进滚动热读库（`market_hot.db`，重建时裁窗外旧行），热库损坏/启动兜底时手动触发。见 [ADR-007](../../docs/adr/ADR-007-market-hot-readonly-window.md)
- 行情库体检:`MANAGED_MARKET_QUALITY`(`kind=data_quality`,默认 cron `30 16 * * mon-fri`,排在热库重建之后,看到的是当日终态),由 `ensure_managed_market_quality_job` 幂等创建。**只读、只报、不改库**——修复各有各的入口(`scripts/resync_market_authoritative.py`、`repair/turnover`),体检擅自动手会让「谁改的库」说不清。六项判据:权威源占比、合成成交额行数、近窗缺回执、最后交易日覆盖、基准指数量级、非权威源水位。超阈值时 payload 里出 `blocked` / `alert`(中文告警),但**不抛异常**:体检报的是「库需要维护」,不是「这次任务出错了」,刷红运维页会让人开始忽略它。阈值可在 job config 覆盖(键名见 `jobs/data_quality._THRESHOLD_KEYS`),配置写错只 warn 并回落默认——配置写错就不体检 = 最需要体检的时候正好没体检
  为什么要有它:换源和全量重写都只解决「当下」。之后主源一旦被限流,回退源会安静地把 `close×volume` 合成的假成交额写回来;spot 会落下无回执的临时行;退市票的水位会一直停在老日期。这些都不报错,只会慢慢把库泡坏。见 [ADR-013](../../docs/adr/ADR-013-tdx-primary-daily-source-and-batch-sync.md)
- 候选兑现：`MANAGED_OUTCOME_TRACK`（`kind=outcome`，默认 cron `45 15 * * mon-fri`），由 `ensure_managed_outcome_job` 幂等创建；lifespan 启动（含未开调度器时预写）确保存在。已存在时**只补齐缺失的配置键**（`limit` / `max_age_trading_days` / `benchmark`），不整体覆盖、不改 enabled / cron
- 运维清理：`MANAGED_PRUNE`（`kind=prune`，默认 cron `30 2 * * mon-fri`），由 `ensure_managed_prune_job` 幂等创建；工作日凌晨清理 `job_runs`（每任务保留最近 200 条）、`leader_role_snapshots`（保留 60 天）与 `second_wave_signals`（保留 180 天，比角色留痕长一倍——它是「强度分是否有效」的唯一样本来源，砍太短等于把没验完的观察期删了），避免运维库无限涨库。`prune_runs` **不删 `status=running` 的记录**（清掉执行中的运行槽会让 `finish_run` 当场报「任务运行不存在」），`keep_per_job` 下限钳到 1（配 0 会连「最近一次跑没跑过」都查不到）
- 悟道情报采集：`情报·开盘/盘中/盘后`（`kind=intel_fetch`），由 `ensure_managed_intel_jobs` 幂等创建；走 **structured 池**（默认 3000/天），Agent/Skill 临机与**战法盯盘 / tape lane** 走 skill 池（默认 2000/天）。**这三条任务的 cron 就是配额估算的真相来源**：`intel_fetch` 自检会读 ops.db 里它们的真实 cron 与 config 反推日耗（`*/15 9-14` = 24 轮/日，不是拍脑袋的 20），改 cron 就等于改预算。默认配置下 structured 预估 **1755 次/日**（开盘 190 + 盘中 53×24 + 盘后 293），压在 3000 以内。`enabled` 参数**只是首次创建的默认值**：已存在的任务只补齐缺失的托管配置键，不回写 enabled / cron / 用户调过的 `theme_top_n` 等参数——否则用户在运维页关掉的情报任务会在下次启动自己复活
- 专属战法：`skill:{slug}`（`kind=skill`，盘后 AI 选股）+ `监测·{slug}`（`kind=skill_watch`，盘中确定性信号）。两者由 `skill_strategy_config.save_strategy_config` 成对写入，**不自动创建**；仅开启盘后 AI 或盘中 AI 解读时要求 LLM 供应商。`SKILL.md` 只声明战法能力、工具、信号与取数窗口，不声明 cron/时段；运行时间、频率、启停和推送由系统配置（见 `DEFAULT_SCREEN_SCHEDULE` / `DEFAULT_WATCH_SCHEDULE`）。
- 盘后选股：每个引擎战法绑定 `screen:{slug}`，默认 cron `30 15 * * mon-fri`（工作日 15:30），由 `ensure_managed_screen_jobs` 幂等创建/对齐；战法可声明自己的托管时点与输出上限。三源 / 杨氏收盘档：`sanyuan-tail-v1` / `yangshi-tail-v1` 固定 15:30（最多 2 / 1 只）。14:50 两档（`sanyuan-tail-1450` / `yangshi-tail-1450`）已连代码删除；启动时活动目录收缩会清掉旧库残留的 `screen:*-1450`。`qianlong-tail-v1` 已下线，启动时 `ensure_managed_screen_jobs` 会删掉旧的 `screen:qianlong-tail-v1`；用户在详情页保存的 `universe`（行情范围）会保留，手动选股未传 universe 时也回落该配置（见 `screen_job_config.resolve_screen_universe`）；无 `screen_schedule` 声明的战法还会保留用户自定义定时；执行前默认走 `ensure_today_quotes_for_screen`：**当日覆盖率已达标则跳过 spot**（不与盘后同步抢写），不足才刷现价；库忙但覆盖已够则软放行
- 活动目录收缩：`ensure_managed_screen_jobs` 会删除 `screen:*` 前缀下不再托管的旧 `screen` 任务（未注册，或声明 `screen_managed_job=False`），避免废弃/不定时战法继续调度或推送；其它同名前缀任务和非 `screen` 任务不受影响
- 调度器：`loci.py` / `cli.serve` 默认 `PALACE_ENABLE_SCHEDULER=1`（pytest 不设）；启动时确保上述托管任务并 `reload`
- **工作日 cron**：一律写 `mon-fri`（或经 `validate_cron` 把历史 `1-5` 归一化）。APScheduler 的数字星期是 **0=周一**，Unix 习惯的 `1-5` 会被当成周二–周六，**整周跳过周一**（龙王盘中监测/纸面盯盘会在周一静默不跑）。
- **启动补跑**：调度器起来后后台执行 `eod_catchup`——对 `screen` / 日终 `sync` / `outcome` 等「工作日定点」cron，若最近交易日触发点已过且尚未跑过，则 `trigger=catchup` 补跑一次。`last_run_at` 无时区时按 UTC/上海本地**任一覆盖**即跳过；若当日已有成功 run，也跳过。选股企微另有 `wecom_push_marks` 防连推。
- `GET /api/jobs/schedule`：未启调度器时仍用 `preview_upcoming_jobs` / `next_cron_fire_at` 按 cron 推算 `next_run_at`，供详情页展示
- **执行互斥与生命周期**：`run_job` 通过 ops.db 原子认领同一任务的执行槽；调度、API、CLI 和助手重叠触发时，后到者返回 `skipped` 和当前 `run_id`，不重复执行副作用。可传 `idempotency_key` 做跨重试幂等；`JobContext.check_cancelled()` 在安全检查点收敛 API 的取消请求或 `timeout_sec`，终态为 `cancelled` / `timed_out`，`finish_run` 不允许覆盖既有终态。`heartbeat_at` 与 `owner_pid` 一起用于 stale recovery。`sync`/`screen` 另有进程内行情闸门（`jobs/market_gate.py`）：**sync=独占写、screen=共享读**（多路选股可并行；不再互相假互斥等 90s）。holder 标签去重（`screen:qianlong-…` 不再变成 `screen:screen:…`）。**14:35–15:00 盘中增量（`mode=full`）占锁前直接 skipped**，避免与杨氏/三源 14:50 同分钟抢锁；日终 `today_refresh` 不跳过。选股等锁 360s（同步仍 90s）。**写者优先**：有 sync 在排队时不再放新 screen 进来，否则一波接一波的选股能把同步无限期饿死。**读槽有租约**（`MARKET_SCREEN_HOLD_LEASE_SEC`，45 分钟，与 screen stale 回收窗同口径）：到点仍不放槽的选股按已废弃处理并放行同步——ops.db 那条 run 此时也已被判 failed，闸门不该继续替一个判死的任务挡路。**同线程重入按 kind 判**：同 kind 直接放行（`run_job` 外层 + `execute_sync` 内层是同一批写入，再抢一次只会自锁），`sync` 写槽里再要 `screen` 读槽也放行（写槽本就涵盖读，排队等于等自己）；但 **`screen` 读槽里再要 `sync` 写槽不算重入**——那是跨 kind，正是本模块要防的「一边扫 market.db、一边写 WAL」组合，旧判据「持有任意 kind 即重入」会把它静默放行、独占写锁形同虚设。现在内层会真去抢写槽：先把**自家**那把读槽临时让出（否则 `_acquire_writer` 会等自己），写完在同一临界区里降级取回；别人的读槽照样挡路，抢不到就按常规排队/超时收场。等锁超时用人话了断，不硬刚挂死同步：**同步排在另一条健康同步后面等不到 → `JobSkipped` → 终态 `skipped`**（两条同步写的是同一批当日行情，先到的写完就够了；判 failed 只会每天刷一次假故障 + 企微「同步失败」）；持锁超过 `MARKET_SYNC_STUCK_SEC`（45 分钟，与 sync stale 回收窗同口径）才算卡死，仍明确 failed 并点名占锁任务；被租约内的选股挡住仍是 failed，但文案改为「选股仍在正常执行」，不再让用户去「停掉卡住的选股」（它们通常是受害者而非元凶）。`LOCI_OBSERVABILITY=1` 时记 `loci.lock.wait_ms` / `market_gate_lock_timeout`（`outcome=skipped|timeout`）。读写双库：`sync`/`screen` 写全量库后把最近交易日增量镜像进热库（`mirror_recent_to_hot`）；`sync` 镜像失败只记 warning、不阻断任务。`screen` 默认只读热库；镜像失败、`hot_unusable_reason` 判定不可用（窗口偏浅或落后于全量）、或策略 `requires_full_history` 时回退全量库选股——`jobs/screen`、`screen_run`、`POST /api/screen` 三条路径共用同一判定函数，不再各写一份；选股前准备当日行情见 `market.application.screen_spot`（覆盖达标跳过 / 库忙复检覆盖）。超时 / 僵尸 running 回收：认领时优先按 `owner_pid` **探活**——进程已死立刻腾槽（不再干等）；时间兜底 `sync`/`screen` **45 分钟**，其它 kind **24 小时**。调度器启动与每次 `claim_run` 都会扫。跨进程行情写锁见 `market.infrastructure.write_lock`（sync/spot 互斥，同线程可重入，**跨线程等待有 deadline**）。**`execute_sync` 自己也占 sync 写槽**：HTTP `/api/market/sync`、首启 bootstrap 回填、CLI 都不走 `run_job`，只在 `run_job` 上挂闸门等于留了后门——2026-08-24 正是 bootstrap 同步在闸门视野之外占着写锁，把 15:30 三只选股拖死，进而让盘后同步与日终重刷连续两次假故障。即时分析预先分配独立运行槽，因此不同请求仍可并行。

### 全局助手调度

全局助手可管理 `sync`、`screen`、`backtest`、`compare`、`optimize`、`prune`、`outcome` 任务，并在创建、更新、删除后请求组合根重载调度器。它不能创建、修改或触发 `skill`、`notify` 等可扩展任务，避免经助手间接取得 CLI、文件或外部 MCP 执行面。助手立即触发任务时必须传入当前工作台的 `JobContext(market_db, palace_db)`。

## 包结构（jobs）
`application/jobs/`：`context`（JobContext/JobError）· 各 kind 执行器（含 `outcome`）· `registry`（EXECUTORS + `run_job`）。对外仍从 `src.ops` / `src.ops.application.jobs` 导入。

## 存储层拆分（infrastructure）
对外仍从 `store` 入口导入：`OpsStore` / `OpsError` / `JOB_KINDS` / `MANAGED_SYNC_*` / `new_id` 等。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_helpers.py` | 常量、`OpsError`、`new_id` / `dumps` / `loads` |
| `store_schema.py` | DDL、`SCHEMA_VERSION`、迁移清单 |
| `store_jobs.py` | 任务定义(cron / config / 托管确保)与 meta 设置 mixin |
| `store_runs.py` | 执行历史 mixin:占槽 / 回收 / 收尾 / 取消。与 `store_jobs` 拆开——前者是**配置**,后者是**状态机**,读的人和改的原因都不一样;崩溃回收(按 `owner_pid` 探活,时间窗兜底)也集中在这里 |
| `store_providers.py` | LLM 供应商 mixin |
| `model_catalog.py` | `models_json` 规范化 / 发现合并 / 启用 id 派生 |
| `store_strategy.py` | 战法档案与策略版本 mixin |
| `store_alerts.py` | 价格提醒规则 / 命中 mixin；`insert_alert_hit` 返回空 dict **只**表示「同一 `(rule_id, trigger_bucket)` 已命中过」的幂等跳过，外键违例 / NOT NULL / schema 漂移一律抛 `OpsError` 或原异常（原先 `except Exception: return {}` 会把没建父规则的整批写入压成「行行成功、一行没落」） |
| `store_paper.py` | 纸面舱 / 持仓 / 成交 / 拒单 / 预案 / monitor mixin；`apply_paper_fill` 把成交流水与仓位快照写在**同一事务**（分两次写会留下「有成交、仓位没动」的半条记录，后续加减仓都在错的基数上算） |
| `store_ai_decisions.py` | AI 决策留痕 mixin（`ai_decisions`）：prompt / 报价数值 / 原始回复 / 解析结果；可整表清空 |
| `store_watch.py` | 龙头角色留痕（只追加）与角色变化推导 mixin |
| `store.py` | `OpsStore` 组合 + 连接/迁移 + re-export；旧库缺列时先迁移再补索引（避免 `idempotency_key` 等 INDEX 抢跑导致桌面 90s 起不来） |

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
