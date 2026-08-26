# 龙王战法系统审查与调整方案（2026-08）

## 范围与方法

只读审查，未改动任何代码。范围为龙王战法大成体三层及其下游纸面链路：

- 扫描侧：`src/ops/application/skill_watch/**`（龙空龙闸门 `market_regime` → 龙头地图 `leader_map` → 龙回头 `dragon_return`）
- 执行侧：`src/ops/application/jobs/paper_quant_{plan,monitor,eod,support}.py`、`nextday_plan.py`、`scenario_gates.py`、`paper_policy/**`、`paper_exec.py`、`rules_exit_orders.py`
- 数据侧：`src/market/infrastructure/tape/**`、`store_hot.py`、`src/ops/infrastructure/store_{watch,paper}.py`
- LLM 触点：`skill_watch/runner.py::_ai_summary`、`paper_quant_monitor.py::_call_monitor_llm`、`paper_style_memory.py`、`src/ai/infrastructure/client.py`
- 前端：`frontend/src/features/market/composables/{usePulseDragonPool,pulseDragonLogic}.ts`、`components/PulseWatchRail.vue`

方法为三路并行只读审查（代码质量与架构 / 性能与资源 / 复用与扩展点），结论经人工逐条复核。文末标注了哪些结论已验证到代码行、哪些是推算。

---

## 结论摘要

扫描侧是这套系统里质量最高的部分，不需要结构性改动：三层职责边界清晰，`dragon_return` 只消费 `leader_map` 判定好的角色而不自己从涨停池猜龙头（`dragon_return.py:3-9`、`_rank_eligible:173-179`），K 线口径只有 `kline_stats.trend_stats` 一份实现，涨停幅度走 `src.formula.limit_ratio_for` 而非硬编码 9.5%，闸门在数据缺失时一律 fail-closed。全链路无超 600 行文件。

问题集中在三个根因：

1. **模型失语时静默无为**——盯盘 job 会报成功但当天什么都没做。
2. **用 slug 字面量代替能力声明**——闸门、`market_store` 注入、日终重扫都绑在硬编码字符串上，已经导致套件内另外两个 slug 默认无闸门。
3. **线程池里复用主线程 sqlite 连接**——一个根因引爆缓存永久失效、本地降级出口反复冷却、外部调用量翻倍三个症状。

另有两处功能目前等于未生效：区间强度段恒定降级、两个调参面板字段从未传到下游。

---

## 一、定位澄清：AI 在纸面舱里的权限边界

这是本轮审查中唯一需要人来拍板、而非代码能回答的问题。已确认的产品意图：**盘中盯盘的卖出决策由 AI 全权行使，规则不替它做决定。**

据此明确两条边界，后续所有改动都不得越界：

| | 允许 | 不允许 |
|---|---|---|
| **业务判断**（该不该卖、卖多少、为什么卖） | AI 全权 | 规则替 AI 决定、或以"未命中阈值"为由否决 AI 的卖出 |
| **输出合法性**（代码是否存在、层数是否合法、价格是否真实） | 系统强制校验 | 因为"AI 全权"就跳过校验 |

### 撤回一条初审结论

初审曾判定"AI 卖出类订单完全不过任何闸门"为阻断级问题。复核后**该结论不成立**，予以撤回。`merge_ai_orders_with_gates`（`scenario_gates.py:283-361`）确实只校验买入侧，但执行层 `validate_and_normalize_order`（`paper_exec.py:62-151`）对卖出侧已有完整的合法性校验：

- 空 code 拒（`:77-78`）、动作不在 `ALL_ACTIONS` 白名单拒（`:79-80`）、动作未授权拒（`:81-82`）
- 无持仓做卖出类动作拒（`:97-98`）——AI 幻觉出的代码在此被拦
- 减仓层数超过持仓拒（`:101-102`）、层数非 `min_step` 倍数拒（`:103-104`）
- 缺有效标记价拒（`:138-139`）——价格来自 quotes，AI 无法编造成交价

