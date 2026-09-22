import { normalizeArtifacts } from './assistantArtifactState'
import { normalizeArtifactKind } from './assistantArtifacts'
import type {
  AiAgentProgress,
  AiArtifactStatus,
  AiChartArtifact,
  AiHitlAsk,
  AiMessage,
  AiRunEvent,
  AiToolReceipt,
} from '@/shared/types/ai_assistant'

export interface AssistantRunState {
  messages: AiMessage[]
  agents: AiAgentProgress[]
}

const META_KEYS = new Set(['id', 'kind', 'title', 'status', 'data', 'call_id', 'name'])

export function beginAssistantTurn(
  messages: AiMessage[],
  userContent: string,
  images: string[] = [],
): AssistantRunState {
  const stamp = String(Date.now())
  const user: AiMessage = {
    id: `local-user-${stamp}`,
    role: 'user',
    content: userContent,
    status: 'done',
  }
  if (images.length) user.images = images
  return {
    agents: [],
    messages: [
      ...messages,
      user,
      { id: `local-assistant-${stamp}`, role: 'assistant', content: '', status: 'streaming', tool_receipts: [], artifacts: [] },
    ],
  }
}

export function applyAiRunEvent(state: AssistantRunState, event: AiRunEvent): AssistantRunState {
  const agents = reduceAgents(state.agents, event)
  if (event.type.startsWith('subagent_')) {
    return agents === state.agents ? state : { messages: state.messages, agents }
  }

  const index = findLastAssistantIndex(state.messages)
  if (index < 0) return agents === state.agents ? state : { messages: state.messages, agents }

  const prior = state.messages[index]!
  const data = event.data

  if (event.type === 'token') {
    const assistant: AiMessage = {
      ...prior,
      content: `${prior.content ?? ''}${String(data.delta ?? '')}`,
    }
    return { messages: replaceMessageAt(state.messages, index, assistant), agents }
  }

  if (event.type === 'think') {
    const assistant: AiMessage = {
      ...prior,
      thinking: `${prior.thinking ?? ''}${String(data.delta ?? '')}`,
    }
    return { messages: replaceMessageAt(state.messages, index, assistant), agents }
  }

  const assistant = cloneAssistantForMutation(prior, event.type)
  let touched = false

  if (event.type === 'warning') {
    assistant.warnings = [...(assistant.warnings ?? []), String(data.message ?? '证据不足')]
    touched = true
  } else if (event.type === 'context_compacted') {
    const notice = String(data.message ?? '').trim() || '已压缩较早对话（库内原文仍在）'
    assistant.warnings = [...(assistant.warnings ?? []), notice]
    const after = numberValue(data.tokens_after)
    if (after != null && after > 0) assistant.context_feed_tokens = after
    touched = true
  } else if (event.type === 'error') {
    const priorStatus = prior.status
    const priorContent = (prior.content ?? '').trim()
    const reason = stringValue(data.stopped_reason) ?? ''
    const hasPayload = data.message != null || data.stopped_reason != null
    const msg = String(data.message ?? '').trim()
    assistant.status = 'error'
    // OpenClaw/Hermes：失败不得保留工具前计划旁白；finishRun 空二次 error 不得冲掉已写好的失败文案
    if (!hasPayload) {
      if (priorStatus === 'error' && priorContent) {
        assistant.content = priorContent
      } else if ((prior.tool_receipts?.length ?? 0) > 0) {
        assistant.content = '助手运行失败'
      } else {
        assistant.content = priorContent || '助手运行失败'
      }
    } else if (reason === 'empty_completion' || reason.startsWith('llm_error')) {
      assistant.content = msg || '助手运行失败'
    } else {
      assistant.content = msg || priorContent || '助手运行失败'
    }
    const settled = settleLiveAgents(
      agents.length ? agents : (assistant.agents ?? []),
      'error',
    )
    settleLiveTools(assistant, 'error')
    assistant.artifacts = normalizeArtifacts(assistant.artifacts ?? [])
    assistant.agents = settled.length ? settled : assistant.agents
    touched = true
    return { messages: replaceMessageAt(state.messages, index, assistant), agents: settled.length ? settled : agents }
  } else if (event.type === 'done') {
    assistant.status = 'done'
    const finalText = stringValue(data.text) || stringValue(data.content) || stringValue(data.message)
    // Hermes：非空终稿始终覆盖工具前旁白；空 done 不擦已流式正文
    if (finalText) assistant.content = finalText
    const settled = settleLiveAgents(
      agents.length ? agents : (assistant.agents ?? []),
      'done',
    )
    settleLiveTools(assistant, 'done')
    assistant.artifacts = normalizeArtifacts(assistant.artifacts ?? [])
    assistant.agents = settled.length ? settled : assistant.agents
    touched = true
    return { messages: replaceMessageAt(state.messages, index, assistant), agents: settled.length ? settled : agents }
  } else if (event.type === 'cancelled') {
    assistant.status = 'cancelled'
    const priorContent = (prior.content ?? '').trim()
    const cancelMark = '（已中止）'
    // 工具已跑、正文仍像中途计划时，不要把旁白留成「终稿」；避免二次 settle 叠后缀
    if ((prior.tool_receipts?.length ?? 0) > 0) {
      if (!priorContent) assistant.content = '已中止'
      else if (priorContent.includes(cancelMark) || prior.status === 'cancelled') {
        assistant.content = priorContent
      } else {
        assistant.content = `${priorContent}\n\n${cancelMark}`
      }
    } else {
      assistant.content ||= '已中止'
    }
    const settled = settleLiveAgents(
      agents.length ? agents : (assistant.agents ?? []),
      'cancelled',
    )
    settleLiveTools(assistant, 'cancelled')
    assistant.artifacts = normalizeArtifacts(assistant.artifacts ?? [])
    assistant.agents = settled.length ? settled : assistant.agents
    touched = true
    return { messages: replaceMessageAt(state.messages, index, assistant), agents: settled.length ? settled : agents }
  } else if (event.type === 'waiting_user') {
    const ask = data.ask && typeof data.ask === 'object' ? data.ask as Record<string, unknown> : data
    const prompt = stringValue(ask.prompt) || stringValue(data.prompt) || stringValue(data.message)
    const rawQuestions = Array.isArray(ask.questions) ? ask.questions : undefined
    const questions = rawQuestions
      ?.map((item) => {
        if (!item || typeof item !== 'object') return null
        const row = item as Record<string, unknown>
        const id = stringValue(row.id)
        const qPrompt = stringValue(row.prompt)
        if (!id || !qPrompt) return null
        return {
          id,
          prompt: qPrompt,
          options: Array.isArray(row.options) ? row.options.map(String) : undefined,
          ...(row.allow_free_text === true ? { allow_free_text: true as const } : {}),
        }
      })
      .filter((item): item is NonNullable<typeof item> => item != null)
    const hitl: AiHitlAsk = {
      prompt,
      options: Array.isArray(ask.options) ? ask.options.map(String) : undefined,
      risk: stringValue(ask.risk ?? data.risk),
      ...(questions?.length ? { questions } : {}),
    }
    assistant.hitl = hitl
    assistant.artifacts = normalizeArtifacts(assistant.artifacts ?? [])
    if (prompt && !assistant.content.trim()) assistant.content = prompt
    assistant.status = 'done'
    const settled = settleLiveAgents(agents, 'done')
    if (settled.length) assistant.agents = settled
    touched = true
    return { messages: replaceMessageAt(state.messages, index, assistant), agents: settled }
  } else if (event.type === 'tool_start') {
    upsertTool(assistant, {
      call_id: String(data.call_id ?? data.name ?? Date.now()), name: String(data.name ?? '工具'), status: 'running',
      arguments: objectValue(data.arguments),
    })
    touched = true
  } else if (event.type === 'tool_end') {
    upsertTool(assistant, {
      call_id: String(data.call_id ?? data.name ?? Date.now()), name: String(data.name ?? '工具'),
      status: data.ok === false ? 'error' : 'done', preview: stringValue(data.preview), elapsed_ms: numberValue(data.elapsed_ms),
    })
    touched = true
  } else if (event.type === 'artifact' || event.type === 'qianlong_kline' || event.type === 'candidate_verdict') {
    addArtifact(assistant, event.type === 'artifact' ? data : { ...data, kind: event.type }, event.id)
    touched = true
  }

  if (!touched) {
    return agents === state.agents ? state : { messages: state.messages, agents }
  }
  return { messages: replaceMessageAt(state.messages, index, assistant), agents }
}

