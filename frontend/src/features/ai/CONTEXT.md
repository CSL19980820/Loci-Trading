# CONTEXT · AI 助手对话面（features/ai）

> 词汇表。不含实现细节。系统级决策见 `docs/adr/`。

## Glossary

### TurnTimeline（时间线轮次）
单次助手回复的有序块序列。块按发生顺序渲染；**结论块永远在最底部**。

### ThinkingBlock（思考块）
过程层：模型推理/内心独白。流式时对话贴底跟滚，块内限高内滚；思考阶段结束（工具/正文/收口）自动收起，视口留给最新块。

### ToolReceipt（工具回执）
过程层：一次工具调用的可审计记录（名称、状态、摘要/入出参预览）。running 时可有加载态。

### Artifact（富组件产物）
过程层与结论之间的结构化可视块：K 线、表格、统计图等。**必须绑定工具或引擎真值**，不得由模型用 Markdown 冒充数字或行情。模型只写 Answer 文案，不发明 ECharts option / 表内数字。

### Answer（结论正文）
时间线最末块：给用户看的最终自然语言结论（Markdown）。不得插在 Artifact 之前。

### ProgressiveReveal（渐进显现）
流式或分阶段过程中，块可以先以 loading/skeleton 出现，再填入真值；结论仍保持在底部。

## Decisions (session)

| 决策 | 选择 | 备注 |
|---|---|---|
| 单轮 UI 编排 | TurnTimeline（时间线块） | 思考→工具→Artifact→Answer 置底 |
| Artifact 数据权威 | 仅工具/引擎真值 | 对齐网关 data-query；禁模型造数 |
| 流式深度 | 真 SSE `token`/`think` | 本轮改 chat_stream；不做假打字机 |
| 思考块来源 | 供应商原生 reasoning 流 | 无则空块；禁止提示词伪造 `<think>` |
| Artifact MVP 包 | 大包 C | K线+表+ECharts+Confirm+代码块；另含净值曲线、候选裁决升级、来源条、对比双轴 |
| 思考/发送器组件栈 | shadcn-vue / Reka 组合 | Collapsible + Textarea / Button；与业务页共享原语 |
| 富状态持久化 | 消息 metadata/旁表随 GET session 带回 | 刷新可复盘；含 agents；不做文件仓 |
| 任务侧栏 | Codex 同构 Plan/Sources/Threads/Artifacts/Summary | 活动条点开子线程检视加载过程 |
| Confirm/HITL 范围 | 仅 waiting_user / needs_hitl | 日常写工具不逐笔确认 |
| 文档冻结 | 2026-08-05 | 详见 `docs/architecture/ai-assistant-rich-render.md` + ADR-006 |