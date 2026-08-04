import { describe, expect, it } from 'vitest'

import { mergeSessionMessages } from './assistantSessionMerge'
import type { AiMessage } from '@/shared/types/ai_assistant'

describe('mergeSessionMessages', () => {
  it('keeps local tool receipts when server ids differ from optimistic local ids', () => {
    const local: AiMessage[] = [
      { id: 'local-user-1', role: 'user', content: '查持仓', status: 'done' },
      {
        id: 'local-assistant-1',
        role: 'assistant',
        content: '持仓正常',
        status: 'done',
        tool_receipts: [{ call_id: 'c1', name: 'ledger_positions', status: 'done' }],
        artifacts: [{ id: 'a1', kind: 'candidate_verdict', data: { candidates: [] } }],
      },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-U', role: 'user', content: '查持仓' },
      { id: 'AIM-A', role: 'assistant', content: '持仓正常' },
    ]

    const merged = mergeSessionMessages(local, remote)
    expect(merged.at(-1)).toMatchObject({
      id: 'AIM-A',
      content: '持仓正常',
      tool_receipts: [{ call_id: 'c1', name: 'ledger_positions' }],
      artifacts: [{ id: 'a1', kind: 'candidate_verdict' }],
    })
  })

  it('fills empty assistant content from remote while preserving prior rich fields by id', () => {
    const local: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '', status: 'streaming', tool_receipts: [{ call_id: 'c1', name: 't', status: 'done' }] },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '终稿正文' },
    ]
    expect(mergeSessionMessages(local, remote)[0]).toMatchObject({
      content: '终稿正文',
      tool_receipts: [{ call_id: 'c1' }],
    })
  })
})
