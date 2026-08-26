# AI（ai）

## 职责
通用 LLM 供应商、对话、Agent / toolbus。不发明数字。

## 边界
密钥明文存 ops.db（本机自用，与 MCP token 同口径；HTTP 只回末四位）。
模型目录（启停 / 上下文 / 输出上限）存在 ops.db `llm_providers.models_json`，由 `src.ops.normalize_models` 等维护。
启动时会清掉非明文的旧 ``encrypted_key`` 残留；请在运维页重录。

## 关键入口
`chat` / `chat_stream` / `chat_text_with_thinking_fallback` / `run_agent` / `build_toolbus`；HTTP：`/api/providers/*` `/api/ai/*`

空 completion 时降级 thinking 再试：`from src.ai import chat_text_with_thinking_fallback`（纸面盯盘与风格评头论足共用；语义不变）。

## 全局助手
`/api/ai/*` 维护会话、运行、轮询 / SSE 事件、静态工具目录、画像与记忆。`owner_full` 助手可以在应用内读取行情/战法、写入候选池与预案复盘，管理已配置厂商，并创建、更新、立即运行受控运维任务。**助手不再有任何持仓、成交、出入金入口**。

- 工具面固定在 `application/system_toolbus.py`（注册/授权/执行壳）；入口执行最小 JSON Schema 校验、只读助手写权限拒绝、工具 receipt 与可选 timeout；成功结果构造在 `system_tool_result.ok`（正文截断 12k）；账本与潜龙分别在 `system_toolbus_ledger.py`、`system_toolbus_qianlong.py`；市场、战法、研究、记忆、运维工具在对应 `system_toolbus_*.py`；**外网** `web_search` / `web_fetch` 在 `system_toolbus_web.py`；**默认挂载**活跃 MCP（`system_toolbus_mcp.py`，上限 48；`attach_mcp=False` 可跳过，只读子 Agent 使用；`allow_tools` 可再裁角色白名单；`LOCI_MCP_TOOL_TIMEOUT_SEC` 可设单工具预算）。Skill `ToolBus` 与助手 `SystemToolBus` 各自保留安全面，仅共享 `application/tool_schema.py`（schema + 无状态 MCP 调用包装；`clamp_mcp_arguments` 裁 limit/codes 防扫池无上限）。账本工具面只剩候选池 / 预案 / 复盘三类写工具（`ledger_upsert_candidate`、`ledger_delete_candidate`、`ledger_delete_candidate_pool`、`ledger_record_plan`、`ledger_record_review`）——**持仓 / 成交 / 现金 / 账户快照工具随实盘账本一起下线，盯市盈亏封装 `attach_mark_prices` 一并移除**。`tool_end.preview` 由 `system_toolbus_preview.py` 本机收成中文摘要，不把 JSON 原文甩给 UI。`research_catalog` / `research_profile` 只返回维度、质量、缺口、来源 ID 和证据 hash。仍不提供 raw SQL、shell、任意文件、券商真实下单。斜杠技能把 `data/skills/<slug>/SKILL.md` 注入本轮 system（`assistant_skill_prompt.py`）。
- **外网工具的 SSRF 护栏**（`system_toolbus_web.py`）：`web_search` / `web_fetch` 是 `write=False` 工具，LLM 与只读子 Agent 不用 `ExecutionGrant` 就能点名 URL，而本仓还会经 `deploy/` 上公网服务器。所以出站目标一律**解析成 IP 后**用 `ipaddress` 判公网：回环 / 私网 / 链路本地（含 `169.254.169.254` 云元数据）/ 保留 / 组播 / 未指定 / CGNAT 全拒，`127.1`、十进制 `2130706433`、`::ffff:127.0.0.1`、6to4 这类写法先归一再判；**httpx 的 `follow_redirects` 已关闭**，改由 `_get_guarded` 手动跟跳（≤5 跳，**每跳重新校验**）——修之前主机检查只做在用户给的那一个 URL 上，一句 `302 Location: http://169.254.169.254/…` 就能取走云凭据。唯一例外：**DNS 名**解析到 Clash/Surge Fake-IP 段 `198.18/15` 放行（代理产物，与 `src/intel` MCP 校验同口径；写成字面量仍拒）。拒绝文案为中文且**不回显解析到的地址**，免得工具变成内网探测器。超时 18s、正文 12k 上限不变。
- 战法选股工具的 `picks/pick_count` 只表示正式信号；弱市低吸观察另放 `watch_picks/watch_count`，不得由 Agent 合并后声称为正式精选。
- **归档** = `status=archived`（可恢复）；**删除** = 永久清除会话及 messages/runs/events；`ai_execution_grants` 保留审计。`POST /api/ai/sessions/batch` 支持批量 archive/unarchive/delete。
- **个性化**：`ai_assistant_profile`（指令/规则/记忆开关）与 `ai_memories`（user/memory 双仓，设置页按整段 Markdown 编辑）在 ops.db。Core Safety Prompt 不可被客户端覆盖；用户指令、规则与记忆以冻结快照追加注入。产品默认规则/回答偏好与 `source=builtin` 记忆文档见 `domain/assistant_defaults.py`（`PRODUCT_DEFAULTS_VERSION`；首次落库、版本升级补种旧产品种子、`POST /api/ai/profile/reset-defaults`）。自动记忆频率默认 **20** 条（范围 5–100）。详见 [`docs/architecture/ai-assistant-personalization.md`](../../docs/architecture/ai-assistant-personalization.md)。
- 会话标题：首条用户消息写入时若仍为占位（空/`新对话`），先用消息截断作临时标题并发 `session_title`；首轮成功收口后用当前模型精炼 8～18 字中文标题再发一次（`title_source=llm`）。`PATCH` 手动改名写入 `title_locked`，之后不再自动覆盖。逻辑在 `application/assistant_session_title.py`。
- 写入由 `AssistantManager` 自动签发绑定本次运行、工具和参数摘要的 `ExecutionGrant`；它提供单次消费、幂等与审计，不要求逐笔匹配用户原话。
- 同一会话同一时刻只允许一条运行；应用启动会把无法跨进程续跑的遗留 `running` 记录标记为中断失败，并保留事件与错误原因。`waiting_user` 跨重启保留，用户仍可回复后**同 run_id resume**。
- HITL：仅 `waiting_user` / `ask_user`（无独立「工具回执等待确认」事件）。工具要求用户确认时，run/session 进入 `waiting_user`（不发 `done`）。主环 `allow_hitl=True`；系统工具面内置 `ask_user`（以及 Skill 同名内置）。`ask_user` 支持旧单题 `prompt`+`options`，以及多题 `questions[{id,prompt,options?,allow_free_text?}]`（无 `questions` 时旧参数仍可用；缺 `prompt` 且无 `questions` → `is_error`）。`pending_ask` / 消息 `hitl` 持久化完整 `questions`；暂停时把 agent transcript 写入 `result.agent_messages`。用户再次 `POST .../messages`（正文可为结构化多题答案）走 `resume_waiting_run`：**同一 `run_id` 回到 `running`**，用户正文覆盖末条 HITL tool result 后续 `run_agent`；也可 `POST .../cancel` 直接取消等待。`GET /api/ai/sessions/{id}` 回可选 `active_run`（占用中的 `running` / `waiting_user`，含事件 `cursor` 与 `pending_ask`）；归档/删除在 `running` 或 `waiting_user` 时拒绝。`public_run` 不会把已 `completed` 的 run 因残留 `cancel_requested` 伪装成 `cancelled`。消息 metadata 折叠含 `hitl`。
- 取消：`cancel_run` 对 `running` / `waiting_user` **立即**落 `cancelled` 并释放会话为 `idle`，以便马上发下一轮；worker 见 `cancel_requested` 后幂等收口（`finish_run` 对已终态 no-op）。助手落库走 `append_assistant_if_run_active`（仅 `running` 且未取消），避免取消后迟到正文插到新 user 之后；`done` 仅在 `finish_run(completed)` 真正生效后发出。
- 多轮喂模：`list_messages` 最近 **200** 条组历史后，优先读 `session.metadata.context_feed`（手动 `/compact` 或上次自动压缩写入的喂模快照）再拼 `through_seq` 之后新消息；否则全量历史。再按 `context_compact` 对**喂模 messages** 做自动压缩（超可用窗 70% 才压；保留近 6 轮原文；更早轮确定性摘要，可选 LLM summarizer；失败头尾拼接，禁止静默丢光）。**手动** `AssistantManager.compact_session` / `POST .../compact` 以 `force=True` 无视阈值强制压，结果写入 `context_feed`。**不删不改 SQLite 会话原文**；与 `maybe_auto_consolidate_memory` 独立。压缩时发 SSE `context_compacted`（折叠进本轮 `warnings`）；前端用量环与时间线可见「已压缩」。**跳过空正文且无附图的 assistant**（取消/落库竞态残留），避免污染下一轮上下文。
- 新 run 会在持久化用户消息前检查自然月输入加输出 Token 用量。默认硬顶为 `1_000_000`，可通过 `LOCI_AI_MONTHLY_TOKEN_BUDGET` 配置为正整数；达到上限直接拒绝本轮。
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