且 `execute_orders` 在循环内逐单更新 `positions`（`paper_exec.py:268`），所以同一批订单里 AI 重复输出两条 `close`，第二条会被"无持仓可清仓"拦下。

**结论：卖出侧的合法性防线是完整的，不需要新增业务闸门。**

### 但需要补一件事：决策归因

既然 AI 全权，就更需要能单独评估 AI 的表现。当前 AI 路径与规则路径产出的成交，`source` 都是 `"strategy_monitor"`（`paper_quant_monitor.py:333`），落库后无法区分。后果是日终复盘（`paper_eod_review.py`）和风格记忆学习（`paper_style_memory.py`）会把 AI 决策与规则决策的绩效混在一起学，"AI 判得准不准"这个问题在数据上无法回答。

建议在 `PaperOrder` 上加一个 `decided_by: Literal["ai", "rules", "scenario_gate"]`，随 fill 落库，日终复盘按此分组统计。这是纯观测增强，不改变任何决策行为。

---

## 二、P0：必须先修

### P0-1 模型失语时静默跳过全部执行，且报告成功

**落点**：`paper_quant_monitor.py:241-268`、`:86-91`、`:33-34`、`:485-491`

**现象**：`_call_monitor_llm` 在两档尝试都拿到空文本时走 `return ""`（`:91`）；`_parse_orders_from_text("")` 内部 `json.JSONDecodeError` 被自己捕获，返回 `([], "")`（`:33-34`）。两条路径都**不抛异常**，因此 `:257` 的 `except` 不触发，`llm_failed` 保持 `False`，`orders` 保持空列表。

连锁后果：

- `scenario_gated_open_orders` 那条回退路径完全不会被调用
- `eventful = bool(result_fills or result_rejects or clock.in_auction)`（`:399`）为假 → `should_follow`（`:414-416`）为假 → **企微不推任何东西**
- `run_status` 在 `:485-491` 判定为 `"success"`

即：模型吐一段散文、或推理模型把 completion 全烧在 thinking 上（`paper_style_memory.py:430` 的注释表明这在本仓真实发生过），当天纸面舱不开仓、不减仓、不止损、不推送，运维界面显示绿色成功。这不是 fail-closed，是 fail-silent。

**方案（按"AI 全权、但失语必须吵醒人"定）**：系统不替 AI 补决策，但必须报错。

1. `_call_monitor_llm` 在两档都拿到空文本时，抛一个明确的领域异常（如 `MonitorLLMEmptyError`），而不是 `return ""`
2. `_parse_orders_from_text` 在 payload 解析不出 dict 时同样抛错，并把原始文本前 500 字带在异常里供排查
3. 该异常**不进入** `:257` 的回退分支（回退到规则会违反 AI 全权的定位），单独捕获后：`run_status = "failed"`、`notes` 写明"模型未产出可执行输出，本轮未执行任何操作"、强制推送一条企微告警
4. 推送条件从 `eventful` 改为 `eventful or llm_unusable`，保证这条告警能出去

**验收**：构造 mock provider 返回 `""` 和返回 `"今天市场不错。"` 两种情况，断言 `run_status == "failed"`、`fills == []`、`dispatch_text` 被调用一次且正文含失语提示。

### P0-2 `ai_mode="suggest"` 但未配 model 时，规则退出被静默跳过

**落点**：`paper_quant_monitor.py:198`、`:269-293`

**现象**：`:198` 的条件是 `ai_mode in {suggest, explain, auto} and cfg.get("model")`。当 `ai_mode="suggest"` 而 `cfg["model"]` 为空时该条件为假，落入 `:270` 的 else 分支；但 `:278` 的 `if ai_mode == "rules"` 同样为假，于是 `rules_position_exit_orders` 一次都不跑，**止损止盈完全消失**，且没有任何日志或告警。

