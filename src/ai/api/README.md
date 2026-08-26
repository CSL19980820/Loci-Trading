归属：`/api/providers*` `/api/ai/*`。

挂载：`src.ai.api.router.build_ai_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

`GET /api/ai/tools` 另回 `system_prompt_tokens`（安全底座粗估）、各工具 `schema_tokens`/`tags`（MCP 标 `mcp`）、以及各厂商 `model_catalog`（含 `context_window`），供前端「上下文用量」环与分段条。

## 全局助手

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/ai/tools` | 返回可用厂商、模型和固定业务工具目录，不回显密钥。 |
| `GET/POST` | `/api/ai/sessions` | 查询或创建助手会话；`?archived_only=true` 仅归档。 |
| `POST` | `/api/ai/sessions/batch` | 批量 `archive` / `unarchive` / `delete`，返回 `{ok, failed}`。 |
| `GET/PATCH/DELETE` | `/api/ai/sessions/{session_id}` | 获取（含可选 `active_run`；`messages` 可含 ADR-006 富字段）、归档/恢复（`archived`）或**永久删除**。`PATCH title` 视为手动命名并锁定。 |
| `GET/PUT` | `/api/ai/profile` | 自定义指令、规则、记忆开关与自动整理阈值；空库首次带产品默认规则/偏好。 |
| `POST` | `/api/ai/profile/reset-defaults` | 恢复产品默认规则与回答偏好，幂等补齐 `source=builtin` 工作记忆；保留「关于你」。 |
| `GET/POST` | `/api/ai/memories` | 列出或新增记忆（`target=user\|memory`）。 |
| `PUT` | `/api/ai/memories/document` | 整仓替换为一篇 Markdown（设置页）；`{target, content}`。 |
| `PATCH/DELETE` | `/api/ai/memories/{id}` | 更新或删除记忆条目。 |
| `POST` | `/api/ai/sessions/{session_id}/messages` | 异步启动一轮 Agent；可选 `provider` / `model` / `thinking`（`off`/`low`/`medium`/`high`/`xhigh`/`max`）/ `images` / `skill_slug`（斜杠技能注入本轮 system）。系统工具含 `web_search`/`web_fetch` 与默认挂载的活跃 MCP。命中话术时并行角色化只读取证子 Agent，侧栏 `subagent_*`（含嵌套 `subagent_tool`），主环注入截断 evidence brief。 |
| `POST` | `/api/ai/sessions/{session_id}/compact` | 手动压缩喂模上下文（Cursor `/compact`）；`force` 写入 `session.metadata.context_feed`，**不删**库内原文；短对话/占用中返回 422。 |
| `GET` | `/api/ai/runs/{run_id}/events` | 轮询工具、子 Agent、候选 artifact 和后台任务事件；含真流式 `think`/`token`（`{delta}`）与终稿 `done`。 |
| `GET` | `/api/ai/runs/{run_id}/events/stream` | SSE 重放并跟随同一持久化事件；支持 `after` 或 `Last-Event-ID` 续接。 |
| `POST` | `/api/ai/runs/{run_id}/cancel` | 显式请求取消运行（含 `waiting_user`）。 |

HITL：`waiting_user` 表示 run 暂停等待用户回复；再次 `POST .../messages` **同 run_id resume**（用户正文写入 HITL tool result 后续环；正文可为多题结构化答案）。主助手环 `allow_hitl=True`，工具 `meta.needs_hitl` / `ask_user` 可进入等待；`ask_user` 参数兼容旧 `prompt`+`options`，并支持 `questions[]`（`id`/`prompt`/`options?`/`allow_free_text?`）。`public_run.pending_ask` 与消息 `hitl` 透出完整 questions。`GET .../sessions/{id}` 在会话占用中时回 `active_run`（`public_run` 映射，含 `cursor`）；前端恢复 running 时从事件头重放；HITL 答复若返回同一 `run_id` 则从暂停处 cursor 续消费事件。`running` 与 `waiting_user` 均阻止归档/删除，须先取消。`POST .../cancel` 对 `running`/`waiting_user` **立即**落库 `cancelled` 并释放会话，可马上发下一轮。`public_run` 仅在仍为 `running` 且 `cancel_requested` 时对外报 `cancelled`；已 `completed`/`failed`/`cancelled` 以终态为准。`/events` 继续返回 JSON，SSE 每条事件为 `id`、`event`、JSON `data`。主环默认真流式 `chat_stream`：原生 reasoning → `think`，正文 → `token`；无 reasoning 不发 `think`；流式失败可降级非流式。`done` 始终带终稿 `text`/`content`（与写入 messages 的正文一致）；`artifact` 可含 `status=loading|ready`。超阈值喂模压缩发 `context_compacted`（`message`/`removed`/`kept`/`tokens_*`；折叠进本轮 `warnings`，不删库）。两条路径均读取 `ai_agent_events`，可以用稳定事件 ID 切换续拉。

消息契约（`public_message`）：始终含 `id` / `role` / `content` / `created_at`；assistant 在有富状态时额外含可选 `thinking`（string）、`tool_receipts`、`artifacts`、`warnings`、`agents`（子 Agent 快照）；user 可含 `images`（data URL 列表）。数据来自 `ai_messages.metadata_json`（ADR-006）；旧消息无这些键。SSE 另可含 `plan`（`{steps:[{id,label,status}]}`）供任务侧栏，不写入 message metadata。

路由由组合根单独挂载，所有访问沿用写鉴权。后台任务在对应 AI run 完结前持续可观察；`owner_full` 的账本和运维写操作由服务端 `ExecutionGrant` 绑定本次运行和参数摘要，不再逐笔核验用户原话。个性化与记忆见 [`docs/architecture/ai-assistant-personalization.md`](../../../docs/architecture/ai-assistant-personalization.md)。
