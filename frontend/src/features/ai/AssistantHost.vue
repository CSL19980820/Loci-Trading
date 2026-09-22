<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { toast } from 'vue-sonner'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  compactAiSession,
  createAiSession,
  deleteAiSession,
  getAiProfile,
  getAiSession,
  getAiTools,
  listAiMemories,
} from '@/shared/api/ai_assistant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  AiAgentProgress,
  AiAssistantProfile,
  AiMemoryItem,
  AiMessage,
  AiProviderProfile,
  AiRun,
  AiSessionDetail,
  AiSessionSummary,
  AiToolsCatalog,
} from '@/shared/types/ai_assistant'
import {
  archiveAiSession,
  batchAiSessionAction,
  deleteAiSessionsWithConfirm,
  refreshAiSessionLists,
  restoreAiSession,
} from './assistantSessionActions'
import { mergeSessionMessages } from './assistantSessionMerge'
import { useAssistantHostRun } from './useAssistantHostRun'
import AssistantFloatBall from './components/AssistantFloatBall.vue'
import AssistantPanel from './components/AssistantPanel.vue'
import AssistantSettingsDialog from './components/AssistantSettingsDialog.vue'
import type { ThinkingLevel } from './components/AssistantRuntimeBar.vue'
import type { TaskPlanStep } from './assistantTaskModel'

type SessionWithRun = AiSessionDetail & { active_run?: AiRun | null }

const THINKING_KEY = 'loci.assistant.thinking'
const THINKING_LEVELS: ThinkingLevel[] = ['off', 'low', 'medium', 'high', 'xhigh', 'max']

const open = ref(false)
const compactMobile = useMediaQuery('(max-width:767px)')
const router = useRouter()
const loading = ref(false)
const error = ref('')
const sessions = ref<AiSessionSummary[]>([])
const archivedSessions = ref<AiSessionSummary[]>([])
const railTab = ref<'active' | 'archived'>('active')
const settingsOpen = ref(false)
const active = ref<AiSessionDetail | null>(null)
// shallowRef：长会话下不必为每条消息及其 tool_receipts / artifacts 建响应式代理。
// 前提是所有更新都换新数组、且改单条消息前先复制（见 assistantRunState 的
// cloneAssistantForMutation）。往 messages.value[i] 上原地赋值不会触发渲染。
const messages = shallowRef<AiMessage[]>([])
const agents = ref<AiAgentProgress[]>([])
const planSteps = ref<TaskPlanStep[]>([])
const run = ref<AiRun | null>(null)
const providerReady = ref(false)
const providers = ref<AiProviderProfile[]>([])
const toolsCatalog = ref<AiToolsCatalog | null>(null)
const profile = ref<AiAssistantProfile | null>(null)
const memories = ref<AiMemoryItem[]>([])
const provider = ref('')
const model = ref('')
const thinking = ref<ThinkingLevel>('medium')
const dispatching = ref(false)
let selectionVersion = 0
let selectingSessionId: string | null = null
let sessionsVersion = 0
let disposed = false

function isActiveRun(): boolean { return run.value?.status === 'running' }
function isWaitingUser(): boolean { return run.value?.status === 'waiting_user' }
function isBusy(): boolean { return dispatching.value || isActiveRun() }
function isSessionLocked(): boolean { return isBusy() || isWaitingUser() }

const selectedProvider = computed(() => providers.value.find((item) => item.name === provider.value))
const models = computed(() => selectedProvider.value?.models ?? [])

function normalizeThinking(value: string | null | undefined): ThinkingLevel {
  return THINKING_LEVELS.includes(value as ThinkingLevel) ? (value as ThinkingLevel) : 'medium'
}

function chooseThinking(next: ThinkingLevel): void {
  thinking.value = normalizeThinking(next)
  localStorage.setItem(THINKING_KEY, thinking.value)
}

function selectionIsCurrent(version: number): boolean {
  return !disposed && version === selectionVersion
}

