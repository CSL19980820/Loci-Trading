import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import type { ScreenSkillPreviewResponse } from '@/shared/types/quant'

import ScreenSkillTestReport from './ScreenSkillTestReport.vue'

const preview: ScreenSkillPreviewResponse = {
  ok: true,
  diagnostics: [],
  logic: [
    {
      id: 'logic_trend',
      title: '站上均线',
      expression: 'close > base',
      explanation: '收盘价高于均线。',
      citations: ['ref_handbook'],
    },
  ],
  references: [
    {
      id: 'ref_handbook',
      title: '均线策略手册',
      kind: 'local',
      path: 'docs/strategy/ma.md',
      section: '第 2 节',
      quote: '站上均线后确认趋势。',
    },
  ],
  explanation: {
    mode: 'manifest',
    summary: 'Python 使用 manifest 逻辑说明。',
    steps: [
      {
        id: 'logic_trend',
        title: '站上均线',
        kind: 'signal',
        expression: 'close > base',
        plain_text: '收盘价高于均线。',
        line: null,
        fields: ['close'],
        functions: [],
      },
    ],
    data_requirements: {
      fields: ['close'],
      min_bars: 20,
      adjust: 'qfq',
      universe: null,
    },
    timing: {
      entry_timing: 'next_open',
      plain_text: '收盘后生成信号，于下一交易日开盘成交',
    },
  },
}

describe('ScreenSkillTestReport', () => {
  it('resolves every logic citation to a detailed source', () => {
    const wrapper = mount(ScreenSkillTestReport, {
      props: { preview },
      global: { plugins: [ElementPlus] },
    })

    const sources = wrapper.get('[aria-label="逻辑资料来源"]')
    expect(sources.text()).toContain('站上均线')
    expect(sources.text()).toContain('均线策略手册')
    expect(sources.text()).toContain('ref_handbook · local')
    expect(sources.text()).toContain('docs/strategy/ma.md · 第 2 节')
    expect(sources.text()).toContain('站上均线后确认趋势。')
  })

  it('keeps citations visible when compilation has no explanation', () => {
    const wrapper = mount(ScreenSkillTestReport, {
      props: {
        preview: {
          ...preview,
          ok: false,
          explanation: null,
          logic: [
            {
              ...preview.logic![0]!,
              citations: ['ref_missing'],
            },
          ],
          references: [],
        },
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.text()).toContain('本次预览未返回中文策略解释。')
    const sources = wrapper.get('[aria-label="逻辑资料来源"]')
    expect(sources.text()).toContain('ref_missing')
    expect(sources.text()).toContain('引用未解析')
  })
})
