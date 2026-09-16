import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import GuardianAccountPanel from './GuardianAccountPanel.vue'
import { getGuardianTrades } from '@/shared/api/guardian'
import type { GuardianAccount, GuardianTrade } from '@/shared/types/guardian'

vi.mock('@/shared/api/guardian', () => ({ getGuardianTrades: vi.fn() }))
const account: GuardianAccount = { account_version: 2, initial_capital_cents: 20000000,
  cash_cents: 19989974, equity_cents: 20000487, market_value_cents: 10513,
  realized_pnl_cents: 200, unrealized_pnl_cents: 287, total_pnl_cents: 487,
  fees_cents: 26, positions: [], stale_codes: [] }

it('shows cents as exact yuan and keeps realized and floating profit separate', () => {
  const wrapper = mount(GuardianAccountPanel, { props: { account, trades: { items: [], total: 0 }, performance: [] } })
  const totals = wrapper.findAll('.account-totals strong').map(item => item.text())
  expect(totals).toEqual(['200,004.87', '199,899.74', '105.13', '4.87', '2.00', '2.87'])
  expect(wrapper.text()).toContain('万 2.5（免 5，无最低收费）')
  expect(wrapper.text()).toContain('T+1')
  wrapper.unmount()
})

it('loads older trades and preserves the selected page across automatic refresh', async () => {
  const rows = [{ id: 'old-trade', code: '603920', name: '旧成交', occurred_at: '2026-09-14T10:00:00' }] as GuardianTrade[]
  vi.mocked(getGuardianTrades).mockResolvedValue({ items: rows, total: 51 })
  const wrapper = mount(GuardianAccountPanel, { props: { account, trades: { items: [], total: 51 }, performance: [] },
    global: { stubs: { ElTable: { name: 'ElTable', props: ['data'], template: '<div>{{ data.map(row => row.id).join() }}</div>' }, ElTableColumn: true } } })
  wrapper.findComponent({ name: 'ElTabs' }).vm.$emit('update:modelValue', 'trades')
  await flushPromises()
  wrapper.findComponent({ name: 'ElPagination' }).vm.$emit('current-change', 2)
  await flushPromises()
  expect(getGuardianTrades).toHaveBeenCalledWith(50, 50, expect.any(AbortSignal))
  expect(wrapper.text()).toContain('old-trade')
  await wrapper.setProps({ trades: { items: [], total: 52 } })
  expect(wrapper.text()).toContain('old-trade')
  wrapper.unmount()
})