async function syncSessionMessages(sessionId: string): Promise<void> {
  try {
    const detail = await getAiSession(sessionId) as SessionWithRun
    if (disposed || active.value?.id !== sessionId) return
    const remote = detail.messages ?? []
    if (!remote.length) return
    messages.value = mergeSessionMessages(messages.value, remote)
    active.value = { ...active.value, ...detail, messages: messages.value }
  } catch {
    /* keep local transcript if refresh fails */
  }
}

async function loadCatalog(): Promise<void> {
  if (visitor.value) return
  const catalog = await getAiTools()
  if (disposed) return
  toolsCatalog.value = catalog
  providers.value = catalog.providers ?? []
  providerReady.value = catalog.provider_configured !== false
  if (!providers.value.some((item) => item.name === provider.value)) {
    chooseProvider(providers.value.find((item) => item.is_default)?.name ?? providers.value[0]?.name ?? '')
  } else if (!models.value.includes(model.value)) {
    model.value = selectedProvider.value?.default_model ?? models.value[0] ?? ''
  }
}

async function loadContextSources(): Promise<void> {
  if (visitor.value) return
  try {
    const [nextProfile, nextMemories] = await Promise.all([
      getAiProfile(),
      listAiMemories(),
    ])
    if (disposed) return
    profile.value = nextProfile
    memories.value = nextMemories
  } catch {
    if (disposed) return
    profile.value = null
    memories.value = []
  }
}

function chooseProvider(next: string): void {
  const selected = providers.value.find((item) => item.name === next)
  provider.value = selected?.name ?? ''
  model.value = selected?.default_model ?? selected?.models[0] ?? ''
}

function chooseModel(next: string): void {
  model.value = models.value.includes(next) ? next : selectedProvider.value?.default_model ?? ''
}

function chooseProviderAndModel(nextProvider: string, nextModel: string): void {
  const selected = providers.value.find((item) => item.name === nextProvider)
  provider.value = selected?.name ?? ''
  const available = selected?.models ?? []
  model.value = available.includes(nextModel)
    ? nextModel
    : selected?.default_model ?? available[0] ?? ''
}

async function loadSessions(): Promise<void> {
  await refreshAiSessionLists(sessions, archivedSessions, {
    bump: () => ++sessionsVersion,
    isCurrent: (version) => !disposed && version === sessionsVersion,
  })
}

async function openAssistant(): Promise<void> {
  if (disposed) return
  open.value = true
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadCatalog(), loadSessions(), loadContextSources()])
    if (disposed) return
    if (!active.value && sessions.value[0]) {
      await selectSession(sessions.value[0].id)
    }
  } catch (caught) {
    error.value = toErrorMessage(caught, '无法连接 AI 助手服务')
  } finally {
    loading.value = false
  }
}

async function selectSession(id: string): Promise<void> {
  if (isSessionLocked() && active.value?.id !== id) {
    error.value = isWaitingUser()
      ? '当前对话等待你的回复，请先回复或取消后再切换。'
      : '当前对话仍在运行，请先中止后再切换。'
    return
  }
  if (isSessionLocked() && active.value?.id === id) return
  if (active.value?.id !== id && !isSessionLocked()) {
    hostRun.abortActiveStream()
    run.value = null
  }
  const version = ++selectionVersion
  selectingSessionId = id
  loading.value = true
  error.value = ''
  try {
    const detail = await getAiSession(id) as SessionWithRun
    if (!selectionIsCurrent(version)) return
    active.value = detail
    messages.value = detail.messages ?? []
    agents.value = []
    planSteps.value = []
    if (detail.provider) chooseProvider(detail.provider)
    if (detail.model) chooseModel(detail.model)
    hostRun.restoreActiveRun(detail, isActiveRun)
  } catch (caught) {
    if (selectionIsCurrent(version)) error.value = toErrorMessage(caught, '加载会话失败')
  } finally {
    if (selectionIsCurrent(version)) {
      loading.value = false
      selectingSessionId = null
    }
  }
}

