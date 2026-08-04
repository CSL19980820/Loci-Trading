<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  cancelAiRun,
  createAiSession,
  deleteAiSession,
  getAiRun,
  getAiRunEvents,
  getAiSession,
  getAiTools,
  listAiSessions,
  sendAiMessage,
  streamAiRunEvents,
} from '@/shared/api/ai_assistant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AiAgentProgress, AiMessage, AiProviderProfile, AiRun, AiRunEvent, AiSessionDetail, AiSessionSummary } from '@/shared/types/ai_assistant'
import { applyAiRunEvent, beginAssistantTurn } from './assistantRunState'
import { mergeSessionMessages } from './assistantSessionMerge'
import AssistantFloatBall from './components/AssistantFloatBall.vue'
import AssistantPanel from './components/AssistantPanel.vue'

type SessionWithRun = AiSessionDetail & { active_run?: AiRun | null }
type FinishStatus = 'cancelled' | 'done' | 'error'

const open = ref(false)
const router = useRouter()
const loading = ref(false)
const error = ref('')
const sessions = ref<AiSessionSummary[]>([])
const active = ref<AiSessionDetail | null>(null)
const messages = ref<AiMessage[]>([])
const agents = ref<AiAgentProgress[]>([])
const run = ref<AiRun | null>(null)
const providerReady = ref(false)
const providers = ref<AiProviderProfile[]>([])
const provider = ref('')
const model = ref('')
const dispatching = ref(false)
let selectionVersion = 0
let selectingSessionId: string | null = null
let sessionsVersion = 0
let pollVersion = 0
let streamAbort: AbortController | null = null
let disposed = false

function isActiveRun(): boolean { return run.value?.status === 'running' }
function isWaitingUser(): boolean { return run.value?.status === 'waiting_user' }
function isBusy(): boolean { return dispatching.value || isActiveRun() }
function isSessionLocked(): boolean { return isBusy() || isWaitingUser() }
function isTerminal(status: AiRun['status']): boolean {
  return status === 'done' || status === 'cancelled' || status === 'error' || status === 'idle' || status === 'archived' || status === 'waiting_user'
}

const selectedProvider = computed(() => providers.value.find((item) => item.name === provider.value))
const models = computed(() => selectedProvider.value?.models ?? [])

function selectionIsCurrent(version: number): boolean {
  return !disposed && version === selectionVersion
}

function runIsCurrent(runId: string, version: number): boolean {
  return !disposed && version === pollVersion && run.value?.id === runId
}

