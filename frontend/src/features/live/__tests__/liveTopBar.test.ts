import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import LiveTopBar from '../components/LiveTopBar.vue'

/*
 * 顶栏中部的时段小字与右侧的会话胶囊都出自 describeSession。
 *
 * 线上实测（loci-verify 容器，收盘时段）顶栏读出来是：
 *   「盯盘大屏 | 已收盘 19:07:59 | ● 已收盘·展示最近快照 」
 * 同一个词在半行字里出现两遍。本模块的规矩是「会话级声明全屏只出现一次」，
 * 那就不能靠人眼自觉——这里钉住。
 */
const stubs = { 'el-button': { template: '<button><slot /></button>' } }

function mountBar(over: Record<string, unknown> = {}) {
  return mount(LiveTopBar, {
    props: {
      status: 'connected' as const,
      asOf: '2026-08-29 15:00:00',
      sessionPhase: 'closed',
      isLive: false,
      ...over,
    },
    global: { stubs },
  })
}

describe('LiveTopBar 会话文案不重复', () => {
  it('收盘时胶囊已含「已收盘」，时段小字让位', () => {
    const wrapper = mountBar()
    const text = wrapper.text()

    expect(text).toContain('已收盘·展示最近快照')
    // 关键：整条顶栏里「已收盘」只出现一次
    expect(text.split('已收盘').length - 1).toBe(1)
    expect(wrapper.find('.topbar__phase').exists()).toBe(false)
  })

  it('交易时段两句不重叠，时段小字照常显示', () => {
    const wrapper = mountBar({ sessionPhase: 'morning', isLive: true })

    expect(wrapper.find('.topbar__phase').text()).toBe('早盘交易')
    expect(wrapper.text()).toContain('实时推流中')
  })

  it('数据源停更时报数据源，且不与时段小字重复', () => {
    const wrapper = mountBar({ sessionPhase: 'morning', isLive: true, dataStale: true })
    const text = wrapper.text()

    expect(text).toContain('数据源暂无更新·链路正常')
    expect(text).not.toContain('连接中断')
    expect(wrapper.find('.topbar__phase').text()).toBe('早盘交易')
  })
})
