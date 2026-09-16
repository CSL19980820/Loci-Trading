import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import GuardianTab from './GuardianTab.vue'
import { getGuardian, getGuardianResearch, getGuardianRun, getGuardianRuns, saveGuardian } from '@/shared/api/guardian'
import type { GuardianRun, GuardianStatus } from '@/shared/types/guardian'

vi.mock('@/shared/api/guardian', () => ({
  getGuardian: vi.fn(),
  getGuardianResearch: vi.fn(),
  getGuardianRun: vi.fn(),
  getGuardianRuns: vi.fn(),
  saveGuardian: vi.fn(),
  scanGuardian: vi.fn(),
  getGuardianTrades: vi.fn(),
}))
vi.mock('@/shared/api/quant', () => ({
  getProviders: vi.fn(async () => [{ id: 'p', name: '客户模型', is_active: true, models: ['model-a', 'model-b'] }]),
  getStrategies: vi.fn(async () => [{ slug: 'trend', name: '趋势战法' }]),
  runJob: vi.fn(async () => ({ run_id: 'r', status: 'running' })),
}))

const sample: GuardianStatus = {
  config: { enabled: false, provider: '客户模型', model: 'model-a', prompt: '内置战法提示词', strategies: [], notify: true },
  default_prompt: '内置战法提示词', job_id: 'job',
  state: { account_version: 2, initial_capital_cents: 20000000, cash_cents: 20000000, equity_cents: 20000000, market_value_cents: 0, realized_pnl_cents: 0, unrealized_pnl_cents: 0, total_pnl_cents: 0, fees_cents: 0, positions: [], stale_codes: [] }, runs: [], trades: { items: [], total: 0 }, performance: [],
}
const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { for (const wrapper of mounted.splice(0)) wrapper.unmount() })

it('shows the new name and filters independently watched stocks outside strategies', async () => {
  const run: GuardianRun = { slot: '2026-09-14T14:40:00+08:00', status: 'success', result: { decisions: [{ code: '603920', action: 'watch', reason: '主动发现', entry_condition: '放量突破', exit_condition: '资金撤离' }] } }
  vi.mocked(getGuardian).mockResolvedValue({ ...structuredClone(sample), watchlist: [
    { code: '603920', name: '自主发现股票', signals: [], strategies: [], watch: { code: '603920', name: '自主发现股票', reason: '主动发现', entry_condition: '放量突破', exit_condition: '资金撤离', added_at: '2026-09-14', updated_at: '2026-09-14' } },
    { code: '002349', name: '策略参考股票', signals: [], strategies: ['trend'] },
  ], runs: [run] })
  vi.mocked(getGuardianResearch).mockResolvedValue({ watchlist: [
    { code: '603920', name: '自主发现股票', signals: [], strategies: [], watch: { code: '603920', name: '自主发现股票', reason: '主动发现', entry_condition: '放量突破', exit_condition: '资金撤离', added_at: '2026-09-14', updated_at: '2026-09-14' } },
    { code: '002349', name: '策略参考股票', signals: [], strategies: ['trend'] },
  ], active_strategies: [] })
  vi.mocked(getGuardianRuns).mockResolvedValue({ items: [run], total: 1 })
  vi.mocked(getGuardianRun).mockResolvedValue(run)
  const wrapper = await loaded()
  expect(wrapper.find('h2').text()).toBe('自主交易员')
  await showResearch(wrapper)
  wrapper.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 'self')
  await nextTick()
  await flushPromises()
  expect(wrapper.find('[aria-label="交易参考池"]').text()).toContain('自主发现股票')
  expect(wrapper.find('[aria-label="交易参考池"]').text()).not.toContain('策略参考股票')
  expect(wrapper.find('[aria-label="交易研判"]').text()).toContain('等待入场：放量突破')
  expect(wrapper.find('[aria-label="交易研判"]').text()).toContain('撤出观察：资金撤离')
})

beforeEach(() => {
  vi.mocked(getGuardian).mockResolvedValue(structuredClone(sample))
  vi.mocked(saveGuardian).mockImplementation(async config => ({ ...structuredClone(sample), config }))
  vi.mocked(getGuardianResearch).mockResolvedValue({ watchlist: [], active_strategies: [] })
  vi.mocked(getGuardianRuns).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(getGuardianRun).mockResolvedValue({ slot: '', status: 'success', result: {} })
})