**方案**：把 `:278` 的条件从 `ai_mode == "rules"` 收敛为 `cfg.get("rules_exit_enabled", True)`。注意这不违反 AI 全权定位——这个分支本来就只在"没有走 AI 路径"时才到达，是规则路径内部的自洽性修复，不会让规则去覆盖 AI 的判断。

**验收**：`ai_mode="suggest"` + 无 model + 持仓已跌破止损线，断言产出 `stop_cut` 订单。

### P0-3 线程池跨线程复用 sqlite 连接

**落点**：`leader_map.py:379-421`、`src/market/infrastructure/store.py:61`、`tape/local_provider.py:74-88`

**现象（已完整验证）**：`MarketStore` 的连接是 `sqlite3.connect(self.db_path, timeout=60.0)`，**没有 `check_same_thread=False`**（对比 `src/ai/infrastructure/assistant_store.py:25` 是显式关掉的）。而生产路径确实把主线程建的连接传进了工作线程：

```
execute_skill_watch 主线程 context.market_hot()   jobs/skill_watch.py:16-26
  → runner._default_call_tool(market_store=...)    runner.py:99-105
  → make_legacy_tape_call(store=...)
  → legacy_bridge.py:173  context={"market_store": store}
  → local_provider._store_from_request:76-78  原样取出复用（owned=False）
```

这整条链跑在 `leader_map` 线程池的 `_fetch_theme` 里（`:379-382`），于是 cache lane 与 local lane 在工作线程内必然抛 `sqlite3.ProgrammingError`，分别被 `cache_provider.py:47` 的裸 `except` 和 local 的降级出口吞掉。

连锁后果：并行段三个题材全部拿到空 rows 且不抛异常 → `:419` 的 `not any(rows ...) and not retry_jobs` 判定成立 → 整批串行重跑，而此时 local provider 已被 `router.py:232-233` 打上 30 秒冷却，重跑只能全打远程。

**方案**（二选一，倾向后者）：

- A：给 `MarketStore` 加 `check_same_thread=False` 并对 `conn` 加锁。改动小，但把线程安全责任推给了所有调用方。
- B：`_fetch_theme` 内不透传注入的 store，让 `_store_from_request` 走 `owned=True` 的每线程独立连接（`local_provider.py:79-85` 已有这条路径），用完 `_close_owned`。语义更干净，且不影响主线程 `_ingest` 里 `_daily_frames` 继续复用注入的 store。

**验收**：新增测试断言并行段拿到的 rows 非空、`fetched` 不为空（即不触发 `:419` 的整批串行兜底）。

---

## 三、P1：正确性

### P1-1 龙空龙闸门只对一个 slug 生效

`paper_quant_support.py:192` 的 `if slug != "dragon-return" and not config.get("market_gate"): return None`，配合 `_apply_market_gate:250` 的 `if not market_gate: return orders, []`，意味着 `DRAGON_SUITE_SLUGS`（`watch_labels.py:15-17`）里另外两个 slug 建的纸面舱**默认没有闸门**。而 `paper_quant_plan.py:62` 正是用这个集合判定观察池，说明这些 slug 确实会建舱。

方案：判定条件改用 `DRAGON_SUITE_SLUGS`；更彻底的做法见 P2-1。

### P1-2 两个调参字段从未生效

`observe_max_same_theme` / `observe_max_age_days` 在 `tuning.py` 里完整登记了默认值（`:50-51`）、钳位（`:92-93`）、字段表（`:192-193`），前端调参面板会渲染出来让用户调；但生产调用点全部漏传：

- `paper_quant_plan.py:80-90` 调 `merge_observe_pool` 未传 `max_same_theme=` / `max_age_days=`
- `paper_quant_eod.py:175-185` 同上
- `dragon_return.py:264-269` 调 `select_daily_observes` 同上

`observe_pool.py:199-200` 于是永远用默认值 2 / 10。全仓只有 `tests/ops/test_observe_pool_policy.py:28-98` 传了这两个参数，所以测试是绿的。**面板在对用户撒谎**。

