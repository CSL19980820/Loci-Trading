import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { QuoteRow, SignalItem } from '@/shared/api/marketStream'

/*
 * 整屏级回归：重构前收盘状态下，「已收盘，展示最近收盘数据；开盘后恢复实时推流」
 * 这一句在一屏里出现了 7 遍（跑马灯 ×2 + 指数区 + 四个榜单 + 信号流）。
 * 这个用例把「会话级声明全屏只准出现一次」钉成断言。
 */

const board = {
  status: ref<'connecting' | 'connected' | 'reconnecting' | 'offline'>('connected'),
  lastAsOf: ref('2026-08-28 15:00:03'),
  source: ref('snapshot'),
  sessionPhase: ref('closed'),
  isLive: ref(false),
  distribution: ref(null),
  quotesMap: shallowRef(new Map<string, QuoteRow>()),
  quotesList: shallowRef<QuoteRow[]>([]),
  indexRows: shallowRef<QuoteRow[]>([]),
  indexTrails: shallowRef(new Map<string, number[]>()),
  gainersRows: shallowRef<QuoteRow[]>([]),
  losersRows: shallowRef<QuoteRow[]>([]),
  turnoverRows: shallowRef<QuoteRow[]>([]),
  amountRows: shallowRef<QuoteRow[]>([]),
  signals: ref<SignalItem[]>([]),
  newSignalIds: ref(new Set<string>()),
  connect: vi.fn(),
  stopStream: vi.fn(),
}

vi.mock('../composables/useLiveBoard', () => ({
  useLiveBoard: () => board,
  // SignalStream 头部读它显示「N/80」，mock 少一个导出就是整屏渲染不出来
  SIGNAL_MAX_ITEMS: 80,
  SIGNAL_MAX_AGE_DAYS: 7,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ params: Object.create(null), query: Object.create(null) }),
}))

import LiveBoardView from '../LiveBoardView.vue'

function mountBoard() {
  return mount(LiveBoardView, {
    global: {
      stubs: {
        StockLink: { template: '<span>{{ name }}</span>', props: ['code', 'name', 'showCode'] },
      },
    },
  })
}

describe('LiveBoardView 收盘态', () => {
  // 顶栏的「暗色」开关读主题 store（大屏不再强改外观，得知道用户选了什么）
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('会话级声明全屏只出现一次', () => {
    const wrapper = mountBoard()
    const text = wrapper.text()

    // split 计数：整屏文本里这句话只准出现一次
    expect(text.split('已收盘·展示最近快照').length - 1).toBe(1)
    // 旧版那句长文案彻底下线
    expect(text).not.toContain('展示最近收盘数据')
    expect(text).not.toContain('开盘后恢复实时推流')
    wrapper.unmount()
  })

  it('无数据时指数带保留五个槽位并显示 —', () => {
    const wrapper = mountBoard()

    expect(wrapper.findAll('.idx')).toHaveLength(5)
    expect(wrapper.findAll('.idx__px').every((el) => el.text() === '—')).toBe(true)
    expect(wrapper.find('.index-bar--void').exists()).toBe(true)
    wrapper.unmount()
  })

  it('根节点带 page-fill 与 page-fill--flush 逃生舱，且无跑马灯空壳', () => {
    const wrapper = mountBoard()

    expect(wrapper.classes()).toContain('page-fill')
    expect(wrapper.classes()).toContain('page-fill--flush')
    expect(wrapper.find('.tape').exists()).toBe(false)
    wrapper.unmount()
  })

  it('四张榜单各自带识别色条，一眼可分', () => {
    const wrapper = mountBoard()

    expect(wrapper.find('.rank--up').exists()).toBe(true)
    expect(wrapper.find('.rank--down').exists()).toBe(true)
    expect(wrapper.find('.rank--info').exists()).toBe(true)
    expect(wrapper.find('.rank--warn').exists()).toBe(true)
    wrapper.unmount()
  })
})
