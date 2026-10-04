import { describe, expect, it } from 'vitest'
import { beijingToday, diarySummary, executedTradeActions, renderAgentMarkdown, tradeActionLabel } from './agentHistoryDisplay'

describe('agent diary display', () => {
  it('uses the Beijing calendar day across the UTC day boundary', () => {
    expect(beijingToday(new Date('2026-09-30T15:59:59Z'))).toBe('2026-09-30')
    expect(beijingToday(new Date('2026-09-30T16:00:00Z'))).toBe('2026-10-01')
  })
  it('keeps only actual trade fills and rejected trade requests in the row', () => {
    const actions = [
      { code: '000001', name: '成交样本', action: 'buy', quantity: 100, status: 'filled' },
      { code: '000002', name: '拒单样本', action: 'sell', quantity: 0, status: 'rejected' },
      { code: '000003', name: '观察样本', action: 'watch', quantity: 0, status: 'recorded' },
      { code: '000004', name: '移出样本', action: 'unwatch', quantity: 0, status: 'recorded' },
      { code: '000005', name: '意图样本', action: 'buy', quantity: 100, status: 'recorded' },
      { code: '000006', name: '持有样本', action: 'hold', quantity: 100, status: 'filled' },
    ]
    expect(executedTradeActions({ actions }).map(row => row.code)).toEqual(['000001', '000002'])
    expect(tradeActionLabel(actions[0]!)).toBe('买入 成交样本 · 已模拟成交')
    expect(tradeActionLabel(actions[1]!)).toBe('卖出 拒单样本 · 拒单')
  })
  it('previews Markdown labels and plain text without dumping destinations or the whole report', () => {
    const source = '# 盘中判断\n\n**等待承接**，参考[公告](https://example.test/news?q=secret)。\n\n' + '后续分析。'.repeat(80)
    const preview = diarySummary(source, 80)
    expect(preview).toContain('等待承接')
    expect(preview).toContain('公告')
    expect(preview).not.toContain('https://')
    expect(preview).not.toContain('**')
    expect(Array.from(preview).length).toBeLessThanOrEqual(81)
    expect(preview.endsWith('…')).toBe(true)
    expect(diarySummary(' 本轮空仓等待。 ')).toBe('本轮空仓等待。')
  })
  it('sanitizes saved Markdown and refuses scripts, event handlers, remote images and script links', () => {
    const html = renderAgentMarkdown('**安全结论**\n\n<script>alert(1)</script><img src="https://example.test/pixel" onerror="alert(2)">\n\n[危险](javascript:alert(3))')
    expect(html).toContain('安全结论')
    expect(html).not.toMatch(/<script|<img|onerror|href="javascript:/i)
    expect(diarySummary('<img src=x onerror=alert(1)>结论')).toBe('结论')
  })
})
