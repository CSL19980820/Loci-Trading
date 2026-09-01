# AI Assistant

全局助手隔离功能包。`AssistantHost.vue` 挂在应用壳上（浮球 + 近全屏弹窗），通过 `shared/api/ai_assistant.ts` 消费会话与运行事件；SSE/轮询运行循环在 `useAssistantHostRun.ts`。

## 布局约定

- 助手以 `el-dialog` 打开，宽高均为视口 **90%**（相对浏览器约 5% 外边距）；**dialog 自身无内边距**（`el-dialog__body { padding:0 }`），内容贴齐弹窗内沿。点击遮罩或 Esc 关闭。
- 对话舞台对齐主流助手骨架：**左历史轨常驻可收缩（约 280px）** / **中对话柱** / **右任务侧栏常驻可收缩** / 底输入坞。无最右图标栏。**对话区用细滚动条**（`scrollbar-width: thin`，hover 加深）——长会话里滚动条是唯一的位置感知，不隐藏；会话列表 / 任务侧栏 / 思考块内滚仍为隐藏滚动条（待收口）。
- 左右侧栏用同一套面板图标：左侧条在左、右侧条在右；展开态底栏左侧 LC、右侧齿轮进设置；收缩态仅 LC 点开设置。
- 输入坞与回合内容随中间舞台变宽，不再锁死 48/56rem。
- 无顶栏：关闭靠浮球 / Esc / 点遮罩；中止靠输入坞。
- 空「新对话」（无消息）关闭助手时静默删除；点新建若已有空草稿则复用，不堆重复会话。
- 会话标题：首条消息立刻用用户话生成临时标题；首轮助手回答收口后由模型精炼短标题（SSE `session_title`）；用户手动改名会锁定不再覆盖。侧栏左对齐：上行标题、下行模型名。
- 任务侧栏：右侧图标展开/收起（默认收起为 ~44px 窄条，展开约 **300px**）；顶栏直接是 pill 分区「计划 / 子进程 / 来源 / 产物 / 上下文」（无「检查器」标题与摘要废话）。计划为竖向步进；子进程为状态点卡片（`AssistantAgentCard`，运行中为 **SVG 边框追光**，短 dash 沿周界跑；不用 conic，避免 WebView 斜线残影）；有子进程时自动切到该页。「上下文」为人话摘要（安全底线 / 偏好 / 记忆用量 / 本轮查询），「改设置」打开 `AssistantSettingsDialog`。助手设置也可由**左历史轨左下角 LC** 打开。过程与工具名均中文展示。
- 助手叠层统一用 **`el-dialog`**（设置、子进程线程），不用 drawer。设置弹窗宽约 **780px**：指令双栏；规则为归拢列表；记忆为**用户画像 / 工作记忆各一整段 Markdown**（`PUT /api/ai/memories/document` 整仓替换），顶栏开关条保留。
- 展开偏好写入 localStorage；有子进程时自动展开侧栏。
- 主时间线含**活动条**（Evidence lane）：派生的子进程以卡片列出，可点开线程弹窗查看加载过程；结论仍置底。
- **思考块**：流式时对话区贴底跟滚（含 `thinking` 增量）；块内限高并内滚跟最新句。思考阶段一结束（出工具 / 正文 / 收口）自动收起，视口留给最新过程与结论。
- 输入坞使用 EP-X **`XSender`**（`AssistantSenderDock`）+ 底栏 `AssistantRuntimeBar`（分组模型 + 思考程度 `off/low/medium/high/xhigh/max`，默认 `medium`，偏好存 `localStorage`）+ 图片上传/粘贴 + **行首 `/` 斜杠**（内置 `/compact` + 技能包；Cursor 式，仅当本行左右无其它文字）+ 发送/中止。
- **上下文用量**：输入坞右侧环状百分比（对齐 Cursor Context Usage）：点开看分段条与分类（系统提示 / 工具 / 规则 / 记忆 / MCP / 技能 / 会话 / 草稿）。窗口取当前模型 `context_window`（缺省 128k）；`GET /api/ai/tools` 回 `system_prompt_tokens` + 工具 `schema_tokens`/`tags` + `model_catalog`。粗估汉字≈1、其它≈4字/token（口径写在读数 tooltip，不占常驻脚注）；≥70%/90% 弹出压力提示。有最近一轮 `input_tokens` 时按比例校准环上 used；`context_compacted.tokens_after` 写入消息后会话段按喂模体积收缩。后端超阈值自动压缩喂模历史时发 `context_compacted`，用量环与时间线显示「已压缩」（库内原文仍在；无事件不显示）。**手动 `/compact`**：`POST /api/ai/sessions/{id}/compact` 强制压缩喂模快照写入 `session.metadata.context_feed`（不删库原文）；会话占用中拒绝；成功后末条助手加 warning 并刷新 `context_feed_tokens`。
- **主柱 Activity**：忙态仅末条用 Host `agents`；历史轮有 `message.agents` 也展示折叠子进程条。子进程线程弹窗可展示嵌套 **工具回执**（SSE `subagent_tool` → `agent.tool_receipts`）。
- 对话中柱助手回合 **横向拉满**：Activity / 回执 / Markdown 气泡 `width:100%`；表用 `table-layout:fixed` 换行，对话区 `overflow-x:hidden`，避免无谓横滚。
- 空状态为 Instrument Stage：Ink Ribbon「落点」标 + 「今天想落在哪？」**同一行** + 一行下一步（「点一条范例，改完再发」）+ **列表式范例**（含「记录当日交割 / 昨日交割补充」等，点击填入输入框）。范例行是 `el-button`，忙态 / 未配模型时置灰（父级 `pickPrompt` 此时会丢弃点击）。**交割范例只写 `<价格>买入<数量>股<标的>` 这类占位**，禁止填看着像真实持仓的价格与股数——范例进输入框后离「回车写进账本」只差一步。
- 助手弹窗相对视口顶部 **5vh**（`top=5vh`，遮罩顶部对齐，不再垂直居中）；高度仍为 `90dvh`，`el-dialog__body` 无内边距。
- 子进程线程弹窗贴顶 **5vh**、加宽约 **52rem**：单行标题（名称 + 状态 + 进度），自定义关闭钮；小节标题一律单行（「加载过程 N 步」/「工具回执 N 条」/摘要标签与正文同框）；有摘要才展示摘要块，无空话占位；有嵌套工具时展示回执列表。
- 浮球默认位置在移动端抬高避开 `--mobile-nav-h`；拖拽后的 inline `bottom`/`right` 生效，clamp 下限含底栏净空。
- 浮球视觉为 Ink Ribbon Disc（深色盘 + 浅色丝带结 + `--seal` 落点；打开变 X；忙态虚线轨道环）。
- 助手回复用 `marked` + `DOMPurify` 渲染 Markdown；**流式中**（`status===streaming`）结论区用纯文本追加，收口后再 Markdown；用户消息保持纯文本。`applyAiRunEvent` 对 `token`/`think` 等只替换末条 assistant（O(末条)），不深拷贝整表。

