import type { AiAgentProgress, AiChartArtifact, AiMessage, AiRunEvent, AiToolReceipt } from '@/shared/types/ai_assistant'

export interface AssistantRunState {
  messages: AiMessage[]
  agents: AiAgentProgress[]
}

export function beginAssistantTurn(messages: AiMessage[], userContent: string): AssistantRunState {
  const stamp = String(Date.now())
  return {
    agents: [],
    messages: [
      ...messages,
      { id: `local-user-${stamp}`, role: 'user', content: userContent, status: 'done' },
      { id: `local-assistant-${stamp}`, role: 'assistant', content: '', status: 'streaming', tool_receipts: [] },
    ],
  }
}

export function applyAiRunEvent(state: AssistantRunState, event: AiRunEvent): AssistantRunState {
  const messages = state.messages.map((message) => ({ ...message, tool_receipts: [...(message.tool_receipts ?? [])] }))
  const assistant = [...messages].reverse().find((message) => message.role === 'assistant')
  if (!assistant) return state
  const data = event.data
  if (event.type === 'token') assistant.content += String(data.delta ?? '')
  if (event.type === 'think') assistant.thinking = `${assistant.thinking ?? ''}${String(data.delta ?? '')}`
  if (event.type === 'warning') assistant.warnings = [...(assistant.warnings ?? []), String(data.message ?? '证据不足')]
  if (event.type === 'error') {
    assistant.status = 'error'
    assistant.content ||= String(data.message ?? '助手运行失败')
  }
  if (event.type === 'done') {
    assistant.status = 'done'
    const finalText = stringValue(data.text) || stringValue(data.content) || stringValue(data.message)
    if (finalText && !assistant.content.trim()) assistant.content = finalText
  }
  if (event.type === 'cancelled') {
    assistant.status = 'cancelled'
    assistant.content ||= '已中止'
  }
  if (event.type === 'waiting_user') {
    const ask = data.ask && typeof data.ask === 'object' ? data.ask as Record<string, unknown> : data
    const prompt = stringValue(ask.prompt) || stringValue(data.prompt) || stringValue(data.message)
    if (prompt && !assistant.content.trim()) assistant.content = prompt
    assistant.status = 'done'
  }
  if (event.type === 'tool_start') upsertTool(assistant, {
    call_id: String(data.call_id ?? data.name ?? Date.now()), name: String(data.name ?? '工具'), status: 'running',
    arguments: objectValue(data.arguments),
  })
  if (event.type === 'tool_end') upsertTool(assistant, {
    call_id: String(data.call_id ?? data.name ?? Date.now()), name: String(data.name ?? '工具'),
    status: data.ok === false ? 'error' : 'done', preview: stringValue(data.preview), elapsed_ms: numberValue(data.elapsed_ms),
  })
  if (event.type === 'tool_awaiting_confirmation') {
    const summary = stringValue(data.summary)
    upsertTool(assistant, {
      call_id: String(data.call_id ?? data.pending_id ?? Date.now()), name: String(data.name ?? '待确认操作'),
      status: 'awaiting_confirmation', risk: stringValue(data.risk), summary,
    })
    if (summary && !assistant.content.trim()) assistant.content = summary
  }
  if (event.type === 'artifact' || event.type === 'qianlong_kline' || event.type === 'candidate_verdict') {
    addArtifact(assistant, event.type === 'artifact' ? data : { ...data, kind: event.type }, event.id)
  }
  return { messages, agents: reduceAgents(state.agents, event) }
}

function upsertTool(message: AiMessage, next: AiToolReceipt): void {
  const tools = message.tool_receipts ?? []
  const index = tools.findIndex((tool) => tool.call_id === next.call_id)
  if (index < 0) tools.push(next)
  else tools[index] = { ...tools[index], ...next }
  message.tool_receipts = tools
}

function addArtifact(message: AiMessage, data: Record<string, unknown>, eventId: AiRunEvent['id']): void {
  const kind = data.kind
  if (kind !== 'qianlong_kline' && kind !== 'candidate_verdict') return
  const artifact: AiChartArtifact = {
    id: String(data.id ?? eventId ?? `${kind}-${Date.now()}`),
    kind,
    title: stringValue(data.title),
    data: objectValue(data.data),
  }
  const previous = message.artifacts ?? []
  message.artifacts = previous.some((item) => item.id === artifact.id)
    ? previous.map((item) => item.id === artifact.id ? artifact : item)
    : [...previous, artifact]
}

function reduceAgents(agents: AiAgentProgress[], event: AiRunEvent): AiAgentProgress[] {
  if (!event.type.startsWith('subagent_')) return agents
  const data = event.data
  const id = String(data.id ?? data.agent_id ?? '')
  if (!id) return agents
  const status = event.type === 'subagent_end' ? (data.ok === false ? 'error' : 'done') : 'running'
  const index = agents.findIndex((agent) => agent.id === id)
  const previous = index < 0 ? undefined : agents[index]
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
