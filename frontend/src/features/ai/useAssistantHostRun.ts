import type { Ref } from 'vue'

import {
  cancelAiRun,
  getAiRun,
  getAiRunEvents,
  sendAiMessage,
  streamAiRunEvents,
} from '@/shared/api/ai_assistant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  AiAgentProgress,
  AiMessage,
  AiRun,
  AiRunEvent,
  AiSessionDetail,
  AiSessionSummary,
} from '@/shared/types/ai_assistant'
import { applyAiRunEvent, beginAssistantTurn, lastAssistantMessage } from './assistantRunState'
import { applyPlanEvent, type TaskPlanStep } from './assistantTaskModel'
import type { ThinkingLevel } from './components/AssistantRuntimeBar.vue'

type FinishStatus = 'cancelled' | 'done' | 'error'
type SessionWithRun = AiSessionDetail & { active_run?: AiRun | null }

export interface UseAssistantHostRunOptions {
  disposed: () => boolean
  selectionVersion: () => number
  active: Ref<AiSessionDetail | null>
  messages: Ref<AiMessage[]>
  agents: Ref<AiAgentProgress[]>
  planSteps: Ref<TaskPlanStep[]>
  run: Ref<AiRun | null>
  error: Ref<string>
  dispatching: Ref<boolean>
  provider: Ref<string>
  model: Ref<string>
  thinking: Ref<ThinkingLevel>
  providerReady: Ref<boolean>
  sessions: Ref<AiSessionSummary[]>
  createSession: (options?: { fromSend?: boolean }) => Promise<AiSessionDetail | null>
  syncSessionMessages: (sessionId: string) => Promise<void>
  loadSessions: () => Promise<void>
}

function isTerminal(status: AiRun['status']): boolean {
  return status === 'done' || status === 'cancelled' || status === 'error' || status === 'idle' || status === 'archived' || status === 'waiting_user'
}

