import { mount } from '@vue/test-utils'
import ElementPlus, { ElRadioGroup, ElSwitch } from 'element-plus'
import { describe, expect, it } from 'vitest'

import LanePurposeBoard from './LanePurposeBoard.vue'
import type { LaneRow } from '../composables/useDataSources'

const LANE: LaneRow = {
  lane: 'hist_daily',
  label: '历史日 K',
  required: true,
  mode: 'auto',
  providerId: null,
  fallback: false,
  effectiveCount: 1,
  supportsDownloadTest: true,
  sources: [
    {
      id: 'sina',
      label: '新浪直连',
      enabled: true,
      masterEnabled: true,
      masterOff: false,
      order: 1,
      probe: null,
    },
    {
      id: 'tencent',
      label: '腾讯财经',
      enabled: false,
      masterEnabled: false,
      masterOff: true,
      order: null,
      probe: null,
    },
  ],
}

function mountBoard(row: LaneRow = LANE) {
  return mount(LanePurposeBoard, {
    props: { rows: [row], busyKey: '' },
    global: { plugins: [ElementPlus] },
  })
}

function switchByLabel(wrapper: ReturnType<typeof mountBoard>, label: string) {
  return wrapper.findAllComponents(ElSwitch).find((item) => item.props('ariaLabel') === label)
}

describe('LanePurposeBoard', () => {
  it('toggles a single source on this lane without touching its other lanes', () => {
    const wrapper = mountBoard()
    // 表体单元格在 happy-dom 里不渲染，直接测行开关的处理函数
    const setup = (wrapper.vm.$ as unknown as { setupState: unknown }).setupState as {
      toggleSourceOnLane: (lane: string, id: string, enabled: boolean) => void
    }

    setup.toggleSourceOnLane('hist_daily', 'sina', false)

    expect(wrapper.emitted('toggleTool')?.[0]).toEqual([
      { id: 'sina', lane: 'hist_daily', enabled: false },
    ])
  })

  it('saves a manual pick straight away, defaulting to the first enabled source', () => {
    const wrapper = mountBoard()

    wrapper.findComponent(ElRadioGroup).vm.$emit('change', 'manual')

    expect(wrapper.emitted('savePolicy')?.[0]).toEqual([
      {
        lane: 'hist_daily',
        policy: { mode: 'manual', provider_id: 'sina', fallback: false },
      },
    ])
  })

  it('keeps the current mode when only the fallback switch moves', () => {
    const wrapper = mountBoard({ ...LANE, mode: 'manual', providerId: 'sina' })
    const fallback = switchByLabel(wrapper, '历史日 K 失败回退')

    expect(fallback).toBeDefined()
    fallback!.vm.$emit('change', true)

    expect(wrapper.emitted('savePolicy')?.[0]).toEqual([
      {
        lane: 'hist_daily',
        policy: { mode: 'manual', provider_id: 'sina', fallback: true },
      },
    ])
  })

  it('marks a required lane that lost every source', () => {
    const wrapper = mountBoard({
      ...LANE,
      effectiveCount: 0,
      sources: [
        {
          id: 'sina',
          label: '新浪直连',
          enabled: false,
          masterEnabled: true,
          masterOff: false,
          order: null,
          probe: null,
        },
      ],
    })

    expect(wrapper.text()).toContain('无可用源')
  })
})