## 尺寸契约（改字号 / 圆角先看这里）

助手域的间距、字阶、圆角、上下文分类色**只在 `AssistantPanel.vue` 末尾的 unscoped `<style>` 里定义一次**，组件一律 `var(--ai-*)`，不再各写各的 rem / px。

| 组 | 变量 | 值 |
|---|---|---|
| 字阶 | `--ai-fs-title` / `--ai-fs-prose` / `--ai-fs-body` / `--ai-fs-aux` / `--ai-fs-meta` | `--fs-title` / `--fs-body` / `--fs-aux` / `--fs-kicker` / `--fs-kicker` |
| 圆角 | `--ai-r-card` / `--ai-r-chip` / `--ai-r-pill` | `--radius` / `4px` / `999px` |
| 间距 | `--ai-gap-xs…lg` / `--ai-pad-x` / `--ai-pad-y` / `--ai-row-min` | 见契约块 |
| 分类色 | `--ai-cat-1…8` | 上下文构成条专用；`assistantContextUsage.ts` 只返回 `var(--ai-cat-N)` |

- **阅读正文与面板 chrome 分档**：助手回答（`.assistant-turn__content` 及其 markdown）用 `--ai-fs-prose`，与全站正文同档 .9rem——它是用户真正在读的内容，不能跟着元信息一起缩；卡片小标题、回执行、会话列表等 chrome 用 `--ai-fs-body` .8rem，比全站正文紧一档。`--fs-kicker` .7rem 是本域**字号地板**，不要再写更小的值。
- `--ai-fs-aux` 与 `--ai-fs-meta` 今天同值（全站字阶 .8 与 .7 之间无档位），语义仍分开：aux = 次要正文，meta = mono / 大写微标。
- 契约块的选择器**必须**同时列出各弹层根（`.assistant-agent-thread-dialog`、`.assistant-settings-dialog`、`.assistant-runtime-popper`、`.ctx-usage-popper`）——它们被 teleport 到 body，取不到 `.assistant-panel` 的继承链。新增 teleport 弹层要顺手加进去。
- **不要给 `var(--ai-*)` 写 fallback**：此前 6 处 fallback 与定义值早已对不上，成了误导性的过期快照。

