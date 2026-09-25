import type { AiMessage } from '@/shared/types/ai_assistant'
import type { GuardianConsultTurn } from '@/shared/types/guardian'

const labels = { queued: '等待研究', preparing: '读取咨询背景', thinking: '正在思考', tools: '查询证据', answering: '正在回复', done: '研究完成', error: '研究中断' } as const

export function guardianPendingLabel(turn?: GuardianConsultTurn): string {
  return turn?.result.phase ? labels[turn.result.phase] : turn?.status === 'queued' ? labels.queued : '正在研究'
}

/** Preserve actual process evidence; old turns without it must not acquire invented reasoning. */
export function guardianMessages(turns: GuardianConsultTurn[]): AiMessage[] {
  return turns.flatMap(turn => {
    const active = turn.status === 'queued' || turn.status === 'running'
    const phase = turn.result.phase ?? (turn.status === 'queued' ? 'queued' : active ? 'preparing' : undefined)
    const created_at = new Date(turn.created * 1000).toISOString()
    return [
      { id: `${turn.id}:user`, role: 'user' as const, content: turn.question, status: 'done' as const, created_at },
      {
        id: `${turn.id}:assistant`, role: 'assistant' as const, content: turn.result.answer || '', created_at,
        status: active ? 'streaming' as const : turn.status === 'failed' ? 'error' as const : 'done' as const,
        thinking: turn.result.thinking,
        tool_receipts: turn.result.tool_receipts ?? turn.result.tools?.map((tool, index) => ({ call_id: `${turn.id}:tool:${index}`, name: tool.name, status: tool.ok ? 'done' as const : 'error' as const })),
        ...(phase ? { progress: { phase, label: active && !turn.result.phase && turn.status !== 'queued' ? '正在研究（等待进度）' : labels[phase] } } : {}),
        ...(turn.status === 'failed' ? { warnings: [turn.result.error || '咨询未完成，请重新提问'] } : {}),
        meta: [turn.result.model, turn.result.as_of?.slice(0, 16).replace('T', ' ')].filter(Boolean).join(' · '),
      },
    ]
  })
}