方案：三处调用点补传参数；补一条断言"tuning 里的 scan 段字段都被下游消费"的测试，防止再漂。

### P1-3 `sector_analysis` 不在 lane 映射表里，区间强度段恒定降级

`theme_interval.py:208` 调 `call_tool("sector_analysis", ...)`，但 `LEGACY_TOOL_TO_LANE`（`legacy_bridge.py:15-23`）只有 7 个键，**没有 `sector_analysis`**。于是走 `:171-172` 的 `_unsupported_payload` 返回 `is_error=True`，`theme_interval.py:128-134` 判定 `tool_failed`，status 恒为 `unavailable`。

即 `theme_interval` 这段功能从未生效，每次扫描白打一次注定失败的调用，并往推送里塞一条 `theme_interval_degraded` 噪声信号。

方案：补 lane 映射 + `wudao_provider.TOOL_BY_LANE` 对应工具；若短期不打算做，先把这段 `stage_enabled` 默认关掉，别让它每次都发降级信号。

### P1-4 降级票文案重复追加

`apply_downgrade_conservative`（`paper_policy/eligibility.py:58-80`）中，layers 用 `min(layers, 0.5)` 是幂等的、veto 有 `if note not in veto` 去重（`:73-74`），但 **`thesis` 是无条件追加**（`:76-77`）。而重入判据 `is_auction_downgraded`（`:48`）读的是 `auction_stance`，这个字段从头到尾没被改写过。

`filter_openable_picks` 在链路上被调三次（`dragon_return.py:281` → `runner.py:227` → `paper_quant_plan.py:36`），所以降级票的 thesis 会被追加三遍，用户在企微里看到同一句"竞价降级：仅半层、高开不追"出现三次。

方案：用 `auction["downgraded"]` 做幂等短路（该标记在 `:68` 已写入，只是没被用作判据）。

### P1-5 跨日 stance 被算进当天教训

`paper_style_memory.py:238-244` 的过滤条件在"`started_at` 非当天但 snapshot 里有 stances"时不会 `continue`，于是继续累加 `revise_n / abandon_n / follow_n`。而 `run_eod_learning:547` 取的是 `list_monitor_runs(slug, limit=40)`，跨多个交易日。

后果：`:257` 的"竞价多次纠偏"教训会被昨天的数据触发，经 `absorb_lessons_into_style:367-370` 写进人设，再注入明天的 prompt——错误信息自我强化。这条在 AI 全权的定位下危害更大，因为人设直接塑造 AI 的决策倾向。

方案：过滤条件收敛为单一判据 `started_at` 是否属于 `trade_date`，删掉 stances 那个例外分支。

---

## 四、P2：性能

按影响排序。量级为推算，未实测。

### P2-1 本地 provider 每次 lane fetch 做一次全市场三表 JOIN

`local_provider.py:423-426` 在分流到具体 lane **之前**就无条件执行 `_rows_for_date(store, day)`，该 SQL（`:139-157`）是 `GROUP BY code` 的 CTE + 两次 `quotes_daily` 自连接 + `instruments` 连接，返回当日全市场约 5000 行。`theme_members` lane 只需要某题材成分，却同样吃全量。叠加 P0-3 的串行兜底，一次扫描最坏 6~9 次全市场扫描。

方案：按 lane 分流后再取行；`is_available` 探测出的 `day` 塞进 request 复用，避免 `fetch` 重算 `_target_date`。

### P2-2 留痕表排序无匹配索引

`store_watch.py:83` 的 `ORDER BY observed_at DESC, code`，而现有索引（`store_schema.py:347-348`）是 `(slug, code, observed_at DESC)` 和 `(slug, trade_date DESC, observed_at DESC)`，**没有 `(slug, observed_at DESC)`**。按盘中每 5 分钟一扫、保留 60 天推算约 7 万行，每次扫描都要为取 600 行而临时排序全表。这是链路里唯一会随交易日线性劣化的一项。

