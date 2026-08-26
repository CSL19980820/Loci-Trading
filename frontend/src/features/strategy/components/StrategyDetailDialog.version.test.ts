import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type * as ElementPlus from 'element-plus'
import type { StrategyInfo, StrategyVersion } from '@/shared/types/quant'

const api = vi.hoisted(() => ({
  deleteStrategyVersion: vi.fn(),
  getStrategyJob: vi.fn(),
  getStrategyVersions: vi.fn(),
  rollbackStrategyVersion: vi.fn(),
  upsertStrategyJob: vi.fn(),
}))
const feedback = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
const confirmation = vi.hoisted(() => ({ confirmDangerous: vi.fn() }))

vi.mock('@/shared/api/quant_strategy', () => api)
vi.mock('@/shared/lib/confirm', () => confirmation)
// 必须 partial mock：Element Plus 已改按需注册，SFC 模板里的 el-* 会被编译成
// 从 'element-plus' 具名 import，整包替换会让 ElDialog/ElTabPane 等全变 undefined。
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof ElementPlus>()
  return { ...actual, ElMessage: feedback }
})

import StrategyDetailDialog from './StrategyDetailDialog.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function strategy(slug: string, sourceKind: 'builtin' | 'formula' = 'formula'): StrategyInfo {
  return {
    slug,
    name: slug,
    description: '',
    entry_timing: 'close',
    required_fields: [],
    min_bars: 60,
    params: {},
    source_kind: sourceKind,
    editable: sourceKind !== 'builtin',
    version: 'v2',
    backtest_metrics: null,
    backtest_config: null,
  }
}

function version(versionValue: string, isActive = false): StrategyVersion {
  return {
    version: versionValue,
    status: 'archived',
    created_at: '2026-08-01 10:00:00',
    is_active: isActive,
  }
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().trim() === text)
  if (!button) throw new Error(`missing button: ${text}`)
  return button
}

function mountDialog(initial = strategy('old')) {
  return mount(StrategyDetailDialog, {
    props: { modelValue: true, strategy: initial },
    global: {
      directives: { loading: () => undefined },
      stubs: {
        'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
        'el-tabs': { template: '<div><slot /></div>' },
        'el-tab-pane': { template: '<div><slot /></div>' },
        'el-descriptions': { template: '<div><slot /></div>' },
        'el-descriptions-item': { props: ['label'], template: '<div>{{ label }}<slot /></div>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'el-checkbox': { template: '<label><slot /></label>' },
        'el-form': { template: '<div><slot /></div>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-option': { template: '<option><slot /></option>' },
        'el-radio-button': { template: '<label><slot /></label>' },
        'el-radio-group': { template: '<div><slot /></div>' },
        'el-select': { template: '<select><slot /></select>' },
        'el-switch': { template: '<input type="checkbox" />' },
      },
    },
  })
}

describe('StrategyDetailDialog versions', () => {
  beforeEach(() => {
    for (const mock of Object.values(api)) mock.mockReset()
    feedback.error.mockReset()
    feedback.success.mockReset()
    confirmation.confirmDangerous.mockReset()
    confirmation.confirmDangerous.mockResolvedValue(true)
  })

  it('does not render a stale version response after selecting another strategy', async () => {
    const oldVersions = deferred<StrategyVersion[]>()
    const newVersions = deferred<StrategyVersion[]>()
    api.getStrategyJob.mockResolvedValue({ bound: false })
    api.getStrategyVersions.mockImplementation((slug: string) =>
      slug === 'old' ? oldVersions.promise : newVersions.promise,
    )

    const wrapper = mountDialog(strategy('old'))
    await wrapper.setProps({ strategy: { ...strategy('new'), description: 'new detail' } })
    newVersions.resolve([version('2')])
    await flushPromises()
    oldVersions.resolve([version('1')])
    await flushPromises()

    expect(wrapper.findAll('strong').map((item) => item.text())).toEqual(['2'])
    wrapper.unmount()
  })

  it('does not expose version mutations for a built-in strategy', async () => {
    api.getStrategyJob.mockResolvedValue({ bound: false })
    const wrapper = mountDialog(strategy('builtin', 'builtin'))
    await flushPromises()

    expect(api.getStrategyVersions).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('回滚')
    expect(wrapper.text()).not.toContain('删除')
    wrapper.unmount()
  })

  it('renders the persisted buy instructions', async () => {
    api.getStrategyJob.mockResolvedValue({ bound: false })
    const wrapper = mountDialog({
      ...strategy('rsi30-dip', 'builtin'),
      entry_instructions: '数据库中的 RSI 买入说明',
    })
    await flushPromises()

    expect(wrapper.text()).toContain('买入说明')
    expect(wrapper.text()).toContain('数据库中的 RSI 买入说明')
    wrapper.unmount()
  })

  it('formats the structured backtest universe for display', async () => {
    api.getStrategyJob.mockResolvedValue({ bound: false })
    const wrapper = mountDialog({
      ...strategy('qianlong-close-v3', 'builtin'),
      backtest_config: {
        start: '2026-02-01',
        universe: { boards: ['main', 'chi_next'], exclude_st: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('股票池=主板、创业板，剔除 ST')
    expect(wrapper.text()).not.toContain('[object Object]')
    wrapper.unmount()
  })

  it('keeps the strategy detail intact after rolling back a version', async () => {
    api.getStrategyJob.mockResolvedValue({ bound: false })
    api.getStrategyVersions
      .mockResolvedValueOnce([version('2', true), version('1')])
      .mockResolvedValueOnce([version('1', true), version('2')])
    api.rollbackStrategyVersion.mockResolvedValue({
      slug: 'old', version: '1', file: 'strategy/custom/old.py', registered: true,
    })
    const wrapper = mountDialog()
    await flushPromises()

    await buttonByText(wrapper, '回滚').trigger('click')
    await flushPromises()

    expect(api.rollbackStrategyVersion).toHaveBeenCalledWith('old', '1')
    expect(wrapper.text()).toContain('公式')
    expect(wrapper.text()).toContain('当前版本1')
    expect(api.getStrategyVersions).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('ignores a rollback completion after selecting another strategy', async () => {
    const pendingRollback = deferred<{ slug: string; version: string; file: string; registered: boolean }>()
    api.getStrategyJob.mockResolvedValue({ bound: false })
    api.getStrategyVersions.mockResolvedValue([version('2', true), version('1')])
    api.rollbackStrategyVersion.mockReturnValue(pendingRollback.promise)
    const wrapper = mountDialog()
    await flushPromises()

    await buttonByText(wrapper, '回滚').trigger('click')
    await flushPromises()
    await wrapper.setProps({ strategy: { ...strategy('new'), description: 'new detail' } })
    pendingRollback.resolve({ slug: 'old', version: '1', file: 'strategy/custom/old.py', registered: true })
    await flushPromises()

    expect(wrapper.text()).toContain('new detail')
    expect(wrapper.text()).toContain('当前版本v2')
    expect(feedback.success).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
