# AI（ai）

手动「测试模型」发送一条短对话，使用 1024 输出 token 预算及供应商对话超时；
避免 `max_tokens=1` 被 B.AI 等兼容接口拒绝，空正文也不会显示测试成功。
保存供应商仍为离线操作，不自动测试或拉取模型目录。

LLM 请求遇到发送前的连接失败（含 TLS 握手中断）或连接超时时，等待 1 秒、2 秒各重试一次。
仅重试当前请求，保留 Agent 的工具结果；读写/流中断、HTTP 余额或参数错误不在该重试范围内，持续连接失败仍如实报错。
回归：`tests/ai/test_connection_retry.py`。

## 职责
通用 LLM 供应商、对话、Agent / toolbus。不发明数字。

## 边界
密钥明文存 ops.db（本机自用，与 MCP token 同口径；HTTP 只回末四位）。
模型目录（启停 / 上下文 / 输出上限）存在 ops.db `llm_providers.models_json`，由 `src.ops.normalize_models` 等维护。
启动时会清掉非明文的旧 ``encrypted_key`` 残留；请在运维页重录。

## 关键入口
`chat` / `chat_stream` / `chat_text_with_thinking_fallback` / `run_agent` / `build_toolbus`；HTTP：`/api/providers/*` `/api/ai/*`

空 completion 时降级 thinking 再试：`from src.ai import chat_text_with_thinking_fallback`（纸面盯盘与风格评头论足共用；语义不变）。

## 多租户：每用户独立的 LLM

隔离**不是**给表加 `user_id`，而是「换一个 data 根」：`src/shared/paths.ops_db()` 随
`src.shared.tenancy.current_tenant()` 变，`llm_providers` / `ai_*` 这些表天然一人一份。
所以本域真正的风险不在 SQL，而在**谁把路径提前算死了**——import 期的模块常量、
`build_*_router` 装配期的 `str(ops_db())`、构造期就绑好库的进程内单例。
这类 bug 不报错，只会静悄悄让所有人共用第一个解析出来的库。

### 审计结果（本批）

| 位置 | 问题 | 修法 |
|---|---|---|
| `api/assistant.py:build_assistant_router` | 装配期 `resolved_ops_db = str(ops_db or default_ops_db())`，router 是进程内装配一次的对象 → 全部用户共用装配那一刻的 ops.db | 改成闭包函数 `resolved_ops_db()`，`store()` / `/api/ai/tools` 每次调用现解析；显式入参仍优先 |
| `application/assistant_manager.py:AssistantManager.__init__` | `self.ops_db` / `self.palace_db` 在构造期定死；该对象是 router 里 new 一次的**进程内单例** | 改成 `@property`，经 `infrastructure/tenant_db.ops_db_for()` / `palace_db_for()` 每次读取现解析；`_ops_db_override` 保留显式钉库 |
| 同上，`monthly_token_budget` | 构造期把环境变量固化成一个进程级数字 | 改成 `@property`：显式覆盖 > 每用户配额 > 环境变量 |
| 同上，`recover_interrupted_runs()` | 只在构造期跑一次 → 只救得了装配那一刻那个租户，别人的中断 run 永远挂 `running` | `_recover_interrupted_once()`，按**解析后的库路径**（已含租户）记账，每租户首次 `start_run` 前各跑一次 |
| `infrastructure/providers.py:migrate_encrypted_llm_keys` | 默认 `OpsStore()`，落到 ops 的 import 期常量库 | 改用 `tenant_db.open_ops_store()`（按当前租户解析） |
| `infrastructure/providers.py:resolve_config` | 已核对：store 由调用方每请求新开，自身无缓存 | 无需改；调用方一律传每请求的 store |
| `src/ops/infrastructure/store_helpers.py:DEFAULT_DB = ops_db()` | **import 期求值**，`OpsStore(None)` 因此钉死在「最先 import 本模块时的那个租户」上。这是供应商隔离的真正拦路石 | `OpsStore.__init__` 改为每次构造调 `paths.ops_db()`；常量保留只为兼容旧 import（**本条越出了 `src/ai` 边界，但不改就没有隔离**） |
| 模块级可变缓存（探测结果 / 模型目录） | 逐个查过：`src/ai/**` 里没有模块级可变缓存；ops 的 `_SCHEMA_READY` 与新增的 `AssistantManager._recovered` 都以**解析后的库路径**为 key，已含租户 | 无需改；新增缓存必须沿用「key 含租户」这条 |

### 已知未修（不在本批授权范围，按影响排序）