方案：`CREATE INDEX IF NOT EXISTS idx_leader_roles_slug_observed ON leader_role_snapshots(slug, observed_at DESC)`；`SELECT *` 换成显式列。

### P2-3 `evaluate_market_gate` 重复全树遍历

`market_regime.py:128-173` 每个 `pl.metric()` 都要 `structured()` + `walk_maps()` 物化整棵树，对 emotion 约 16 遍、ladder 约 8 遍、themes 约 8 遍。最内层 `payload.normal_key`（`payload.py:87-88`）是无缓存的正则 sub。注意 `fetch_market_snapshot` 的 90 秒缓存只缓存原始 payload，评分每次全量重算。

方案：入口处对每份 payload 做一次 `walk_maps` 复用；`normal_key` 加 `lru_cache`。

### P2-4 重复读库与重复读配置

- `load_tuning` 在一次预案生成里读两遍（`paper_quant_plan.py:41` 与 `:65`）
- `list_leader_roles(limit=600)` 在一次扫描里读两遍（`runner.py:143` 与 `:240-241`），且 `role_history` 段关闭时 `:240` 仍会读
- `_by_code(600 行)` 跑三遍（`runner.py:143` 一次、`suggest_tuning_adjustments` 内部两次）
- `shared/paths.py:87-95` 的 `load_config()` 无缓存，每次 lane 调用触发约 4 次读盘 + JSON 解析
- 盘中每轮开两次 `MarketStore` 并各拉一次全量交易日历（`paper_quant_support.py:121-131` 与 `:63-76`，两函数都支持 `market=` 参数但调用方没传）

### P2-5 LLM 调用成本

- `_call_monitor_llm` 双档重试 × `DEFAULT_TIMEOUT=120.0`（`client.py:29`）= 最坏 240 秒阻塞一个盘中 job（P0-1 修复后这条更重要，因为失语会变成显式失败，等待时间直接影响告警时效）
- `runner.py:180` 的 `_ai_summary` 默认 `thinking="medium"`，走 Anthropic 协议时 `client.py:211-222` 会把 `max_tokens` 从 512 强制放大到 5120。一个"3 行以内中文概括"不该开思考档
- `runner.py:169-170` 把 `list[dict]` 的 Python repr 直接 f-string 进 prompt，含 `'validation': 'unverified'` 这类对模型无价值的字段

---

## 五、架构：扩展点评估

新增第 4 个战法需要改 **注册表 5 处 + 散改 7 处**。

良性扩展点（表驱动，符合规范）：`runner.py:32-42` `_ENGINES`、`:45-70` `_ENGINE_SIGNALS`、`watch_labels.py:7-12`、`tuning.py:181-214` `FIELD_META`、`watch_summary.py:12-35` 信号标签表。其中 `tuning.py` 的"字段表即 schema，前端照着渲染"设计得好。

坏味道，同一个病：**用 slug 字面量代替能力声明**。

| 落点 | 硬编码内容 |
|---|---|
| `runner.py:215-219` | `market_store` 只注入给硬编码的两个 engine target |
| `paper_quant_support.py:192` | 硬编码 slug 决定是否走龙空龙闸门（即 P1-1） |
| `paper_quant_eod.py:66` | 日终重扫写死 `"dragon-return"` |
| `paper_quant_plan.py:62`、`paper_quant_monitor.py:206` | 观察池能力绑在 `DRAGON_SUITE_SLUGS` 上，而该常量语义本是"共用套件短名" |
| `notify.py:287-297` | 第二张 slug 中文名表，且已与 `watch_labels` 漂移（`market-leader-map` 一处叫"龙头战法"、一处叫"龙头地图"） |
| `skill_strategy_config.py:16-22` | 第三张 slug 表，决定默认推不推企微 |

