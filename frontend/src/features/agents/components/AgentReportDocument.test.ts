import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { AgentRunDetail } from '@/shared/types/stock_agents'
import AgentReportDocument from './AgentReportDocument.vue'

const run = (detail: AgentRunDetail['detail']): AgentRunDetail => ({ id: 'isolated-run', phase: 'intraday',
  status: 'success', started_at: '2026-09-30T14:00:00+08:00', summary: '等待系统候选确认。', detail })

describe('saved agent report', () => {
  it('separates model participation, observation and rejected intentions from actual fills', () => {
    const wrapper = mount(AgentReportDocument, { props: { run: run({
      assessments: [{ code: '600001', stance: 'participate', summary: '条件满足时考虑参与。', focus: true, evidence_refs: ['run:isolated:600001'] }],
      assessment_coverage: { total: 2, reviewed: 1, complete: false, required_codes: ['600001', '600002'],
        reviewed_codes: ['600001'], unreviewed_codes: ['600002'], focus_codes: ['600001'] },
      quotes: { '600001': { name: '保存名称' } },
      decisions: [{ code: '600001', action: 'buy', quantity: 100, reason: '计划参与。' },
        { code: '300001', action: 'watch', quantity: 0, reason: '加入观察。' }],
      rejects: [{ code: '600001', action: 'buy', reason: '行情未满足执行条件。' }], fills: [],
    }) } })
    expect(wrapper.find('[aria-label="分股票研判"]').text()).toContain('已研判 1 / 2')
    expect(wrapper.find('[data-stance="unreviewed"]').text()).toContain('600002')
    expect(wrapper.find('[data-stance="participate"]').text()).toContain('保存名称')
    expect(wrapper.find('[aria-label="实际模拟成交回执"]').text()).toContain('本轮无模拟成交')
    expect(wrapper.find('[aria-label="决策与观察管理"]').text()).toContain('拟买入')
    expect(wrapper.find('[aria-label="决策与观察管理"]').text()).toContain('观察管理')
    expect(wrapper.find('[aria-label="拒单与未执行"]').text()).toContain('未执行')
    expect(wrapper.findAll('.is-filled')).toHaveLength(0)
  })
  it('labels a legacy conversion explicitly without presenting a new execution', () => {
    const wrapper = mount(AgentReportDocument, { props: { run: run({ fills: [{ code: '600001', action: 'buy',
      quantity: 100, price_cents: 1200, origin: 'legacy_conversion' }] }) } })
    expect(wrapper.find('[aria-label="实际模拟成交回执"]').text()).toContain('历史折算（非新成交）')
    expect(wrapper.find('[aria-label="实际模拟成交回执"]').text()).not.toContain('已模拟买入')
  })
  it('retains distinct historical source texts with safe Markdown and a literal original', () => {
    const old = '# 原始结论\n\n**保留原文** <img src="https://example.test/pixel" onerror="alert(1)">'
    const wrapper = mount(AgentReportDocument, { props: { run: run({ summary: old,
      analysis: '保存的分析全文。', body: '另一份旧正文。', research_plan: '保存的旧计划。' }) } })
    expect(wrapper.find('.agent-report-original').text()).toContain(old)
    expect(wrapper.find('.agent-report-original').text()).toContain('保存的分析全文。')
    expect(wrapper.find('.agent-report-original').text()).toContain('另一份旧正文。')
    expect(wrapper.find('.agent-report-original').text()).toContain('保存的旧计划。')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.findAll('.agent-report-source')).toHaveLength(4)
  })
})