## 如何扩展
新工具挂 toolbus；新协议扩展 infrastructure/client。
`resolve_config` / `get_model_entry` 会带上目录里的 `context_window` / `max_output_tokens`（本批不改 chat 请求公式）。

## 给 Agent 的用法
- 对话：`from src.ai import chat, chat_stream, chat_text_with_thinking_fallback, ChatMessage, ToolCall, resolve_config`
- 目录：`from src.ai import get_model_entry, update_provider_models`；规范化也可 `from src.ops import normalize_models, merge_discovered`
- Agent/工具：`application/agent.py`、`application/toolbus.py`、`application/system_toolbus.py`（本域也可 `from src.ai import ...`）
- 新增工具出口：结果一律经 `system_tool_result.ok()`（自带截断标记）；任何裁剪/截断/降级都要能被模型从 `text` 里读到
- 禁忌：生成权威行情/盈亏数字；把工具失败或被裁剪的结果讲成完整事实；跨上下文深掏兄弟域 `infrastructure`

## README 维护
改协议、工具清单、密钥处理、模型目录字段时必须更新本文。

## 相关测试
`tests/ai/`（含 `test_chat_thinking_fallback.py`、`test_assistant_evidence_agents.py`、`test_system_toolbus_contract.py`、`test_system_toolbus_web_ssrf.py`、`test_toolbus_observability.py`、`test_assistant_rich_state.py`、`test_context_compact.py`） · `tests/ops/test_model_catalog.py` · `tests/app/test_quant_api.py`（providers）
