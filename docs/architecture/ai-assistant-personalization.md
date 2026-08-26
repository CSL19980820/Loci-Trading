# Loci 助手 · 会话生命周期与个性化

> **状态**：已落地（与代码同步）  
> **读者**：后端 / 前端 / Agent  
> **配套**：[`src/ai/README.md`](../../src/ai/README.md)、[`ADR-005`](../adr/ADR-005-assistant-archive-and-memory.md)  
> **参考**：ChatGPT（归档/真删、Custom Instructions、Memory）· Hermes Agent（双仓 MEMORY/USER、冻结快照、memory 工具）· Codex（规则层）

## 1. 产品定调

| 能力 | 语义 |
|---|---|
| 归档 | `status='archived'`，主列表隐藏，可恢复 |
| 删除 | **永久清除**会话及 messages / runs / events；`ai_execution_grants` 保留审计 |
| Custom Instructions | 用户手写「关于你」「回答偏好」；仅用户改 |
| Rules | 用户条目列表；仅用户改 |
| Memory | Hermes 双仓 `user` / `memory`；工具写入 + 满 N 轮自动整理；字符硬顶 |
| Core Safety | [`assistant_system_prompt()`](../../src/ai/domain/assistant.py) **不可被客户端覆盖** |

## 2. Prompt 组装（每次 run 冻结快照）

```text
[Core Safety]
[Custom Instructions]
  ## 关于用户
  ## 回答偏好
[Rules]
  - ...
[Memory]          # memory_enabled 时
  ## 用户画像      # target=user
  ## 工作记忆      # target=memory
```

中途 `memory_update` 只写库，**不刷新当前 run 的 system**；下一轮 run 再生效。

## 3. 数据（ops.db）

- `ai_sessions` / `ai_messages` / `ai_agent_runs` / `ai_agent_events` — 既有
- `ai_assistant_profile` — 单行 `id='default'`：指令、规则、记忆开关与阈值
- `ai_memories` — `target ∈ {user,memory}`，`source ∈ {manual,tool,auto}`

上限：`user` 仓合计 ≤1400；`memory` 仓 ≤2200；`about_user`/`response_style` 各 ≤2000；规则总长 ≤3000。

## 4. API 摘要

| 操作 | 路径 |
|---|---|
| 列活动 / 归档 | `GET /api/ai/sessions` · `?archived_only=true` |
| 归档 / 恢复 | `PATCH .../sessions/{id}` `{archived:true\|false}` |
| 真删 | `DELETE .../sessions/{id}` |
| 批量 | `POST /api/ai/sessions/batch` `{action, ids}` |
| 画像 | `GET/PUT /api/ai/profile` |
| 恢复产品默认 | `POST /api/ai/profile/reset-defaults`（保留「关于你」） |
| 记忆 CRUD | `GET/POST/PATCH/DELETE /api/ai/memories` |

批量返回 `{ok: string[], failed: [{id, error}]}`，逐条容错。

## 5. 自动记忆

Run **成功完成**且非 cancel 后，若 `memory_enabled && auto_memory_enabled`，且会话 user+assistant 消息数 ≥ `auto_memory_min_turns`（默认 **20**，可调范围 **5–100**），且距上次整理至少又积累该阈值条数，则轻量二次 LLM（无工具）产出 JSON 补丁并写入 `source=auto`。失败不影响主回答。

## 6. 前端

- 历史轨：对话 | 归档；行操作归档/删除（`ElMessageBox` 确认）；多选批量
- 设置弹窗：指令 | 规则 | 记忆；记忆为用户画像 / 工作记忆各一整段 Markdown；`PUT /api/ai/memories/document` 整仓替换；底部「恢复产品默认」

## 7. 产品内置默认（可编辑）

与 Core Safety **分工**：安全底座仍在 `assistant_system_prompt()`；下列内容写进 profile / memories，用户可改可删。

| 层 | 来源模块 | 行为 |
|---|---|---|
| 回答偏好 / Rules | `src/ai/domain/assistant_defaults.py` | 空画像首次落库写入；`POST /api/ai/profile/reset-defaults` 恢复；规则按主题归拢 |
| 记忆文档种子 | 同上 `DEFAULT_MEMORY_SEEDS`（`source=builtin`，每仓一篇 Markdown，固定 id） | 首次/恢复时幂等 upsert；旧短种子 id 会被清理 |
| 「关于你」 | 用户手写 | 恢复默认时**保留** |

种子内容覆盖：三库边界、工具能力边界、记忆双仓与冻结快照、策略 `entry_timing` / 潜龙纪律、子 Agent 证据口径。

`defaults_version`：遗留空画像可自动补种；若用户已改过指令/规则则只抬版本、不静默覆盖。

## 8. 明确不做

跨设备同步、隐式全库 Dreaming、会话级 Project 隔离、客户端覆盖 Core Safety、用内置记忆冒充用户偏好。
