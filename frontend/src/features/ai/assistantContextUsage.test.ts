import { describe, expect, it } from 'vitest'

import {
  buildContextUsage,
  estimateTokens,
  formatTokenCount,
} from './assistantContextUsage'

describe('assistantContextUsage', () => {
  it('estimates CJK denser than latin', () => {
    expect(estimateTokens('持仓盈亏')).toBe(4)
    expect(estimateTokens('abcd')).toBe(1)
  })

  it('counts the conversation segment exactly like tokenizing the whole transcript', () => {
    // 会话段按条缓存字符数再合并，必须和「整段拼起来算一次」逐值相等。
    // token 公式带 floor((other + 3) / 4) 的取整，逐条算 token 再相加会漂；
    // 消息之间的 '\n\n' 分隔符也要算进去，漏了同样对不上。
    const naive = (rows: Array<{ role?: string; content?: string; thinking?: string }>): number =>
      estimateTokens(
        rows
          .map((row) => [row.role, row.content, row.thinking].filter(Boolean).join('\n'))
          .join('\n\n'),
      )
    const cases = [
      [],
      [{ role: 'user', content: '' }],
      [{ role: 'user', content: '' }, { role: 'assistant', content: '' }],
      [{ role: 'user', content: '持仓怎么办' }, { role: 'assistant', content: 'abc def' }],
      [
        { role: 'user', content: '复盘一下', thinking: '先看仓位' },
        { role: 'assistant', content: 'x'.repeat(777) },
        { role: 'user', content: '涨停回撤模型'.repeat(31) },
      ],
    ]
    for (const rows of cases) {
      const segment = buildContextUsage({ messages: rows, systemPromptTokens: 0 })
        .segments.find((row) => row.kind === 'conversation')
      expect(segment?.tokens ?? 0).toBe(naive(rows))
    }
  })

  it('formats token counts like Cursor short labels', () => {
    expect(formatTokenCount(593)).toBe('593')
    expect(formatTokenCount(11600)).toBe('11.6K')
    expect(formatTokenCount(141400)).toBe('141.4K')
    expect(formatTokenCount(1_200_000)).toBe('1.2M')
  })

  it('builds segmented usage with conversation dominating long chats', () => {
    const usage = buildContextUsage({
      contextWindow: 256_000,
      systemPromptTokens: 280,
      rules: ['不要编造数字'],
      tools: [{ name: 'ledger_positions', description: '读取持仓' }],
      messages: [
        { role: 'user', content: '先看仓位再决定怎么平。'.repeat(20) },
        { role: 'assistant', content: '已核对持仓。'.repeat(20) },
      ],
      draftText: '继续',
    })

    expect(usage.window).toBe(256_000)
    expect(usage.used).toBeGreaterThan(280)
    expect(usage.percent).toBeGreaterThanOrEqual(0)
    expect(usage.segments.some((row) => row.kind === 'system')).toBe(true)
    expect(usage.segments.some((row) => row.kind === 'conversation')).toBe(true)
    const conversation = usage.segments.find((row) => row.kind === 'conversation')
    expect(conversation!.tokens).toBeGreaterThan(usage.segments.find((row) => row.kind === 'draft')!.tokens)
  })

  it('splits mcp tools into their own bucket', () => {
    const usage = buildContextUsage({
      tools: [
        { name: 'ledger_positions', description: '本地' },
        { name: 'wudao_mcp_kline', description: '外挂', tags: ['mcp'] },
      ],
    })
    expect(usage.segments.some((row) => row.kind === 'tools')).toBe(true)
    expect(usage.segments.some((row) => row.kind === 'mcp')).toBe(true)
  })

  it('detects server__tool MCP names and prefers schema_tokens', () => {
    const usage = buildContextUsage({
      tools: [
        { name: 'ledger_positions', description: '本地', schema_tokens: 40 },
        { name: 'wudao__kline', description: '悟道K线', schema_tokens: 220 },
      ],
    })
    expect(usage.segments.find((row) => row.kind === 'tools')?.tokens).toBe(40)
    expect(usage.segments.find((row) => row.kind === 'mcp')?.tokens).toBe(220)
  })

  it('shrinks conversation when context_feed_tokens is present after compact', () => {
    const long = '持仓复盘结论。'.repeat(80)
    const raw = buildContextUsage({
      messages: [
        { role: 'user', content: long },
        { role: 'assistant', content: long },
      ],
    })
    const compacted = buildContextUsage({
      messages: [
        { role: 'user', content: long },
        { role: 'assistant', content: long, context_feed_tokens: 40 },
      ],
    })
    expect(compacted.segments.find((row) => row.kind === 'conversation')!.tokens)
      .toBeLessThan(raw.segments.find((row) => row.kind === 'conversation')!.tokens)
  })

  it('calibrates total used toward observed input_tokens', () => {
    const usage = buildContextUsage({
      systemPromptTokens: 100,
      tools: [{ name: 't', description: 'd', schema_tokens: 100 }],
      messages: [{ role: 'user', content: '你好' }],
      observedInputTokens: 900,
    })
    expect(usage.calibrated).toBe(true)
    expect(usage.used).toBeGreaterThanOrEqual(850)
    expect(usage.used).toBeLessThanOrEqual(950)
  })
})
