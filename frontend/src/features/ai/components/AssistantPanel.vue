<script setup lang="ts">
import { ChatDotRound, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

import { copyTextToClipboard } from '../assistantMessageActions'
import { buildTaskModel, type TaskPlanStep } from '../assistantTaskModel'
import AssistantAgentThread from './AssistantAgentThread.vue'
import AssistantConversation from './AssistantConversation.vue'
import AssistantEmptyState, { type AssistantPromptCard } from './AssistantEmptyState.vue'
import AssistantSenderDock from './AssistantSenderDock.vue'
import type { ThinkingLevel } from './AssistantRuntimeBar.vue'
import AssistantSessionRail from './AssistantSessionRail.vue'
import AssistantTaskSidebar from './AssistantTaskSidebar.vue'
import type {
  AiAgentProgress,
  AiAssistantProfile,
  AiMemoryItem,
  AiMessage,
  AiProviderProfile,
  AiSessionSummary,
  AiToolsCatalog,
} from '@/shared/types/ai_assistant'

const HISTORY_KEY = 'loci.assistant.historyOpen'
const TASK_KEY = 'loci.assistant.taskSidebarOpen'
/*
 * 侧栏折叠态是 v-if 切 DOM 的 rail 视图（历史 48px / 任务 44px），纯 CSS 断点只会把
 * 展开态的 280–300px 内容裁进窄壳里，所以断点必须落在 JS 上。
 * 900px 沿用此前 historyOpen 的初始化阈值；任务侧栏更宽，980px 以下先收它。
 */
const SESSION_RAIL_MIN_W = 900
const TASK_SIDEBAR_MIN_W = 980
/** 用户本次会话显式动过的那一侧，断点不再插手 */
const userToggled = { history: false, task: false }
/** 记住「这次是断点折的」，窗口变宽才好还回去；自动路径不写 localStorage，偏好不被改写 */
const autoCollapsed = { history: false, task: false }

/*
 * 交割范例只教格式，禁止写成像真实持仓的价格 / 股数：
 * 范例填进输入框后离「回车写进账本」只差一步，具体数字会被误当成用户自己的仓位。
 */
const PROMPTS: AssistantPromptCard[] = [
  {
    id: 'settle-today',
    title: '记录当日交割',
    hint: '<价格>买入<数量>股<标的>，多笔用逗号分隔',
    prompt: [
      '记录当日交割',
      '<价格>买入<数量>股<标的>，<价格>卖出<数量>股<标的>',
      '多笔用逗号或换行分隔；不确定的字段可以留空让我问你',
    ].join('\n'),
  },
  {
    id: 'settle-yesterday',
    title: '昨日交割补充',
    hint: '<价格>卖出<数量>股<标的>',
    prompt: '昨日交割补充\n<价格>卖出<数量>股<标的>',
  },
  {
    id: 'positions',
    title: '查看持仓',
    hint: '今天持仓怎么样？',
    prompt: '今天持仓怎么样？',
  },
  {
    id: 'screen',
    title: '跑一遍选股',
    hint: '用当前默认策略跑一遍选股',
    prompt: '用当前默认策略跑一遍选股',
  },
  {
    id: 'strategy',
    title: '解释策略参数',
    hint: '解释一下当前默认策略的关键参数和入口时机',
    prompt: '解释一下当前默认策略的关键参数和入口时机',
  },
  {
    id: 'market',
    title: '检查行情同步',
    hint: '检查一下本地行情数据同步状态',
    prompt: '检查一下本地行情数据同步状态',
  },
]

const props = defineProps<{
  open: boolean
  title?: string
  sessions: AiSessionSummary[]
  archivedSessions: AiSessionSummary[]
  railTab: 'active' | 'archived'
  activeId?: string
  messages: AiMessage[]
  agents: AiAgentProgress[]
  planSteps?: TaskPlanStep[]
  loading?: boolean
  busy?: boolean
  waitingUser?: boolean
  providerReady: boolean
  providers: AiProviderProfile[]
  provider: string
  model: string
  thinking: ThinkingLevel
  error?: string
  profile?: AiAssistantProfile | null
  memories?: AiMemoryItem[]
  toolsCatalog?: AiToolsCatalog | null
  /** 最近一轮供应商 input_tokens，供上下文环校准 */
  observedInputTokens?: number | null
}>()
const emit = defineEmits<{
  close: []
  create: []
  select: [id: string]
  remove: [id: string]
  archive: [id: string]
  restore: [id: string]
  batch: [payload: { action: 'archive' | 'unarchive' | 'delete'; ids: string[] }]
  'update:railTab': [tab: 'active' | 'archived']
  settings: []
  send: [payload: string | { text: string; images?: string[] }]
  cancel: []
  'clear-error': []
  'runtime-select': [payload: { provider: string; model: string }]
  thinking: [level: ThinkingLevel]
  configure: []
  'slash-command': [slug: string]
}>()

/** true = expanded; false = collapsed icon strip (history / task). */
const historyOpen = ref(true)
const taskSidebarOpen = ref(false)
const threadOpen = ref(false)
const threadAgentId = ref<string | null>(null)
const senderDock = ref<{ focus: () => void; setText: (text: string) => void } | null>(null)

const sessionLocked = computed(() => Boolean(props.busy || props.waitingUser))
const showEmpty = computed(() => !props.messages.length && props.providerReady)
const taskModel = computed(() => buildTaskModel({
  agents: props.agents,
  messages: props.messages,
  planSteps: props.planSteps,
  busy: props.busy,
}))
const threadAgent = computed(() => {
  if (!threadAgentId.value) return null
  return taskModel.value.agents.find((agent) => agent.id === threadAgentId.value) ?? null
})
const latestAssistant = computed(() => {
  for (let index = props.messages.length - 1; index >= 0; index -= 1) {
    if (props.messages[index]?.role === 'assistant') return props.messages[index]
  }
  return undefined
})

watch(() => props.open, async (open) => {
  if (!open || !props.providerReady) return
  await nextTick()
  senderDock.value?.focus()
})

watch(() => props.agents.length, (count) => {
  // 窄屏别自动铺开 300px 侧栏：正文区会被挤没，折叠态的 live dot 已经能提示有任务在跑
  if (count > 0 && hasRoom(TASK_SIDEBAR_MIN_W)) setTaskSidebarOpen(true, false)
})

function hasRoom(minWidth: number): boolean {
  return window.matchMedia(`(min-width: ${minWidth}px)`).matches
}

function applyAutoCollapse(key: 'history' | 'task', open: Ref<boolean>, roomy: boolean): void {
  if (userToggled[key]) return
  if (!roomy && open.value) {
    open.value = false
    autoCollapsed[key] = true
  } else if (roomy && autoCollapsed[key]) {
    open.value = true
    autoCollapsed[key] = false
  }
}

function syncViewportCollapse(): void {
  applyAutoCollapse('history', historyOpen, hasRoom(SESSION_RAIL_MIN_W))
  applyAutoCollapse('task', taskSidebarOpen, hasRoom(TASK_SIDEBAR_MIN_W))
}

onMounted(() => {
  const saved = localStorage.getItem(HISTORY_KEY)
  if (saved === '0') historyOpen.value = false
  else if (saved === '1') historyOpen.value = true
  const taskSaved = localStorage.getItem(TASK_KEY)
  if (taskSaved === '0') taskSidebarOpen.value = false
  if (taskSaved === '1') taskSidebarOpen.value = true
  // 记住的偏好也要过一遍断点：窄屏上把侧栏铺开等于把正文区挤没
  syncViewportCollapse()
  window.addEventListener('resize', syncViewportCollapse)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncViewportCollapse)
})

