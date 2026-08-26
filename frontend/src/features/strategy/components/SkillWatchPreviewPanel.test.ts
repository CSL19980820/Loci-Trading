import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SkillWatchPreviewPanel from './SkillWatchPreviewPanel.vue'

const previewSkillWatch = vi.fn()
const getLeaderRoles = vi.fn()

vi.mock('@/shared/api/quant_ops', () => ({
  previewSkillWatch: (slug: string) => previewSkillWatch(slug),
  getLeaderRoles: (slug: string) => getLeaderRoles(slug),
}))

function mountPanel(props: Record<string, unknown>) {
  return mount(SkillWatchPreviewPanel, {
    props: { slug: 'dragon-return', available: true, ...props },
    global: { plugins: [ElementPlus] },
  })
}

describe('skill watch preview', () => {
  beforeEach(() => {
    previewSkillWatch.mockReset()
    getLeaderRoles.mockReset()
    getLeaderRoles.mockResolvedValue({ slug: 'dragon-return', history: [], transitions: [] })
  })

  it('never calls the scanner when wudao mcp is not installed', async () => {
    const wrapper = mountPanel({ available: false, unavailableReason: '悟道 MCP 未配置 API Key' })

    expect(wrapper.text()).toContain('悟道 MCP 未配置 API Key')
    const button = wrapper.findComponent({ name: 'ElButton' })
    expect(button.props('disabled')).toBe(true)

    await button.trigger('click')
    await nextTick()
    expect(previewSkillWatch).not.toHaveBeenCalled()
  })

  it('renders leader roles and unverified candidates from a preview run', async () => {
    previewSkillWatch.mockResolvedValue({
      trade_date: '2026-08-07',
      validation_label: '未经过前向验证',
      market_gate: { state: 'dragon', mode: '龙', label: '进攻窗口', reason: '晋级率支持' },
      themes: [{ theme_code: '801843k', theme_name: '机器人', strength: 82 }],
      leaders: [
        {
          code: '600001',
          name: '测试龙',
          role: 'leader',
          role_label: '龙头',
          role_basis: '题材内连板最高（3 板）',
          theme_name: '机器人',
          ladder_level: 3,
          gain_20_pct: 25,
          drawdown_pct: 4,
        },
      ],
      picks: [{ code: '600001', name: '测试龙', score: 88, validation: 'unverified' }],
      signals: [{ type: 'paper_candidate', code: '600001', reason: '角色与形态同时通过' }],
    })

    const wrapper = mountPanel({})
    await wrapper.findComponent({ name: 'ElButton' }).trigger('click')
    await nextTick()
    await nextTick()

    expect(previewSkillWatch).toHaveBeenCalledWith('dragon-return')
    const text = wrapper.text()
    expect(text).toContain('龙头')
    expect(text).toContain('机器人')
    expect(text).toContain('未经过前向验证')
    expect(text).toContain('纸面候选·未验证')
  })

  it('shows accumulated leader survival from role history', async () => {
    previewSkillWatch.mockResolvedValue({ market_gate: { state: 'dragon', mode: '龙' } })
    getLeaderRoles.mockResolvedValue({
      slug: 'dragon-return',
      history: [],
      transitions: [],
      summary: {
        observations: 12,
        trade_days: 5,
        leader_survival: [
          {
            code: '600001',
            name: '测试龙',
            theme_name: '机器人',
            leader_days: 3,
            current_role: 'failed',
            still_leader: false,
          },
        ],
        warning_lead: { samples: 2, avg_days: 1.5, min_days: 1, max_days: 2 },
      },
    })

    const wrapper = mountPanel({})
    await wrapper.findComponent({ name: 'ElButton' }).trigger('click')
    await nextTick()
    await nextTick()
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('龙头存活')
    expect(text).toContain('3 日')
    expect(text).toContain('结构破坏')
    expect(text).toContain('走弱预警提前量')
  })

  it('keeps the scan result when role history cannot be read', async () => {
    previewSkillWatch.mockResolvedValue({
      market_gate: { state: 'dragon', mode: '龙', reason: '晋级率支持' },
    })
    getLeaderRoles.mockRejectedValue(new Error('留痕表不可读'))

    const wrapper = mountPanel({})
    await wrapper.findComponent({ name: 'ElButton' }).trigger('click')
    await nextTick()
    await nextTick()
    await nextTick()

    // 补充信息读不到，本次扫描结果仍要留在屏幕上
    expect(wrapper.text()).toContain('晋级率支持')
    expect(wrapper.text()).not.toContain('龙头存活')
  })
})