**建议**：把 `_ENGINES` 的值从 `str` 升成小 dataclass，携带 `needs_market_store` / `uses_market_gate` / `emits_observe` / `eod_rescan` 四个能力声明，前四处硬编码一次性消掉。观察池的判据从"slug 在不在套件里"改成"picks 里有没有 `intent=observe`"——这个事实在 `filter_openable_picks` 输出里现成就有。三张 slug 表合并成一张。

---

## 六、明确不改的部分

以下经审查确认为合理设计或收益不足，**不要动**：

- `dragon_return._paper_pick` 与 `limit_up_momentum._paper_pick` 的相似结构。共用部分已抽在 `actionable_line.enrich_actionable_fields`，剩下的是各自领域字典字面量，再抽只会得到十来个可选参数的 builder。
- `skill_watch/` 下的 `str(row.get("code") or "")`。这些读的是内部已清洗过的 dict（code 在 `leader_map.py:145` 等入口就过了 `pl.clean_code`），下游再洗会掩盖上游漏洗的 bug。
- `payload.py` 的复用现状。逐个核查过所有碰 MCP 载荷的模块，全部正确使用 `pl.field` / `pl.text_field` / `pl.rows_by_code`，无别名兜底重复实现。
- K 线 / 涨停 / MA / 回撤计算。`kline_stats.py` 是唯一源，是正面样板。
- 四套中文推送文案表。受众和信息密度不同，`paper_policy/stances.py` 的存在正是为了把扫描态度与纸面门闩两套状态机显式分开，合并会糊在一起。
- 统一的"ops 侧 LLM 门面"。三处调用的 provider 来源、参数、system、异常语义全不同，硬包一层只会得到 8 参数函数。**但**其中"空返回则降级 thinking 重试"那段（`paper_quant_monitor.py:77-91` 与 `paper_style_memory.py:431-448`）是同一个模型行为补丁，值得抽到 `src/ai` 侧共用。
- `runner.py` 的引擎注册表机制本身。

---

## 七、次要项