async function createSession(options: { fromSend?: boolean } = {}): Promise<AiSessionDetail | null> {
  if (visitor.value) return null
  if (isActiveRun() || isWaitingUser() || (dispatching.value && !options.fromSend)) return null
  // Reuse the current empty draft so 「新建」不会堆出一串「新对话」.
  if (active.value && !messages.value.length) return active.value
  const draftSummary = sessions.value.find((session) => {
    const title = (session.title || '').trim()
    return !title || title === '新对话'
  })
  if (draftSummary && draftSummary.id !== active.value?.id) {
    await selectSession(draftSummary.id)
    if (active.value?.id === draftSummary.id && !messages.value.length) return active.value
  }
  const version = ++selectionVersion
  selectingSessionId = null
  loading.value = true
  error.value = ''
  try {
    const detail = await createAiSession({ provider: provider.value, model: model.value })
    if (!selectionIsCurrent(version)) {
      void loadSessions().catch(() => undefined)
      return null
    }
    hostRun.abortActiveStream()
    run.value = null
    active.value = detail
    messages.value = detail.messages ?? []
    agents.value = []
    planSteps.value = []
    sessionsVersion += 1
    sessions.value = [detail, ...sessions.value.filter((session) => session.id !== detail.id)]
    return detail
  } catch (caught) {
    error.value = toErrorMessage(caught, '新建对话失败')
    return null
  } finally {
    if (selectionIsCurrent(version)) loading.value = false
  }
}

const hostRun = useAssistantHostRun({
  disposed: () => disposed,
  selectionVersion: () => selectionVersion,
  active,
  messages,
  agents,
  planSteps,
  run,
  error,
  dispatching,
  provider,
  model,
  thinking,
  providerReady,
  sessions,
  createSession,
  syncSessionMessages,
  loadSessions,
})

async function onSlashCommand(slug: string): Promise<void> {
  if (slug !== 'compact') return
  const sessionId = active.value?.id
  if (!sessionId) {
    toast.warning('请先打开或新建对话')
    return
  }
  if (isSessionLocked()) {
    toast.warning('会话占用中，请先结束或取消本轮再压缩')
    return
  }
  try {
    const result = await compactAiSession(sessionId)
    const notice = (result.message || '').trim() || '已压缩较早对话（库内原文仍在）'
    const after = Number(result.tokens_after)
    const msgs = messages.value
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      const row = msgs[i]
      if (row?.role !== 'assistant') continue
      const next = {
        ...row,
        warnings: [...(row.warnings ?? []), notice],
        ...(after > 0 ? { context_feed_tokens: after } : {}),
      }
      messages.value = [...msgs.slice(0, i), next, ...msgs.slice(i + 1)]
      break
    }
    toast.success(notice)
  } catch (caught) {
    toast.error(toErrorMessage(caught, '压缩失败'))
  }
}

/** Drop empty drafts when leaving the assistant; landed sessions (有消息) keep. */
async function discardEmptyDraftOnClose(): Promise<void> {
  if (visitor.value) return
  if (isSessionLocked()) return
  const draft = active.value
  if (!draft || messages.value.length > 0) return
  const id = draft.id
  clearIfActive(id)
  sessions.value = sessions.value.filter((session) => session.id !== id)
  try {
    await deleteAiSession(id)
  } catch {
    /* best-effort prune; list refresh on next open */
  }
}

function clearIfActive(id: string): void {
  if (selectingSessionId === id || (!selectingSessionId && active.value?.id === id)) {
    selectionVersion += 1
    selectingSessionId = null
    loading.value = false
    hostRun.abortActiveStream()
    run.value = null
  }
  if (active.value?.id === id) {
    active.value = null
    messages.value = []
    agents.value = []
  }
}

async function removeSession(id: string): Promise<void> {
  if (isSessionLocked()) return
  sessionsVersion += 1
  await deleteAiSessionsWithConfirm({
    ids: [id],
    sessions,
    archivedSessions,
    clearIfActive,
    setError: (message) => { error.value = message },
    disposed: () => disposed,
    reload: loadSessions,
  })
}