## 富渲染时间线（ADR-006）

单轮助手回复走 **TurnTimeline**（`AssistantTurnTimeline.vue`），顺序固定：

1. **Thinking**（`AssistantThinkingBlock`）— `vue-element-plus-x` 的 `Thinking`；无 reasoning 则不渲染
2. **Activity**（`AssistantActivityStrip`）— 仅最新助手回合；子进程 Evidence lane（「仅证据 · 非终裁」）；可点开线程弹窗
3. **ToolReceipt***（`AssistantToolReceiptList`）— **本机回执条**：默认一行总览，展开逐步；有 Activity 时降权折叠；失败自动展开
4. **Artifact***（`AssistantArtifactHost`）— 仅工具/引擎真值；`status=loading` 显示 skeleton
5. **Answer** — Markdown 结论，**永远在最底**
6. **MessageActions** — 用户气泡「复制 / 重跑」；助手气泡「复制 / 重新生成」（重跑上一轮用户输入；忙态禁用）
7. **Warnings / Confirm** — Confirm 仅 `waiting_user` HITL

### 工具过程三面职责

| 面 | 职责 | 文案 |
|---|---|---|
| 主柱回执条 | 流式过程；无子 Agent 时为签名位 | `toolLabel` 人话标题；raw name 仅展开后次要显示 |
| 任务侧栏 · 来源 | Codex 式审计索引（计划在侧栏，不进主柱） | 同源 `toolLabel`；detail 可含 raw / preview |
| 任务侧栏 · 上下文 | 人话摘要（安全 / 偏好 / 记忆 / 本轮查询） | 短句；深潜设置走 LC /「改设置」 |

映射表：`toolLabel.ts`。过程 ≠ 产物：图表/表走 Artifact，不进回执正文。写操作确认入口只有底部 `AssistantConfirmCard`。

Artifact 大包：`kline`（兼容 `qianlong_kline`，复用 `KlineChart` + `prepChartOffthread`，MA5/10/20，可视≥20）/ `table` / `echarts`·`dual_axis` / `equity_curve` / `candidate_verdict` / `source_strip` / `code`；未知 kind 折叠 JSON。

持久化字段与后端对齐（GET session 带回时消费）：`thinking` / `tool_receipts` / `artifacts` / 可选 `agents` / `hitl`；`empty_completion` 消息可带 `status=error`。`assistantRunState` 认 SSE `think` / `token` / `artifact(status)` / 工具与 plan 事件；收口（`done`/`error`/`cancelled`/`waiting_user`）把直播 `agents` fold 进末条 assistant，并收口未完成的 tool receipts。`error` 且 `stopped_reason=empty_completion`/`llm_error*` 时覆盖工具前计划旁白；`finishRun` 空二次 settle 不冲已写失败文案；sync merge 保本地/远端 `error`。主柱 Activity：忙态用 Host `agents`，历史用 `message.agents`；任务侧栏经 `buildTaskModel` 同样回退。

### EP-X 与降级

- 已安装 `vue-element-plus-x@2.0.3`（peer：Vue ^3.5.17、Element Plus ^2.9；本仓 Vue 3.5 + EP 2.14 兼容）。
- **Thinking**：助手层直接用 EP-X；业务页不引入。
- **Sender**：助手层用 EP-X **`XSender`**（`AssistantSenderDock`）+ 底栏 RuntimeBar/发送/中止，对齐网关 ChatSenderComposite。
- 若某环境装不上 EP-X：Thinking/Sender 可自研降级，**保持 TurnTimeline 顺序不变**，并在本段注明降级。

## `waiting_user`

后端 HITL 暂停时 run/session 进入 `waiting_user`。前端停止轮询、展示 `AssistantConfirmCard`（抉择票），用户直接回复即可继续。答复经同一 `POST .../messages`；若返回 **同一 `run_id`**，Host 从暂停处 cursor 续消费事件流（不新建冒充第二轮的本地 run）。无独立「工具回执等待确认」事件；写确认只走 Confirm。

