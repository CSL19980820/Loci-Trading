import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, shallowRef, triggerRef } from 'vue'
import HeatStrip from '../components/HeatStrip.vue'
import IndexBar from '../components/IndexBar.vue'
import LiveEmptyState from '../components/LiveEmptyState.vue'
import LiveTopBar from '../components/LiveTopBar.vue'
import RankColumn from '../components/RankColumn.vue'
import SignalStream from '../components/SignalStream.vue'
import TickerTape from '../components/TickerTape.vue'
import type { QuoteRow, SignalItem } from '@/shared/api/marketStream'
import { describeSession, phaseLabel } from '../lib/sessionCopy'

const stubs = {
  StockLink: {
    template: '<span class="stub-stock-link">{{ name }}</span>',
    props: ['code', 'name', 'showCode'],
  },
}

function quote(patch: Partial<QuoteRow> & { code: string }): QuoteRow {
  return {
    name: patch.code,
    price: 10,
    prevClose: 10,
    change: 0,
    pct: 0,
    volume: 0,
    amount: 0,
    turnover: 0,
    amplitude: 0,
    speed: 0,
    high: 10,
    low: 10,
    open: 10,
    staleMs: 0,
    ...patch,
  }
}

describe('IndexBar', () => {
  it('无数据时仍渲染全部槽位，数值位显示 —，不塌成空态卡', () => {
    const wrapper = mount(IndexBar, { props: { rows: [] } })

    const cells = wrapper.findAll('.idx')
    expect(cells).toHaveLength(5)
    // 名称槽位恒定：位置不因为缺数据而变
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('深证成指')
    expect(wrapper.text()).toContain('创业板指')
    // 每个单元的点位 / 涨跌点数 / 涨跌幅三处都得是占位符
    expect(wrapper.findAll('.idx__px').every((el) => el.text() === '—')).toBe(true)
    expect(wrapper.findAll('.idx__chg').every((el) => el.text() === '—')).toBe(true)
    expect(wrapper.findAll('.idx__pct').every((el) => el.text() === '—')).toBe(true)
    // 整条带降透明度，而不是被替换成大空态
    expect(wrapper.find('.index-bar--void').exists()).toBe(true)
    expect(wrapper.findComponent(LiveEmptyState).exists()).toBe(false)
  })

  it('有行情时按槽位填数并给出涨跌语义色', () => {
    const wrapper = mount(IndexBar, {
      props: {
        rows: [
          quote({
            code: '000001',
            name: '上证指数',
            price: 3882.5,
            prevClose: 3870,
            change: 12.5,
            pct: 0.32,
          }),
          quote({
            code: '399006',
            name: '创业板指',
            price: 2100,
            prevClose: 2120,
            change: -20,
            pct: -0.94,
          }),
        ],
        trails: new Map([['000001', [3870, 3875, 3882.5]]]),
      },
    })

    expect(wrapper.find('.index-bar--void').exists()).toBe(false)
    expect(wrapper.text()).toContain('3882.50')
    expect(wrapper.text()).toContain('+0.32%')
    expect(wrapper.text()).toContain('-0.94%')
    expect(wrapper.findAll('.idx--up').length).toBe(1)
    expect(wrapper.findAll('.idx--down').length).toBe(1)
    // 有点列才画折线，没有的槽位画一条平线，绝不造假走势
    expect(wrapper.findAll('.spark__line')).toHaveLength(1)
    expect(wrapper.findAll('.spark__void')).toHaveLength(4)
  })

  it('点列原地追加后 sparkline 仍重画，不定格在第一帧', async () => {
    // 复刻 useLiveBoard 的真实写法：点列原地 push + triggerRef，指数行换新引用。
    // IndexBar.cells 里那句 `[...trail]` 一旦被「优化」掉，这条就红。
    const trails = shallowRef(new Map<string, number[]>([['000001', [3870, 3875]]]))
    const rows = shallowRef<QuoteRow[]>([
      quote({ code: '000001', name: '上证指数', price: 3875, prevClose: 3870, pct: 0.13 }),
    ])
    const host = mount(
      defineComponent({
        setup() {
          return () => h(IndexBar, { rows: rows.value, trails: trails.value })
        },
      }),
    )
    const before = host.find('.spark__line').attributes('points')

    trails.value.get('000001')?.push(3900)
    triggerRef(trails)
    rows.value = [
      quote({ code: '000001', name: '上证指数', price: 3900, prevClose: 3870, pct: 0.78 }),
    ]
    await host.vm.$nextTick()

    expect(host.find('.spark__line').attributes('points')).not.toBe(before)
  })
})