async function archiveSession(id: string): Promise<void> {
  if (isSessionLocked()) return
  sessionsVersion += 1
  await archiveAiSession({
    id,
    clearIfActive,
    setError: (message) => { error.value = message },
    disposed: () => disposed,
    reload: loadSessions,
  })
}

async function restoreSession(id: string): Promise<void> {
  if (isSessionLocked()) return
  sessionsVersion += 1
  await restoreAiSession({
    id,
    railTab,
    setError: (message) => { error.value = message },
    disposed: () => disposed,
    reload: loadSessions,
  })
}

async function batchSessions(payload: { action: 'archive' | 'unarchive' | 'delete'; ids: string[] }): Promise<void> {
  if (isSessionLocked() || !payload.ids.length) return
  sessionsVersion += 1
  await batchAiSessionAction({
    ...payload,
    sessions,
    archivedSessions,
    clearIfActive,
    setError: (message) => { error.value = message },
    disposed: () => disposed,
    reload: loadSessions,
  })
}

function configureProviders(): void {
  open.value = false
  void router.push({ path: '/ops', query: { tab: 'llm' } })
}

function onShortcut(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === '/') {
    event.preventDefault()
    void openAssistant()
  }
  // 设置等子弹窗自己会吃掉 Esc；这里再关一次会把助手一起收走
  if (event.key === 'Escape' && open.value && !document.querySelector('[data-state="open"][role="dialog"], [data-state="open"][role="alertdialog"]')) {
    open.value = false
  }
}

watch(open, (visible) => {
  if (visible && !disposed) void openAssistant()
  else if (!visible && !disposed) void discardEmptyDraftOnClose()
})

watch(settingsOpen, (visible, wasVisible) => {
  // 设置关闭后刷新 profile/memories，上下文用量条立刻对齐
  if (wasVisible && !visible && !disposed) void loadContextSources()
})

function onExternalOpen(): void {
  void openAssistant()
}

onMounted(() => {
  thinking.value = normalizeThinking(localStorage.getItem(THINKING_KEY))
  window.addEventListener('keydown', onShortcut)
  window.addEventListener('loci:assistant-open', onExternalOpen)
})
onUnmounted(() => {
  disposed = true
  selectionVersion += 1
  sessionsVersion += 1
  hostRun.disposeRun()
  window.removeEventListener('keydown', onShortcut)
  window.removeEventListener('loci:assistant-open', onExternalOpen)
})
</script>

<template>
  <AssistantFloatBall v-if="!compactMobile" :open="open" :busy="isBusy() || isWaitingUser()" :unavailable="!providerReady && !visitor" @toggle="open ? (open = false) : openAssistant()" />
  <AssistantPanel
    :open="open"
    :title="active?.title"
    :sessions="sessions"
    :archived-sessions="archivedSessions"
    :rail-tab="railTab"
    :active-id="active?.id"
    :messages="messages"
    :agents="agents"
    :plan-steps="planSteps"
    :loading="loading"
    :busy="isBusy()"
    :waiting-user="isWaitingUser()"
    :provider-ready="providerReady"
    :providers="providers"
    :provider="provider"
    :model="model"
    :thinking="thinking"
    :error="error"
    :profile="profile"
    :memories="memories"
    :tools-catalog="toolsCatalog"
    :observed-input-tokens="run?.input_tokens ?? null"
    @close="open = false"
    @create="createSession"
    @select="selectSession"
    @remove="removeSession"
    @archive="archiveSession"
    @restore="restoreSession"
    @batch="batchSessions"
    @update:rail-tab="railTab = $event"
    @settings="settingsOpen = true"
    @send="hostRun.send"
    @cancel="() => hostRun.cancel(isActiveRun, isWaitingUser)"
    @clear-error="error = ''"
    @runtime-select="(payload) => chooseProviderAndModel(payload.provider, payload.model)"
    @thinking="chooseThinking"
    @configure="configureProviders"
    @slash-command="onSlashCommand"
  />
  <AssistantSettingsDialog v-if="!visitor" v-model:open="settingsOpen" />
</template>
