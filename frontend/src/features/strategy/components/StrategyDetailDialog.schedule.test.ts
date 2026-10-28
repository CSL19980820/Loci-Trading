import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getStrategyJob, upsertStrategyJob } from '@/shared/api/quant_strategy'
import type { StrategyInfo, StrategyJob } from '@/shared/types/quant'
import { Select, SelectItem } from '@/shared/components/ui/select'
import { ToggleGroup } from '@/shared/components/ui/toggle-group'
import StrategyDetailConfigPane from './StrategyDetailConfigPane.vue'
import StrategyDetailDialog from './StrategyDetailDialog.vue'
import { buildPreview } from './strategyDetailFormat'

vi.mock('@/shared/api/quant_strategy', () => ({
  getStrategyJob: vi.fn(), upsertStrategyJob: vi.fn(), getStrategyVersions: vi.fn(),
  deleteStrategyVersion: vi.fn(), rollbackStrategyVersion: vi.fn(),
}))
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const SLUG = 'double-volume-yin-low-open-v1'
let wrapper: VueWrapper | undefined

async function open(slug = SLUG, job: Partial<StrategyJob> = { bound: false }) {
  vi.mocked(getStrategyJob).mockResolvedValue(job as StrategyJob)
  vi.mocked(upsertStrategyJob).mockResolvedValue({ ...job, bound: true } as StrategyJob)
  wrapper = shallowMount(StrategyDetailDialog, {
    props: { modelValue: true, strategy: { slug, name: '测试战法', source_kind: 'builtin' } as StrategyInfo },
    global: { renderStubDefaultSlot: true },
  })
  await flushPromises()
  return wrapper.getComponent(StrategyDetailConfigPane)
}

async function save() {
  wrapper!.getComponent({ name: 'PageTabs' }).vm.$emit('update:modelValue', 'config')
  await flushPromises()
  const button = wrapper!.findAll('button-stub').find(item => item.text().includes('保存调度'))
  expect(button).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

describe('双阶段战法调度', () => {
  it('回读保留服务端实际下次时间，用户改时间后才切换至未来北京时间预览', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-08T01:30:00Z'))
    const pane = await open(SLUG, {
      bound: true, enabled: true,
      next_runs: ['2026-10-09 09:25'],
      config: { schedule: { mode: 'once', run_hour: 9, run_minute: 25 } as NonNullable<StrategyJob['config']>['schedule'] },
    })
    expect(pane.props('displayRuns')).toEqual(['2026-10-09 09:25'])
    pane.vm.$emit('patch-config', { runMinute: 27 })
    await flushPromises()
    expect(pane.props('displayRuns')).toEqual(['2026-10-09 09:27'])
  })

  it('本地预览跳过已过时刻和周末，不使用浏览器本地时区', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-09T01:30:00Z'))
    expect(buildPreview('once', 9, 25, 10, 9, 30, 14, 50)).toEqual(['2026-10-12 09:25'])
    expect(buildPreview('once', 16, 30, 10, 9, 30, 14, 50)).toEqual(['2026-10-09 16:30'])
    expect(buildPreview('interval', 9, 25, 10, 9, 30, 10, 0)).toEqual([
      '2026-10-09 09:40', '2026-10-09 09:50', '2026-10-09 10:00', '2026-10-12 09:30', '2026-10-12 09:40',
    ])
  })

  it('只展示盘后预选和竞价窗口内的定点时刻', async () => {
    const pane = await open()
    const config = { ...pane.props('config'), scheduleEnabled: true }
    wrapper!.unmount()
    wrapper = shallowMount(StrategyDetailConfigPane, {
      props: { config, twoStage: true, loadingJob: false, displayRuns: [] },
      global: { renderStubDefaultSlot: true },
    })
    const options = wrapper.findAllComponents(Select).map(select => select.findAllComponents(SelectItem).map(item => item.props('value')))
    expect(options[0]).toEqual([15, 16, 17, 18, 19, 20, 21, 22, 23])
    expect(options[1]).toHaveLength(60)
    expect(options[2]).toEqual([9])
    expect(options[3]).toEqual([25, 26, 27, 28, 29])
    expect(wrapper.findComponent(ToggleGroup).exists()).toBe(false)
    expect(wrapper.text()).toContain('仅推送早上选股结果，晚上预选不推送')
  })

  it('默认晚上 16:30、早上 09:25，两个时间随保存一起提交', async () => {
    const pane = await open()
    expect(pane.props('twoStage')).toBe(true)
    expect(pane.props('config')).toMatchObject({ prepareHour: 16, prepareMinute: 30, runHour: 9, runMinute: 25 })
    pane.vm.$emit('patch-config', { scheduleEnabled: true, prepareHour: 17, prepareMinute: 5, runMinute: 27 })
    await save()
    expect(upsertStrategyJob).toHaveBeenCalledWith(SLUG, expect.objectContaining({
      schedule_mode: 'once', prepare_hour: 17, prepare_minute: 5, run_hour: 9, run_minute: 27, push_wecom: true,
    }))
  })

  it('回读晚间时间，并在关闭时保留两阶段配置和企微选择', async () => {
    const pane = await open(SLUG, {
      bound: true, enabled: true,
      prepare_schedule: { mode: 'once', run_hour: 16, run_minute: 45 } as StrategyJob['prepare_schedule'],
      config: { schedule: { mode: 'once', run_hour: 9, run_minute: 25 } as NonNullable<StrategyJob['config']>['schedule'], push_wecom: false },
    })
    expect(pane.props('config')).toMatchObject({ prepareHour: 16, prepareMinute: 45, runHour: 9, runMinute: 25, pushWecom: false })
    pane.vm.$emit('patch-config', { scheduleEnabled: false })
    await save()
    expect(upsertStrategyJob).toHaveBeenCalledWith(SLUG, expect.objectContaining({
      schedule_mode: 'off', enabled: false, prepare_hour: 16, prepare_minute: 45, push_wecom: false,
    }))
  })

  it('普通战法保留盘中间隔，不提交预选时间', async () => {
    const pane = await open('other-strategy')
    expect(pane.props('twoStage')).toBe(false)
    pane.vm.$emit('patch-config', { scheduleEnabled: true, scheduleMode: 'interval' })
    await save()
    const payload = vi.mocked(upsertStrategyJob).mock.calls[0]![1]
    expect(payload.schedule_mode).toBe('interval')
    expect(payload).not.toHaveProperty('prepare_hour')
  })
})