describe('HeatStrip', () => {
  it('无数据时压成一条 hairline，不画 11 个空盒子', () => {
    const wrapper = mount(HeatStrip, { props: { rows: [] } })

    expect(wrapper.find('.heat__bar--void').exists()).toBe(true)
    expect(wrapper.findAll('.heat__seg')).toHaveLength(0)
    // 11 档刻度槽位保留，数值位是占位符
    expect(wrapper.findAll('.heat__tick')).toHaveLength(11)
    expect(wrapper.findAll('.heat__tick-count').every((el) => el.text() === '—')).toBe(true)
    expect(wrapper.text()).toContain('涨 —')
  })

  it('有分布时按数量占比铺 stacked bar 并给出三色读数', () => {
    const wrapper = mount(HeatStrip, {
      props: {
        rows: [
          quote({ code: 'A', pct: 10 }),
          quote({ code: 'B', pct: 2 }),
          quote({ code: 'C', pct: -4 }),
          quote({ code: 'D', pct: 0 }),
        ],
      },
    })

    expect(wrapper.find('.heat__bar--void').exists()).toBe(false)
    // 只有 count>0 的档进条：涨停 / +1 / -3 / 平 共 4 段
    expect(wrapper.findAll('.heat__seg')).toHaveLength(4)
    expect(wrapper.text()).toContain('涨 2')
    expect(wrapper.text()).toContain('平 1')
    expect(wrapper.text()).toContain('跌 1')
  })
})

describe('RankColumn', () => {
  it('列头带识别色条，行给出序号/名称/代码/数值', () => {
    const wrapper = mount(RankColumn, {
      props: {
        title: '涨幅榜',
        rows: [quote({ code: '600519', name: '贵州茅台', price: 1800.5, pct: 3.25 })],
        valueType: 'pct',
        accent: 'up',
      },
      global: { stubs },
    })

    expect(wrapper.find('.rank--up .rank__mark').exists()).toBe(true)
    expect(wrapper.find('.rank__idx').text()).toBe('1')
    expect(wrapper.text()).toContain('贵州茅台')
    expect(wrapper.text()).toContain('600519')
    expect(wrapper.find('.rank__val').text()).toBe('+3.25%')
    expect(wrapper.find('.rank__val').classes()).toContain('live-tone-up')
  })

  it('换手率/成交额不着涨跌色（D1：红绿只属于价格）', () => {
    const turnover = mount(RankColumn, {
      props: {
        title: '换手率榜',
        rows: [quote({ code: '000002', name: '万科A', turnover: 12.5, pct: -3 })],
        valueType: 'turnover',
        accent: 'info',
      },
      global: { stubs },
    })
    expect(turnover.find('.rank__val').text()).toBe('12.50%')
    expect(turnover.find('.rank__val').classes()).toContain('rank__val--plain')

    const amount = mount(RankColumn, {
      props: {
        title: '成交额榜',
        rows: [quote({ code: '000003', name: '某股', amount: 3.2e8, pct: 5 })],
        valueType: 'amount',
        accent: 'warn',
      },
      global: { stubs },
    })
    expect(amount.find('.rank__val').text()).toBe('3.20亿')
    expect(amount.find('.rank__val').classes()).not.toContain('live-tone-up')
  })

  it('空态是一行 ≤8 字短语，不复述会话级文案', () => {
    const wrapper = mount(RankColumn, {
      props: { title: '涨幅榜', rows: [], accent: 'up', emptyHint: '待开盘', status: 'connected' },
      global: { stubs },
    })

    expect(wrapper.findComponent(LiveEmptyState).exists()).toBe(true)
    expect(wrapper.text()).toContain('待开盘')
    expect(wrapper.text()).not.toContain('已收盘')
    expect(wrapper.text()).not.toContain('展示最近快照')
  })
})

