import { mount } from '@vue/test-utils'
import ElementPlus, { ElInputNumber, ElSwitch, ElTable } from 'element-plus'
import { defineComponent, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import type { AkshareCatalogCapability } from '@/shared/types/quant'

import AkshareToolTable from './AkshareToolTable.vue'

function capability(index: number): AkshareCatalogCapability {
  return {
    name: `api_${String(index).padStart(2, '0')}`,
    category: index % 2 ? 'spot_quotes' : 'financials',
    category_label: index % 2 ? '实时行情' : '财务报表',
    provider: 'AkShare',
    provider_id: 'akshare',
    signature: 'api(symbol)',
    summary: `接口 ${index}`,
    sample_params: { symbol: '600519' },
    parameters: [],
    execution_mode: 'read',
    status: 'available',
  }
}

function tableRows(wrapper: ReturnType<typeof mount>): AkshareCatalogCapability[] {
  const table = wrapper.findComponent(ElTable) as unknown as { props: (name: string) => unknown }
  return table.props('data') as AkshareCatalogCapability[]
}

function dialogSwitch(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAllComponents(ElSwitch).find((item) => !item.props('ariaLabel'))!
}

const DialogStub = defineComponent({
  props: { modelValue: Boolean },
  template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
})

const baseProps = {
  busy: false,
  probeResult: null,
  batchOpen: false,
  batchProgress: { done: 0, total: 0, ok: 0, failed: 0, skipped: 0 },
  batchResults: [],
}

describe('AkshareToolTable', () => {
  it('filters the backend catalog and keeps pagination within the filtered result', async () => {
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: { akshare_version: '1.0', capabilities: Array.from({ length: 27 }, (_, index) => capability(index)) },
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.text()).toContain('筛选 27 / 目录 27')
    expect(tableRows(wrapper).map((item) => item.name)).toContain('api_24')
    expect(tableRows(wrapper).map((item) => item.name)).not.toContain('api_25')

    await wrapper.find('input[aria-label="接口名筛选"]').setValue('api_25')
    await nextTick()
    expect(wrapper.text()).toContain('筛选 1 / 目录 27')
    expect(tableRows(wrapper).map((item) => item.name)).toEqual(['api_25'])
  })

  it('starts filtered by the source the user came from', () => {
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: {
          akshare_version: '1.0',
          capabilities: [
            { ...capability(1), provider: '东方财富', provider_id: 'eastmoney' },
            { ...capability(2), provider: '新浪', provider_id: 'sina' },
          ],
        },
        source: 'sina',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(tableRows(wrapper).map((item) => item.provider_id)).toEqual(['sina'])
  })

  it('puts batch actions on the sheet header and opens full probe', async () => {
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: { akshare_version: '1.0', capabilities: [capability(1)] },
        versionInfo: {
          installed: '1.0',
          latest: '1.2',
          update_available: true,
        },
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.text()).toContain('一键全测')
    expect(wrapper.text()).toContain('检查版本更新')
    expect(wrapper.text()).toContain('1.0 → 1.2')

    await wrapper.findAll('button').find((btn) => btn.text().includes('一键全测'))!.trigger('click')
    expect(wrapper.emitted('probe-all')).toBeTruthy()

    await wrapper.findAll('button').find((btn) => btn.text().includes('检查版本更新'))!.trigger('click')
    expect(wrapper.emitted('check-version')).toBeTruthy()
  })

  it('shows Chinese category labels in filters', () => {
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: {
          akshare_version: '1.0',
          capabilities: [
            { ...capability(1), category: 'history', category_label: '历史行情' },
            { ...capability(2), category: 'spot_quotes', category_label: '实时行情' },
          ],
        },
      },
      global: { plugins: [ElementPlus] },
    })

    const setup = (wrapper.vm.$ as unknown as { setupState: { categoryOptions: [string, string][] } }).setupState
    expect(setup.categoryOptions.map((item) => item[1])).toEqual(['历史行情', '实时行情'])
  })

  it('filters by health result when asked', async () => {
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: {
          akshare_version: '1.0',
          capabilities: [
            { ...capability(1), health_ok: true },
            { ...capability(2), health_ok: false },
            { ...capability(3) },
          ],
        },
      },
      global: { plugins: [ElementPlus] },
    })

    const setup = (wrapper.vm.$ as unknown as { setupState: { health: string } }).setupState
    setup.health = 'ok'
    await nextTick()
    expect(tableRows(wrapper).map((item) => item.name)).toEqual(['api_01'])
    setup.health = 'untested'
    await nextTick()
    expect(tableRows(wrapper).map((item) => item.name)).toEqual(['api_03'])
  })

  it('opens a typed probe form from the catalog parameters', async () => {
    const parameters = [
      {
        name: 'symbol',
        required: true,
        kind: 'positional_or_keyword',
        annotation: 'str',
        has_default: false,
        default: null,
        sample: '600519',
      },
      {
        name: 'limit',
        required: false,
        kind: 'positional_or_keyword',
        annotation: 'int',
        has_default: true,
        default: 10,
        sample: 10,
      },
      {
        name: 'flag',
        required: false,
        kind: 'positional_or_keyword',
        annotation: 'bool',
        has_default: true,
        default: false,
        sample: false,
      },
    ]
    const wrapper = mount(AkshareToolTable, {
      props: {
        ...baseProps,
        catalog: {
          akshare_version: '1.0',
          capabilities: [{ ...capability(1), parameters }],
        },
      },
      global: {
        plugins: [ElementPlus],
        stubs: { 'el-dialog': DialogStub },
      },
    })

    const setup = (wrapper.vm.$ as unknown as { setupState: unknown }).setupState as {
      openProbe: (item: AkshareCatalogCapability) => void
      submitProbe: () => void
      params: Record<string, unknown>
    }
    setup.openProbe({ ...capability(1), parameters })
    await nextTick()
    expect(setup.params.symbol).toBe('600519')
    expect(wrapper.findComponent(ElInputNumber).exists()).toBe(true)
    expect(dialogSwitch(wrapper).exists()).toBe(true)

    setup.submitProbe()
    expect(wrapper.emitted('probe')?.[0]).toEqual([
      { name: 'api_01', params: { symbol: '600519', limit: 10, flag: false } },
    ])
  })
})
