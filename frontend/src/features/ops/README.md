# ops

运维页：技能包 / MCP / LLM / 数据目录 / 行情同步 / 线路 / 推送 / 定时任务 / 执行历史。

- 壳：`OpsView.vue`（tabs + 刷新 + 全局 notice/error）
- Tab 子组件：`components/*Tab.vue`
- 共享：`composables/useOpsFeedback.ts`（busy/guard）、`composables/opsLabels.ts`
- 大段 JSON/YAML/Markdown：`components/CodeEditor.vue`（Monaco，主题跟 CSS 变量；小 input 仍用 `el-input`）；`useJobsQuery` / `useJobRunsQuery`（Pinia Colada 只读；写操作后显式 refetch）
