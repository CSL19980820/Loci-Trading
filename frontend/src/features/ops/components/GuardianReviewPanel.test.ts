import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import GuardianReviewPanel from './GuardianReviewPanel.vue'
import { getGuardianReview, runGuardianReview } from '@/shared/api/guardian'

vi.mock('@/shared/api/guardian', () => ({ getGuardianReview: vi.fn(), runGuardianReview: vi.fn() }))

it('loads a report, displays full account review and does not refetch unchanged polls', async () => {
  vi.mocked(getGuardianReview).mockResolvedValue({ report_key: 'daily:2026-09-14', period: 'daily', trade_date: '2026-09-14', status: 'success', result: { body: '成本 10.0026元/股\n期间盈亏 -502.60元\n待验证经验 · 观察后再验证', notify: { success: true } } })
  const reports = [{ report_key: 'daily:2026-09-14', period: 'daily' as const, trade_date: '2026-09-14', status: 'success', created_at: '2026-09-14T16:00:00', notify: { success: true } }]
  const wrapper = mount(GuardianReviewPanel, { props: { enabled: true, reports } })
  await flushPromises()
  expect(wrapper.find('.review-body').text()).toContain('成本 10.0026元/股')
  expect(wrapper.find('.review-body').text()).toContain('期间盈亏 -502.60元')
  expect(wrapper.text()).toContain('通知已送达')
  const count = vi.mocked(getGuardianReview).mock.calls.length
  await wrapper.setProps({ reports: structuredClone(reports) })
  await flushPromises()
  expect(getGuardianReview).toHaveBeenCalledTimes(count)
  wrapper.unmount()
})

it('queues today review and exposes a rejected premarket request', async () => {
  vi.mocked(runGuardianReview).mockResolvedValueOnce({ status: 'accepted', report_key: 'daily:2026-09-14' })
  const wrapper = mount(GuardianReviewPanel, { props: { enabled: true, reports: [] } })
  await wrapper.findAll('button').find(b => b.text() === '生成今日日复盘')!.trigger('click')
  await flushPromises()
  expect(runGuardianReview).toHaveBeenCalledWith('daily')
  expect(wrapper.emitted('changed')).toHaveLength(1)
  expect(wrapper.text()).toContain('报告任务已提交')
  vi.mocked(runGuardianReview).mockRejectedValueOnce(new Error('当前已过盘前时段'))
  await wrapper.findAll('button').find(b => b.text() === '生成盘前计划')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('当前已过盘前时段')
  wrapper.unmount()
})
