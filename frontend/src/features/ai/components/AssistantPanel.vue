<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import { SidebarProvider } from '@/shared/components/ui/sidebar'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import {
  History,
  ListTodo,
  Maximize2,
  Minimize2,
  Settings2,
  Sparkles,
  X as Close,
} from '@lucide/vue'
import { toast } from 'vue-sonner'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/shared/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'

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

/**
 * 助手面板（ChatGPT / Claude 桌面端一路）。
 *
 * 壳：桌面默认是**贴右侧浮起的 520px 面板**（四角 16px、大投影、透明遮罩点外即关），
 * 可一键展开成占满视口的工作台（左会话列表 / 中对话 / 右任务侧栏三栏）；
 * ≤640 直接铺满整屏。Dialog 只提供焦点与弹层生命周期，unstyled 内容保留工作台布局；
 * unmountOnHide=false 保活会话草稿，同时关闭时释放焦点、页面可访问性与指针限制。
 *
 * 侧栏：宽屏工作台里两栏内联；贴右 / 窄屏时它们是**从面板边缘滑出的抽屉**，
 * 由页头按钮开关，同一时刻只开一侧。
 */
const HISTORY_KEY = 'loci.assistant.historyOpen'
const TASK_KEY = 'loci.assistant.taskSidebarOpen'
const WIDE_KEY = 'loci.assistant.wide'
/*
 * 侧栏折叠态是 v-if 切 DOM 的 rail 视图（历史 48px / 任务 44px），纯 CSS 断点只会把
 * 展开态的 280–300px 内容裁进窄壳里，所以断点必须落在 JS 上。
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
    hint: '<价格>买入<数量>股<标的>',
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
/** 宽屏工作台（占满视口）还是贴右浮起的窄面板 */
const wide = ref(false)
const smallScreen = useMediaQuery('(max-width: 640px)')
const workspaceWide = computed(() => wide.value && !smallScreen.value)
const threadOpen = ref(false)
const threadAgentId = ref<string | null>(null)
const senderDock = ref<{ focus: () => void; setText: (text: string) => void } | null>(null)

const sessionLocked = computed(() => Boolean(props.busy || props.waitingUser))
const showEmpty = computed(() => !props.messages.length && (props.providerReady || visitor.value))
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
const liveAgents = computed(() => props.agents.filter((agent) => agent.status === 'running' || agent.status === 'queued').length)
const activeModelLabel = computed(() => props.model || '')

let returnFocus: HTMLElement | null = null
function onOpenAutoFocus(event: Event): void {
  event.preventDefault()
  // On a phone, opening history is a reading action, not a request for the keyboard.
  if (window.matchMedia('(max-width: 640px)').matches || !props.providerReady || !senderDock.value) {
    if (event.target instanceof HTMLElement) event.target.focus({ preventScroll: true })
    return
  }
  senderDock.value.focus()
}
function onCloseAutoFocus(event: Event): void {
  event.preventDefault()
  if (returnFocus?.isConnected) returnFocus.focus()
}

watch(() => props.open, async (open) => {
  if (open && document.activeElement instanceof HTMLElement) returnFocus = document.activeElement
  await nextTick()
  if (props.open !== open) return
  if (!open) {
    if (returnFocus?.isConnected) returnFocus.focus()
  } else if (props.providerReady && !window.matchMedia('(max-width: 640px)').matches) senderDock.value?.focus()
}, { flush: 'sync' })

watch(() => props.agents.length, (count) => {
  // 窄屏别自动铺开 300px 侧栏：正文区会被挤没，折叠态的 live dot 已经能提示有任务在跑
  if (count > 0 && hasRoom(TASK_SIDEBAR_MIN_W)) setTaskSidebarOpen(true, false)
})

function hasRoom(minWidth: number): boolean {
  return window.matchMedia(`(min-width: ${minWidth}px)`).matches
}

/** 侧栏能不能内联：只有宽屏工作台且视口够宽才行，其余情况都是抽屉 */
function inlineRoom(minWidth: number): boolean {
  return wide.value && hasRoom(minWidth)
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
  applyAutoCollapse('history', historyOpen, inlineRoom(SESSION_RAIL_MIN_W))
  applyAutoCollapse('task', taskSidebarOpen, inlineRoom(TASK_SIDEBAR_MIN_W))
}