function setHistoryOpen(value: boolean): void {
  historyOpen.value = value
  // 覆盖侧栏同一时刻只展开一侧；不改写另一侧的持久偏好。
  if (value && !hasRoom(1101)) taskSidebarOpen.value = false
  userToggled.history = true
  autoCollapsed.history = false
  localStorage.setItem(HISTORY_KEY, value ? '1' : '0')
}

function pickPrompt(prompt: string): void {
  if (props.busy || !props.providerReady) return
  senderDock.value?.setText(prompt)
}

function onConfirmReply(text: string): void {
  const trimmed = text.trim()
  if (!trimmed || props.busy || !props.providerReady) return
  // Cursor askQuestions：选项点击直接开下一轮，不再只填草稿
  emit('send', trimmed)
}

async function onCopyMessage(text: string): Promise<void> {
  const ok = await copyTextToClipboard(text)
  if (ok) ElMessage.success('已复制')
  else ElMessage.error('复制失败，请手动选中消息文本复制')
}

function onRerunMessage(payload: { text: string; images?: string[] }): void {
  if (props.busy || props.waitingUser || !props.providerReady) return
  emit('send', payload)
}

function openAgent(agentId: string): void {
  threadAgentId.value = agentId
  threadOpen.value = true
  setTaskSidebarOpen(true)
}

