import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import PaperRoleReviewPanel from './PaperRoleReviewPanel.vue'

function mountPanel(props: Record<string, unknown>) {
  return mount(PaperRoleReviewPanel, {
    props: {
      roleData: null,
      positions: [],
      ...props,
    },
    global: {
      plugins: [ElementPlus],
      // jsdom 无真实画布尺寸，ECharts 会炸；图逻辑另测 paperRoleTimeline
      stubs: {
        PaperRoleTimelineChart: {
          template: '<div class="role-timeline-stub" aria-label="角色演进图" />',
        },
      },
    },
  })
}

describe('PaperRoleReviewPanel', () => {
  it('shows empty state when no role history', () => {
    const wrapper = mountPanel({})
    expect(wrapper.text()).toContain('还没有龙头角色留痕')
  })

  it('renders timeline chart, survival, transitions and position role alerts', () => {
    const wrapper = mountPanel({
      positions: [{ code: '600001', name: '测试龙', layers: 2 }],
      roleData: {
        slug: 'dragon-return',
        history: [
          {
            code: '600001',
            name: '测试龙',
            role: 'leader',
            trade_date: '2026-08-05',
            observed_at: '2026-08-05T15:00:00',
            theme_name: '机器人',
          },
          {
            code: '600001',
            name: '测试龙',
            role: 'weakened',
            trade_date: '2026-08-07',
            observed_at: '2026-08-07T15:00:00',
            role_basis: '连板断档',
            theme_name: '机器人',
          },
        ],
        transitions: [
          {
            code: '600001',
            name: '测试龙',
            from_role: 'leader',
            to_role: 'weakened',
            to_at: '2026-08-07T15:00:00',
            basis: '连板断档',
          },
        ],
        summary: {
          observations: 12,
          trade_days: 5,
          leader_survival: [
            {
              code: '600001',
              name: '测试龙',
              theme_name: '机器人',
              leader_days: 3,
              current_role: 'weakened',
              still_leader: false,
            },
          ],
          warning_lead: { samples: 2, avg_days: 1.5, min_days: 1, max_days: 2 },
        },
      },
    })

    const text = wrapper.text()
    expect(text).toContain('角色演进图')
    expect(text).toContain('纵轴是角色档位')
    expect(text).toContain('持仓角色告警')
    expect(text).toContain('已判走弱仍在持仓')
    expect(text).toContain('龙头存活榜')
    expect(text).toContain('最近角色转移')
    expect(text).toContain('连板断档')
    expect(text).toContain('走弱预警提前量')
    expect(wrapper.findAll('.el-table').length).toBeGreaterThan(0)
  })
})