| 位置 | 问题 | 建议修法 |
|---|---|---|
| `src/app/main.py:607` | 组合根在启动期把 `PALACE_OPS_DB` / `PALACE_DB` 读成字符串传进 `build_assistant_router`。env 只对主租户有意义（见 `paths._tenant_scoped`），传进来等于给所有租户钉同一个库 | 删掉这两个入参，交给本域惰性解析；本批已保证「传 `None` 就按租户解析」 |
| `src/ops/application/jobs/context.py:23` `DEFAULT_PALACE_DB` | 同上，任务侧账本回退路径 | 换成函数 |
| `src/strategy/application/converter.py:37` `DEFAULT_OPS_DB` | 同上，策略版本历史会写进别人的库 | 换成函数 |
| `src/market/infrastructure/store_schema.py:6` `DEFAULT_DB` | 行情库是**全局共享**的，不构成越权；但仍会让 `LOCI_DATA_DIR` 的运行时切换失效 | 低优先级，换成函数 |

### 后台线程与租户上下文

`ContextVar` **不跨** `threading.Thread` 与 `ThreadPoolExecutor` 边界（只有 asyncio Task 与
anyio 的 `run_in_threadpool` 会复制 Context）。从请求里裸起一条线程，线程内
`current_tenant()` 直接吃默认值落回 `PRIMARY_TENANT`——也就是**管理员的老 `data/`**。
这个 bug 不报错、不刷红，单机形态下 100% 观察不到。

所以本域（以及全仓）的规矩只有一条：**后台线程一律经 `src.shared.tenancy` 起**，
禁止 `threading.Thread(...)` / `executor.submit(...)`。

```python
from src.shared.tenancy import spawn_tenant_thread, submit_with_tenant

spawn_tenant_thread(worker, name="skill-run-x")      # 取代 threading.Thread(...).start()
submit_with_tenant(self._pool, self._run, run_id)    # 取代 self._pool.submit(...)
```

| 位置 | 原来 | 现在 | 不改会怎样 |
|---|---|---|---|
| `application/assistant_manager.py:start_run` | `self._pool.submit(self._run, …)` | `submit_with_tenant` | run 行建在发起用户库、`_run` 在主租户库里 `get_run` 查不到 → 直接 return，**会话永久卡 `running`**，静默失败 |
| `application/assistant_evidence_agents.py:run_evidence_agents` | `pool.submit(run_one, …)` | 同上 | 证据子 Agent 的只读工具面读到管理员的行情/账本，还当成用户自己的证据讲出来 |
| `application/multi_agent.py:run_ammo_agents` | `pool.submit(_one, …)` | 同上 | 弹药子 agent 用主租户的技能目录与 `mcp.json`（= 管理员的悟道 Key） |

同一批还改了域外的四处（同一个失效模式，注释都写在调用点）：
`src/ops/api/skill_runs_api.py`（skill run / reply 两条）、`src/strategy/api/router.py`
（即时对比与退出扫描）、`src/research/api/router.py` 与 `factor_router.py` 的两个模块级
`ThreadPoolExecutor`。

注意事项：

- `submit_with_tenant` 复制的是**提交那一刻**的 Context。池子的工作线程是复用的，
  它们自己的 Context 停在线程创建那一刻，与任何请求都无关——所以「池子只建一次」
  不是可以裸 submit 的理由，恰恰是必须包装的理由。
- **嵌套扇出也要包**：worker 里再起的线程池会把上下文再丢一次。
- 进程级可变缓存同理：key 必须含租户（范式见 `src/ops/application/notify_registry._recent`
  与 `src/intel/infrastructure/quota._INFLIGHT`）。`AssistantManager._recovered` 用的是
  **解析后的库路径**做 key，已经含租户，属于同一条纪律的另一种写法。
- **拆文件时守卫清单要跟着走**：`tests/ai/test_tenant_threads.py::_GUARDED_FILES` 是那条
  AST 源码守卫的扫描清单。把带线程/池的代码搬进新文件却不登记，守卫就出现盲区——
  且盲区不会报错，用例照样绿。`application/assistant_run_executor.py`（`_run` 段的新家）
  已经登记在册。
- 回归：`tests/ai/test_tenant_threads.py`（含一条 AST 源码守卫，直接拦 revert）、
  `tests/ops/test_skill_run_tenant_threads.py`、`tests/strategy/test_analysis_tenant_threads.py`、
  `tests/research/test_research_tenant_threads.py`。

### 上游结束原因

流式适配器保留OpenAI `finish_reason`和Anthropic `stop_reason`，AgentResult.finish_reason及to_dict原样带给调用方；stopped_reason仍表示本地工具循环结束原因。结构化报告须区分正常结束与length/max_tokens截断，不能仅凭循环completed保存成功。

### 额度与计费