async function loaded() {
  // 几何布局由真实浏览器验收；这里验证本页的数据流，不运行 EP 的尺寸观察器。
  const wrapper = mount(GuardianTab, { global: { stubs: {
    teleport: true,
    ElDrawer: { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /><slot name="footer" /></aside>' },
    ElSelect: { name: 'ElSelect', props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>' },
    ElOption: { props: ['value', 'label'], template: '<option :value="value">{{ label }}</option>' },
    ElTable: { props: ['data'], template: '<div><span v-for="row in data" :key="row.code">{{ row.name }}</span></div>' },
    ElTableColumn: true,
  } } })
  mounted.push(wrapper)
  await wrapper.vm.load()
  await flushPromises()
  return wrapper
}

async function showResearch(wrapper: ReturnType<typeof mount>) {
  const tabs = wrapper.findComponent({ name: 'ElTabs' })
  expect(tabs.exists()).toBe(true)
  const tab = wrapper.findAll('.el-tabs__item').find(item => item.text() === '观察与研判')
  expect(tab).toBeDefined()
  await tab!.trigger('click')
  await nextTick()
  await flushPromises()
  await vi.waitFor(() => expect(wrapper.find('[aria-label="观察与研判"]').exists()).toBe(true), { timeout: 10_000 })
}

it('saves the selected model and edited prompt, and restores the built-in prompt', async () => {
  const wrapper = await loaded()
  expect(wrapper.find('textarea').exists()).toBe(false)
  await wrapper.findAll('button').find(b => b.text() === '交易员设置')!.trigger('click')
  await flushPromises()
  const selects = wrapper.findAllComponents({ name: 'ElSelect' })
  selects[1]!.vm.$emit('update:modelValue', 'model-b')
  await wrapper.find('textarea').setValue('按回踩战法守护')
  await wrapper.findAll('button').find(b => b.text() === '保存配置')!.trigger('click')
  await flushPromises()
  expect(saveGuardian).toHaveBeenCalledWith(expect.objectContaining({ model: 'model-b', prompt: '按回踩战法守护' }))
  await wrapper.findAll('button').find(b => b.text() === '交易员设置')!.trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === '恢复内置提示词')!.trigger('click')
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('内置战法提示词')
  wrapper.unmount()
})

it('renders a consolidated run and portfolio without hiding failure as no action', async () => {
  vi.mocked(getGuardian).mockResolvedValue({ ...structuredClone(sample),
    state: { ...sample.state, positions: [{ code: '600001', name: '测试持仓', quantity: 100, available_quantity: 0, cost_cents: 100026, average_cost: 10.0026, mark_price_cents: 1000, market_value_cents: 100000, unrealized_pnl_cents: -26, mark_at: '2026-09-14 10:00:00' }] },
    runs: [{ slot: '2026-09-11T10:00:00+08:00', status: 'failed', result: { error: '模型输出无效' } }],
  })
  const run: GuardianRun = { slot: '2026-09-11T10:00:00+08:00', status: 'failed', result: { error: '模型输出无效' } }
  vi.mocked(getGuardianRuns).mockResolvedValue({ items: [run], total: 1 })
  vi.mocked(getGuardianRun).mockResolvedValue(run)
  const wrapper = await loaded()
  await showResearch(wrapper)
  expect(wrapper.find('[aria-label="交易研判"]').text()).toContain('模型输出无效')
  expect(wrapper.find('.guardian-analysis').text()).not.toContain('无动作')
  expect(wrapper.text()).toContain('测试持仓')
  expect(wrapper.text()).toContain('清仓后可再次买入')
  wrapper.unmount()
})

it('shows autonomous holding plans and filters the real observation pool', async () => {
  const holding = { code: '600001', name: '长期持仓', quantity: 100, available_quantity: 100, cost_cents: 100026, average_cost: 10.0026, mark_price_cents: 1000, market_value_cents: 100000, unrealized_pnl_cents: -26, mark_at: '2026-09-14 10:00:00', holding_plan: '趋势持续就持有，不设固定天数' }
  vi.mocked(getGuardian).mockResolvedValue({ ...structuredClone(sample),
    state: { ...sample.state, positions: [holding] },
    watchlist: [{ code: '600002', name: '新入池股票', signals: [], strategies: [] }],
    runs: [{ slot: '2026-09-11T10:00:00+08:00', status: 'success', result: { body: '无动作', analysis: '继续持有', decisions: [{ code: '600001', action: 'hold', layers: 0, reason: '结构未破坏', holding_plan: holding.holding_plan }] } }],
  })
  const run: GuardianRun = { slot: '2026-09-11T10:00:00+08:00', status: 'success', result: { body: '无动作', analysis: '继续持有', decisions: [{ code: '600001', action: 'hold', layers: 0, reason: '结构未破坏', holding_plan: holding.holding_plan }] } }
  vi.mocked(getGuardianResearch).mockResolvedValue({ watchlist: [{ code: '600002', name: '新入池股票', signals: [], strategies: [] }], active_strategies: [] })
  vi.mocked(getGuardianRuns).mockResolvedValue({ items: [run], total: 1 })
  vi.mocked(getGuardianRun).mockResolvedValue(run)
  const wrapper = await loaded()
  await showResearch(wrapper)
  expect(wrapper.find('[aria-label="交易研判"]').text()).toContain('趋势持续就持有，不设固定天数')
  expect(wrapper.find('[aria-label="交易参考池"]').text()).toContain('新入池股票')
  wrapper.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 'holding')
  await nextTick()
  await flushPromises()
  expect(wrapper.find('[aria-label="交易参考池"]').text()).not.toContain('新入池股票')
  expect(wrapper.find('[aria-label="交易参考池"]').text()).toContain('长期持仓')
  wrapper.unmount()
})
