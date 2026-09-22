# ADR-006 · 助手富渲染时间线与真流式

- **状态**：Accepted（决策 4 已由后续的 UI 底座拆除取代，见下方追记）
- **日期**：2026-08-05

> **2026-09 追记（取代决策 4）**：`element-plus`、`@element-plus/icons-vue`、
> `vue-element-plus-x` 已从仓库整体移除，`main.ts` 不再全局安装 UI 库，组件按需显式 import。
> 助手层现由 `src/shared/components/ui/app/` 的组件（`ActionButton`、`SidePanel`、
> `Disclosure` 等）与 `@lucide/vue` 图标承载。
>
> 本 ADR 的其它决策**仍然有效**：TurnTimeline 的时序分层（1–3）、跨轮持久化与 HITL（5）、
> 以及 Artifact 的取数边界（6）。只有「用哪个 UI 库」这一条变了，而且这一条本来就是实现细节。
> 当前组件落点与令牌约定见
> [`frontend/docs/ui-component-map.md`](../../frontend/docs/ui-component-map.md)。

## 背景

Loci 助手需对齐网关对话节奏（思考→工具→结论置底），并扩展 K 线/表格/ECharts 等富组件；同时坚持「AI 不发明数字」。网关仓库只读借鉴，不得修改。

## 决策

1. 采用 **TurnTimeline**：Thinking → ToolReceipt → Artifact* → **Answer（置底）**。
2. Artifact **只绑定工具/引擎结构化结果**；禁止模型用 Markdown/自由 option 冒充行情与账本数字。
3. 本轮上 **真 SSE `think`/`token`**（供应商原生 reasoning）；不做假打字机。
4. 助手层引入 **vue-element-plus-x**（Thinking/Sender）；业务页保持 Element Plus。
5. 富状态（思考/回执/Artifact）**持久化**并经 `GET session` 返回；Confirm 仅 HITL。
6. 组件包取 **大包**（K线≥20+MA5/10/20、el-table、ECharts、净值、裁决升级、来源条、对比图、代码块）。

## 后果

- 需实现 `chat_stream` 与消息富字段/旁表；前端 Conversation 重排。
- 增加 EP-X 依赖与包体积（限助手入口）。
- 与网关原则一致，实现分仓，后续可互借交互而非拷贝代码。

## 详细设计

见 [`ai-assistant-rich-render.md`](../architecture/ai-assistant-rich-render.md)。