- `application/quota.py` 是唯一入口：`current_llm_quota()` / `check_llm_quota()` / `record_llm_usage()` / `QuotaExceeded`，包根也导出（`from src.ai import check_llm_quota, record_llm_usage`）。
- 跨上下文只经 `from src.identity import IdentityStore`（包根），禁止深路径。当前用户 = `current_tenant()` → `SELECT id FROM users WHERE tenant_id=?`。
- **降级优先于正确**：identity 打不开、schema 没建、该租户没账号，一律退回环境变量，绝不因为配额读不出来就把 AI 停掉。计费失败同理，只记 `warning`。
- 用量写当前租户 `ops.db:ai_usage_daily`（配额判定的权威口径），并**尽力**回写 identity `usage_counters`（`llm_tokens` / `llm_calls`，供管理员跨租户盘点，失败即忽略）。
- **任务侧计费缺口已补**（原来 `ai_usage_daily` 只覆盖助手会话，月度用量系统性低估）：
  | 调用点 | 覆盖的任务 |
  |---|---|
  | `infrastructure/chat_retry.py:chat_text_with_thinking_fallback` | 纸面盯盘（`jobs/paper_monitor_llm.py`）、风格复盘（`paper_style_memory.py`）；**两档 thinking 各记一笔**，降级重试是真花了两次钱 |
  | `src/ops/application/jobs/screen.py:_ai_pick_codes` | AI 精选选股；解析失败回退也照记 |
  | `src/ops/application/skill_watch/runner.py:_ai_summary` | 战法监测摘要 |
  | `src/ops/application/jobs/skill.py:execute_skill` | 技能定时任务（`run_agent` 整条工具链的加总） |
  | `src/ops/application/skill_runtime.py:_drive` | 对话式技能 run（HITL 续跑逐次记） |
  任务侧一律显式传 `ops_db=`（调用方手里那条库路径），别让用量写去另一个租户的库。

### 分享包

`ai_sessions` / `ai_messages` / `ai_agent_runs` / `ai_agent_events` / `ai_usage_daily` /
`ai_execution_grants` / `ai_assistant_profile` / `ai_memories` 全部登记进
`src/ops/application/share_pack_sanitize.PERSONAL_TABLES`（此前八张一张都没登记，
分享包会把对话原文与个人画像记忆一起外发）。新增 AI 表只要命中
`PERSONAL_TABLE_PREFIXES`（`ai_` / `paper_mem`）就必须一起登记，
`tests/ai/test_share_pack_ai_tables.py` 对着真实建出来的 ops.db 卡这条回归。

## 全局助手
`/api/ai/*` 维护会话、运行、轮询 / SSE 事件、静态工具目录、画像与记忆。`owner_full` 助手可以在应用内读取行情/战法、写入候选池与预案复盘，管理已配置厂商，并创建、更新、立即运行受控运维任务。**助手不再有任何持仓、成交、出入金入口**。

