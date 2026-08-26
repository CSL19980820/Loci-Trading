import type { AiAgentProgress } from '@/shared/types/ai_assistant'

export type AgentStatusTone = 'queued' | 'running' | 'done' | 'error' | 'cancelled'

export function agentStatusLabel(status: AiAgentProgress['status']): string {
  return {
    queued: '排队',
    running: '运行中',
    done: '完成',
    error: '失败',
    cancelled: '已中止',
  }[status]
}

export function agentStatusTone(status: AiAgentProgress['status']): AgentStatusTone {
  return status
}

export function agentDisplayName(agent: Pick<AiAgentProgress, 'id' | 'name'>): string {
  return agent.name?.trim() || agent.id
}

export function agentRunning(status: AiAgentProgress['status']): boolean {
  return status === 'running' || status === 'queued'
}
