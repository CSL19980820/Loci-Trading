# AI Assistant

全局助手隔离功能包。`AssistantHost.vue` 挂在应用壳上（浮球 + 右侧抽屉），通过 `shared/api/ai_assistant.ts` 消费会话与运行事件。

## 布局约定

- 抽屉默认宽度 560px，可在窄/标准/宽三档间切换并写入 `localStorage`。
- `.assistant-drawer .el-drawer__body` 强制 `height:100%; padding:0; overflow:hidden`，让 `.assistant-panel` 吃满抽屉高度。
- 历史会话侧栏与子 Agent 侧栏在窄面板下改为叠层；子 Agent overlay 带半透明遮罩，点击可临时收起（agents 列表变化后重显）。
- 窄宽（&lt;480 或 compact）时 header 宽度 segmented 折行缩小，避免挤出操作按钮。
- 浮球默认位置在移动端抬高避开 `--mobile-nav-h`；拖拽后的 inline `bottom`/`right` 生效，clamp 下限含底栏净空。
- 助手回复用 `marked` + `DOMPurify` 渲染 Markdown；用户消息保持纯文本。

## `waiting_user`

后端 HITL 暂停时 run/session 进入 `waiting_user`。前端停止轮询、展示等待条，用户直接回复即可继续；`busy || waitingUser` 时会话侧栏与顶部「新建」禁用（不可切换/删除/新建），但可取消。

## 运行时约定

- 选中会话后按 `detail.status` / `detail.active_run` 恢复：`waiting_user` 只展示等待；`running` **从事件头重放** stream/poll（忽略 latest cursor），以便重建工具回执与图表。
- `consumeRun` 遇到 `waiting_user` 走 `pauseForUser`，不把其当作终态 `finishRun`；轮询在事件终态后不再用 `getAiRun(running)` 盖回 busy。
- 关闭抽屉不中止进行中的 run；切换未锁定会话时可 abort 旧 stream，靠 `pollVersion`/`selectionVersion` 失效旧消费。
- 非流式 chat 常只发 `done`（无 token）：`finishRun` 后会 `getAiSession` 合并消息——按 id，并把 `local-*` 乐观气泡的 tool_receipts/artifacts 折到同 role 远端消息上。

## README 维护

改抽屉布局、事件消费、会话恢复或 HITL 交互时同步更新本文。

## 相关测试

`frontend/src/features/ai/**/*.test.ts`
