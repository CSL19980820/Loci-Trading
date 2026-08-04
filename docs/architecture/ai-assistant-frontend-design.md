# Loci AI 对话助手 · 前端设计细则

> **状态**：设计稿（未开工）  
> **读者**：前端 / 设计落地 Agent  
> **配套后端**：[`ai-assistant-backend-plan.md`](./ai-assistant-backend-plan.md)  
> **参考**：主流助手（ChatGPT / Claude / DeepSeek 侧栏会话）、`qiz-ai-gateway-ui`（GatewayChatPlayground + `packages/widget` 悬浮球）、**vue-element-plus-x / AI Elements** 流式对话范式  
> **约束**：[`frontend/AGENTS.md`](../../frontend/AGENTS.md)（Element Plus、`page-fill` 无文档级滚动、单文件 ≤600 行）

---

## 0. 设计定调（先钉死再画）

| 轴 | 选择 |
|---|---|
| 主体 | Loci 单机量化工作台助手 |
| 受众 | 本人：盘中/盘后快速问持仓、调配置、跑选股、记一笔 |
| 页面单一职责 | **随时可唤起的对话层**：不抢走当前页工作，完成后能把用户送回业务页 |
| 视觉方向 | **「行情终端旁的耳语台」**：沿用现有 `--ink / --paper / --mist / 涨跌色`；不是奶油衬线站、不是酸绿赛博黑、不是报纸栏 |
| 签名记忆点 | **可拖拽墨点悬浮球 + 右侧滑出「耳语台」面板**；球上有极细呼吸环表示生成中 |
| Elements 技术 | 引入 **`vue-element-plus-x`**（与 gateway 一致：Bubble / Typewriter / XSender / Thinking 等）专用于助手层；业务表单仍只用 Element Plus。若体积/CSP 不达标，降级为自研等价组件（信息架构不变） |

### 相对「AI 默认皮」的刻意偏离

- 不用大数字英雄卡、不用紫靛渐变 CTA。
- 空态不是插画吉祥物，而是**三条可点的本机场景提示**（持仓 / 选股 / 配置）。
- 工具调用卡片用「终端 receipt」气质（等宽小标签 + 耗时），不是彩虹 pill 堆。

---

## 1. 信息架构

```
App Shell (已有)
 └─ AssistantHost（全局挂载，登录后可见）
     ├─ AssistantFloatBall          # 悬浮球
     └─ AssistantPanel              # 对话框（抽屉/浮层）
         ├─ PanelHeader             # 标题 / 新建 / 历史 / 关闭
         ├─ HistoryDrawer           # 历史会话（可叠在面板内左侧）
         ├─ ConversationPane        # 消息流
         │   ├─ EmptyStateHints
         │   ├─ UserBubble
         │   ├─ AssistantTurn
         │   │   ├─ ThinkingBlock
         │   │   ├─ ToolReceiptList
         │   │   ├─ ConfirmCard / AskUserChips
         │   │   ├─ MarkdownAnswer（Typewriter/流式）
         │   │   └─ TurnActions（复制/重新生成）
         │   └─ EvidenceWarning
         ├─ Composer                # XSender 区
         └─ StatusFooter            # 模型 / tokens / 状态
```

**不是**独立路由页（可另提供 `/assistant` 全屏模式作二期）；MVP = 全局浮层，任意业务页可用。

---

## 2. 布局与断点

### 2.1 桌面（≥960px）

```
┌────────────────────────────────────────────────────────────┐
│  侧栏 │              当前业务页（不变）                      │
│       │                                                    │
│       │                              ┌──────────────────┐  │
│       │                              │ Panel 420–480px  │  │
│       │                              │ 或 40vw max 560  │  │
│       │                              │ ┌────┬─────────┐ │  │
│       │                              │ │Hist│ Convo   │ │  │
│       │                              │ │160 │         │ │  │
│       │                              │ └────┴─────────┘ │  │
│       │                              │ Composer         │  │
│       │                              └──────────────────┘  │
│       │                                         (●) 球     │
└────────────────────────────────────────────────────────────┘
```

