import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SessionRuler from './SessionRuler.vue'

describe('SessionRuler', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('盘中：画刻针，轨道按时间填充', () => {
    vi.setSystemTime(new Date(2026, 7, 27, 10, 42, 0))
    const wrapper = mount(SessionRuler, { props: { isTradingDay: true } })
    expect(wrapper.find('.ruler__needle').exists()).toBe(true)
    expect(wrapper.find('.ruler').classes()).not.toContain('is-dim')
    expect(wrapper.find('.ruler__status').text()).toBe('早盘 · 距午休 48 分')
    // 断口（09:25–09:30 与午休）不画轨：只剩 4 段
    expect(wrapper.findAll('.ruler__seg')).toHaveLength(4)
    const morning = wrapper.findAll('.ruler__seg')[1]
    const fill = morning.find('.ruler__fill').attributes('style') || ''
    expect(fill).toMatch(/width: 60%/)
    wrapper.unmount()
  })

  it('收盘后：整轨降级、无刻针、右端报距下次开盘', () => {
    vi.setSystemTime(new Date(2026, 7, 27, 15, 1, 0))
    const wrapper = mount(SessionRuler, { props: { isTradingDay: true } })
    expect(wrapper.find('.ruler__needle').exists()).toBe(false)
    expect(wrapper.find('.ruler').classes()).toContain('is-dim')
    expect(wrapper.find('.ruler__status').text()).toContain('已收盘 · 距下次开盘')
    wrapper.unmount()
  })

  it('休市日：不画刻针，报休市', () => {
    vi.setSystemTime(new Date(2026, 7, 29, 10, 0, 0))
    const wrapper = mount(SessionRuler, { props: { isTradingDay: false } })
    expect(wrapper.find('.ruler__needle').exists()).toBe(false)
    expect(wrapper.find('.ruler__status').text()).toContain('休市')
    wrapper.unmount()
  })

  it('四个刻度按真实时段比例落位', () => {
    vi.setSystemTime(new Date(2026, 7, 27, 10, 0, 0))
    const wrapper = mount(SessionRuler, { props: { isTradingDay: true } })
    const ticks = wrapper.findAll('.ruler__tick')
    expect(ticks.map((t) => t.text())).toEqual(['09:30', '11:30', '13:00', '15:00'])
    // 09:30 → (570-555)/345 ≈ 4.35%；15:00 → 100%
    expect(ticks[0].attributes('style')).toMatch(/left: 4\.34/)
    expect(ticks[3].attributes('style')).toMatch(/left: 100%/)
    expect(ticks[3].classes()).toContain('is-last')
    wrapper.unmount()
  })

  it('卸载时清掉定时器（不留悬挂 tick）', () => {
    vi.setSystemTime(new Date(2026, 7, 27, 10, 0, 0))
    const clear = vi.spyOn(globalThis, 'clearInterval')
    const wrapper = mount(SessionRuler, { props: { isTradingDay: true } })
    const before = vi.getTimerCount()
    expect(before).toBeGreaterThan(0)
    wrapper.unmount()
    expect(clear).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    clear.mockRestore()
  })

  it('时间往前走 30s 后刻针跟着动', async () => {
    vi.setSystemTime(new Date(2026, 7, 27, 10, 0, 0))
    const wrapper = mount(SessionRuler, { props: { isTradingDay: true } })
    const first = wrapper.find('.ruler__needle').attributes('style')
    vi.setSystemTime(new Date(2026, 7, 27, 10, 30, 0))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(wrapper.find('.ruler__needle').attributes('style')).not.toBe(first)
    wrapper.unmount()
  })
})
