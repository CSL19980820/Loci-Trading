import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import InsightsView from './InsightsView.vue'
import { getOverlap } from '@/shared/api/quant'

vi.mock('@/shared/api/quant', () => ({ getOverlap: vi.fn() }))
vi.mock('@/features/review/composables/useHealthCheckup', () => ({
  useHealthCheckup: () => ({
    phase: ref('idle'), error: ref(''), report: ref(null), progress: ref(null),
    repairBusy: ref(''), score: ref(0), grade: ref(''), repairPlan: ref(null),
    canOneClickRepair: ref(false), hasRepairableIssues: ref(false), subtitle: ref(''),
    issueRows: ref([]), okRows: ref([]), pendingRows: ref([]), scan: vi.fn(), cancelScan: vi.fn(),
    repairAll: vi.fn(), repairFinding: vi.fn(),
  }),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('InsightsView overlap refreshes', () => {
  it('retains the newest overlap result and loading state across concurrent refreshes', async () => {
    const first = deferred<never>()
    const second = deferred<never>()
    vi.mocked(getOverlap).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mount(InsightsView, {
      global: {
        stubs: {
          PageTabs: { props: ['modelValue'], template: '<button @click="$emit(\'update:modelValue\', \'overlap\')">重叠</button>' },
          Sheet: { template: '<section><slot /><slot name="actions" /></section>' },
          BasicTable: { props: ['dataSource'], template: '<pre>{{ dataSource }}</pre>' },
          EmptyState: true, PageBusy: true, HealthCheckList: true, HealthScanProgress: true, HealthSealDial: true,
          'el-alert': true, 'el-input-number': true, 'el-tag': true,
          'el-button': { props: ['loading', 'disabled'], template: '<button :data-loading="String(loading)"><slot /></button>' },
        },
      },
    })

    await wrapper.get('button').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '刷新')?.trigger('click')
    second.resolve([{ strategy_a: 'new', strategy_b: 'B' }] as never)
    await flushPromises()
    expect(wrapper.text()).toContain('new')
    expect(wrapper.findAll('button').some((button) => button.attributes('data-loading') === 'true')).toBe(true)

    first.resolve([{ strategy_a: 'old', strategy_b: 'B' }] as never)
    await flushPromises()
    expect(wrapper.text()).toContain('new')
    expect(wrapper.text()).not.toContain('old')
  })
})