- **跨上下文深路径导入 4 处**：`paper_quant_support.py:102` 掏私有 `from src.market.application.session import _resolve_trading_day`（且这条链决定 `buy_execution_allowed`）、`paper_quant_monitor.py:96`、`alert_rules.py:9`、`ops/api/paper_quant.py:242`。四个符号都不在 `src/market/__init__.py` 的 `__all__` 里。`.importlinter:11-21` 只保护 `src.market.infrastructure`，`src.market.application` 无护栏，所以 CI 是绿的。建议补导出 + 补一条 protected 契约。
- **`auction_excluded` 投影抄了 4 份**：`dragon_return.py:385-389`、`limit_up_momentum.py:286-290`、`runner.py:228-232`、`paper_quant_plan.py:139-143`，逐字相同。让 `filter_openable_picks` 多返回一项即可。
- **quote 取价 4 个版本，key 集合不同**：`observe_format.py:87-101` 与 `paper_follow_push.py:90-104` 用 `price→last→close`，`rules_exit_orders.py:14-19` 用 `price→current_price→close`，`scenario_gates.py:71` 与 `alert_rules.py:62-63` 只有 `price→close`。同一份 quote 在不同路径可能取到不同价——只有 `last` 字段时，规则止损会读成 `None` 直接跳过该票。建议在 `paper_policy` 下统一成一个 `quote_price()`，key 取并集。
- **`_safe_float` 有 3 份**（`plan_build.py:7-13`、`paper_eod_review.py:36-42`、`alert_rules.py:12-18`），而 `payload.number()` 是其超集。且 `rules_exit_orders.py:10`、`scenario_gates.py:8` 已在跨模块导入下划线私有的 `_safe_float`。
- **`is_observe_intent` 手写副本**：`dragon_return.py:283` 缺 `.strip().lower()`。目前 intent 都由内部写死为 `"observe"` 所以无症状，但一旦从预案回读或旧库进来带空格/大写，观察票会被 `:282` 的 `or "buy"` 兜底算进 `buy_picks`——开仓侧错误。
- **`market_regime.py:141`** 的 `_ladder_height(ladder) or pl.metric(...)`：`_ladder_height` 已用 `return max(levels) if levels else None` 区分了"没有"和"是 0"，这个 `or` 把区分丢了。
- **`plan_build.py:180-188`**：`**{k: v for k, v in auction.items()}` 展开在最后，会覆盖上面所有显式默认值和 `float()` 清洗。若 pick 携带 `follow_requires_band: false`，闸门会被静默关掉。
- **`leader_map.py:366-367`** 无日志的 `except Exception: owned_market_store = None`，热库打不开时静默降级，同文件其他 except 都有 `logger.warning`。
- **`leader_map_frames.py:65-96`** 四层嵌套 `try/except TypeError` 逐步删参数猜 store 签名（注释写"最旧 fake"），把测试替身的历史包袱固化进了生产热路径。
- **`market_gate.py:80-92`** 读者不让路，持续到来的 screen 读者会饿死等待中的 sync 写者直到 90 秒超时。另：该模块名为 `market_gate` 但与龙空龙闸门 `market_regime` 无关，而 `paper_quant_support.py` 里又把龙空龙叫 `market_gate`，命名冲突建议改一个。
- **死代码**：`runner.py:89-96` `skill_watch_mcp_call` 无生产调用点；`_ENGINES` 里 `"theme_rotation"` / `"dragon_return"` 下划线版无真实来源，仅测试引用。
- **前端**：`PulseWatchRail.vue:84-88` 的 `fmtPct` 与 `shared/lib/format.ts:16-20` 的 `pct()` 行为完全一致；`:79-93` 的 `fmtPrice`/`fmtScore` + 模板手写 `is-up`/`is-down`（`:200-212`）可直接换 `NumText`，连带删掉 `:358-377` 四段 scoped 样式。`pulseDragonLogic.ts:43-44` 的 `text: String(openBlocked)` 会把后端布尔 `true` 渲染成字面量 `"true"` 当作阻塞原因给用户看（真正的中文原因在 `auction_reason` / `role_basis`）；`:59` 的 `Number(...).toFixed(1)` 缺 `isFinite` 检查，band 缺边界时显示 `待价 NaN~NaN%`。`usePulseDragonPool.ts:160-164` 在池表折叠时（默认收起）仍每 8 秒轮询 `/market/board?live=true`。

---

## 八、建议执行顺序

1. **P0-1 + P0-2**：失语告警与规则退出修复。改动小、风险低、直接消除"当天静默不作为"这个最大风险面。
2. **P0-3**：跨线程 sqlite。独立于业务逻辑，可单独验证。
3. **P1-1 + P1-2 + P1-3**：三条"功能未生效"，都是小改动且各自有明确验收点。
4. **P1-4 + P1-5**：文案重复与跨日教训污染。
5. **P2-2**（加索引）可随时插入，一行 DDL。
6. **五节的注册表能力声明重构**：范围最大，建议单独一轮，前置条件是 P1-1 已修（否则重构与修 bug 混在一起难以回归）。
7. 七节的次要项按接触到哪块顺手清理，不单独开工。

---

## 附：验证状态

**已验证到代码行**：P0-1 全链路、P0-2 配置陷阱、P0-3 全链路（含 `MarketStore` 缺 `check_same_thread=False`、注入 store 经 `legacy_bridge.py:173` 进工作线程）、P1-2（生产调用点全部漏传，仅测试传参）、P1-3（`LEGACY_TOOL_TO_LANE` 确无该键）、P1-4（`thesis` 无条件追加而重入判据未被改写）、买入侧三层闸门有效、卖出侧执行层合法性校验完整、`execute_orders` 循环内更新 positions。

**来自审查报告、带行号但未逐条复跑**：P1-1、P1-5、P2 全部量级估算（如"7 万行临时排序""24 次串行远程日 K"为按默认参数推算）、五节扩展点统计、七节次要项。

**未做**：任何代码改动、性能实测、测试运行。