function setTaskSidebarOpen(value: boolean, byUser = true): void {
  taskSidebarOpen.value = value
  if (value && !hasRoom(1101)) historyOpen.value = false
  if (byUser) {
    userToggled.task = true
    autoCollapsed.task = false
  }
  localStorage.setItem(TASK_KEY, value ? '1' : '0')
}
</script>

<template>
  <el-dialog
    :model-value="open"
    width="90%"
    :align-center="false"
    top="5vh"
    :show-close="false"
    :destroy-on-close="false"
    :close-on-click-modal="true"
    append-to-body
    aria-label="落点助手"
    class="assistant-dialog"
    modal-class="assistant-dialog-overlay"
    @update:model-value="(value: boolean) => !value && emit('close')"
  >
    <section
      class="assistant-panel flex min-h-0 flex-col overflow-hidden"
      :class="{ 'has-rail': historyOpen, 'has-task': taskSidebarOpen }"
      aria-label="落点助手"
    >
      <header class="assistant-panel__head">
        <span class="assistant-panel__identity"><el-icon><ChatDotRound /></el-icon><strong>{{ title || 'Loci 助手' }}</strong></span>
        <el-tag v-if="waitingUser" size="small" type="warning" effect="plain">等待确认</el-tag>
        <el-tag v-else-if="busy" size="small" effect="plain">运行中</el-tag>
        <span v-if="model" class="assistant-panel__model" :title="model">{{ model }}</span>
        <el-tooltip content="关闭助手 · Esc">
          <el-button class="assistant-panel__close" :icon="Close" text circle aria-label="关闭助手" @click="emit('close')" />
        </el-tooltip>
      </header>
      <el-alert
        v-if="error"
        class="assistant-panel__alert"
        type="error"
        closable
        :title="error"
        show-icon
        @close="emit('clear-error')"
      />
      <div v-if="!providerReady" class="assistant-panel__provider-empty">
        <el-alert
          class="assistant-panel__alert"
          type="warning"
          :closable="false"
          title="尚未配置可用模型"
          show-icon
        />
        <el-button data-testid="assistant-configure-provider" type="primary" plain size="small" @click="emit('configure')">
          配置模型
        </el-button>
      </div>

      <div class="assistant-panel__body">
        <AssistantSessionRail
          :sessions="sessions"
          :archived-sessions="archivedSessions"
          :rail-tab="railTab"
          :active-id="activeId"
          :loading="loading"
          :disabled="sessionLocked"
          :collapsed="!historyOpen"
          @create="emit('create')"
          @select="emit('select', $event)"
          @remove="emit('remove', $event)"
          @archive="emit('archive', $event)"
          @restore="emit('restore', $event)"
          @batch="emit('batch', $event)"
          @settings="emit('settings')"
          @update:rail-tab="emit('update:railTab', $event)"
          @update:collapsed="(value) => setHistoryOpen(!value)"
        />
        <main class="assistant-panel__stage">
          <AssistantEmptyState
            v-if="showEmpty"
            :prompts="PROMPTS"
            :busy="busy"
            :provider-ready="providerReady"
            @pick="pickPrompt"
          />
          <AssistantConversation
            v-else
            :messages="messages"
            :busy="busy"
            :waiting-user="waitingUser"
            :agents="agents"
            @confirm-reply="onConfirmReply"
            @open-agent="openAgent"
            @copy="onCopyMessage"
            @rerun="onRerunMessage"
          />
          <footer class="assistant-panel__composer">
            <AssistantSenderDock
              ref="senderDock"
              :providers="providers"
              :provider="provider"
              :model="model"
              :thinking="thinking"
              :provider-ready="providerReady"
              :busy="busy"
              :waiting-user="waitingUser"
              :session-locked="sessionLocked"
              :messages="messages"
              :profile="profile"
              :memories="memories"
              :tools-catalog="toolsCatalog"
              :observed-input-tokens="observedInputTokens"
              @send="emit('send', $event)"
              @cancel="emit('cancel')"
              @runtime-select="emit('runtime-select', $event)"
              @thinking="emit('thinking', $event)"
              @slash-command="emit('slash-command', $event)"
            />
          </footer>
        </main>
        <AssistantTaskSidebar
          :model="taskModel"
          :open="taskSidebarOpen"
          :tools="latestAssistant?.tool_receipts"
          :artifacts="latestAssistant?.artifacts"
          :profile="profile"
          :memories="memories"
          @update:open="setTaskSidebarOpen"
          @open-agent="openAgent"
          @settings="emit('settings')"
        />
      </div>
    </section>

    <AssistantAgentThread v-model:open="threadOpen" :agent="threadAgent" />
  </el-dialog>