- **单题**：选项点击或数字键 1–9 即发送下一轮。
- **多题（askQuestions）**：`hitl.questions[]`（`id`/`prompt`/`options?`/`allow_free_text?`）一次填完后点「提交全部」；正文为结构化答案文本（含题号与选项），经既有 `POST .../messages` 续跑。空必答题不可提交。数字键作用于当前焦点题或首个未答选择题。
- `busy || waitingUser` 时会话侧栏与顶部「新建」禁用，等待态也可点中止取消。刷新后靠 `active_run.pending_ask`（含 `questions`）+ 消息 `hitl` 还原选项。
- 已移除无人挂载的 Agents 侧轨组件；主柱过程面为 Activity + TaskSidebar。

## 运行时约定

- 选中会话后按 `detail.status` / `detail.active_run` 恢复：`waiting_user` 只展示等待；`running` **从事件头重放** stream/poll（忽略 latest cursor），以便重建工具回执与图表。
- `consumeRun` 遇到 `waiting_user` 走 `pauseForUser`，不把其当作终态 `finishRun`；轮询在事件终态后不再用 `getAiRun(running)` 盖回 busy。
- 中止会清掉顶栏错误条并收口本机子进程/工具；若服务端取消失败也会在本机结束本轮，避免一直 busy 挡后续发送。错误条可手动关闭。后端取消 `running` 会立即释放会话，可马上发下一轮。
- 关闭助手弹窗不中止进行中的 run；切换未锁定会话时可 abort 旧 stream，靠 `pollVersion`/`selectionVersion` 失效旧消费。`finishRun` / `pauseForUser` 也会抬 `pollVersion`，避免晚到 SSE 改写终态气泡。
- 非流式 chat 常只发 `done`（无 token）：`finishRun` 后会 `getAiSession` 合并消息——按 id，并把 `local-*` 乐观气泡的 tool_receipts/artifacts **只折到「最新用户之后」同 role 远端消息**；若远端已有更新的 user 且尚无本轮 assistant，则 **追加** local 气泡，禁止折到上一轮助手。同文案连发时：若 local 已含远端末条 user 的 id，则追加新一轮，不误折。有正文的远端气泡不会被折回 `streaming`。
- `finishRun` 触发的 sync / 空正文补拉带 `pollVersion`+runId 守卫：下一轮 `consumeRun` 抬版本后，旧轮延迟 sync 不得覆盖新乐观消息。
- SSE 若中途断流而 run 仍 `running`，会回落 JSON 轮询，避免停在「正在整理回复…」。后端 `done` 先于标题 LLM 落库，避免 completed 后关流丢终稿。空助手正文不进入多轮模型历史。
- 对话区贴底跟滚：用户上翻后不再抢滚动，回到底部附近再恢复。

## README 维护

改助手布局、事件消费、会话恢复、归档/删除、富渲染时间线或 HITL 交互时同步更新本文。设计冻结见 [`docs/architecture/ai-assistant-rich-render.md`](../../../../docs/architecture/ai-assistant-rich-render.md) 与词表 [`CONTEXT.md`](./CONTEXT.md)。

## 相关测试

`frontend/src/features/ai/**/*.test.ts`

Host 级用例按主题分文件，单文件不超 600 行：

| 文件 | 覆盖 |
|---|---|
| `AssistantHost.run.stream.test.ts` | SSE 流、断流/失败后回落 JSON 轮询、`active_run` 续跑 |
| `AssistantHost.run.hitl.test.ts` | `waiting_user` 还原与答复、中止收口（含取消 API 失败的本机强收） |
| `AssistantHost.run.sync.test.ts` | 发送护栏（建会话中重复发送、发送中卸载）、`finishRun` 后的会话回填与旧轮延迟 sync |
| `AssistantHost.session.test.ts` / `AssistantHost.resume.test.ts` | 会话列表/归档删除、刷新恢复 |

**共享 mock 与 fixture 都在 `AssistantHost.test.helpers.ts`**：`vi.mock('@/shared/api/ai_assistant' | 'vue-router' | 'element-plus')` 是模块级提升的，只能待在该文件（或各测试文件）顶部；`toolsReady` / `sessionDetail` / `aiRun` / `primeAssistantReady` / `primeNewSession` / `transcriptPanel` 等是纯 fixture 与面板 stub 工厂。改后端报文契约只改这一处，别把 mock 复制进各测试文件。