- 面板：自右侧滑入的 `el-drawer`（`direction="rtl"`），`size` 默认 `440px`，可拖拽改宽（二期）；`modal=true` 但遮罩透明度低（`0.28`），点击遮罩关闭。
- 历史：面板内左侧 rail，默认收起；点「历史」展开 160–200px，对话区变窄。
- z-index：球 `3200`，面板 `3100`，低于全局 MessageBox（EP 默认更高时跟主题变量对齐）。

### 2.2 平板 / 手机（&lt;960px）

- 面板改为 **近全屏 drawer**（`100%` 宽，顶安全区），历史改为顶部下拉或全宽列表页内切换。
- 球默认右下，避开 `MobileBottomNav`：底边上移 `72px + safe-area`。
- 禁止出现文档级（html/body）滚动；面板内部 `.assistant-scroll` 自管。

### 2.3 与现有 FAB 共存

现有记一笔 `record-fab`（若仍显示）：助手球默认在其**上方** 16px，或水平错开；localStorage 记住球位置后以用户拖拽为准，仅首次默认避让。

---

## 3. 悬浮球（Float Ball）

### 3.1 视觉

| 属性 | 规格 |
|---|---|
| 尺寸 | 52×52px（对齐 gateway `BALL_SIZE`） |
| 形状 | 正圆；填充 `color-mix(in srgb, var(--ink) 92%, var(--accent, #3d6bf3) 8%)` |
| 图标 | 简化 Loci 印（`assets/loci-icon` 单色反白）或「耳语」两点波形；**不用机器人 emoji** |
| 阴影 | 单层 `0 8px 24px color-mix(in srgb, var(--ink) 22%, transparent)` |
| 边 | 1px `color-mix(in srgb, #fff 18%, transparent)` |
| 焦点环 | `:focus-visible` 2px `var(--el-color-primary)` offset 3px |

### 3.2 状态

| 状态 | 表现 |
|---|---|
| idle | 静止；hover 轻微放大 1.04（reduced-motion 关闭） |
| panel open | 球可隐藏或缩成 40px 贴边；点击仍 toggle |
| streaming | 外周 2px 呼吸环（opacity 0.35–0.85，1.6s）；`aria-busy=true` |
| waiting_user | 环改为脉冲琥珀（与确认卡片同色相） |
| error | 短暂红点角标，下一条成功后清除 |
| offline / 未配置供应商 | 灰态 + tooltip「先去运维配置模型」 |

### 3.3 交互（对齐 gateway FloatBall）

- **拖拽阈值 6px**：小于阈值算点击，避免吞 click。
- **位置持久化**：`localStorage['loci.assistant.ball.pos']`；resize 时重新 clamp 视口。
- **贴边吸附（可选 MVP+）**：松手后吸附左右边，边距 24px。
- **键盘**：全局快捷键 `Ctrl+/`（或 `Meta+/`）打开并 focus 输入框；`Esc` 关闭面板（生成中 Esc = 先确认是否中止，见 §8）。
- **气泡 tip（可选）**：首次登录显示一次「按 Ctrl+/ 唤起助手」，3s 淡出；朝向按球所在半屏翻转。

### 3.4 无障碍

- `role="button"` `aria-label="打开 Loci 助手"`
- 面板打开时 `aria-expanded=true`
- 不依赖仅颜色传达 streaming（加 `aria-busy` + footer 文案）

---

## 4. 对话面板详规

### 4.1 Header（高 52px）

左 → 右：

1. **标题**：会话 title（空则「新对话」）；单行 ellipsis。
2. **模型 chip**：当前 `provider/model` 缩写；点击打开轻量 popover 切换（数据来自已有 providers API）。
3. **图标按钮组**（`el-button` circle/text）：
   - 新建对话
   - 历史（toggle rail）
   - 更多（清空本会话、导出 Markdown 二期、只读模式开关）
   - 关闭

