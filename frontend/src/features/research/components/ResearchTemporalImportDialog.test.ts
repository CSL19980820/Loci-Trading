import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  importResearchMembershipSnapshots: vi.fn(),
  importResearchPointInTimeFacts: vi.fn(),
}))

vi.mock('@/shared/api/quant_research', () => api)

import ResearchTemporalImportDialog from './ResearchTemporalImportDialog.vue'

const InputStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
})

function mountDialog(kind: 'membership' | 'fact' = 'membership') {
  return mount(ResearchTemporalImportDialog, {
    props: { visible: true, kind },
    global: {
      stubs: {
        'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-form': { template: '<form><slot /></form>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': InputStub,
        'el-button': { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
      },
    },
  })
}

describe('ResearchTemporalImportDialog', () => {
  afterEach(() => vi.clearAllMocks())

  it('rejects non-string membership codes before sending the import request', async () => {
    const wrapper = mountDialog()
    await wrapper.find('textarea').setValue(JSON.stringify([{
      universe_id: 'CSI300',
      as_of: '2025-01-02',
      available_at: '2025-01-02',
      members: [42],
      source_id: 'fixture',
      source_url: 'https://example.test/membership',
      snapshot_revision: 'r1',
      fetched_at: '2026-08-05T09:30:00Z',
      payload_sha256: 'a'.repeat(64),
      parser_revision: 'parser-r1',
    }]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')

    expect(api.importResearchMembershipSnapshots).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('members 必须是非空、无重复的字符串数组')
    wrapper.unmount()
  })

  it('requires available_at and submits a valid membership payload unchanged', async () => {
    api.importResearchMembershipSnapshots.mockResolvedValue({ total: 1 })
    const payload = {
      universe_id: 'CSI300',
      as_of: '2025-01-02',
      available_at: '2025-01-02',
      members: ['600519'],
      source_id: 'fixture',
      source_url: 'https://example.test/membership',
      snapshot_revision: 'r1',
      fetched_at: '2026-08-05T09:30:00Z',
      payload_sha256: 'a'.repeat(64),
      parser_revision: 'parser-r1',
    }
    const wrapper = mountDialog()
    await wrapper.find('textarea').setValue(JSON.stringify([payload]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')
    await flushPromises()

    expect(api.importResearchMembershipSnapshots).toHaveBeenCalledWith({ snapshots: [payload] })
    expect(wrapper.emitted('imported')?.[0]).toEqual(['membership', 1])
    wrapper.unmount()
  })

  it('rejects an empty or duplicated membership list before sending the import request', async () => {
    const payload = {
      universe_id: 'CSI300', as_of: '2025-01-02', available_at: '2025-01-02',
      members: ['600519', '600519'], source_id: 'fixture',
      source_url: 'https://example.test/membership', snapshot_revision: 'r1',
      fetched_at: '2026-08-05T09:30:00Z', payload_sha256: 'a'.repeat(64), parser_revision: 'parser-r1',
    }
    const wrapper = mountDialog()
    await wrapper.find('textarea').setValue(JSON.stringify([payload]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')

    expect(api.importResearchMembershipSnapshots).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('非空、无重复')
    wrapper.unmount()
  })

  it('keeps the rejection reason and server detail visible when an import is rejected', async () => {
    const rejected = Object.assign(new Error('available_at 不可见'), { status: 422 })
    api.importResearchMembershipSnapshots.mockRejectedValue(rejected)
    const payload = {
      universe_id: 'CSI300', as_of: '2025-01-02', available_at: '2025-01-02',
      members: ['600519'], source_id: 'fixture',
      source_url: 'https://example.test/membership', snapshot_revision: 'r1',
      fetched_at: '2026-08-05T09:30:00Z', payload_sha256: 'a'.repeat(64), parser_revision: 'parser-r1',
    }
    const wrapper = mountDialog()
    await wrapper.find('textarea').setValue(JSON.stringify([payload]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('不符合研究库的格式要求')
    expect(wrapper.text()).toContain('available_at 不可见')
    wrapper.unmount()
  })

  it('rejects a membership snapshot without frozen payload provenance before sending it', async () => {
    const wrapper = mountDialog()
    await wrapper.find('textarea').setValue(JSON.stringify([{
      universe_id: 'CSI300', as_of: '2025-01-02', available_at: '2025-01-02',
      members: ['600519'], source_id: 'fixture',
      source_url: 'https://example.test/membership', snapshot_revision: 'r1',
    }]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')

    expect(api.importResearchMembershipSnapshots).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('抓取时间、载荷 hash 和解析版本')
    wrapper.unmount()
  })

  it('submits a fully provenanced PIT fact unchanged', async () => {
    api.importResearchPointInTimeFacts.mockResolvedValue({ total: 1 })
    const payload = {
      observation_id: 'announcement-1', entity_id: '600519', observed_on: '2025-01-02',
      available_at: '2025-01-03', published_at: '2025-01-03', values: { revenue: 1 },
      source_id: 'fixture', source_url: 'https://example.test/facts', revision: 'r1',
      fetched_at: '2026-08-05T09:30:00Z', payload_sha256: 'b'.repeat(64), parser_revision: 'parser-r1',
      fact_type: 'event',
    }
    const wrapper = mountDialog('fact')
    await wrapper.find('textarea').setValue(JSON.stringify([payload]))
    await wrapper.findAll('button').find((button) => button.text().includes('导入并校验'))!.trigger('click')
    await flushPromises()

    expect(api.importResearchPointInTimeFacts).toHaveBeenCalledWith({ facts: [payload] })
    expect(wrapper.emitted('imported')?.[0]).toEqual(['fact', 1])
    wrapper.unmount()
  })
})