export function useAssistantHostRun(options: UseAssistantHostRunOptions) {
  let pollVersion = 0
  let streamAbort: AbortController | null = null

  function runIsCurrent(runId: string, version: number): boolean {
    return !options.disposed() && version === pollVersion && options.run.value?.id === runId
  }

  function abortActiveStream(): void {
    pollVersion += 1
    streamAbort?.abort()
    streamAbort = null
  }

  function disposeRun(): void {
    pollVersion += 1
    streamAbort?.abort()
    streamAbort = null
  }

  function applySessionTitle(title: string): void {
    const cleaned = title.trim()
    if (!cleaned || !options.active.value) return
    const id = options.active.value.id
    options.active.value = { ...options.active.value, title: cleaned }
    options.sessions.value = options.sessions.value.map((session) => (
      session.id === id ? { ...session, title: cleaned } : session
    ))
  }

  function pauseForUser(runId?: string, cursor?: string): void {
    if (!options.run.value || (runId && options.run.value.id !== runId)) return
    pollVersion += 1
    options.run.value = {
      ...options.run.value,
      status: 'waiting_user',
      ...(cursor ? { cursor } : {}),
    }
    streamAbort?.abort()
    streamAbort = null
    void options.loadSessions().catch(() => undefined)
  }

  function finishRun(status: FinishStatus, runId?: string): void {
    if (!options.run.value || (runId && options.run.value.id !== runId)) return
    const sessionId = options.run.value.session_id
    const finishedRunId = options.run.value.id
    // 抬版本：丢弃本轮晚到的 SSE；下一轮 consumeRun 再抬一次会使旧 sync 失效
    pollVersion += 1
    const syncGeneration = pollVersion
    options.run.value = { ...options.run.value, status }
    if (status === 'cancelled') options.error.value = ''
    options.planSteps.value = []
    const lastAssistant = lastAssistantMessage(options.messages.value)
    // SSE 已用带 payload 的 error/done/cancelled 收口时，禁止再用空 data 二次 apply（会冲掉失败文案或抛异常）
    const alreadySettled = lastAssistant
      && (
        (status === 'error' && lastAssistant.status === 'error')
        || (status === 'done' && lastAssistant.status === 'done')
        || (status === 'cancelled' && lastAssistant.status === 'cancelled')
      )
    // 消息那份已收口时，只剩子进程还挂在 running/queued 才需要再 apply 一次收尾
    const hasLiveAgents = options.agents.value.some(
      (agent) => agent.status === 'running' || agent.status === 'queued',
    )
    if (!alreadySettled || hasLiveAgents) {
      const eventType = status === 'error' ? 'error' : status === 'cancelled' ? 'cancelled' : 'done'
      const next = applyAiRunEvent(
        { messages: options.messages.value, agents: options.agents.value },
        { type: eventType, data: {} },
      )
      options.messages.value = next.messages
      options.agents.value = next.agents
    }
    streamAbort?.abort()
    streamAbort = null
    void options.loadSessions().catch(() => undefined)

    function syncStillForThisFinish(): boolean {
      if (options.disposed() || options.active.value?.id !== sessionId) return false
      if (syncGeneration !== pollVersion) return false
      const current = options.run.value
      if (current && current.id !== finishedRunId && (current.status === 'running' || current.status === 'waiting_user')) {
        return false
      }
      return true
    }

    if (options.active.value?.id === sessionId) {
      void (async () => {
        if (!syncStillForThisFinish()) return
        await options.syncSessionMessages(sessionId)
        if (!syncStillForThisFinish()) return
        // done 空正文时再补一次，覆盖「SSE 关流早于 done/落库」窗口
        const last = lastAssistantMessage(options.messages.value)
        if (status === 'done' && last && !String(last.content || '').trim()) {
          window.setTimeout(() => {
            if (!syncStillForThisFinish()) return
            void options.syncSessionMessages(sessionId)
          }, 400)
        }
      })()
    }
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
    if (!options.run.value || options.run.value.id !== runId) return
    const localStatus = options.run.value.status
    if (isTerminal(localStatus) && !isTerminal(latest.status)) return
    options.run.value = latest
    if (isTerminal(latest.status)) settleRunStatus(latest.status, runId)
  }

  function applyEvent(event: AiRunEvent, runId?: string, cursor?: string): void {
    if (event.type === 'session_title') {
      applySessionTitle(String((event.data as { title?: string } | undefined)?.title || ''))
      return
    }
    options.planSteps.value = applyPlanEvent(options.planSteps.value, event)
    const next = applyAiRunEvent({ messages: options.messages.value, agents: options.agents.value }, event)
    if (next.messages !== options.messages.value) options.messages.value = next.messages
    if (next.agents !== options.agents.value) options.agents.value = next.agents
    if (event.type === 'waiting_user') {
      pauseForUser(runId, cursor)
      return
    }
    if (event.type === 'done' || event.type === 'error' || event.type === 'cancelled') {
      finishRun(event.type === 'error' ? 'error' : event.type === 'cancelled' ? 'cancelled' : 'done', runId)
    }
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
      applyEvent(event, nextRun.id, id || undefined)
    }

    function shouldContinue(): boolean {
      return runIsCurrent(nextRun.id, version) && !isTerminal(options.run.value?.status ?? 'error')
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
        if (!runIsCurrent(nextRun.id, version) || latest.id !== options.run.value?.id) return
        adoptRunSnapshot(latest, nextRun.id)
        // SSE 正常收到终态事件时 shouldContinue 已 false；若仅断流而 run 仍在跑，必须回落轮询
        if (!shouldContinue()) return
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
        if (!runIsCurrent(nextRun.id, version) || latest.id !== options.run.value?.id) return
        adoptRunSnapshot(latest, nextRun.id)
        if (!shouldContinue()) return
        await new Promise<void>((resolve) => window.setTimeout(resolve, 750))
        failures = 0
      } catch {
        if (!shouldContinue()) return
        try {
          const latest = await getAiRun(nextRun.id)
          if (!runIsCurrent(nextRun.id, version) || latest.id !== options.run.value?.id) return
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

  function restoreActiveRun(detail: SessionWithRun, isActiveRun: () => boolean): void {
    const activeRun = detail.active_run ?? null
    const waiting = detail.status === 'waiting_user' || activeRun?.status === 'waiting_user'
    if (waiting) {
      if (!activeRun?.id) {
        options.run.value = null
        options.error.value = '会话在等待回复，但缺少有效运行；请新建对话或联系运维。'
        return
      }
      const pendingAsk = activeRun.pending_ask
      options.run.value = { ...activeRun, status: 'waiting_user' }
      // 刷新后用 pending_ask / 消息 hitl 还原选项，避免 ConfirmCard 只剩 fallback
      if (pendingAsk && (pendingAsk.prompt || pendingAsk.options?.length || pendingAsk.questions?.length)) {
        const hitl = {
          prompt: pendingAsk.prompt || '',
          options: pendingAsk.options?.length ? [...pendingAsk.options] : undefined,
          ...(pendingAsk.questions?.length ? { questions: pendingAsk.questions.map((q) => ({ ...q })) } : {}),
          ...(pendingAsk.risk ? { risk: pendingAsk.risk } : {}),
        }
        const messages = [...options.messages.value]
        for (let index = messages.length - 1; index >= 0; index -= 1) {
          const row = messages[index]
          if (row?.role !== 'assistant') continue
          const hasHitl = Boolean(
            row.hitl?.prompt || row.hitl?.options?.length || row.hitl?.questions?.length,
          )
          messages[index] = {
            ...row,
            hitl: hasHitl ? row.hitl : hitl,
            status: row.status === 'streaming' ? 'done' : row.status,
          }
          options.messages.value = messages
          break
        }
      }
      return
    }
    if (activeRun?.status === 'running') {
      if (options.run.value?.id === activeRun.id && isActiveRun()) return
      options.run.value = activeRun
      const hasStreamingAssistant = options.messages.value.some((message) => message.role === 'assistant' && message.status === 'streaming')
      if (!hasStreamingAssistant) {
        options.messages.value = [
          ...options.messages.value,
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
    options.run.value = null
  }

  async function send(payload: string | { text: string; images?: string[]; skillSlug?: string }): Promise<void> {
    const text = typeof payload === 'string' ? payload.trim() : (payload.text || '').trim()
    const images = typeof payload === 'string' ? [] : [...(payload.images ?? [])]
    const skillSlug = typeof payload === 'string' ? '' : String(payload.skillSlug || '').trim()
    if ((!text && !images.length) || options.dispatching.value || !options.providerReady.value || options.disposed()) return
    if (options.run.value?.status === 'running') {
      options.error.value = '上一轮仍在运行，请先点中止再发送'
      return
    }
    const priorRun = options.run.value
    const resumeSame = priorRun?.status === 'waiting_user'
    const resumeCursor = priorRun?.cursor
    options.dispatching.value = true
    try {
      const session = options.active.value ?? await options.createSession({ fromSend: true })
      if (!session || options.disposed()) return
      const intent = options.selectionVersion()
      options.error.value = ''
      const intentTitle = (session.title || '').trim()
      if (!intentTitle || intentTitle === '新对话') {
        const seed = (text || (skillSlug ? `/${skillSlug}` : '') || '附图提问').replace(/\s+/g, ' ')
        const preview = seed.slice(0, 28)
        applySessionTitle(preview.length < seed.length ? `${preview}…` : preview)
      }
      const started = beginAssistantTurn(options.messages.value, text || '（附图）', images)
      options.messages.value = started.messages
      options.agents.value = started.agents
      options.planSteps.value = []
      const response = await sendAiMessage(session.id, text, {
        provider: options.provider.value,
        model: options.model.value,
        thinking: options.thinking.value,
        ...(images.length ? { images } : {}),
        ...(skillSlug ? { skill_slug: skillSlug } : {}),
      })
      if (options.disposed() || intent !== options.selectionVersion() || options.active.value?.id !== session.id) return
      // 同 run_id HITL 续跑：从暂停 cursor 续消费，勿当全新一轮重放整段事件
      if (resumeSame && priorRun && response.run_id === priorRun.id) {
        const nextRun: AiRun = {
          ...priorRun,
          id: response.run_id,
          session_id: session.id,
          status: 'running',
          cursor: resumeCursor,
          provider: options.provider.value,
          model: options.model.value,
        }
        options.run.value = nextRun
        void consumeRun(nextRun)
        return
      }
      const nextRun: AiRun = { id: response.run_id, session_id: session.id, status: 'running', provider: options.provider.value, model: options.model.value }
      options.run.value = nextRun
      void consumeRun(nextRun)
    } catch (caught) {
      if (options.disposed()) return
      // 中止/切会话导致的中断不当成「发送失败」挂死错误条
      if (isAbortLike(caught)) {
        const next = applyAiRunEvent(
          { messages: options.messages.value, agents: options.agents.value },
          { type: 'cancelled', data: {} },
        )
        options.messages.value = next.messages
        options.agents.value = next.agents
        options.error.value = ''
        return
      }
      options.error.value = toErrorMessage(caught, '发送消息失败')
      const next = applyAiRunEvent(
        { messages: options.messages.value, agents: options.agents.value },
        { type: 'error', data: { message: '发送失败' } },
      )
      options.messages.value = next.messages
      options.agents.value = next.agents
    } finally {
      if (!options.disposed()) options.dispatching.value = false
    }
  }

  async function cancel(isActiveRun: () => boolean, isWaitingUser: () => boolean): Promise<void> {
    const currentRun = options.run.value
    if (!currentRun || (!isActiveRun() && !isWaitingUser())) return
    if (!currentRun.id || currentRun.id.startsWith('waiting-') || currentRun.id.startsWith('local-')) {
      finishRun('cancelled', currentRun.id)
      options.error.value = ''
      return
    }
    try {
      const cancelled = await cancelAiRun(currentRun.id)
      if (!options.run.value || options.run.value.id !== currentRun.id) return
      if (options.run.value.status === 'done' || options.run.value.status === 'error' || options.run.value.status === 'cancelled') {
        options.error.value = ''
        return
      }
      const status: FinishStatus = cancelled.status === 'error'
        ? 'error'
        : cancelled.status === 'done'
          ? 'done'
          : 'cancelled'
      finishRun(status, currentRun.id)
    } catch {
      if (!options.run.value || options.run.value.id !== currentRun.id) return
      if (options.run.value.status === 'done' || options.run.value.status === 'error' || options.run.value.status === 'cancelled') {
        options.error.value = ''
        return
      }
      // API 取消失败也在本机收口，避免一直 busy 挡后续记账；不把失败条挂死
      finishRun('cancelled', currentRun.id)
    }
  }

  return {
    abortActiveStream,
    disposeRun,
    restoreActiveRun,
    send,
    cancel,
    consumeRun,
  }
}

function isAbortLike(caught: unknown): boolean {
  if (!caught || typeof caught !== 'object') return false
  const name = String((caught as { name?: string }).name || '')
  const message = String((caught as { message?: string }).message || '')
  return name === 'AbortError' || /aborted|abort/i.test(message)
}