标题区不放营销 slogan。

### 4.2 历史记录（History Rail）

| 元素 | 行为 |
|---|---|
| 搜索 | `el-input` 小尺寸，过滤 title |
| 列表项 | 标题 + 相对时间（`shared/lib` 格式化）+ 状态小点（streaming/waiting） |
| 当前项 | 左侧 2px primary 条 |
| 右键/悬停 | 重命名、删除（`ElMessageBox` 确认） |
| 空 | 「还没有对话」+ 按钮「开始新对话」 |
| 分页 | 滚到底加载更多（cursor） |

切换会话：若当前 `streaming`，先提示「生成中，切换将保留后台流 / 或中止」——MVP 选 **中止再切换**（实现简单）。

### 4.3 对话区（Conversation）

#### 空态（EmptyStateHints）

居中偏上，不是整页空白：

- 一行说明：「问持仓、改配置、跑选股——数字都来自本机工具。」
- 三个 `el-button` plain 场景：
  1. 「今天持仓怎么样？」
  2. 「用当前默认策略跑一遍选股」
  3. 「把默认模型换成 …」（打开时带半填 prompt）

#### 用户消息

- 右对齐气泡；背景 `color-mix(in srgb, var(--el-color-primary) 12%, var(--paper))`
- 最大宽度 85%；支持多行；不渲染任意 HTML（纯文本 + 轻量换行）

#### 助手轮次（AssistantTurn）

垂直时间线，**左对齐**，头像用 24px Loci 印。顺序固定：

1. ThinkingBlock（若有）
2. ToolReceiptList（按 call 顺序）
3. ConfirmCard / AskUserChips（若有）
4. Markdown 正文（流式）
5. EvidenceWarning（若 `flags.needs_evidence_warning`）
6. TurnActions（完成后显示）

---

## 5. Elements / 打字机 / 流式渲染

### 5.1 技术选型落点

| 能力 | 推荐组件（vue-element-plus-x） | 降级 |
|---|---|---|
| 气泡 | `Bubble` / `BubbleList` | 自研 `.assistant-bubble` |
| 打字机 | `Typewriter` **或** 直接流式追加（见下） | CSS 光标 + rAF |
| 发送器 | `XSender` / `EditorSender` | `el-input` textarea + 发送钮 |
| 思考 | `Thinking` 折叠 | `<details>` |
| Markdown | 库内 Markdown 或现成 `markdown-it` | 与 gateway widget 同级：流式期 rAF 节流 |

**重要经验（gateway 已踩坑）**：正文在 SSE 同步更新时，**不要再套一层 GSAP/假打字机**与 Markdown 叠字。正确策略：

1. **流式中**：`token` delta 追加到字符串 → rAF 节流重渲染 Markdown（或 Typewriter 仅驱动纯文本阶段）。
2. **流式结束**：一次性 normalize Markdown，关掉光标。
3. `prefers-reduced-motion: reduce`：关闭光标闪烁与球呼吸，保留即时追加。

### 5.2 AI Elements 信息架构映射

即便不全量引入 AI Elements Vue，**parts 模型**对齐：

```ts
type MessagePart =
  | { type: 'text'; text: string }
  | { type: 'thinking'; text: string; collapsed?: boolean }
  | { type: 'tool'; callId: string; name: string; status: ToolStatus; ... }
  | { type: 'confirm'; pendingId: string; summary: string; diff: unknown; risk: string }
  | { type: 'ask'; prompt: string; options: string[] }
  | { type: 'warning'; code: string; message: string }
```

前端 `useAssistantChat` 把 SSE 事件折叠进当前 assistant message 的 `parts[]`。

### 5.3 光标与「打字机感」

- 流式文本尾部显示 `▍` 块光标（高 1em，宽 2px，闪烁 1s）。
- 工具卡片出现时**不必**打字机；卡片用 120ms fade。
- 思考区默认折叠「思考中…」；结束后标题变为「已思考 · 3.2s」，可展开纯文本（不强制 Markdown）。

