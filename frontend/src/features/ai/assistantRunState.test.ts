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

  it('folds live agents into the assistant message on done', () => {
    let state = beginAssistantTurn([], '看候选')
    state = applyAiRunEvent(state, { type: 'subagent_start', data: { id: 'evidence', name: '候选证据', progress: 10 } })
    state = applyAiRunEvent(state, { type: 'subagent_end', data: { id: 'evidence', ok: true, detail: '完成' } })
    state = applyAiRunEvent(state, { type: 'done', data: { content: '结论' } })

    expect(state.messages.at(-1)?.agents).toEqual([expect.objectContaining({
      id: 'evidence', status: 'done',
    })])
  })

  it('keeps a cancelled turn distinct from a completed turn', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '停止'), {
      type: 'cancelled',
      data: {},
    })

    expect(state.messages.at(-1)).toMatchObject({ status: 'cancelled', content: '已中止' })
  })

  it('settles live subagents and tools when the run is cancelled', () => {
    let state = beginAssistantTurn([], '核对')
    state = applyAiRunEvent(state, {
      type: 'subagent_start',
      data: { id: 'ledger', name: '账本核对', progress: 5, detail: '已启动' },
    })
    state = applyAiRunEvent(state, {
      type: 'tool_start',
      data: { call_id: 't1', name: 'ledger_positions' },
    })
    state = applyAiRunEvent(state, { type: 'cancelled', data: {} })

    expect(state.agents).toEqual([expect.objectContaining({
      id: 'ledger', status: 'cancelled', progress: 5,
    })])
    expect(state.messages.at(-1)).toMatchObject({
      status: 'cancelled',
      agents: [expect.objectContaining({ id: 'ledger', status: 'cancelled' })],
      tool_receipts: [expect.objectContaining({ call_id: 't1', status: 'done', preview: '已中止' })],
    })
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

  it('prefers a longer done.text over a short pre-tool streamed stub', () => {
    let state = beginAssistantTurn([], '平账')
    state = applyAiRunEvent(state, { type: 'token', data: { delta: '先读取账本再决定。' } })
    state = applyAiRunEvent(state, {
      type: 'done',
      data: { text: '账已核对：建议补记卖出 400 股 @ 20.92，实盈对齐 274。' },
    })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'done',
      content: '账已核对：建议补记卖出 400 股 @ 20.92，实盈对齐 274。',
    })
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

  it('replaces long plan narration with a shorter non-empty done.text', () => {
    let state = beginAssistantTurn([], '平账')
    state = applyAiRunEvent(state, {
      type: 'token',
      data: { delta: '先读取账本核实当前状态，再决定怎么平。' },
    })
    state = applyAiRunEvent(state, {
      type: 'done',
      data: { text: '建议卖出。', content: '建议卖出。' },
    })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'done',
      content: '建议卖出。',
    })
  })

  it('replaces plan narration on empty_completion error (Hermes/OpenClaw)', () => {
    let state = beginAssistantTurn([], '平账')
    state = applyAiRunEvent(state, {
      type: 'token',
      data: { delta: '先读取账本核实当前状态，再决定怎么平。' },
    })
    state = applyAiRunEvent(state, {
      type: 'tool_end',
      data: { call_id: 'c1', name: 'ledger_positions', preview: 'ok' },
    })
    state = applyAiRunEvent(state, {
      type: 'error',
      data: {
        message: '本轮模型未产出可读终稿（常见于思考档位只返回推理、正文为空）。',
        stopped_reason: 'empty_completion',
      },
    })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'error',
      content: '本轮模型未产出可读终稿（常见于思考档位只返回推理、正文为空）。',
    })

    // finishRun 空二次 error 不得冲掉失败文案 / 不得抛 startsWith
    state = applyAiRunEvent(state, { type: 'error', data: {} })
    expect(state.messages.at(-1)).toMatchObject({
      status: 'error',
      content: '本轮模型未产出可读终稿（常见于思考档位只返回推理、正文为空）。',
    })
  })

  it('status-only error after tools does not keep plan narration', () => {
    let state = beginAssistantTurn([], '平账')
    state = applyAiRunEvent(state, {
      type: 'token',
      data: { delta: '先读取账本再决定。' },
    })
    state = applyAiRunEvent(state, {
      type: 'tool_end',
      data: { call_id: 'c1', name: 'ledger_positions', preview: 'ok' },
    })
    state = applyAiRunEvent(state, { type: 'error', data: {} })

    expect(state.messages.at(-1)).toMatchObject({
      status: 'error',
      content: '助手运行失败',
    })
  })

  it('ignores legacy tool_awaiting_confirmation and does not invent a dual HITL receipt', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '写入'), {
      type: 'tool_awaiting_confirmation',
      data: { call_id: 'pending-1', name: 'ledger_write', summary: '确认写入 2 笔成交？', risk: 'write' },
    })

    const assistant = state.messages.at(-1)
    expect(assistant?.content).toBe('')
    expect(assistant?.tool_receipts ?? []).toEqual([])
    expect(assistant?.hitl).toBeUndefined()
  })

  it('accumulates think deltas onto the assistant turn', () => {
    let state = beginAssistantTurn([], '推理')
    state = applyAiRunEvent(state, { type: 'think', data: { delta: '先看仓位' } })
    state = applyAiRunEvent(state, { type: 'think', data: { delta: '再看风险' } })
    expect(state.messages.at(-1)?.thinking).toBe('先看仓位再看风险')
  })

  it('token/think replace only the last assistant without cloning prior messages', () => {
    let state = beginAssistantTurn([], '查询')
    const user = state.messages[0]!
    const assistantBefore = state.messages[1]!
    const toolsBefore = assistantBefore.tool_receipts

    state = applyAiRunEvent(state, { type: 'token', data: { delta: '持' } })
    expect(state.messages[0]).toBe(user)
    expect(state.messages[1]).not.toBe(assistantBefore)
    expect(state.messages[1]?.content).toBe('持')
    expect(state.messages[1]?.tool_receipts).toBe(toolsBefore)
    expect(assistantBefore.content).toBe('')

    const afterToken = state.messages[1]!
    state = applyAiRunEvent(state, { type: 'think', data: { delta: '想' } })
    expect(state.messages[0]).toBe(user)
    expect(state.messages[1]).not.toBe(afterToken)
    expect(state.messages[1]?.thinking).toBe('想')
    expect(afterToken.thinking).toBeUndefined()
  })

  it('keeps message identity for subagent-only updates', () => {
    const base = beginAssistantTurn([], '研究')
    const next = applyAiRunEvent(base, {
      type: 'subagent_start',
      data: { id: 'evidence', kind: 'research', progress: 10 },
    })
    expect(next.messages).toBe(base.messages)
    expect(next.agents).toEqual([expect.objectContaining({ id: 'evidence', status: 'running' })])
  })

  it('accepts loading then ready artifact payloads for kline kinds', () => {
    let state = beginAssistantTurn([], '看 K 线')
    state = applyAiRunEvent(state, {
      type: 'artifact',
      data: { id: 'k1', kind: 'kline', status: 'loading', title: '日K' },
    })
    expect(state.messages.at(-1)?.artifacts).toMatchObject([{ id: 'k1', kind: 'kline', status: 'loading' }])

    state = applyAiRunEvent(state, {
      type: 'artifact',
      data: {
        id: 'k1', kind: 'kline', status: 'ready',
        data: { bars: [{ trade_date: '2026-08-01', open: 10, high: 11, low: 9, close: 10.5 }] },
      },
    })
    expect(state.messages.at(-1)?.artifacts?.[0]).toMatchObject({
      id: 'k1', status: 'ready', data: { bars: [expect.any(Object)] },
    })
  })

  it('maps top-level qianlong bars into artifact.data', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '看潜龙'), {
      type: 'qianlong_kline',
      data: { id: 'chart-1', bars: [[10, 11, 12, 9]] },
    })
    expect(state.messages.at(-1)?.artifacts?.[0]?.data.bars).toEqual([[10, 11, 12, 9]])
  })

  it('stores waiting_user hitl ask separately from answer text', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '确认？'), {
      type: 'waiting_user',
      data: { ask: { prompt: '是否继续写入？', options: ['是', '否'], risk: 'write' } },
    })
    expect(state.messages.at(-1)?.hitl).toMatchObject({
      prompt: '是否继续写入？', options: ['是', '否'], risk: 'write',
    })
  })

  it('stores waiting_user multi-question hitl for restore', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '确认？'), {
      type: 'waiting_user',
      data: {
        ask: {
          prompt: '请回答',
          questions: [
            { id: 'path', prompt: '选路径？', options: ['提交', '再看看'] },
            { id: 'note', prompt: '备注？', allow_free_text: true },
          ],
        },
      },
    })
    expect(state.messages.at(-1)?.hitl?.questions).toEqual([
      { id: 'path', prompt: '选路径？', options: ['提交', '再看看'] },
      { id: 'note', prompt: '备注？', allow_free_text: true },
    ])
  })

  it('surfaces context_compacted as a short warning on the turn', () => {
    const state = applyAiRunEvent(beginAssistantTurn([], '长会话'), {
      type: 'context_compacted',
      data: {
        message: '已压缩较早对话（库内原文仍在）',
        removed: 12,
        kept: 12,
        tokens_after: 420,
      },
    })
    expect(state.messages.at(-1)?.warnings).toEqual(['已压缩较早对话（库内原文仍在）'])
    expect(state.messages.at(-1)?.context_feed_tokens).toBe(420)
  })

  it('reverse: no compact notice without context_compacted event', () => {
    let state = beginAssistantTurn([], '普通问')
    state = applyAiRunEvent(state, { type: 'token', data: { delta: '答' } })
    state = applyAiRunEvent(state, { type: 'done', data: { text: '答' } })
    const warnings = state.messages.at(-1)?.warnings ?? []
    expect(warnings.some((row) => row.includes('已压缩'))).toBe(false)
  })

  it('accumulates nested subagent_tool receipts through subagent_end', () => {
    let state = beginAssistantTurn([], '核对持仓')
    state = applyAiRunEvent(state, {
      type: 'subagent_start',
      data: { id: 'ledger', name: '账本核对', progress: 5 },
    })
    state = applyAiRunEvent(state, {
      type: 'subagent_tool',
      data: {
        id: 'ledger',
        call_id: 'c1',
        tool_name: 'ledger_positions',
        status: 'running',
      },
    })
    state = applyAiRunEvent(state, {
      type: 'subagent_tool',
      data: {
        id: 'ledger',
        call_id: 'c1',
        tool_name: 'ledger_positions',
        status: 'done',
        preview: '3 持仓',
      },
    })
    state = applyAiRunEvent(state, {
      type: 'subagent_end',
      data: { id: 'ledger', ok: true, detail: '完成' },
    })
    expect(state.agents).toEqual([
      expect.objectContaining({
        id: 'ledger',
        status: 'done',
        tool_receipts: [
          expect.objectContaining({
            call_id: 'c1',
            name: 'ledger_positions',
            status: 'done',
            preview: '3 持仓',
          }),
        ],
      }),
    ])
  })
})