function findLastAssistantIndex(messages: AiMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === 'assistant') return i
  }
  return -1
}

/**
 * 末条助手消息。倒序循环，不要写成 `[...messages].reverse().find(...)`——
 * 那会在流式期间对每个 token 复制一遍整张消息表。
 */
export function lastAssistantMessage(messages: AiMessage[]): AiMessage | undefined {
  const index = findLastAssistantIndex(messages)
  return index >= 0 ? messages[index] : undefined
}

function replaceMessageAt(messages: AiMessage[], index: number, message: AiMessage): AiMessage[] {
  const next = messages.slice()
  next[index] = message
  return next
}

/** Clone only the active assistant; copy nested arrays when the event may mutate them. */
function cloneAssistantForMutation(message: AiMessage, eventType: string): AiMessage {
  const next: AiMessage = { ...message }
  if (
    eventType === 'tool_start'
    || eventType === 'tool_end'
    || eventType === 'cancelled'
    || eventType === 'error'
    || eventType === 'done'
  ) {
    next.tool_receipts = [...(message.tool_receipts ?? [])]
  }
  if (
    eventType === 'artifact'
    || eventType === 'qianlong_kline'
    || eventType === 'candidate_verdict'
  ) {
    next.artifacts = [...(message.artifacts ?? [])]
  }
  return next
}