---

## 6. 工具卡片与确认交互

### 6.1 Tool Receipt（工具回执）

外观：一条横向 compact 卡，左状态点 + 工具名 + 右侧耗时。

| status | 点颜色 | 文案 |
|---|---|---|
| running | 动画灰点 | `market_kline · 执行中` |
| ok | 绿 | `market_kline · 182ms` |
| error | 红 | `market_kline · 失败` |
| awaiting | 琥珀 | `ledger_propose_trade · 待确认` |

展开后：arguments JSON（折叠 `<el-collapse>`）、结果 preview 前 400 字。  
**禁止**在卡片里显示密钥或完整持仓大表；大结果引导「打开档案页」。

### 6.2 ConfirmCard（写确认）

主内容：

- 标题：`确认写入账本`
- 摘要：后端 `summary` 一句人话
- Diff：键值表（代码、方向、价格…），数字用 `NumText`
- 按钮：`确认执行`（primary） / `取消`（plain）
- destructive：确认钮 `type="danger"`，摘要前加警告 `el-alert`

确认中：按钮 loading；成功：卡片变绿「已写入」+ 可选「查看档案」link（`navigate_hint`）。  
拒绝：卡片变灰「已取消」，流自动续跑。

### 6.3 AskUserChips

问题文案 + `el-check-tag` / `el-button` 选项；也可在 Composer 自由输入。选中即 `POST .../reply`。

### 6.4 EvidenceWarning

`el-alert type="warning"`：  
「回复里出现了行情类表述，但本轮没有成功的行情工具结果——请当参考，勿直接下单。」

---

## 7. Composer（输入区）

### 7.1 结构（参考 DeepSeek / gateway XSender）

```
┌─────────────────────────────────────────┐
│  [可选：场景 chip 持仓|选股|运维]         │
│  ┌───────────────────────────────────┐  │
│  │ textarea 自动增高 1–6 行           │  │
│  └───────────────────────────────────┘  │
│  思考开关   工具范围   tokens估   [发送] │
└─────────────────────────────────────────┘
```

- Enter 发送；Shift+Enter 换行（与主流一致）。
- streaming 时发送钮变 **停止**（方块图标），调用 abort。
- placeholder 随场景：`问问持仓、选股或配置…`
- 未配置供应商：输入禁用 + 链接到运维 LLM Tab。

### 7.2 附件（二期）

MVP 不做图片/文件；若做，仅允许文本粘贴代码块。

---

## 8. 状态机（前端）

```
panel: closed | open
historyRail: collapsed | expanded
session: idle | streaming | waiting_user | error
composer: ready | disabled | stopping
```

| 用户动作 | 结果 |
|---|---|
| 点球 | toggle panel；open 时 focus textarea |
| 发送 | append user；建 assistant 壳；连 SSE |
| 停止 | abort；parts 保留已生成；status=idle |
| Esc | 若 streaming → MessageBox「停止生成并关闭？」；否则关面板 |
| 确认写 | confirm API；卡片更新；继续收 SSE |
| 切换历史 | 见 §4.2 |

滚动：仅当用户贴底时自动跟随；上翻查看时不抢滚（gateway widget 同款）。

---

## 9. 动效预算（有意、克制）

至少 2–3 个有编排的动效，其余静默：

1. **面板开合**：220ms transform + fade（`prefers-reduced-motion` 则瞬时）。
2. **球呼吸环**：仅 streaming（§3.2）。
3. **首条助手消息**：opacity 0→1 160ms；后续消息无交错 cascade（避免 AI 模板感）。

禁止：粒子背景、鼠标跟随光斑、多阴影浮层卡片墙。

---

## 10. 视觉 Token（助手层局部）

在 `features/ai/assistant.css`（或组件 scoped + 少量 CSS 变量）扩展，不污染全局主题：