</template>

<style scoped src="./AssistantPanel.css"></style>

<!-- Dialog shell must be unscoped: el-dialog teleports to body. -->
<style>
/*
 * 助手域尺寸契约：间距 / 字阶 / 圆角 / 分类色只在这里定义一次。
 * 必须 unscoped 并列出各弹层根——AgentThread、设置弹窗、上下文用量 popover
 * 都被 el-dialog / el-popover teleport 到 body，取不到 .assistant-panel 的继承链。
 */
.assistant-panel,
.assistant-task-sidebar,
.assistant-agent-thread-dialog,
.assistant-settings-dialog,
.assistant-runtime-popper,
.ctx-usage-popper {
  /* 紧凑内容型：行内有气口，块与块别糊、也别拉成空白大海 */
  --ai-gap-xs: var(--gap-1);
  --ai-gap-sm: var(--gap-2);
  --ai-gap-md: var(--gap-2);
  --ai-gap-lg: var(--gap-3);
  --ai-pad-y: var(--gap-2);
  --ai-pad-x: var(--gap-3);
  --ai-block-pad: var(--ai-pad-y) var(--ai-pad-x);
  --ai-row-min: var(--ctl-h);
  --ai-process-max: 100%;

  /*
   * 字阶：助手是密集工作面，正文比全站正文紧一档（--fs-body .9 → --fs-aux .8）。
   * 整体放大 / 缩小只改这四行，不要回到各组件里写死。
   * aux 与 meta 今天同值：全站字阶在 .8 与 .7 之间没有档位，--fs-kicker 就是本域地板；
   * 两者语义仍分开（aux = 次要正文，meta = mono / 大写微标），要拉开层级也只改这里。
   */
  --ai-fs-title: var(--fs-title);
  /*
   * prose 只给「用户真正在读的」助手回答正文，与全站正文同档；
   * body 给面板 chrome（卡片小标题、回执行、会话列表）保持紧一档。
   * 两者分开，是因为把阅读正文和 UI 元信息压成同一个字号，
   * 会让助手成为全站唯一需要凑近看的区域。
   */
  --ai-fs-prose: var(--fs-body);
  --ai-fs-body: var(--fs-aux);
  --ai-fs-aux: var(--fs-kicker);
  --ai-fs-meta: var(--fs-kicker);

  /* 圆角：卡片跟全站 --radius，chip 收一档，pill 走胶囊 */
  --ai-r-card: var(--radius);
  --ai-r-chip: var(--radius-sm);
  --ai-r-pill: var(--radius-pill);

  /*
   * 上下文构成条的定性分类色：只负责「八段互相可分」，不承载涨跌 / 成败语义，
   * 因此不挂 --up / --down / --warn 这类会被误读的 token。
   * 这批是 Tailwind 600/700 档（L≈0.47–0.55），只为浅底挑的；深色档覆写见下面一块。
   */
  --ai-cat-1: #64748b;
  --ai-cat-2: #4f46e5;
  --ai-cat-3: #15803d;
  --ai-cat-4: #a16207;
  --ai-cat-5: #be185d;
  --ai-cat-6: #9a3412;
  --ai-cat-7: #0f766e;
  --ai-cat-8: #0369a1;
}

