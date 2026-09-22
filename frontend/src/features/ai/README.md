# AI Assistant · 当前实现导览

本文用于定位界面与运行事件，不冻结设计、模型、思考程度、上下文能力、工具或后续架构。具体功能以当前源码为准。

`AssistantHost.vue` 挂在应用壳上，通过 `shared/api/ai_assistant.ts` 读取会话与运行事件；SSE / 轮询循环在 `useAssistantHostRun.ts`。

## 界面与组件

助手使用 shadcn-vue / Reka 原语：`AssistantSenderDock` 组合 Textarea、Button 和工具栏；`AssistantThinkingBlock` 使用 Collapsible；弹窗与侧栏使用 Dialog / Sheet 组合。
没有额外的助手组件库运行时。模型、提供方与运行参数仍由 `AssistantRuntimeBar` 和既有 API 配置，不因本次 UI 替换改变算法或提示词。

界面由会话历史、中间时间线、任务侧栏与输入区组成；展开偏好记录在 localStorage，窄屏响应式行为避免挤压输入区。宽高、断点、字号、布局和滚动策略均可根据体验继续改进，不受固定像素表限制。

时间线组件分别呈现推理摘要、活动、工具回执、产物、正文和操作。图表/代码等产物由 `AssistantArtifactHost` 分发；Markdown 使用 marked 与 DOMPurify，流式正文先增量展示、收口后再完整渲染。
`toolLabel.ts` 提供可读工具名称。事件状态与数据来源、用户草稿和模型分析保持可区分，不把模拟值伪装成已发生的账本交易。

输入区支持草稿、发送/中止、图片上传/粘贴和行首斜杠命令。中文输入法确认、Shift+Enter 换行和点击发送需要分别处理，避免误发或丢失最后输入。
上下文用量展示来自模型配置、接口元数据与近轮统计，具体估算和压缩接口见 `assistantContextUsage.ts` 与相应 API。估算值不是对模型能力的限制。

通用卡片外观见 `assistant-card.css`，助手主题令牌见 `AssistantPanel.vue`。复用令牌有助于一致性，但可以添加或调整令牌、局部样式和组件。

## 时间线与持久化

`AssistantTurnTimeline.vue` 当前编排思考摘要、活动、工具回执、产物、正文、操作与等待确认。顺序可以因新的交互需求而演进。
会话报文包含 `thinking`、`tool_receipts`、`artifacts`、可选 `agents` / `hitl`。
`assistantRunState` 处理 `think`、`token`、产物、工具和计划事件；终态收口未完成的回执并保留错误文案。
已支持 K 线、表格、ECharts、权益曲线、候选分析、来源和代码产物；未知类型使用可展开 JSON，后续可以扩展新的渲染器。

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


## 测试定位

`AssistantHost.run.stream.test.ts` 覆盖 SSE 与轮询恢复；`run.hitl` 覆盖等待答复与中止；`run.sync` 覆盖发送和回填；`session` / `resume` 覆盖会话操作与刷新恢复。
共享夹具和 API / 确认替身在 `AssistantHost.test.helpers.ts`。组件测试见 `components/*.test.ts`；浏览器检查可使用隔离接口夹具，不调用真实模型或修改真实账本。

这些文件是定位入口，不设文件行数上限、固定阅读顺序或强制工作流程。历史架构资料描述过去的实现，不是设计冻结。