- 工具面固定在 `application/system_toolbus.py`（注册/授权/执行壳）；入口执行最小 JSON Schema 校验、只读助手写权限拒绝、工具 receipt 与可选 timeout；成功结果构造在 `system_tool_result.ok`（正文截断 12k）；账本与潜龙分别在 `system_toolbus_ledger.py`、`system_toolbus_qianlong.py`；市场、战法、研究、记忆、运维工具在对应 `system_toolbus_*.py`；**外网** `web_search` / `web_fetch` 在 `system_toolbus_web.py`；**默认挂载**活跃 MCP（`system_toolbus_mcp.py`，上限 48；`attach_mcp=False` 可跳过，只读子 Agent 使用；`allow_tools` 可再裁角色白名单；`LOCI_MCP_TOOL_TIMEOUT_SEC` 可设单工具预算）。Skill `ToolBus` 与助手 `SystemToolBus` 各自保留安全面，仅共享 `application/tool_schema.py`（schema + 无状态 MCP 调用包装；`clamp_mcp_arguments` 裁 limit/codes 防扫池无上限）。账本工具面只剩候选池 / 预案 / 复盘三类写工具（`ledger_upsert_candidate`、`ledger_delete_candidate`、`ledger_delete_candidate_pool`、`ledger_record_plan`、`ledger_record_review`）——**持仓 / 成交 / 现金 / 账户快照工具随实盘账本一起下线，盯市盈亏封装 `attach_mark_prices` 一并移除**。`tool_end.preview` 由 `system_toolbus_preview.py` 本机收成中文摘要，不把 JSON 原文甩给 UI。`research_catalog` / `research_profile` 只返回维度、质量、缺口、来源 ID 和证据 hash。仍不提供 raw SQL、shell、任意文件、券商真实下单。斜杠技能把 `data/skills/<slug>/SKILL.md` 注入本轮 system（`assistant_skill_prompt.py`）。
- **外网工具的 SSRF 护栏**（`system_toolbus_web.py`）：`web_search` / `web_fetch` 是 `write=False` 工具，LLM 与只读子 Agent 不用 `ExecutionGrant` 就能点名 URL，而本仓还会经 `deploy/` 上公网服务器。所以出站目标一律**解析成 IP 后**用 `ipaddress` 判公网：回环 / 私网 / 链路本地（含 `169.254.169.254` 云元数据）/ 保留 / 组播 / 未指定 / CGNAT 全拒，`127.1`、十进制 `2130706433`、`::ffff:127.0.0.1`、6to4 这类写法先归一再判；**httpx 的 `follow_redirects` 已关闭**，改由 `_get_guarded` 手动跟跳（≤5 跳，**每跳重新校验**）——修之前主机检查只做在用户给的那一个 URL 上，一句 `302 Location: http://169.254.169.254/…` 就能取走云凭据。唯一例外：**DNS 名**解析到 Clash/Surge Fake-IP 段 `198.18/15` 放行（代理产物，与 `src/intel` MCP 校验同口径；写成字面量仍拒）。拒绝文案为中文且**不回显解析到的地址**，免得工具变成内网探测器。超时 18s、正文 12k 上限不变。
- **外网工具的出网代理**（`LOCI_WEB_TOOL_PROXY`，`system_toolbus_web._web_proxy`）：`web_search` / `web_fetch` **专用**，不配置就传 `proxy=None`、交回 httpx 的 `trust_env`（开发机原有走法不受影响）。**为什么不复用全局 `HTTP_PROXY`**：同一个进程还要拉 akshare / 腾讯 / 新浪 / 通达信这些**国内**行情源，全局代理会把它们一起绕到境外出口——又慢又容易直接断，而行情是这套系统的命根子。生产实测（2026-08-26，容器内）：直连 `html.duckduckgo.com` 报 `Network is unreachable`，经宿主 `172.17.0.1:7890` 是 **380ms / HTTP 202**；不配这一行，助手在国内服务器上永远只会回「外网调研暂时不可达」。**走代理不放松 SSRF 护栏**：`_guard_url` 判的是目标 URL 解析出来的地址，与走不走代理无关（代理自身是私网地址也不受影响——它不是被校验的目标）。回归 `tests/ai/test_system_toolbus_web_proxy.py`
- 战法选股工具的 `picks/pick_count` 只表示正式信号；弱市低吸观察另放 `watch_picks/watch_count`，不得由 Agent 合并后声称为正式精选。
- **归档** = `status=archived`（可恢复）；**删除** = 永久清除会话及 messages/runs/events；`ai_execution_grants` 保留审计。`POST /api/ai/sessions/batch` 支持批量 archive/unarchive/delete。
- **个性化**：`ai_assistant_profile`（指令/规则/记忆开关）与 `ai_memories`（user/memory 双仓，设置页按整段 Markdown 编辑）在 ops.db。Core Safety Prompt 不可被客户端覆盖；用户指令、规则与记忆以冻结快照追加注入。产品默认规则/回答偏好与 `source=builtin` 记忆文档见 `domain/assistant_defaults.py`（`PRODUCT_DEFAULTS_VERSION`；首次落库、版本升级补种旧产品种子、`POST /api/ai/profile/reset-defaults`）。自动记忆频率默认 **20** 条（范围 5–100）。详见 [`docs/architecture/ai-assistant-personalization.md`](../../docs/architecture/ai-assistant-personalization.md)。
- 会话标题：首条用户消息写入时若仍为占位（空/`新对话`），先用消息截断作临时标题并发 `session_title`；首轮成功收口后用当前模型精炼 8～18 字中文标题再发一次（`title_source=llm`）。`PATCH` 手动改名写入 `title_locked`，之后不再自动覆盖。逻辑在 `application/assistant_session_title.py`。
- 写入由 `AssistantManager` 自动签发绑定本次运行、工具和参数摘要的 `ExecutionGrant`；它提供单次消费、幂等与审计，不要求逐笔匹配用户原话。
- 同一会话同一时刻只允许一条运行；应用启动会把无法跨进程续跑的遗留 `running` 记录标记为中断失败，并保留事件与错误原因。`waiting_user` 跨重启保留，用户仍可回复后**同 run_id resume**。
- HITL：仅 `waiting_user` / `ask_user`（无独立「工具回执等待确认」事件）。工具要求用户确认时，run/session 进入 `waiting_user`（不发 `done`）。主环 `allow_hitl=True`；系统工具面内置 `ask_user`（以及 Skill 同名内置）。`ask_user` 支持旧单题 `prompt`+`options`，以及多题 `questions[{id,prompt,options?,allow_free_text?}]`（无 `questions` 时旧参数仍可用；缺 `prompt` 且无 `questions` → `is_error`）。`pending_ask` / 消息 `hitl` 持久化完整 `questions`；暂停时把 agent transcript 写入 `result.agent_messages`。用户再次 `POST .../messages`（正文可为结构化多题答案）走 `resume_waiting_run`：**同一 `run_id` 回到 `running`**，用户正文覆盖末条 HITL tool result 后续 `run_agent`；也可 `POST .../cancel` 直接取消等待。`GET /api/ai/sessions/{id}` 回可选 `active_run`（占用中的 `running` / `waiting_user`，含事件 `cursor` 与 `pending_ask`）；归档/删除在 `running` 或 `waiting_user` 时拒绝。`public_run` 不会把已 `completed` 的 run 因残留 `cancel_requested` 伪装成 `cancelled`。消息 metadata 折叠含 `hitl`。
- 取消：`cancel_run` 对 `running` / `waiting_user` **立即**落 `cancelled` 并释放会话为 `idle`，以便马上发下一轮；worker 见 `cancel_requested` 后幂等收口（`finish_run` 对已终态 no-op）。助手落库走 `append_assistant_if_run_active`（仅 `running` 且未取消），避免取消后迟到正文插到新 user 之后；`done` 仅在 `finish_run(completed)` 真正生效后发出。
- 多轮喂模：`list_messages` 最近 **200** 条组历史后，优先读 `session.metadata.context_feed`（手动 `/compact` 或上次自动压缩写入的喂模快照）再拼 `through_seq` 之后新消息；否则全量历史。再按 `context_compact` 对**喂模 messages** 做自动压缩（超可用窗 70% 才压；保留近 6 轮原文；更早轮确定性摘要，可选 LLM summarizer；失败头尾拼接，禁止静默丢光）。**手动** `AssistantManager.compact_session` / `POST .../compact` 以 `force=True` 无视阈值强制压，结果写入 `context_feed`。**不删不改 SQLite 会话原文**；与 `maybe_auto_consolidate_memory` 独立。压缩时发 SSE `context_compacted`（折叠进本轮 `warnings`）；前端用量环与时间线可见「已压缩」。**跳过空正文且无附图的 assistant**（取消/落库竞态残留），避免污染下一轮上下文。
- 新 run 会在持久化用户消息前过一次**每用户配额**（`application/quota.py`）：月度输入+输出 Token 与当日调用次数都判，用尽直接拒绝本轮。额度取自 `identity.db` 的 `user_quotas`（`llm_monthly_tokens` / `llm_daily_calls`；`0`=用系统默认，负数=不限），身份库不可用或该租户还没建账号时降级回 `LOCI_AI_MONTHLY_TOKEN_BUDGET` / `LOCI_AI_DAILY_CALL_BUDGET`（默认 `1_000_000` / 不限）。`AssistantManager(monthly_token_budget=...)` 显式传值仍然最优先（测试与单机钉额度）。
- **运行次数配额（可选）**：`LOCI_AI_ASSISTANT_RUN_MONTHLY_QUOTA`（默认 `0`=不限）；`>0` 时在 `start_run` 按自然月计数硬拒绝。监测/纸面盯盘 LLM 走任务侧调用，不计入该助手 run 配额。
- `GET /api/ai/runs/{run_id}/events` 保持 JSON 轮询兼容；`GET /api/ai/runs/{run_id}/events/stream` 以 `id` / `event` / JSON `data` 重放并跟随同一持久化事件流，支持 `after` 和 `Last-Event-ID` 续接；遇到 `done` / `error` / `cancelled` / `waiting_user` 结束跟随。助手主环默认走真流式 `chat_stream`：有供应商原生 reasoning 时发 `think`（`{delta}`），正文增量发 `token`（`{delta}`）；无 reasoning 则不发 `think`。流式 `token`/`think` 由 `StreamEventBuffer` 内存合并后批写（≥120 字符或 ≥120ms，或遇其它事件/收口前 flush）；同 run 复用一条 `AssistantStore` 连接写事件，避免每次 flush 开库。SSE/轮询仍只读持久化事件。流式不可用时降级非流式，仅靠终稿 `done`（仍含与 `ai_messages` 一致的 `text`/`content`）。`artifact` 可带 `status`：`loading` / `ready`（如 `market_kline`）。
- **富状态持久化（ADR-006）**：assistant 消息在 run 收口写入时，把本轮 `think` / `tool_*` / `artifact` / `warning` / `subagent_*` 事件折叠进 `ai_messages.metadata_json` 约定键 `thinking`、`tool_receipts`、`artifacts`、`warnings`、`agents`（不建旁表）。user 附图写入同表 `images`（data URL，最多 4 张）。`GET /api/ai/sessions/{id}` 的 `messages[]` 经 `public_message` 透出这些键；旧消息无键则省略。**角色化只读证据子 Agent**（`application/assistant_evidence_agents.py`）：按话术选 ≤3 角色（`market` / `qianlong` / `web` / `research`；账本角色随持仓工具一并撤除），`read_only` + `attach_mcp=False` + `allow_tools` 白名单；仅 `web` 可调 `web_search`/`web_fetch`。侧栏仍发 `subagent_*` / `plan`（工具起止另发 `subagent_tool`，折叠进 `agents[].tool_receipts`，progress/end 保留回执）；主环注入截断 brief（每角 ≤800 字、合计 ≤2400），标明非终裁，数字须主环工具复核。折叠逻辑：`application/assistant_rich_state.py`。思考档位：`off`/`low`/`medium`/`high`/`xhigh`/`max`（OpenAI `reasoning_effort` / Anthropic budget）。**空终稿恢复（对齐 Hermes / OpenClaw）**：工具后一轮正文为空时，按 Hermes 插入 `assistant("(empty)")` + user nudge（「process the tool results…」），**工具 schema 全程保持**；催完仍空再按 OpenClaw `EMPTY_RESPONSE_RETRY_INSTRUCTION`（若本轮只流式 `think` 则用 `REASONING_ONLY_RETRY_INSTRUCTION`）再催一轮。`visible_text` 会剥 think 标签。空回复恢复有 `RECOVERY_ROUND_SLACK=3`，不被 `max_rounds` 饿死；slack 耗尽仍空 → `empty_completion`（禁止伪装 `max_rounds`/`done`）。`llm_error` 后不清用工具前旁白。收口前清掉**全部**合成 scaffolding（含 HITL 中间夹层）。`emit_terminal_event` 对 `empty_completion`/`llm_error*` 发 `error` 而非 `done`。manager 落 `failed`+`error`；`public_message` 带 `status=error`；前端覆盖计划旁白，`finishRun` 空二次 settle 不冲失败文案。证据子 Agent 以 `stopped_reason==completed` 计 `ok`。
- 潜龙提交必须先读取同日同池的整池和本机日 K 证据，且提交代码与候选池完全一致；精选上限仍为两只。
- `sync` / `screen` / `backtest` / `compare` / `optimize` / `prune` / `outcome` 任务可由助手管理。写入后重载调度器；立即运行以当前工作台的 `market_db` / `palace_db` 执行，并让 AI run 保持运行直到后台任务收尾。

