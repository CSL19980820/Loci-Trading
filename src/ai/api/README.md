归属：`/api/providers*` `/api/ai/*`。

挂载：`src.ai.api.router.build_ai_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

模型目录：`GET/POST /api/providers` 回 `model_catalog` + 启用 `models`；`POST .../models` 拉取合并；`PUT .../models` 整表保存。

## 全局助手

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/ai/tools` | 返回可用厂商、模型和固定业务工具目录，不回显密钥。 |
| `GET/POST` | `/api/ai/sessions` | 查询或创建助手会话。 |
| `GET/PATCH/DELETE` | `/api/ai/sessions/{session_id}` | 获取（含可选 `active_run`）、归档或删除会话。 |
| `POST` | `/api/ai/sessions/{session_id}/messages` | 异步启动一轮 Agent。 |
| `GET` | `/api/ai/runs/{run_id}/events` | 轮询工具、子 Agent、候选 artifact 和后台任务事件。 |
| `GET` | `/api/ai/runs/{run_id}/events/stream` | SSE 重放并跟随同一持久化事件；支持 `after` 或 `Last-Event-ID` 续接。 |
| `POST` | `/api/ai/runs/{run_id}/cancel` | 显式请求取消运行（含 `waiting_user`）。 |

HITL：`waiting_user` 表示 run 暂停等待用户回复；再次 `POST .../messages` 会收敛等待中的 run 并启动新一轮。主助手环 `allow_hitl=True`，工具 `meta.needs_hitl` / `ask_user` 可进入等待。`GET .../sessions/{id}` 在会话占用中时回 `active_run`（`public_run` 映射，含 `cursor`）；前端恢复 running 时从事件头重放。`running` 与 `waiting_user` 均阻止归档/删除，须先取消。`public_run` 仅在仍为 `running` 且 `cancel_requested` 时对外报 `cancelled`；已 `completed`/`failed` 以终态为准。`/events` 继续返回 JSON，SSE 每条事件为 `id`、`event`、JSON `data`；`done` 带终稿 `text`/`content`（与写入 messages 的正文一致）。两条路径均读取 `ai_agent_events`，可以用稳定事件 ID 切换续拉。路由由组合根单独挂载，所有访问沿用写鉴权。后台任务在对应 AI run 完结前持续可观察；`owner_full` 的账本和运维写操作由服务端 `ExecutionGrant` 绑定本次运行和参数摘要，不再逐笔核验用户原话。
