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

  it('keeps folded agents when remote transcript omits them', () => {
    const local: AiMessage[] = [
      {
        id: 'AIM-A',
        role: 'assistant',
        content: '结论',
        status: 'done',
        agents: [{ id: 'ag-1', name: '账本', status: 'done' }],
      },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '结论' },
    ]
    expect(mergeSessionMessages(local, remote)[0]?.agents).toEqual([
      { id: 'ag-1', name: '账本', status: 'done' },
    ])
  })

  it('keeps local error status when syncing empty_completion failure', () => {
    const local: AiMessage[] = [
      { id: 'local-a', role: 'assistant', content: '本轮模型未产出可读终稿。', status: 'error' },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '本轮模型未产出可读终稿。' },
    ]
    expect(mergeSessionMessages(local, remote)[0]).toMatchObject({
      status: 'error',
      content: '本轮模型未产出可读终稿。',
    })
  })

  it('keeps remote error status when local was still streaming', () => {
    const local: AiMessage[] = [
      { id: 'local-a', role: 'assistant', content: '先读取账本。', status: 'streaming' },
    ]
    const remote: AiMessage[] = [
      {
        id: 'AIM-A',
        role: 'assistant',
        content: '本轮模型未产出可读终稿。',
        status: 'error',
      },
    ]
    expect(mergeSessionMessages(local, remote)[0]).toMatchObject({
      status: 'error',
      content: '本轮模型未产出可读终稿。',
    })
  })

  it('does not fold turn-2 local assistant onto turn-1 when remote already has a newer user', () => {
    const local: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '第一问', status: 'done' },
      {
        id: 'AIM-A1',
        role: 'assistant',
        content: '第一答',
        status: 'done',
        tool_receipts: [{ call_id: 'c1', name: 'ledger_positions', status: 'done' }],
      },
      { id: 'local-user-2', role: 'user', content: '第二问', status: 'done' },
      {
        id: 'local-assistant-2',
        role: 'assistant',
        content: '第二答流式',
        status: 'streaming',
        tool_receipts: [{ call_id: 'c2', name: 'market_quote', status: 'running' }],
      },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '第一问' },
      { id: 'AIM-A1', role: 'assistant', content: '第一答' },
      { id: 'AIM-U2', role: 'user', content: '第二问' },
    ]

    const merged = mergeSessionMessages(local, remote)
    expect(merged.map((row) => row.id)).toEqual(['AIM-U1', 'AIM-A1', 'AIM-U2', 'local-assistant-2'])
    expect(merged[1]).toMatchObject({
      id: 'AIM-A1',
      content: '第一答',
      tool_receipts: [{ call_id: 'c1', name: 'ledger_positions' }],
    })
    expect(merged.at(-1)).toMatchObject({
      id: 'local-assistant-2',
      content: '第二答流式',
      tool_receipts: [{ call_id: 'c2', name: 'market_quote' }],
    })
  })

  it('appends a local next-turn user instead of folding onto a completed prior user', () => {
    const local: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '第一问', status: 'done' },
      { id: 'AIM-A1', role: 'assistant', content: '第一答', status: 'done' },
      { id: 'local-user-2', role: 'user', content: '第二问', status: 'done' },
      { id: 'local-assistant-2', role: 'assistant', content: '', status: 'streaming' },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '第一问' },
      { id: 'AIM-A1', role: 'assistant', content: '第一答' },
    ]

    const merged = mergeSessionMessages(local, remote)
    expect(merged.map((row) => ({ id: row.id, role: row.role }))).toEqual([
      { id: 'AIM-U1', role: 'user' },
      { id: 'AIM-A1', role: 'assistant' },
      { id: 'local-user-2', role: 'user' },
      { id: 'local-assistant-2', role: 'assistant' },
    ])
  })

  it('does not re-mark a remote assistant with content as streaming when folding local state', () => {
    const local: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '终稿', status: 'streaming', tool_receipts: [{ call_id: 'c1', name: 't', status: 'done' }] },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-A', role: 'assistant', content: '终稿' },
    ]
    expect(mergeSessionMessages(local, remote)[0]?.status).toBe('done')
  })

  it('appends a repeated same-text user as a new turn instead of folding onto the prior user', () => {
    const local: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '再看看', status: 'done' },
      { id: 'AIM-A1', role: 'assistant', content: '第一答', status: 'done' },
      { id: 'local-user-2', role: 'user', content: '再看看', status: 'done' },
      { id: 'local-assistant-2', role: 'assistant', content: '第二答', status: 'streaming' },
    ]
    const remote: AiMessage[] = [
      { id: 'AIM-U1', role: 'user', content: '再看看' },
      { id: 'AIM-A1', role: 'assistant', content: '第一答' },
    ]

    const merged = mergeSessionMessages(local, remote)
    expect(merged.map((row) => row.id)).toEqual([
      'AIM-U1',
      'AIM-A1',
      'local-user-2',
      'local-assistant-2',
    ])
    expect(merged[1]).toMatchObject({ id: 'AIM-A1', content: '第一答' })
    expect(merged.at(-1)).toMatchObject({ id: 'local-assistant-2', content: '第二答' })
  })
})