### 不许把「没取到」讲成「数据显示」

模型**只看得到工具结果的 `text`**，`structured` / `truncated` / `clamped` 这些旁路字段进不了它的上下文。凡是会缩小或砍掉结果的地方，都必须写进 `text`：

- `system_tool_result.ok()` 正文超 12k 时追加显式截断说明并返回 `truncated=True`；半截 JSON 不标注，模型会当成全量去数行、去求和。
- 悟道/外部 MCP 走 `guarded_client_call`，参数被裁或正文被截断时 `text` 末尾追加 `[取数范围提示] …`。
- 工具失败一律 `is_error=True` 由 `run_agent` 原样转述给模型（见 `tests/intel/test_intel.py::AgentLoopTests`），**禁止**返回空结果糊弄——空结果会被读成「查到了但今天没有」。
- 撞 `max_rounds` 时不发终稿：拒绝那一轮的响应文本是工具前旁白（「我再查一轮资金流」），不是结论，必须丢弃，只留「已达到轮数上限」的说明。`AgentResult.rounds` 只计已完成轮次；模型仍可在硬顶后用 slack 轮收口（`tests/ai/test_agent_round_limit.py`）。

**AI 能落库的数字**：写工具都要 `ExecutionGrant`，落库带 `source="ai_assistant"` 与幂等键，可审计。但 `ledger_record_review(return_pct…)` 接受的是**模型转述的数字**——它是「替用户记一笔」，不是复盘引擎的产出。禁止把这些值当权威复盘口径回读；复盘数字只认 `src.review` 由账本+行情算出的结果。行情侧无写路径：`src/ai` 只读 `MarketStore`，AI 不能把自己算的价格写进 `market.db`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/providers` | 列表；含 `model_catalog` + 启用 id 列表 `models` |
| POST | `/api/providers` | 新建/更新供应商（可发现模型） |
| POST | `/api/providers/{name}/models` | 拉取并**合并**进目录 |
| PUT | `/api/providers/{name}/models` | 整表保存目录与默认模型 |
| POST | `/api/providers/{name}/default` | 设默认供应商 |
| POST | `/api/providers/{name}/test` | 探针 |
| DELETE | `/api/providers/{name}` | 删除 |

## 助手链路的文件清单与职责划分

全仓硬规则是**单文件 ≤ 600 行**，助手这条链路最容易堆。两处门面已按「一组内聚职责
搬出去」拆开，新增切片必须归进同一套命名，不要另起一套：

### `application/`：run 编排（原 `assistant_manager.py` 708 行）

| 文件 | 职责 | 边界 |
|---|---|---|
| `assistant_manager.py` | **进池之前**：会话/归档校验、`resolve_config`、每用户配额与 run 配额、建 run 行与首条用户消息、`submit_with_tenant` 投递、`cancel_run` / `close`、手动 `compact_session`；线程池与惰性库路径属性（`ops_db` / `palace_db` / `monthly_token_budget`）都在这里 | 不放 worker 里的业务；`ops_db` 属性**每次读取现解析、绝不缓存** |
| `assistant_run_executor.py` | **进池之后**：`AssistantRunExecutorMixin`（`_run` / `_run_with_event_store`）——建工具面与 grant 回调、证据子 Agent、自动压缩、主环 `run_agent`、HITL 暂停、收口落库与 done、标题/记忆收尾 | 由 `AssistantManager` 混入，只经宿主属性拿库路径；登记在租户线程守卫清单里 |
| `assistant_context_feed.py` | 喂模上下文：`history_to_chat_messages` / `feed_messages_for_session` / `context_feed_payload`（`session.metadata.context_feed` 快照的统一构造） | 手动 `/compact` 与自动压缩共用同一份构造，避免两处漂移；不碰库原文 |

其余同前缀模块各管一段：`assistant_prompt`（system 拼装）、`assistant_images`、
`assistant_memory`、`assistant_session_title`、`assistant_skill_prompt`、
`assistant_rich_state`（ADR-006 折叠）、`assistant_stream_buffer`、
`assistant_evidence_agents`、`context_compact` / `context_usage`、`quota`。

### `infrastructure/`：`AssistantStore`（原 616 行）

沿用仓内 mixin 拆分范式（对照 `src/ops/infrastructure/store.py`、
`src/identity/infrastructure/store.py`）：

| 文件 | 职责 |
|---|---|
| `assistant_store.py` | 门面：连接 / PRAGMA / `_tx`，以及会话、消息、run、事件、用量的直接读写；混入下列 mixin |
| `assistant_store_schema.py` | 六张表的建表 DDL 常量 `ASSISTANT_SCHEMA_DDL`（画像/记忆两张表除外，见下） |
| `assistant_store_lifecycle.py` | run 生命周期 mixin：取消、HITL 暂停/续跑、中断恢复、`finish_run`、`TERMINAL_EVENT_TYPES` |
| `assistant_store_profile.py` | 画像与双仓记忆 mixin，自带 `_ensure_profile_schema` 补建（旧库升级路径，所以不并进 schema 常量） |
| `assistant_store_grants.py` | `ExecutionGrant` mixin：签发 / 消费 / 收口，只管 `ai_execution_grants` 一张表 |
| `assistant_store_util.py` | 共享小工具：脱敏 `redact`、`_dump` / `_load` / `_hash` / `_now` |

新加一组表的读写 → 再切一个 `assistant_store_<域>.py` mixin 挂上去；新加表还要同步
`share_pack_sanitize.PERSONAL_TABLES`（见「分享包」）。

## 如何扩展
新工具挂 toolbus；新协议扩展 infrastructure/client。
`resolve_config` / `get_model_entry` 带上目录里的 `context_window` / `max_output_tokens`；Agent 每次模型请求由 `agent_budget.py` 按已知容量和剩余时间计算预算。

## 给 Agent 的用法
- 对话：`from src.ai import chat, chat_stream, chat_text_with_thinking_fallback, ChatMessage, ToolCall, resolve_config`
- 配额 / 计费：`from src.ai import check_llm_quota, record_llm_usage, current_llm_quota, QuotaExceeded`（任务侧记账务必传 `ops_db=`，见「多租户」一节）
- 目录：`from src.ai import get_model_entry, update_provider_models`；规范化也可 `from src.ops import normalize_models, merge_discovered`
- Agent/工具：`application/agent.py`、`application/toolbus.py`、`application/system_toolbus.py`（本域也可 `from src.ai import ...`）
- 新增工具出口：结果一律经 `system_tool_result.ok()`（自带截断标记）；任何裁剪/截断/降级都要能被模型从 `text` 里读到
- 禁忌：生成权威行情/盈亏数字；把工具失败或被裁剪的结果讲成完整事实；跨上下文深掏兄弟域 `infrastructure`

## README 维护
改协议、工具清单、密钥处理、模型目录字段时必须更新本文。

## 相关测试
`tests/ai/`（含 `test_chat_thinking_fallback.py`、`test_assistant_evidence_agents.py`、`test_system_toolbus_contract.py`、`test_system_toolbus_web_ssrf.py`、`test_toolbus_observability.py`、`test_assistant_rich_state.py`、`test_context_compact.py`、`test_quota.py`、`test_tenant_isolation.py`、`test_tenant_threads.py`、`test_task_side_billing.py`、`test_share_pack_ai_tables.py`） · `tests/ops/test_model_catalog.py` · `tests/app/test_quant_api.py`（providers）
## Agent 执行、容量与交易员证据

`run_agent` 的 `max_tool_result_chars` 默认12000，`None` 保留完整工具正文。交易员使用完整正文；超长材料由自身的 `ResearchContext` 保存原文、SHA-256和分页入口，容量不足不能解释为查无数据。成功和异常终止均由 `evidence_snapshot` 在档案锁内深拷贝回执/文档，取消后的迟到工具不能修改已收口快照。完整执行边界见[交易员执行契约](../../docs/guardian-execution.md)。

`agent_execution.py` 只并发调用方通过 `parallel_tool_names` 明确允许的独立只读工具，且受 `max_parallel_tools` 限制；默认不自动推断工具安全性。连续白名单请求可成组并行，白名单外请求形成顺序屏障，最终结果按模型原请求顺序回填。`ask_user` 不并发；暂停后的工具请求仍保留未执行回执。
每次提交通过 `submit_with_tenant` 复制当前ContextVar；并发上限同时限制在途提交数。超过 `max_calls_per_round` 的每个请求ID都得到 `TOOL_NOT_EXECUTED`、`executed=false` 回执，不丢弃协议里的工具请求。MCP调用方还须保证可变客户端会话不跨线程/租户共享，不能只复制租户而共享session和request ID。

`deadline` 是单调时钟绝对截止时刻。`agent_budget.request_config` 为每次请求及流式降级复制配置，将超时压到剩余预算；不修改共享供应商配置。取消、运维超时和协作式终止沿异常原因链传播，不能被包装成普通工具错误继续研究。未派发调用停止提交，已开始的同步只读调用不能由Python强杀，其迟到结果不得用于成交。

`agent_budget.output_budget` 仅用明确配置的上下文窗口与输出上限。文本估算包含system、历史消息、工具schema、参数、调用ID和原始 `reasoning_content`；输出预算不超过已知窗口扣除估算输入后的余量。输入已超限或思考档位所需预算不足时明确报错，不静默删除消息、工具证据或推理。未知窗口不猜默认容量；图像token由上游编码决定，不按data URL的base64长度估算，文本预检不保证多模态请求一定可容纳。

`agent_usage.py` 用ContextVar隔离每次Agent调用的已知用量；模型响应返回后即计入本次累计，随后取消也不漏记。异常携带本次调用增量，交易员 `run_accounted_agent` 分别记录研究、完整性修复和预检修正的增量，再累加到整轮诊断，不能重复记整轮累计。上游未返回的在途用量不猜测。

`stopped_reason` 是本地循环状态，`finish_reason` / `stop_reason` 是上游结束状态。交易员成功须同时满足本地completed、上游stop/end_turn和完整schema，缺失结束原因不能直接放行；不完整正文最多一次无工具修复，仍须通过同一契约。`thinking_requested` 只记录请求的档位或 `provider_default`，不证明上游实际启用该档位或采用何种内部推理。返回的原始推理字段仍按下文规则回传。

相关回归入口：`tests/ai/test_agent_execution.py`、`test_agent_budget.py`、`test_agent_usage.py`，以及 `tests/ops/test_guardian_agent_repair.py`、`test_guardian_usage.py`；测试结果以实际运行记录为准。

## 保存模型配置

供应商保存默认不校验 Key、不请求模型列表，前端“保存”直接落库。连通测试与模型目录刷新
由用户单独触发；显式调用 `save_provider(validate=True)` 仍可用于主动验证。上下文容量是用户配置值。

### DeepSeek 多轮推理回传

OpenAI兼容接口的 `reasoning_content` 由流式/非流式响应原样保留到 ChatResponse，工具轮写入 ChatMessage，后续请求与 Agent 消息快照继续携带；HITL 暂停和恢复不丢字段。None 表示上游未提供，空字符串表示提供了空字段，不互相替换；不会给其他供应商凭空注入推理字段。

序列化集中在 `application/agent_messages.py`，原 `agent.messages_to_json/messages_from_json` 入口保留。推理不混入工具结果或最终正文，也不按工具展示长度截断。

回归：`tests/ai/test_reasoning_content.py` 覆盖6轮12次工具调用、长推理分片、空值与HITL续跑。

携带工具定义时，DeepSeek要求非工具回合也回传推理：推理空回复恢复与最终回复的推理都进入消息快照，后续续问仍保留。依据 https://api-docs.deepseek.com/guides/thinking_mode/ 。

### 自适应研究容量（2026-09-15）

run_agent支持max_rounds=None（必须提供真实deadline）与max_calls_per_round=None。交易员研判/咨询/报告使用该模式，不再在16/8/5轮或12/6次调用处人为停止；其他调用方显式上限保持原契约。并发仍控制同时在途工作量，所有请求ID与已返回证据保留。agent_mcp.py承接MCP路由及轨迹格式化，agent.py继续兼容导出。交易员三个研究入口使用实际选定的thinking，并按run_accounted_agent记录成功和异常的用量增量；报告/咨询修复不伪造成功正文。