function abortActiveStream(): void {
  pollVersion += 1
  streamAbort?.abort()
  streamAbort = null
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
  const catalog = await getAiTools()
  if (disposed) return
  providers.value = catalog.providers ?? []
  providerReady.value = catalog.provider_configured !== false
  if (!providers.value.some((item) => item.name === provider.value)) {
    chooseProvider(providers.value.find((item) => item.is_default)?.name ?? providers.value[0]?.name ?? '')
  } else if (!models.value.includes(model.value)) {
    model.value = selectedProvider.value?.default_model ?? models.value[0] ?? ''
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

async function loadSessions(): Promise<void> {
  const version = ++sessionsVersion
  const rows = await listAiSessions()
  if (!disposed && version === sessionsVersion) sessions.value = rows
}

function restoreActiveRun(detail: SessionWithRun): void {
  const activeRun = detail.active_run ?? null
  const waiting = detail.status === 'waiting_user' || activeRun?.status === 'waiting_user'
  if (waiting) {
    if (!activeRun?.id) {
      run.value = null
      error.value = '会话在等待回复，但缺少有效运行；请新建对话或联系运维。'
      return
    }
    run.value = { ...activeRun, status: 'waiting_user' }
    return
  }
  if (activeRun?.status === 'running') {
    if (run.value?.id === activeRun.id && isActiveRun()) return
    run.value = activeRun
    const hasStreamingAssistant = messages.value.some((message) => message.role === 'assistant' && message.status === 'streaming')
    if (!hasStreamingAssistant) {
      messages.value = [
        ...messages.value,
        {
          id: `local-assistant-resume-${activeRun.id}`,
          role: 'assistant',
          content: '',
          status: 'streaming',
          tool_receipts: [],
        },
      ]
    }
    // Replay from the start so tool/artifact events rebuild UI; do not skip via latest cursor.
    void consumeRun({ ...activeRun, cursor: undefined })
    return
  }
  run.value = null
}

async function openAssistant(): Promise<void> {
  if (disposed) return
  open.value = true
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadCatalog(), loadSessions()])
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
    abortActiveStream()
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
    if (detail.provider) chooseProvider(detail.provider)
    if (detail.model) chooseModel(detail.model)
    restoreActiveRun(detail)
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
  if (isActiveRun() || isWaitingUser() || (dispatching.value && !options.fromSend)) return null
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
    abortActiveStream()
    run.value = null
    active.value = detail
    messages.value = detail.messages ?? []
    agents.value = []
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

async function removeSession(id: string): Promise<void> {
  if (isSessionLocked()) return
  if (selectingSessionId === id || (!selectingSessionId && active.value?.id === id)) {
    selectionVersion += 1
    selectingSessionId = null
    loading.value = false
    abortActiveStream()
    run.value = null
  }
  sessionsVersion += 1
  try {
    await deleteAiSession(id)
    if (disposed) return
    sessions.value = sessions.value.filter((session) => session.id !== id)
    if (active.value?.id === id) {
      active.value = null
      messages.value = []
      agents.value = []
    }
  } catch (caught) {
    error.value = toErrorMessage(caught, '删除会话失败')
  }
}

function applyEvent(event: AiRunEvent, runId?: string): void {
  const next = applyAiRunEvent({ messages: messages.value, agents: agents.value }, event)
  messages.value = next.messages
  agents.value = next.agents
  if (event.type === 'waiting_user') {
    pauseForUser(runId)
    return
  }
  if (event.type === 'done' || event.type === 'error' || event.type === 'cancelled') {
    finishRun(event.type === 'error' ? 'error' : event.type === 'cancelled' ? 'cancelled' : 'done', runId)
  }
}

function pauseForUser(runId?: string): void {
  if (!run.value || (runId && run.value.id !== runId)) return
  run.value = { ...run.value, status: 'waiting_user' }
  streamAbort?.abort()
  streamAbort = null
  void loadSessions().catch(() => undefined)
}

function finishRun(status: FinishStatus, runId?: string): void {
  if (!run.value || (runId && run.value.id !== runId)) return
  const sessionId = run.value.session_id
  run.value = { ...run.value, status }
  const index = [...messages.value].map((message) => message.role).lastIndexOf('assistant')
  if (index >= 0) {
    const message = messages.value[index]
    const messageStatus = status === 'error' ? 'error' : status === 'cancelled' ? 'cancelled' : 'done'
    const fallback = status === 'error' ? '助手运行失败' : status === 'cancelled' ? '已中止' : ''
    messages.value = messages.value.map((item, current) => current === index
      ? { ...message, status: messageStatus, content: message.content || fallback }
      : item)
  }
  streamAbort?.abort()
  streamAbort = null
  void loadSessions().catch(() => undefined)
  if (active.value?.id === sessionId) void syncSessionMessages(sessionId)
}

function settleRunStatus(status: AiRun['status'], runId: string): void {
  if (status === 'waiting_user') {
    pauseForUser(runId)
    return
  }
  if (status === 'done' || status === 'cancelled' || status === 'error') {
    finishRun(status, runId)
    return
  }
  if (isTerminal(status)) finishRun('done', runId)
}

function adoptRunSnapshot(latest: AiRun, runId: string): void {
  if (!run.value || run.value.id !== runId) return
  const localStatus = run.value.status
  if (isTerminal(localStatus) && !isTerminal(latest.status)) return
  run.value = latest
  if (isTerminal(latest.status)) settleRunStatus(latest.status, runId)
}

async function consumeRun(nextRun: AiRun): Promise<void> {
  const version = ++pollVersion
  let after = nextRun.cursor
  const seenEventIds = new Set<string>()
  streamAbort = new AbortController()

  function applyNext(event: AiRunEvent): void {
    const id = event.id == null ? '' : String(event.id)
    if (id) {
      after = id
      if (seenEventIds.has(id)) return
      seenEventIds.add(id)
      if (seenEventIds.size > 500) {
        const oldest = seenEventIds.values().next().value
        if (oldest) seenEventIds.delete(oldest)
      }
    }
    applyEvent(event, nextRun.id)
  }

  function shouldContinue(): boolean {
    return runIsCurrent(nextRun.id, version) && !isTerminal(run.value?.status ?? 'error')
  }

  try {
    const streamed = await streamAiRunEvents(nextRun.id, after, (event) => {
      if (!runIsCurrent(nextRun.id, version)) return
      applyNext(event)
    }, streamAbort.signal)
    if (!shouldContinue()) return
    if (streamed) {
      const latest = await getAiRun(nextRun.id)
      if (!shouldContinue()) return
      if (!runIsCurrent(nextRun.id, version) || latest.id !== run.value?.id) return
      adoptRunSnapshot(latest, nextRun.id)
      return
    }
  } catch {
    if (!shouldContinue()) return
  }

  let failures = 0
  while (shouldContinue()) {
    try {
      const page = await getAiRunEvents(nextRun.id, after)
      for (const event of page.events) {
        if (!shouldContinue()) return
        applyNext(event)
      }
      after = page.after ?? after
      if (!shouldContinue()) return
      const latest = await getAiRun(nextRun.id)
      if (!runIsCurrent(nextRun.id, version) || latest.id !== run.value?.id) return
      adoptRunSnapshot(latest, nextRun.id)
      if (!shouldContinue()) return
      await new Promise<void>((resolve) => window.setTimeout(resolve, 750))
      failures = 0
    } catch {
      if (!shouldContinue()) return
      try {
        const latest = await getAiRun(nextRun.id)
        if (!runIsCurrent(nextRun.id, version) || latest.id !== run.value?.id) return
        adoptRunSnapshot(latest, nextRun.id)
        if (!shouldContinue()) return
      } catch {
        if (!shouldContinue()) return
      }
      const retryAfter = Math.min(750 * 2 ** failures, 6_000)
      failures += 1
      await new Promise<void>((resolve) => window.setTimeout(resolve, retryAfter))
    }
  }
}

async function send(content: string): Promise<void> {
  const prompt = content.trim()
  if (!prompt || isBusy() || !providerReady.value || disposed) return
  dispatching.value = true
  try {
    const session = active.value ?? await createSession({ fromSend: true })
    if (!session || disposed) return
    const intent = selectionVersion
    error.value = ''
    const started = beginAssistantTurn(messages.value, prompt)
    messages.value = started.messages
    agents.value = started.agents
    const response = await sendAiMessage(session.id, prompt, { provider: provider.value, model: model.value })
    if (disposed || intent !== selectionVersion || active.value?.id !== session.id) return
    const nextRun: AiRun = { id: response.run_id, session_id: session.id, status: 'running', provider: provider.value, model: model.value }
    run.value = nextRun
    void consumeRun(nextRun)
  } catch (caught) {
    if (disposed) return
    error.value = toErrorMessage(caught, '发送消息失败')
    const index = [...messages.value].map((message) => message.role).lastIndexOf('assistant')
    if (index >= 0) {
      const assistant = messages.value[index]
      messages.value = messages.value.map((item, current) => current === index
        ? { ...assistant, status: 'error', content: assistant.content || '发送失败' }
        : item)
    }
  } finally {
    if (!disposed) dispatching.value = false
  }
}

async function cancel(): Promise<void> {
  const currentRun = run.value
  if (!currentRun || (!isActiveRun() && !isWaitingUser())) return
  if (!currentRun.id || currentRun.id.startsWith('waiting-') || currentRun.id.startsWith('local-')) {
    error.value = '无法取消：缺少有效运行'
    return
  }
  try {
    const cancelled = await cancelAiRun(currentRun.id)
    if (!run.value || run.value.id !== currentRun.id) return
    if (run.value.status === 'done' || run.value.status === 'error' || run.value.status === 'cancelled') return
    const status: FinishStatus = cancelled.status === 'error'
      ? 'error'
      : cancelled.status === 'done'
        ? 'done'
        : 'cancelled'
    finishRun(status, currentRun.id)
  } catch (caught) {
    if (run.value && (run.value.status === 'done' || run.value.status === 'error' || run.value.status === 'cancelled')) return
    error.value = toErrorMessage(caught, '中止运行失败')
  }
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
  if (event.key === 'Escape' && open.value) open.value = false
}

watch(open, (visible) => { if (visible && !disposed) void openAssistant() })
onMounted(() => window.addEventListener('keydown', onShortcut))
onUnmounted(() => {
  disposed = true
  selectionVersion += 1
  sessionsVersion += 1
  pollVersion += 1
  streamAbort?.abort()
  window.removeEventListener('keydown', onShortcut)
})
</script>

<template>
  <AssistantFloatBall :open="open" :busy="isBusy() || isWaitingUser()" :unavailable="!providerReady" @toggle="open ? (open = false) : openAssistant()" />
  <AssistantPanel
    :open="open"
    :title="active?.title"
    :sessions="sessions"
    :active-id="active?.id"
    :messages="messages"
    :agents="agents"
    :loading="loading"
    :busy="isBusy()"
    :waiting-user="isWaitingUser()"
    :provider-ready="providerReady"
    :providers="providers"
    :provider="provider"
    :model="model"
    :models="models"
    :error="error"
    @close="open = false"
    @create="createSession"
    @select="selectSession"
    @remove="removeSession"
    @send="send"
    @cancel="cancel"
    @provider="chooseProvider"
    @model="chooseModel"
    @configure="configureProviders"
  />
</template>
