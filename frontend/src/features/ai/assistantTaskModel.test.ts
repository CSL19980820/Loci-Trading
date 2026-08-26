import { describe, expect, it } from 'vitest'

import { applyPlanEvent, buildTaskModel } from './assistantTaskModel'
import type { AiMessage } from '@/shared/types/ai_assistant'

describe('assistantTaskModel', () => {
  it('builds activity summary and sources from agents and tools', () => {
    const messages: AiMessage[] = [
      {
        id: 'a1',
        role: 'assistant',
        content: '',
        status: 'streaming',
        tool_receipts: [{ call_id: 't1', name: 'market_kline', status: 'done', preview: '320 bars' }],
        artifacts: [{ id: 'art1', kind: 'kline', title: '000001', status: 'loading', data: {} }],
      },
    ]
    const model = buildTaskModel({
      busy: true,
      messages,
      agents: [
        { id: 'market-evidence', name: '行情证据', status: 'running', progress: 62, detail: '读日K' },
        { id: 'candidate-evidence', name: '候选证据', status: 'done', detail: '8 只' },
      ],
    })
    expect(model.sources.map((row) => row.label)).toEqual(['拉取日 K', '000001'])
    expect(model.sources[0]?.detail).toBe('完成')
    expect(model.summary).toContain('等待子进程')
    expect(model.activityLines[0]).toContain('行情证据')
    expect(model.plan[0]?.status).toBe('running')
  })

  it('applies plan events from the backend', () => {
    const steps = applyPlanEvent([], {
      type: 'plan',
      data: {
        steps: [
          { id: 'evidence', label: '并行收集只读证据', status: 'running' },
          { id: 'main', label: '主助手综合回答', status: 'queued' },
        ],
      },
    })
    expect(steps).toHaveLength(2)
    expect(steps[0]?.label).toBe('并行收集只读证据')
  })
})
