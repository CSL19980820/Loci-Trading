import type {
  AiAgentProgress,
  AiChartArtifact,
  AiMessage,
  AiRunEvent,
  AiToolReceipt,
} from '@/shared/types/ai_assistant'
import { lastAssistantMessage } from './assistantRunState'
import { toolLabel } from './toolLabel'

export interface TaskPlanStep {
  id: string
  label: string
  status: 'queued' | 'running' | 'done' | 'error'
}

export interface TaskSourceItem {
  id: string
  label: string
  kind: 'tool' | 'artifact' | 'rule'
  detail?: string
}

export interface AssistantTaskModel {
  plan: TaskPlanStep[]
  sources: TaskSourceItem[]
  agents: AiAgentProgress[]
  artifacts: AiChartArtifact[]
  summary: string
  activityLines: string[]
}

export function emptyTaskModel(): AssistantTaskModel {
  return { plan: [], sources: [], agents: [], artifacts: [], summary: '', activityLines: [] }
}

/** Derive Codex-style task sidebar model from live agents + latest assistant turn. */
export function buildTaskModel(options: {
  agents: AiAgentProgress[]
  messages: AiMessage[]
  planSteps?: TaskPlanStep[]
  busy?: boolean
}): AssistantTaskModel {
  const assistant = lastAssistantMessage(options.messages)
  const tools = assistant?.tool_receipts ?? []
  const artifacts = assistant?.artifacts ?? []
  const agents = options.agents.length
    ? options.agents
    : (assistant?.agents ?? [])
  const sources = [
    ...tools.map((tool) => sourceFromTool(tool)),
    ...artifacts.map((item) => sourceFromArtifact(item)),
  ]
  const plan = options.planSteps?.length
    ? options.planSteps
    : derivePlan(agents, Boolean(options.busy), Boolean(assistant?.content?.trim()))
  return {
    plan,
    sources,
    agents,
    artifacts,
    summary: buildSummary(agents, options.busy, assistant),
    activityLines: buildActivityLines(agents),
  }
}

export function applyPlanEvent(
  steps: TaskPlanStep[],
  event: AiRunEvent,
): TaskPlanStep[] {
  if (event.type !== 'plan') return steps
  const raw = event.data.steps
  if (!Array.isArray(raw)) return steps
  const next: TaskPlanStep[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const id = String(row.id ?? row.label ?? '').trim()
    const label = String(row.label ?? row.id ?? '').trim()
    if (!id || !label) continue
    const status = normalizePlanStatus(row.status)
    next.push({ id, label, status })
  }
  return next.length ? next : steps
}

function normalizePlanStatus(value: unknown): TaskPlanStep['status'] {
  if (value === 'running' || value === 'done' || value === 'error' || value === 'queued') return value
  return 'queued'
}

function sourceFromTool(tool: AiToolReceipt): TaskSourceItem {
  const status =
    tool.status === 'done'
      ? '完成'
      : tool.status === 'running'
        ? '运行中'
        : tool.status === 'error'
          ? '失败'
          : '未知'
  const ms = tool.elapsed_ms != null ? ` · ${tool.elapsed_ms}ms` : ''
  return {
    id: `tool:${tool.call_id}`,
    label: toolLabel(tool.name),
    kind: 'tool',
    detail: `${status}${ms}`,
  }
}

function sourceFromArtifact(item: AiChartArtifact): TaskSourceItem {
  return {
    id: `art:${item.id}`,
    label: item.title || item.kind,
    kind: 'artifact',
    detail: item.status || 'ready',
  }
}

function derivePlan(
  agents: AiAgentProgress[],
  busy: boolean,
  hasAnswer: boolean,
): TaskPlanStep[] {
  if (!agents.length && !busy) return []
  const evidenceDone = agents.length > 0 && agents.every((agent) => agent.status === 'done' || agent.status === 'error')
  const evidenceRunning = agents.some((agent) => agent.status === 'running' || agent.status === 'queued')
  return [
    {
      id: 'evidence',
      label: agents.length ? `并行证据（${agents.length}）` : '收集证据',
      status: evidenceDone ? 'done' : evidenceRunning || busy ? 'running' : 'queued',
    },
    {
      id: 'main',
      label: '主助手综合',
      status: hasAnswer ? 'done' : evidenceDone && busy ? 'running' : busy ? 'queued' : 'queued',
    },
    {
      id: 'answer',
      label: '结论置底',
      status: hasAnswer ? 'done' : 'queued',
    },
  ]
}

function buildSummary(
  agents: AiAgentProgress[],
  busy: boolean | undefined,
  assistant: AiMessage | undefined,
): string {
  if (assistant?.status === 'error') return '本轮失败'
  if (assistant?.status === 'cancelled') return '本轮已中止'
  const running = agents.filter((agent) => agent.status === 'running' || agent.status === 'queued')
  const done = agents.filter((agent) => agent.status === 'done').length
  const failed = agents.filter((agent) => agent.status === 'error').length
  if (running.length) return `等待子进程回传 · ${done}/${agents.length} 完成`
  if (failed && !busy) return `${failed} 路子进程失败 · 见线程详情`
  if (agents.length && assistant?.content?.trim()) return `已汇总 ${agents.length} 路证据`
  if (busy) return '主助手运行中'
  if (assistant?.content?.trim()) return '本轮已完成'
  return agents.length ? `${done} 路子进程已完成` : ''
}

function buildActivityLines(agents: AiAgentProgress[]): string[] {
  return agents.map((agent) => {
    const name = agent.name || agent.id
    if (agent.status === 'running' || agent.status === 'queued') {
      const pct = agent.progress != null ? ` ${agent.progress}%` : ''
      return `已派生「${name}」· 运行中${pct} · 点开查看`
    }
    if (agent.status === 'cancelled') return `「${name}」已中止`
    if (agent.status === 'error') return `「${name}」失败 · ${agent.detail || '见线程'}`
    const preview = agent.detail ? ` · ${clip(agent.detail, 48)}` : ''
    return `「${name}」已完成${preview}`
  })
}

function clip(text: string, max: number): string {
  const value = text.trim()
  return value.length <= max ? value : `${value.slice(0, max)}…`
}
