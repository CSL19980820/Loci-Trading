import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  listResearchMembershipSnapshots: vi.fn(),
  listResearchPointInTimeFacts: vi.fn(),
}))

vi.mock('@/shared/api/quant_research', () => api)

import ResearchTemporalDataPanel from './ResearchTemporalDataPanel.vue'

const InputStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
})

const ButtonStub = defineComponent({
  props: { loading: Boolean, disabled: Boolean },
  emits: ['click'],
  template: '<button :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
})

const FormStub = defineComponent({
  emits: ['submit'],
  template: '<form @submit="$emit(\'submit\', $event)"><slot /></form>',
})

const DatePickerStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<button class="date-picker" type="button"></button>',
})

let tableRow = snapshot()

const TableColumnStub = defineComponent({
  setup() {
    return { row: tableRow }
  },
  template: '<div><slot :row="row" /></div>',
})

function snapshot() {
  return {
    universe_id: 'IDX/1',
    as_of: '2025-01-31',
    available_at: '2025-01-31',
    members: ['000001'],
    source_id: 'source',
    source_url: 'https://example.test/source',
    snapshot_revision: 'r1',
    fetched_at: '2026-08-05T09:30:00Z',
    payload_sha256: 'a'.repeat(64),
    parser_revision: 'parser-r1',
    pit_membership: true,
    survivorship_bias: false,
    degraded: false,
    missing_reason: '',
  }
}

function mountPanel() {
  return mount(ResearchTemporalDataPanel, {
    global: {
      stubs: {
        ResearchTemporalImportDialog: true,
        'el-form': FormStub,
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': InputStub,
        'el-date-picker': DatePickerStub,
        'el-select': { template: '<div><slot /></div>' },
        'el-option': true,
        'el-button': ButtonStub,
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': TableColumnStub,
        'el-link': { template: '<a><slot /></a>' },
        'el-empty': true,
      },
    },
  })
}

describe('ResearchTemporalDataPanel', () => {
  afterEach(() => vi.clearAllMocks())

  it('loads a requested historical universe and emits its id for the backtest form', async () => {
    tableRow = snapshot()
    api.listResearchMembershipSnapshots.mockResolvedValue({ items: [snapshot()], total: 1, resolved: snapshot() })
    const wrapper = mountPanel()

    await wrapper.find('input').setValue('IDX/1')
    await wrapper.findAll('form')[0].trigger('submit')
    await flushPromises()

    expect(api.listResearchMembershipSnapshots).toHaveBeenCalledWith({ universeId: 'IDX/1', asOf: undefined })
    expect(wrapper.text()).toContain('PIT 可用')
    const useButton = wrapper.findAll('button').find((button) => button.text().includes('用于严格 PIT'))
    await useButton!.trigger('click')
    expect(wrapper.emitted('select-universe')?.[0]).toEqual(['IDX/1'])
    wrapper.unmount()
  })

  it('refuses an as-of membership resolution without a universe id', async () => {
    const wrapper = mountPanel()
    wrapper.findAllComponents(DatePickerStub)[0].vm.$emit('update:modelValue', '2025-01-31')
    await nextTick()
    const forms = wrapper.findAll('form')
    await forms[0].trigger('submit')

    expect(api.listResearchMembershipSnapshots).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('必须填写股票池标识')
    wrapper.unmount()
  })

  it('does not expose an empty membership snapshot as strict PIT input', async () => {
    tableRow = { ...snapshot(), members: [] }
    api.listResearchMembershipSnapshots.mockResolvedValue({
      items: [{ ...snapshot(), members: [] }], total: 1,
    })
    const wrapper = mountPanel()
    await wrapper.find('input').setValue('IDX/1')
    await wrapper.findAll('form')[0].trigger('submit')
    await flushPromises()

    const useButton = wrapper.findAll('button').find((button) => button.text().includes('用于严格 PIT'))
    expect(useButton!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('空成员')
    wrapper.unmount()
  })

  it('does not expose a snapshot missing source payload provenance as strict PIT input', async () => {
    tableRow = { ...snapshot(), payload_sha256: '' }
    api.listResearchMembershipSnapshots.mockResolvedValue({
      items: [{ ...snapshot(), payload_sha256: '' }], total: 1,
    })
    const wrapper = mountPanel()
    await wrapper.find('input').setValue('IDX/1')
    await wrapper.findAll('form')[0].trigger('submit')
    await flushPromises()

    const useButton = wrapper.findAll('button').find((button) => button.text().includes('用于严格 PIT'))
    expect(useButton!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('不可用于严格 PIT')
    wrapper.unmount()
  })
})
