import { describe, expect, it } from 'vitest'

import { applyAiRunEvent, beginAssistantTurn } from './assistantRunState'

describe('assistantRunState', () => {
  it('keeps tool and token events on the active assistant turn', () => {
    let state = beginAssistantTurn([], '查询持仓')
    state = applyAiRunEvent(state, { type: 'tool_start', data: { call_id: 'call-1', name: 'ledger_positions' } })
    state = applyAiRunEvent(state, { type: 'token', data: { delta: '当前持仓正常。' } })
    state = applyAiRunEvent(state, { type: 'tool_end', data: { call_id: 'call-1', name: 'ledger_positions', ok: true } })

    const assistant = state.messages.at(-1)
    expect(assistant?.content).toBe('当前持仓正常。')
    expect(assistant?.tool_receipts).toMatchObject([{ call_id: 'call-1', name: 'ledger_positions', status: 'done' }])
  })

  it('does not create agent state for unrelated events', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], 'x'), { type: 'token', data: { delta: 'x' } })
    expect(state.agents).toEqual([])
  })

  it('renders direct Qianlong chart events as artifacts', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '看潜龙'), {
      type: 'qianlong_kline',
      data: { id: 'chart-1', bars: [[10, 11, 12, 9]] },
    })

    expect(state.messages.at(-1)?.artifacts).toMatchObject([{ id: 'chart-1', kind: 'qianlong_kline' }])
  })

  it('deduplicates a replayed artifact event and retains preview-only agent completion', () => {
    let state = beginAssistantTurn([], '看候选')
    const artifact = { id: '42', type: 'candidate_verdict', data: { data: { candidates: [{ code: '600000' }] } } } as const
    state = applyAiRunEvent(state, artifact)
    state = applyAiRunEvent(state, artifact)
    state = applyAiRunEvent(state, { type: 'subagent_start', data: { id: 'evidence', kind: 'research', progress: 120 } })
    state = applyAiRunEvent(state, { type: 'subagent_end', data: { id: 'evidence', ok: true, preview: '已完成证据整理' } })

    expect(state.messages.at(-1)?.artifacts).toHaveLength(1)
    expect(state.agents).toEqual([expect.objectContaining({
      id: 'evidence', name: 'research', status: 'done', progress: 100, detail: '已完成证据整理',
    })])
  })

  it('keeps a cancelled turn distinct from a completed turn', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '停止'), {
      type: 'cancelled',
      data: {},
    })

    expect(state.messages.at(-1)).toMatchObject({ status: 'cancelled', content: '已中止' })
  })

  it('fills assistant content from a done event payload when present', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '你好'), {
      type: 'done',
      data: { content: '非流式完整回复' },
    })

    expect(state.messages.at(-1)).toMatchObject({ status: 'done', content: '非流式完整回复' })
  })

  it('does not clear streamed content when done has no text', () => {
    let state = beginAssistantTurn([], '你好')
    state = applyAiRunEvent(state, { type: 'token', data: { delta: '已有正文' } })
    state = applyAiRunEvent(state, { type: 'done', data: {} })

    expect(state.messages.at(-1)).toMatchObject({ status: 'done', content: '已有正文' })
  })

  it('surfaces waiting_user ask text on the assistant turn', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '确认？'), {
      type: 'waiting_user',
      data: { ask: { prompt: '是否继续写入？', options: ['是', '否'] } },
    })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'done',
      content: '是否继续写入？',
    })
  })

  it('fills assistant content from done.text when no tokens arrived', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '总结一下'), {
      type: 'done',
      data: { text: '本轮无流式增量，最终答复在此。' },
    })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'done',
      content: '本轮无流式增量，最终答复在此。',
    })
  })

  it('does not let an empty done payload wipe streamed content', () => {
    let state = beginAssistantTurn([], '继续')
    state = applyAiRunEvent(state, { type: 'token', data: { delta: '已流式输出。' } })
    state = applyAiRunEvent(state, { type: 'done', data: { text: '', content: '   ', message: null } })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'done',
      content: '已流式输出。',
    })
  })

  it('surfaces tool_awaiting_confirmation summary when the turn has no content yet', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '写入'), {
      type: 'tool_awaiting_confirmation',
      data: { call_id: 'pending-1', name: 'ledger_write', summary: '确认写入 2 笔成交？', risk: 'write' },
    })

    expect(state.messages.at(-1)).toMatchObject({
      content: '确认写入 2 笔成交？',
      tool_receipts: [{ call_id: 'pending-1', status: 'awaiting_confirmation', summary: '确认写入 2 笔成交？' }],
    })
  })
})