onMounted(() => {
  const saved = localStorage.getItem(HISTORY_KEY)
  if (saved === '0') historyOpen.value = false
  else if (saved === '1') historyOpen.value = true
  const taskSaved = localStorage.getItem(TASK_KEY)
  if (taskSaved === '0') taskSidebarOpen.value = false
  if (taskSaved === '1') taskSidebarOpen.value = true
  wide.value = localStorage.getItem(WIDE_KEY) === '1'
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
  if (value && !inlineRoom(1101)) taskSidebarOpen.value = false
  userToggled.history = true
  autoCollapsed.history = false
  localStorage.setItem(HISTORY_KEY, value ? '1' : '0')
}

function setTaskSidebarOpen(value: boolean, byUser = true): void {
  taskSidebarOpen.value = value
  if (value && !inlineRoom(1101)) historyOpen.value = false
  if (byUser) {
    userToggled.task = true
    autoCollapsed.task = false
  }
  localStorage.setItem(TASK_KEY, value ? '1' : '0')
}

function toggleWide(): void {
  wide.value = !wide.value
  localStorage.setItem(WIDE_KEY, wide.value ? '1' : '0')
  // 切回窄面板时抽屉不该还敞着
  if (!wide.value) {
    if (historyOpen.value) historyOpen.value = false
    if (taskSidebarOpen.value) taskSidebarOpen.value = false
  }
}

/** 抽屉模式下遮罩点一下就收起 */
function closeDrawers(): void {
  if (historyOpen.value) setHistoryOpen(false)
  if (taskSidebarOpen.value) setTaskSidebarOpen(false)
}

function pickPrompt(prompt: string): void {
  if (visitor.value) return
  if (props.busy || !props.providerReady) return
  senderDock.value?.setText(prompt)
}

function onConfirmReply(text: string): void {
  if (visitor.value) return
  const trimmed = text.trim()
  if (!trimmed || props.busy || !props.providerReady) return
  // Cursor askQuestions：选项点击直接开下一轮，不再只填草稿
  emit('send', trimmed)
}

async function onCopyMessage(text: string): Promise<void> {
  const ok = await copyTextToClipboard(text)
  if (ok) toast.success('已复制')
  else toast.error('复制失败，请手动选中消息文本复制')
}

function onRerunMessage(payload: { text: string; images?: string[] }): void {
  if (visitor.value) return
  if (props.busy || props.waitingUser || !props.providerReady) return
  emit('send', payload)
}

function openAgent(agentId: string): void {
  threadAgentId.value = agentId
  threadOpen.value = true
  setTaskSidebarOpen(true)
}

function onOverlayClick(): void {
  emit('close')
}

/** 抽屉模式下选了会话 / 新建后自动收起抽屉，别让用户再点一次遮罩 */
function onSelectSession(id: string): void {
  emit('select', id)
  if (!workspaceWide.value && historyOpen.value) setHistoryOpen(false)
}

function onCreateSession(): void {
  emit('create')
  if (!workspaceWide.value && historyOpen.value) setHistoryOpen(false)
}
</script>

<template>
  <Dialog :open="open" :unmount-on-hide="false" @update:open="!$event && emit('close')">
      <DialogContent
        unstyled
        :show-overlay="false"
        :show-close-button="false"
        :aria-describedby="undefined"
        aria-modal="true"
        class="assistant-overlay"
        :class="{ 'is-wide': workspaceWide }"
        data-testid="assistant-overlay"
        @click.self="onOverlayClick"
        @open-auto-focus="onOpenAutoFocus"
        @close-auto-focus="onCloseAutoFocus"
      >
        <DialogTitle class="sr-only">落点助手</DialogTitle>
        <section
          class="assistant-panel"
          :class="{ 'is-wide': workspaceWide, 'has-rail': historyOpen, 'has-task': taskSidebarOpen }"
          data-testid="assistant-dialog"
        >
          <header class="assistant-panel__head">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button access="read"
                  variant="ghost"
                  size="icon-sm"
                  class="assistant-panel__icon"
                  :class="{ 'is-on': historyOpen }"
                  :aria-pressed="historyOpen"
                  aria-label="历史对话"
                  data-testid="assistant-history-toggle"
                  @click="setHistoryOpen(!historyOpen)"
                >
                  <History />
                </Button>
              </TooltipTrigger>
              <TooltipContent>历史对话</TooltipContent>
            </Tooltip>
            <span class="assistant-panel__brand" :class="{ 'is-busy': busy }" aria-hidden="true"><Sparkles /></span>
            <div class="assistant-panel__identity">
              <strong class="assistant-panel__title">{{ title || 'Loci 助手' }}</strong>
              <span v-if="activeModelLabel" class="assistant-panel__model" :title="activeModelLabel">{{ activeModelLabel }}</span>
            </div>
            <UiBadge v-if="waitingUser" variant="warn" dot class="assistant-panel__state">等待确认</UiBadge>
            <UiBadge v-else-if="busy" variant="info" dot class="assistant-panel__state">运行中</UiBadge>
            <div class="assistant-panel__tools">
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button access="read"
                    variant="ghost"
                    size="icon-sm"
                    class="assistant-panel__icon"
                    :class="{ 'is-on': taskSidebarOpen }"
                    :aria-pressed="taskSidebarOpen"
                    aria-label="本轮任务"
                    data-testid="assistant-task-toggle"
                    @click="setTaskSidebarOpen(!taskSidebarOpen)"
                  >
                    <ListTodo />
                    <span v-if="liveAgents" class="assistant-panel__live" aria-hidden="true" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>本轮任务 / 来源 / 产物</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button access="read"
                    variant="ghost"
                    size="icon-sm"
                    class="assistant-panel__icon assistant-panel__wide"
                    :aria-label="wide ? '收成侧栏' : '展开为工作台'"
                    data-testid="assistant-wide-toggle"
                    @click="toggleWide"
                  >
                    <Minimize2 v-if="wide" />
                    <Maximize2 v-else />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{{ wide ? '收成侧栏' : '展开为工作台' }}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    class="assistant-panel__icon"
                    aria-label="助手设置"
                    data-testid="assistant-settings"
                    @click="emit('settings')"
                  >
                    <Settings2 />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>助手设置</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button access="read"
                    variant="ghost"
                    size="icon-sm"
                    class="assistant-panel__icon assistant-panel__close"
                    aria-label="关闭助手"
                    @click="emit('close')"
                  >
                    <Close />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>关闭助手 · Esc</TooltipContent>
              </Tooltip>
            </div>
          </header>

          <div v-if="error" class="assistant-panel__alert" role="alert">
            <span class="min-w-0 flex-1">{{ error }}</span>
            <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" @click="emit('clear-error')">
              <Close class="size-3.5" />
            </Button>
          </div>
          <div v-if="!providerReady && !visitor" class="assistant-panel__provider-empty" role="status">
            <span class="assistant-panel__provider-text">未配置模型</span>
            <Button data-testid="assistant-configure-provider" size="sm" @click="emit('configure')">
              配置模型
            </Button>
          </div>

          <SidebarProvider :open="historyOpen" :persist="false" :keyboard-shortcut="false" class="assistant-panel__body min-h-0" @update:open="setHistoryOpen">
            <div
              v-if="!workspaceWide && (historyOpen || taskSidebarOpen)"
              class="assistant-panel__scrim"
              aria-hidden="true"
              @click="closeDrawers"
            />
            <AssistantSessionRail
              :sessions="sessions"
              :archived-sessions="archivedSessions"
              :rail-tab="railTab"
              :active-id="activeId"
              :loading="loading"
              :disabled="sessionLocked"
              :collapsed="!historyOpen"
              :drawer="!workspaceWide"
              @create="onCreateSession"
              @select="onSelectSession"
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
              <footer v-if="!visitor" class="assistant-panel__composer">
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
              :drawer="!workspaceWide"
              :tools="latestAssistant?.tool_receipts"
              :artifacts="taskModel.artifacts"
              :profile="profile"
              :memories="memories"
              @update:open="setTaskSidebarOpen"
              @open-agent="openAgent"
              @settings="emit('settings')"
            />
          </SidebarProvider>
        </section>

        <AssistantAgentThread v-model:open="threadOpen" :agent="threadAgent" />
      </DialogContent>
  </Dialog>
</template>

<style scoped src="./AssistantPanel.css"></style>

<!-- 助手域尺寸契约（unscoped）：弹层被 teleport 到 body，取不到 .assistant-panel 的继承链 -->
<style>
.assistant-panel,
.assistant-task-sidebar,
.assistant-agent-thread-dialog,
.assistant-settings-dialog,
.assistant-runtime-popper,
.ctx-usage-popper {
  --ai-gap-xs: var(--gap-1);
  --ai-gap-sm: var(--gap-2);
  --ai-gap-md: var(--gap-3);
  --ai-gap-lg: var(--gap-4);
  --ai-pad-y: var(--gap-2);
  --ai-pad-x: var(--gap-3);
  --ai-block-pad: var(--ai-pad-y) var(--ai-pad-x);
  --ai-row-min: var(--ctl-h);
  --ai-process-max: 100%;

  --ai-fs-title: var(--fs-title);
  --ai-fs-prose: var(--fs-body);
  --ai-fs-body: var(--fs-ui);
  --ai-fs-aux: var(--fs-aux);
  --ai-fs-meta: var(--fs-kicker);

  --ai-r-card: var(--radius-lg);
  --ai-r-chip: var(--radius-sm);
  --ai-r-pill: var(--radius-pill);

  /*
   * 上下文构成条的定性分类色：只负责「八段互相可分」，不承载涨跌 / 成败语义，
   * 因此不挂 --up / --down / --warn 这类会被误读的 token。
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

/* 开合动效：遮罩淡入，面板从右侧 12px 滑入（手机从底部） */
.assistant-fade-enter-active,
.assistant-fade-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.assistant-fade-enter-active .assistant-panel,
.assistant-fade-leave-active .assistant-panel {
  transition:
    transform var(--dur) var(--ease),
    opacity var(--dur) var(--ease);
}

.assistant-fade-enter-from,
.assistant-fade-leave-to {
  opacity: 0;
}

.assistant-fade-enter-from .assistant-panel,
.assistant-fade-leave-to .assistant-panel {
  transform: translateX(16px);
  opacity: 0;
}

@media (max-width: 640px) {
  .assistant-fade-enter-from .assistant-panel,
  .assistant-fade-leave-to .assistant-panel {
    transform: translateY(24px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-fade-enter-active,
  .assistant-fade-leave-active,
  .assistant-fade-enter-active .assistant-panel,
  .assistant-fade-leave-active .assistant-panel {
    transition: none;
  }
}
</style>