```css
.assistant-host {
  --as-panel-bg: var(--paper);
  --as-panel-border: color-mix(in srgb, var(--mist) 35%, transparent);
  --as-user-bg: color-mix(in srgb, var(--el-color-primary) 12%, var(--paper));
  --as-tool-bg: color-mix(in srgb, var(--ink) 4%, var(--paper));
  --as-await: #c47a1a; /* 琥珀，浅色主题可读 */
  --as-radius: 12px;
  --as-font-ui: inherit; /* 跟工作台 */
  --as-font-mono: ui-monospace, "Cascadia Mono", "Sarasa Mono SC", monospace;
}
```

深色主题：复用现有 `html.dark` 变量；琥珀改为更亮 `#e0a04a`。

排版：

- 正文 14px / 1.55
- 工具名 12px mono
- 标题 15px medium
- 不新引展示衬线字体（工作台一致性优先）

---

## 11. 组件树与文件落点

```
frontend/src/features/ai/
  README.md
  AssistantHost.vue              # 挂 App.vue；球+面板
  components/
    AssistantFloatBall.vue
    AssistantPanel.vue
    AssistantHeader.vue
    HistoryRail.vue
    ConversationPane.vue
    EmptyHints.vue
    UserBubble.vue
    AssistantTurn.vue
    ThinkingBlock.vue
    ToolReceipt.vue
    ConfirmCard.vue
    AskUserChips.vue
    EvidenceWarning.vue
    TurnActions.vue
    AssistantComposer.vue
    AssistantFooter.vue
  composables/
    useAssistantSessions.ts      # 列表/CRUD
    useAssistantChat.ts          # SSE / parts / abort
    useAssistantBall.ts          # 拖拽位置
    assistantSse.ts              # 纯解析
    truncateForRegenerate.ts     # 对齐 gateway regenerate
  types.ts
```

API：`shared/api/quant_ai.ts`（或并入 `quant_ops.ts`）— **唯一** HTTP 出口。  
类型：`shared/types/ai_assistant.ts`。  
Store：轻量 `useAssistantStore`（panelOpen、activeSessionId）；消息正文以 composable 会话缓存为主，避免巨型全局。

**App.vue**：登录非 public 路由挂载 `<AssistantHost />`；快捷键注册与现有 n/c/p 共存（输入框焦点时不抢）。

---

## 12. 逐屏效果说明（验收用）

### 12.1 首次打开

1. 球在右下，无面板。
2. 点击 → 面板自右滑入，遮罩淡入；输入框 focus。
3. 空态三枚提示可见；历史 rail 收起。
4. Header 模型 chip 显示默认供应商。

### 12.2 只读问答

1. 用户点「今天持仓怎么样？」→ 填入并发送。
2. 用户气泡出现；助手壳出现「连接中」。
3. `tool_start/end` 闪过 1–N 张 receipt。
4. 正文流式涌出，尾部光标；贴底滚动。
5. `done` 后光标消失；出现复制按钮。
6. Footer 显示 tokens 与耗时。

### 12.3 写持仓（确认）

1. 用户：「帮我记一笔 600519 买入 100 股 1680」。
2. 工具 receipt → 待确认卡片弹出摘要。
3. 球环变琥珀；Composer 可仍用，但建议引导点卡片。
4. 点确认 → loading → 「已写入」→ 模型续写一句确认。
5. 可选 link 跳转 `/archive/600519`。

### 12.4 选股

1. 用户要求跑选股 → 可能 AskUser 选策略。
2. 触发 run 后 receipt 含 `run_id`；可与全局 `ScreenRunChip` 同步进度。
3. 完成后摘要数字来自工具；引导打开策略页。

### 12.5 历史

1. 点历史 → rail 展开，列表载入。
2. 点旧会话 → 对话区替换为历史 messages（无光标）。
3. 删除会话 → 列表更新；若删当前则回空态。

