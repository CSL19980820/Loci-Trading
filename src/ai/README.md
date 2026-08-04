# AI（ai）

## 职责
通用 LLM 供应商、对话、Agent / toolbus。不发明数字。

## 边界
密钥经 ops 存储加密；计算结论以 review/strategy 为准。
模型目录（启停 / 上下文 / 输出上限）存在 ops.db `llm_providers.models_json`，由 `src.ops.normalize_models` 等维护。
本机（非 production）启动时 `ensure_local_master_key()` 会把主密钥落到程序旁 `.palace_ai_master_key`（gitignore）并注入环境；生产仍须显式配 `PALACE_AI_MASTER_KEY`。

## 关键入口
`chat` / `run_agent` / `build_toolbus`；HTTP：`/api/providers/*` `/api/ai/*`

## 全局助手
`/api/ai/*` 维护会话、运行、轮询 / SSE 事件和静态工具目录。`owner_full` 助手可以在应用内读取和写入账本/行情/战法，管理已配置厂商，并创建、更新、立即运行受控运维任务。

- 工具面固定在 `application/system_toolbus.py`；战法执行位于 `application/system_toolbus_strategy.py`。不提供 raw SQL、shell、文件、任意 URL、动态 MCP、密钥读取或真实券商下单。
- 写入由 `AssistantManager` 自动签发绑定本次运行、工具和参数摘要的 `ExecutionGrant`；它提供单次消费、幂等与审计，不要求逐笔匹配用户原话。
- 同一会话同一时刻只允许一条运行；应用启动会把无法跨进程续跑的遗留 `running` 记录标记为中断失败，并保留事件与错误原因。`waiting_user` 跨重启保留，用户仍可回复后开新 run。
- HITL：工具要求用户确认时，run/session 进入 `waiting_user`（不发 `done`）。主环 `allow_hitl=True`。用户再次 `POST .../messages` 会先 `resolve_waiting_session` 再开新 run；也可 `POST .../cancel` 直接取消等待。`GET /api/ai/sessions/{id}` 回可选 `active_run`（占用中的 `running` / `waiting_user`，含事件 `cursor`）；归档/删除在 `running` 或 `waiting_user` 时拒绝。`public_run` 不会把已 `completed` 的 run 因残留 `cancel_requested` 伪装成 `cancelled`。
- 新 run 会在持久化用户消息前检查自然月输入加输出 Token 用量。默认硬顶为 `1_000_000`，可通过 `LOCI_AI_MONTHLY_TOKEN_BUDGET` 配置为正整数；达到上限直接拒绝本轮。
- `GET /api/ai/runs/{run_id}/events` 保持 JSON 轮询兼容；`GET /api/ai/runs/{run_id}/events/stream` 以 `id` / `event` / JSON `data` 重放并跟随同一持久化事件流，支持 `after` 和 `Last-Event-ID` 续接；遇到 `done` / `error` / `cancelled` / `waiting_user` 结束跟随。`done` 的 payload 含与 `ai_messages` 一致的终稿 `text`/`content`（非流式无 token 时前端据此填气泡）。
- 潜龙提交必须先读取同日同池的整池和本机日 K 证据，且提交代码与候选池完全一致；精选上限仍为两只。
- `sync` / `screen` / `backtest` / `compare` / `optimize` / `prune` / `outcome` 任务可由助手管理。写入后重载调度器；立即运行以当前工作台的 `market_db` / `palace_db` 执行，并让 AI run 保持运行直到后台任务收尾。

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
- 对话：`from src.ai import chat, ChatMessage, ToolCall, resolve_config`
- 目录：`from src.ai import get_model_entry, update_provider_models`；规范化也可 `from src.ops import normalize_models, merge_discovered`
- Agent/工具：`application/agent.py`、`application/toolbus.py`、`application/system_toolbus.py`（本域也可 `from src.ai import ...`）
- 禁忌：生成权威行情/盈亏数字；跨上下文深掏兄弟域 `infrastructure`

## README 维护
改协议、工具清单、密钥处理、模型目录字段时必须更新本文。

## 相关测试
`tests/ai/` · `tests/ops/test_model_catalog.py` · `tests/app/test_quant_api.py`（providers）
