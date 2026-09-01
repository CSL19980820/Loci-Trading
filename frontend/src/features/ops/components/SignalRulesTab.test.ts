import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/*
 * 规则面板的三件事：一行一条渲染、改完即时 PUT、失败回滚并报真实原因。
 * 接口全部打桩；契约见 shared/api/signalRules.ts（后端实现的是
 * GET /api/market/signals/rules、PUT /api/market/signals/rules/{id}）。
 */

const api = vi.hoisted(() => ({
  getSignalRules: vi.fn(),
  updateSignalRule: vi.fn(),
}))

const message = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))

vi.mock('@/shared/api/signalRules', () => api)
// element-plus 只换掉 ElMessage：<el-xxx> 在编译期就被 unplugin 直接 import 了，
// 整包 mock 会把 ElAlert / ElSwitch 一起抹掉，组件当场渲染不出来。
vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ElMessage: message,
}))

import SignalRulesTab from './SignalRulesTab.vue'

/** 形状对齐 signalRules.parseSignalRule 的产物（后端 rule_view 解析后的样子）。 */
function rule(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ma_golden_cross',
    label: '均线金叉',
    description: '快线上穿慢线',
    enabled: true,
    params: { fast: 5, slow: 20 },
    defaults: { fast: 5, slow: 20 },
    overrides: {},
    specs: [
      { key: 'fast', label: '快线', default: 5, min: 2, max: 60, unit: '日', integer: true },
      { key: 'slow', label: '慢线', default: 20, min: 3, max: 250, unit: '日', integer: true },
    ],
    repeatable: false,
    minBars: 30,
    ...overrides,
  }
}

const stubs = {
  SettingsPanel: { props: ['title', 'receipt', 'fill'], template: '<section><slot /></section>' },
  EmptyState: { props: ['description', 'reason'], template: '<div class="empty">{{ description }}</div>' },
  'el-alert': { props: ['title'], template: '<div class="alert">{{ title }}</div>' },
  'el-switch': {
    props: ['modelValue', 'disabled'],
    emits: ['update:modelValue'],
    template: '<button class="sw" :disabled="disabled" @click="$emit(\'update:modelValue\', !modelValue)"></button>',
  },
  'el-input-number': {
    props: ['modelValue', 'disabled'],
    emits: ['change'],
    template: '<input class="num" :value="modelValue" :disabled="disabled" @input="$emit(\'change\', Number($event.target.value))" />',
  },
  // 与 McpTab.test 同一口径：tooltip 只渲染触发内容，别把 popper 拖进 happy-dom
  'el-tooltip': { template: '<div><slot /></div>' },
  'el-button': {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
}

async function mountTab() {
  const wrapper = mount(SignalRulesTab, {
    global: { stubs, directives: { loading: {} } },
  })
  await (wrapper.vm as unknown as { load: () => Promise<void> }).load()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getSignalRules.mockResolvedValue([rule()])
  api.updateSignalRule.mockResolvedValue(null)
})

describe('SignalRulesTab', () => {
  it('一行一条：开关 + 中文名 + 口径 + 可调参数 + 恢复默认', async () => {
    const wrapper = await mountTab()

    expect(wrapper.findAll('.rule')).toHaveLength(1)
    expect(wrapper.find('.rule__label').text()).toBe('均线金叉')
    expect(wrapper.text()).toContain('快线上穿慢线')
    expect(wrapper.text()).toContain('至少 30 根K线')
    expect(wrapper.findAll('.num')).toHaveLength(2)
    expect(wrapper.text()).toContain('恢复默认')
  })

  it('没有可调参数的规则照实说，不编格子', async () => {
    api.getSignalRules.mockResolvedValue([
      rule({ id: 'macd_golden_cross', label: 'MACD 金叉', params: {}, defaults: {}, specs: [] }),
    ])
    const wrapper = await mountTab()

    expect(wrapper.findAll('.num')).toHaveLength(0)
    expect(wrapper.text()).toContain('无可调参数')
  })

  it('关开关即时 PUT', async () => {
    const wrapper = await mountTab()

    await wrapper.find('.sw').trigger('click')
    await flushPromises()

    expect(api.updateSignalRule).toHaveBeenCalledWith('ma_golden_cross', { enabled: false })
  })

  it('改参数即时 PUT，且带上整份 params', async () => {
    const wrapper = await mountTab()

    const input = wrapper.findAll('.num')[0]!
    await input.setValue('8')
    await flushPromises()

    expect(api.updateSignalRule).toHaveBeenCalledWith('ma_golden_cross', {
      params: { fast: 8, slow: 20 },
    })
  })

  it('PUT 失败：回滚 + 弹后端原话', async () => {
    api.updateSignalRule.mockRejectedValue(new Error('规则 ma_golden_cross 已被锁定'))
    const wrapper = await mountTab()

    await wrapper.find('.sw').trigger('click')
    await flushPromises()

    // 开关回到 true（乐观值被撤销）
    expect(wrapper.find('.rule').classes()).not.toContain('rule--off')
    expect(message.error).toHaveBeenCalled()
    expect(String(message.error.mock.calls[0]?.[0])).toContain('规则 ma_golden_cross 已被锁定')
  })

  it('恢复默认：参数没动时点不了，动过之后回填 defaults', async () => {
    api.getSignalRules.mockResolvedValue([
      rule({ params: { fast: 9, slow: 20 }, overrides: { fast: 9 } }),
    ])
    const wrapper = await mountTab()

    const restore = wrapper.findAll('.btn').at(-1)!
    expect(restore.attributes('disabled')).toBeUndefined()
    await restore.trigger('click')
    await flushPromises()

    expect(api.updateSignalRule).toHaveBeenCalledWith('ma_golden_cross', {
      params: { fast: 5, slow: 20 },
    })
  })

  it('后端没给 param_specs 时退回前端静态表，格子照样在', async () => {
    api.getSignalRules.mockResolvedValue([rule({ specs: [] })])
    const wrapper = await mountTab()

    expect(wrapper.findAll('.num')).toHaveLength(2)
    expect(wrapper.text()).toContain('快线')
    expect(wrapper.text()).toContain('慢线')
  })

  it('接口读不到：报错不留白，也不假装有规则', async () => {
    api.getSignalRules.mockRejectedValue(new Error('HTTP 404'))
    const wrapper = await mountTab()

    expect(wrapper.findAll('.rule')).toHaveLength(0)
    expect(wrapper.find('.alert').text()).toContain('HTTP 404')
  })
})