### 12.6 错误 / 无供应商

- SSE `error`：助手轮内红色错误条 + 可「重试」。
- 无供应商：空态主按钮「去配置模型」→ `/ops` LLM。

### 12.7 移动端

- 球上移避开底栏；面板全宽；历史为面板内顶栏二级。

---

## 13. 与主流助手的对标清单

| 能力 | ChatGPT/Claude | Loci MVP |
|---|---|---|
| 悬浮入口 | 少见（多为整页） | **有**（工作台场景） |
| 历史侧栏 | 有 | 有（面板内） |
| 流式 Markdown | 有 | 有（Elements/自研） |
| 工具可视化 | 部分有 | **强制** receipt |
| 写操作确认 | 少 | **强制** ConfirmCard |
| 思考链 | 有 | 可选 Thinking |
| 插件商店 | 有 | 不做；工具=系统注册表 |
| 语音 | 有 | 不做 |

---

## 14. 依赖与工程约束

```text
+ vue-element-plus-x   # 助手层；按需注册组件，勿全局污染业务页
+ markdown-it（或 x 内置）
# 不引入第二套业务组件库替代 Element Plus
# 不引入 shadcn-vue 全量（主计划已砍）；AI Elements Vue 仅作范式参考
```

CSP：若打包 inline worker/eval，跟现有 Vite 配置验证；助手 Markdown 禁用原始 HTML。

包体积：助手路由级/`import()` 延迟加载 `AssistantPanel` 重依赖；球可同步轻量。

---

## 15. 测试与 DoD（前端）

| 项 | 命令 / 标准 |
|---|---|
| 类型 | `bun run typecheck` |
| 单测 | SSE 解析、regenerate 截断、球 clamp、parts 折叠 |
| 组件测 | ConfirmCard 点击 emit；History 删除确认 |
| e2e（可选） | 打开球 → 发 mock stream → 见 token |
| 布局 | 无 html/body 滚动；面板内滚动 |
| EP | 按钮/输入/对话框皆 EP；球可用 button role 原生圆形（注释 why：拖拽指针事件） |
| 行数 | 单文件 ≤600；Host 只编排 |

---

## 16. 文案语气（界面用词）

| 场景 | 文案 |
|---|---|
| 发送 | 发送 |
| 停止 | 停止生成 |
| 确认写 | 确认执行 |
| 拒绝写 | 取消 |
| 空历史 | 还没有对话 |
| 无模型 | 先配置模型供应商 |
| 证据警告 | 见 §6.4（不道歉、给下一步） |

用词前后一致；toast 用「已写入」「已取消」「已停止」。

---

## 17. 分阶段前端交付

| 阶段 | 交付 |
|---|---|
| F0 | 球 + 空面板 + 本地假消息（不接 SSE） |
| F1 | 接 sessions + SSE token/tool；历史列表 |
| F2 | ConfirmCard / AskUser；模型切换；快捷键 |
| F3 | 选股 run 联动、EvidenceWarning、动效打磨 |
| F4 | 全屏路由、导出、拖拽改宽 |

---

## 18. 给实现 Agent 的注意事项

1. 先接后端 SSE 契约类型，再堆皮肤。
2. 数字展示走 `NumText` / 后端字段，前端不算胜率。
3. 改 `App.vue` 保持瘦；逻辑进 composable。
4. 同步 `features/ai/README.md`。
5. 与「记一笔」FAB、底栏、ScreenRunChip 做一次真机避让验收。

---

## 19. 验收清单（前端设计落地）

- [ ] 悬浮球可拖拽、可点开、位置记忆、避让底栏
- [ ] 面板含历史 / 对话 / Composer / Footer
- [ ] 流式正文 + 思考折叠 + 工具回执
- [ ] 写确认卡片完整走通
- [ ] Elements（或降级方案）打字机/流式符合 §5
- [ ] reduced-motion 可关动画
- [ ] typecheck / 相关 test 绿；无超 600 行巨石