describe('SignalStream', () => {
  it('渲染信号行，且头部不再出现红字「盘中信号未定稿」', () => {
    const signals: SignalItem[] = [
      {
        id: 's1',
        code: '600519',
        name: '贵州茅台',
        strategy: 'breakthrough',
        strategyName: '放量突破',
        title: '突破20日线',
        detail: '量比>2.5',
        direction: 'long',
        strength: 0.85,
        price: 1800.5,
        pct: 3.25,
        provisional: true,
        triggeredAt: '2026-08-27T10:15:30',
      },
    ]

    const wrapper = mount(SignalStream, {
      props: { signals, newSignalIds: new Set(['s1']) },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('实时策略信号')
    expect(wrapper.text()).toContain('放量突破')
    expect(wrapper.text()).toContain('1800.50')
    expect(wrapper.text()).toContain('买入')
    // 免责声明已并入底部状态栏，这里不得再挂红字
    expect(wrapper.text()).not.toContain('盘中信号未定稿')
  })

  it('空态只说「无信号」', () => {
    const wrapper = mount(SignalStream, {
      props: { signals: [], newSignalIds: new Set<string>(), status: 'connected' },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('无信号')
    expect(wrapper.text()).not.toContain('展示最近快照')
  })
})

describe('TickerTape', () => {
  it('无数据时整条不渲染，绝不平铺两遍空文案', () => {
    const wrapper = mount(TickerTape, { props: { rows: [] }, global: { stubs } })

    expect(wrapper.find('.tape').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('有数据时两份副本首尾相接，价格热更新不重建结构', async () => {
    const rows = [
      quote({ code: '000001', name: '平安银行', price: 12, prevClose: 11.5, pct: 4.35 }),
    ]
    const wrapper = mount(TickerTape, { props: { rows }, global: { stubs } })

    expect(wrapper.findAll('.tape__group')).toHaveLength(2)
    expect(wrapper.text()).toContain('12.00')

    await wrapper.setProps({ rows: [{ ...rows[0], price: 12.5, pct: 8.7 }] })
    expect(wrapper.findAll('.tape__group')).toHaveLength(2)
    expect(wrapper.text()).toContain('12.50')
    expect(wrapper.text()).toContain('+8.70%')
  })
})

describe('LiveEmptyState', () => {
  it('默认极窄：只有一行短语，没有会话级长文案', () => {
    const wrapper = mount(LiveEmptyState, { props: { hint: '无信号', status: 'connected' } })

    expect(wrapper.find('.live-empty__text').text()).toBe('无信号')
    expect(wrapper.find('.live-empty--verbose').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('开盘后恢复实时推流')
  })

  it('断线时短语切成「连接中断」并转为 warn 色，仍是一行', () => {
    const wrapper = mount(LiveEmptyState, { props: { hint: '待开盘', status: 'offline' } })

    expect(wrapper.text()).toBe('连接中断')
    expect(wrapper.find('.live-empty--warn').exists()).toBe(true)
  })

  it('verbose 是唯一能吐出会话级声明的开关', () => {
    const wrapper = mount(LiveEmptyState, {
      props: { verbose: true, status: 'connected', isLive: false, sessionPhase: 'closed' },
    })

    expect(wrapper.text()).toContain('已收盘·展示最近快照')
  })
})

describe('LiveTopBar 时钟与时段', () => {
  it('时钟走本机秒针，不再显示（会冻住的）快照时间', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 7, 31, 13, 45, 7))
    const wrapper = mount(LiveTopBar, {
      props: {
        status: 'connected' as const,
        // 快照停在 12:00:02（午休那一帧）——时钟**不许**跟着停在这里
        asOf: '2026-08-31 12:00:02',
        sessionPhase: 'afternoon',
        isLive: true,
      },
      global: { stubs: { 'el-button': true, 'el-tooltip': true } },
    })

    expect(wrapper.find('.topbar__clock').text()).toBe('13:45:07')
    vi.advanceTimersByTime(2000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.topbar__clock').text()).toBe('13:45:09')
    expect(wrapper.text()).not.toContain('12:00:02')
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('落后超过 10s 时在时钟旁标出延迟', () => {
    const wrapper = mount(LiveTopBar, {
      props: {
        status: 'connected' as const,
        asOf: '2026-08-31 13:45:00',
        sessionPhase: 'afternoon',
        isLive: true,
        staleMs: 42_000,
      },
      global: { stubs: { 'el-button': true, 'el-tooltip': true } },
    })
    expect(wrapper.find('.topbar__lag').text()).toBe('延迟 42s')
    wrapper.unmount()
  })
})

describe('describeSession 时段文案', () => {
  it('午休说午休，不说已收盘（12:00 顶着「已收盘」正是那张截图的病灶）', () => {
    const noon = describeSession('connected', false, 'noon_break')
    expect(noon.phase).toBe('午间休市')
    expect(noon.text).toContain('午间休市')
    expect(noon.text).not.toContain('已收盘')
  })

  it('盘中相位全部有中文标签，绝不漏机器码', () => {
    for (const phase of ['pre_open', 'pre_market', 'morning', 'noon_break', 'afternoon', 'closing_auction', 'closed']) {
      expect(phaseLabel(phase)).not.toMatch(/[a-z_]{3,}/)
    }
  })

  it('数据源报错时说数据源，不赖到连接头上', () => {
    const broken = describeSession('connected', true, 'morning', false, '东财整表失败')
    expect(broken.tone).toBe('warn')
    expect(broken.text).toContain('数据源')
  })
})
