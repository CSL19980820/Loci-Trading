import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SkillWatchTuningPanel from './SkillWatchTuningPanel.vue'

const getWatchTuning = vi.fn()
const saveWatchTuning = vi.fn()
const resetWatchTuning = vi.fn()

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessageBox: {
      ...actual.ElMessageBox,
      confirm: vi.fn().mockResolvedValue(undefined),
    },
  }
})

vi.mock('@/shared/api/quant_ops', () => ({
  getWatchTuning: (slug: string) => getWatchTuning(slug),
  saveWatchTuning: (slug: string, patch: unknown) => saveWatchTuning(slug, patch),
  resetWatchTuning: (slug: string) => resetWatchTuning(slug),
}))

function tuningFixture(overrides: Record<string, unknown> = {}) {
  return {
    stages: {
      market_gate: true,
      auction_confirm: true,
      role_history: true,
      paper_candidates: true,
    },
    gate: { promotion_attack: 0.35, promotion_empty: 0.2, broken_empty: 0.45 },
    roles: { leader_min_level: 2, weakened_drawdown: 25 },
    scan: { theme_limit: 3, member_limit: 6, candidate_score: 65, max_candidates: 2 },
    auction: { strong_gap_pct: 3, downgrade_gap_pct: -2, abandon_gap_pct: -5 },
    ...overrides,
  }
}

/** 字段清单由后端下发，前端只渲染——这里模拟后端的 schema */
function schemaFixture() {
  return {
    presets: [
      { id: 'aggressive', label: '偏进攻', summary: '闸门更松' },
      { id: 'balanced', label: '中性', summary: '默认档' },
      { id: 'defensive', label: '偏防守', summary: '闸门更严' },
    ],
    stages: [
      { key: 'market_gate', label: '龙空龙闸门', hint: '关掉 = 不做市场择时', default: true },
      { key: 'auction_confirm', label: '竞价确认', hint: '集合竞价复核龙头', default: true },
      { key: 'role_history', label: '角色留痕', hint: '追加角色观测', default: true },
      { key: 'paper_candidates', label: '纸面候选', hint: '关掉只出观察信号', default: true },
    ],
    sections: [
      {
        name: 'scan',
        label: '扫描范围',
        fields: [
          { key: 'theme_limit', label: '主线题材数', step: 1, min: 1, max: 10, default: 3 },
          { key: 'candidate_score', label: '候选形态分线', step: 5, min: 0, max: 100, default: 65 },
        ],
      },
      {
        name: 'gate',
        label: '闸门阈值',
        fields: [
          { key: 'promotion_attack', label: '晋级率·进攻', step: 0.05, min: 0, max: 1, default: 0.35 },
        ],
      },
    ],
  }
}

function response(overrides: Record<string, unknown> = {}) {
  return {
    slug: 'dragon-return',
    tuning: tuningFixture(),
    defaults: tuningFixture(),
    schema: schemaFixture(),
    ...overrides,
  }
}

async function mountPanel(available = true) {
  const wrapper = mount(SkillWatchTuningPanel, {
    props: { slug: 'dragon-return', available },
    global: { plugins: [ElementPlus] },
  })
  await nextTick()
  await nextTick()
  return wrapper
}

describe('skill watch tuning', () => {
  beforeEach(() => {
    getWatchTuning.mockReset()
    saveWatchTuning.mockReset()
    resetWatchTuning.mockReset()
    getWatchTuning.mockResolvedValue(response())
  })

  it('warns which pipeline stages are switched off', async () => {
    getWatchTuning.mockResolvedValue(
      response({
        tuning: tuningFixture({
          stages: {
            market_gate: false,
            auction_confirm: false,
            role_history: true,
            paper_candidates: true,
          },
        }),
      }),
    )

    const wrapper = await mountPanel()

    expect(wrapper.text()).toContain('龙空龙闸门')
    expect(wrapper.text()).toContain('竞价确认')
    expect(wrapper.text()).toContain('按降级口径运行')
  })

  it('saves the edited tuning back to the server', async () => {
    saveWatchTuning.mockResolvedValue(response())
    const wrapper = await mountPanel()

    const saveBtn = wrapper.findAll('button').find((btn) => btn.text().includes('保存调参'))
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await nextTick()

    expect(saveWatchTuning).toHaveBeenCalledTimes(1)
    const [slug, patch] = saveWatchTuning.mock.calls[0]!
    expect(slug).toBe('dragon-return')
    expect((patch as { scan: { candidate_score: number } }).scan.candidate_score).toBe(65)
  })

  it('locks every control when wudao mcp is missing', async () => {
    const wrapper = await mountPanel(false)

    const switches = wrapper.findAllComponents({ name: 'ElSwitch' })
    expect(switches.length).toBeGreaterThan(0)
    expect(switches.every((item) => item.props('disabled') === true)).toBe(true)
  })

  it('renders whatever fields the backend declares, not a hardcoded list', async () => {
    getWatchTuning.mockResolvedValue(
      response({
        schema: {
          presets: [{ id: 'balanced', label: '中性', summary: '' }],
          stages: [{ key: 'market_gate', label: '龙空龙闸门', hint: '', default: true }],
          sections: [
            {
              name: 'gate',
              label: '闸门阈值',
              fields: [
                { key: 'brand_new_knob', label: '新加的阈值', step: 1, min: 0, max: 9, default: 1 },
              ],
            },
          ],
        },
      }),
    )

    const wrapper = await mountPanel()

    // 后端新增阈值，前端不改代码就能出现在界面上
    expect(wrapper.text()).toContain('新加的阈值')
  })

  it('applies a named preset after confirmation', async () => {
    saveWatchTuning.mockResolvedValue(response())
    const wrapper = await mountPanel()
    await nextTick()

    const presetBtn = wrapper.findAll('button').find((btn) => btn.text().includes('偏防守'))
    expect(presetBtn).toBeTruthy()
    await presetBtn!.trigger('click')
    await nextTick()

    expect(saveWatchTuning).toHaveBeenCalledWith('dragon-return', { preset: 'defensive' })
  })
})