/*
 * night / ink / dark 的画布明度只有 0.13–0.19，上面那批 600/700 档 hex 压上去
 * 对画布只有 2.5–4.2:1，相邻两段糊成一片（实测：明档八色对 night 画布 3.89 2.94
 * 3.69 3.76 3.06 2.53 3.38 3.12）。深色档把 L 抬到 .64–.78，色相沿用明档实测的
 * 八个（257 277 150 72 350 33 186 243），保证同一段换外观还是「同一个色」。
 * 实测改后对 night 画布 5.1–9.0:1，八段两两 sRGB 最小色距 56（明档 48），可分性不降。
 */
html[data-appearance='night']
  :is(.assistant-panel, .assistant-task-sidebar, .assistant-agent-thread-dialog, .assistant-settings-dialog, .assistant-runtime-popper, .ctx-usage-popper),
html[data-appearance='ink']
  :is(.assistant-panel, .assistant-task-sidebar, .assistant-agent-thread-dialog, .assistant-settings-dialog, .assistant-runtime-popper, .ctx-usage-popper),
html.dark
  :is(.assistant-panel, .assistant-task-sidebar, .assistant-agent-thread-dialog, .assistant-settings-dialog, .assistant-runtime-popper, .ctx-usage-popper) {
  --ai-cat-1: oklch(.72 .04 257);
  --ai-cat-2: oklch(.7 .16 277);
  --ai-cat-3: oklch(.72 .14 150);
  --ai-cat-4: oklch(.78 .14 72);
  --ai-cat-5: oklch(.72 .17 350);
  --ai-cat-6: oklch(.64 .16 33);
  --ai-cat-7: oklch(.72 .09 186);
  --ai-cat-8: oklch(.72 .12 243);
}

.assistant-dialog.el-dialog {
  --el-dialog-padding-primary: 0;
  width: 90% !important;
  height: 90dvh;
  max-height: 90dvh;
  margin-top: 5vh !important;
  margin-bottom: 5vh !important;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 !important;
}
.assistant-dialog .el-dialog__header {
  display: none;
  padding: 0 !important;
  margin: 0;
}
.assistant-dialog > .el-dialog__body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
  /* 普通表单弹窗的全局 68dvh 限高不适用于已自行管理滚动的助手工作台。 */
  max-height: none;
  /* 去掉 dialog 默认内边距，内容贴齐弹窗内沿 */
  padding: 0 !important;
  margin: 0 !important;
  overflow: hidden;
}
.assistant-dialog-overlay {
  display: flex;
  align-items: flex-start;
  justify-content: center;
}
.assistant-dialog-overlay .el-overlay-dialog {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 0;
}
@media (max-width: 640px) {
  .assistant-dialog.el-dialog {
    width: calc(100% - var(--gap-4)) !important;
    max-width: calc(100vw - var(--gap-4));
    height: calc(100dvh - var(--gap-4));
    max-height: calc(100dvh - var(--gap-4));
    margin-block: var(--gap-2) !important;
  }
  .ctx-usage-popper { max-width: calc(100vw - var(--gap-4)); }
}
</style>