/** 终态时把仍在跑的子进程收口，避免侧栏卡在「运行中」。 */
function settleLiveAgents(
  agents: AiAgentProgress[],
  status: 'cancelled' | 'error' | 'done',
): AiAgentProgress[] {
  let changed = false
  const next = agents.map((agent) => {
    if (agent.status !== 'running' && agent.status !== 'queued') return agent
    changed = true
    const detail = status === 'cancelled'
      ? (agent.detail ? `${agent.detail} · 已中止` : '已中止')
      : agent.detail
    return { ...agent, status, ...(detail ? { detail } : {}) }
  })
  return changed ? next : agents
}

function settleLiveTools(message: AiMessage, mode: 'cancelled' | 'error' | 'done'): void {
  const tools = message.tool_receipts
  if (!tools?.length) return
  let changed = false
  const next = tools.map((tool) => {
    if (tool.status !== 'running') return tool
    changed = true
    if (mode === 'cancelled') {
      return { ...tool, status: 'done' as const, preview: tool.preview || tool.summary || '已中止' }
    }
    if (mode === 'done') {
      return { ...tool, status: 'done' as const, preview: tool.preview || tool.summary || '已完成' }
    }
    return { ...tool, status: 'error' as const, preview: tool.preview || tool.summary || '已中断' }
  })
  if (changed) message.tool_receipts = next
}

function upsertTool(message: AiMessage, next: AiToolReceipt): void {
  const tools = message.tool_receipts ?? []
  const index = tools.findIndex((tool) => tool.call_id === next.call_id)
  if (index < 0) tools.push(next)
  else tools[index] = { ...tools[index], ...next }
  message.tool_receipts = tools
}

function addArtifact(message: AiMessage, data: Record<string, unknown>, eventId: AiRunEvent['id']): void {
  const kind = normalizeArtifactKind(data.kind)
  const nested = objectValue(data.data)
  const payload = Object.keys(nested).length ? nested : omitMeta(data)
  const status = normalizeStatus(data.status) ?? (Object.keys(payload).length ? 'ready' : 'loading')
  const artifact: AiChartArtifact = {
    id: String(data.id ?? eventId ?? `${kind}-${Date.now()}`),
    kind,
    title: stringValue(data.title),
    status,
    data: payload,
  }
  message.artifacts = normalizeArtifacts([...(message.artifacts ?? []), artifact], true)
}

function omitMeta(data: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(data)) {
    if (!META_KEYS.has(key)) out[key] = value
  }
  return out
}

function normalizeStatus(value: unknown): AiArtifactStatus | undefined {
  return value === 'loading' || value === 'ready' || value === 'error' ? value : undefined
}

function reduceAgents(agents: AiAgentProgress[], event: AiRunEvent): AiAgentProgress[] {
  if (!event.type.startsWith('subagent_')) return agents
  const data = event.data
  const id = String(data.id ?? data.agent_id ?? '')
  if (!id) return agents
  const index = agents.findIndex((agent) => agent.id === id)
  const previous = index < 0 ? undefined : agents[index]

  if (event.type === 'subagent_tool') {
    const callId = String(data.call_id ?? data.tool_receipt_id ?? data.tool_name ?? 'tool')
    const toolName = String(data.tool_name ?? data.name ?? '工具')
    const rawStatus = String(data.status ?? 'running')
    const status = rawStatus === 'done' || rawStatus === 'error' ? rawStatus : 'running'
    const receipts = [...(previous?.tool_receipts ?? [])]
    const found = receipts.findIndex((row) => row.call_id === callId)
    const nextReceipt: AiToolReceipt = {
      call_id: callId,
      name: toolName,
      status,
      preview: stringValue(data.preview),
      elapsed_ms: numberValue(data.elapsed_ms),
      arguments: objectValue(data.arguments),
    }
    if (found >= 0) receipts[found] = { ...receipts[found], ...nextReceipt }
    else receipts.push(nextReceipt)
    const next: AiAgentProgress = {
      id,
      name: stringValue(data.name) || previous?.name || id,
      status: previous?.status === 'done' || previous?.status === 'error' ? previous.status : 'running',
      progress: previous?.progress,
      detail: previous?.detail,
      timeline: previous?.timeline,
      tool_receipts: receipts.slice(-24),
    }
    return index < 0 ? [...agents, next] : agents.map((agent, i) => (i === index ? next : agent))
  }

  const status = event.type === 'subagent_end' ? (data.ok === false ? 'error' : 'done') : 'running'
  const detail = stringValue(data.detail ?? data.text ?? data.preview)
  const timeline = detail
    ? [...(previous?.timeline ?? []), detail]
      .filter((item, position, items) => !position || item !== items[position - 1])
      .slice(-12)
    : previous?.timeline
  const next: AiAgentProgress = {
    id,
    name: stringValue(data.name ?? data.kind) || previous?.name || id,
    status,
    progress: progressValue(data.progress) ?? previous?.progress,
    detail: detail || previous?.detail,
    timeline,
    tool_receipts: previous?.tool_receipts,
  }
  return index < 0 ? [...agents, next] : agents.map((agent, i) => i === index ? next : agent)
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function progressValue(value: unknown): number | undefined {
  const progress = numberValue(value)
  return progress == null ? undefined : Math.min(100, Math.max(0, progress))
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
