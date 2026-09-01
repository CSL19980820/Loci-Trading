/**
 * 工坊（/quant）首屏只挂当前 Tab 的回归测试。
 *
 * 背景：八个 Tab 里有六块面板原来是 v-show 常挂，首帧就得建六份 DOM，且
 * DataSourcePanel / JobsTab / MarketPanel / PaperQuantPanel 的 onMounted 各自拉数
 * ——落地工坊明显卡一下，而用户当次通常只看一个 Tab。
 *
 * 这里用「假面板」记挂载/卸载/load 流水（真面板一挂就发请求，挂没挂等价于有没有那波
 * 请求），钉死三件事：
 * 1. 首屏只挂当前 Tab 的面板，别的一个都不挂；
 * 2. 进过的 Tab 切走不卸载（保状态），只是 v-show 隐藏；
 * 3. 技能 / 研究台照旧离开就卸（它们带轮询，必须停）。
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getJobs: vi.fn(),
  getMarketCoverage: vi.fn(),
  getSkills: vi.fn(),
  getStrategies: vi.fn(),
  removeSkill: vi.fn(),
  syncMarket: vi.fn(),
}))

/**
 * 面板替身工厂：只记流水 + 画一个可查的空 div，不发任何请求。
 *
 * 工厂要在 `vi.mock` 的提升块里调用，那时取不到文件顶部的 import 绑定，所以 vue 只能
 * 在这里 `await import()`——vitest mock 提升的固有约束，不是随手写的动态导入。
 */
const lab = vi.hoisted(() => {
  const events: string[] = []
  async function stubPanel(name: string, opts: { exposeLoad?: boolean } = {}) {
    const { defineComponent, h, onUnmounted } = await import('vue')
    return defineComponent({
      name,
      inheritAttrs: false,
      setup(_props, { expose }) {
        events.push(`mount:${name}`)
        if (opts.exposeLoad) {
          expose({
            load: async (): Promise<void> => {
              events.push(`load:${name}`)
            },
          })
        }
        onUnmounted(() => events.push(`unmount:${name}`))
        return () => h('div', { 'data-testid': name })
      },
    })
  }
  return { events, stubPanel }
})

const route = reactive({ query: {} as Record<string, string | undefined> })
const router = { push: vi.fn(), replace: vi.fn() }

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => router,
}))

vi.mock('@/shared/api/quant', () => ({
  ...api,
  CapabilityUnavailableError: class CapabilityUnavailableError extends Error {},
}))

// `__esModule: true` 是给 defineAsyncComponent 看的：Vue 靠它认出「这是模块命名空间，
// 该取 default」，缺了它会把整个命名空间当组件用（vitest 工厂 mock 不自带这个标记）。
vi.mock('@/features/datasource/DataSourcePanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('DataSourcePanel'),
}))
vi.mock('@/features/marketplace/components/MarketPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('MarketPanel'),
}))
vi.mock('@/features/ops/components/JobsTab.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('JobsTab', { exposeLoad: true }),
}))
vi.mock('@/features/ops/components/PaperQuantPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('PaperQuantPanel'),
}))
vi.mock('@/features/research/ResearchPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('ResearchPanel'),
}))
vi.mock('../components/QuantBacktestPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('QuantBacktestPanel'),
}))
vi.mock('../components/QuantSkillsPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('QuantSkillsPanel'),
}))
vi.mock('../components/QuantStrategiesPanel.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('QuantStrategiesPanel'),
}))
vi.mock('../components/ScreenSkillBundleImportDialog.vue', async () => ({
  __esModule: true,
  default: await lab.stubPanel('BundleImportDialog'),
}))

import QuantView from '../QuantView.vue'

/** 除「战法」外的七块面板：默认 Tab 的首屏一块都不该挂。 */
const LAZY_PANELS = [
  'QuantSkillsPanel',
  'DataSourcePanel',
  'JobsTab',
  'MarketPanel',
  'QuantBacktestPanel',
  'ResearchPanel',
  'PaperQuantPanel',
]

const MOUNT_PREFIX = 'mount:'

function mountedPanels(): string[] {
  return lab.events
    .filter((row) => row.startsWith(MOUNT_PREFIX))
    .map((row) => row.slice(MOUNT_PREFIX.length))
}

function mountWorkshop(): VueWrapper {
  const pending = new Promise<never>(() => {})
  api.getStrategies.mockReturnValue(pending)
  api.getSkills.mockReturnValue(pending)
  api.getMarketCoverage.mockReturnValue(pending)
  api.getJobs.mockReturnValue(pending)
  return mount(QuantView, { global: { stubs: { PageBusy: true } } })
}

/** 切 Tab 走 URL（工坊自己 watch query）；异步面板还要等一次 flush 才落地。 */
async function goTab(tab: string | undefined): Promise<void> {
  route.query.tab = tab
  await flushPromises()
}

let wrapper: VueWrapper | null = null

describe('QuantView 懒挂 Tab', () => {
  beforeEach(() => {
    route.query = {}
    lab.events.length = 0
    vi.clearAllMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('首屏只挂当前 Tab 的面板', async () => {
    wrapper = mountWorkshop()
    await flushPromises()

    expect(mountedPanels()).toContain('QuantStrategiesPanel')
    for (const panel of LAZY_PANELS) {
      expect(mountedPanels()).not.toContain(panel)
    }
  })

  it('深链进研究台时不顺手把战法/回测挂上', async () => {
    route.query.tab = 'research'
    wrapper = mountWorkshop()
    await flushPromises()

    expect(mountedPanels()).toContain('ResearchPanel')
    expect(mountedPanels()).not.toContain('QuantStrategiesPanel')
    expect(mountedPanels()).not.toContain('QuantBacktestPanel')
  })

  it('进过的 Tab 切走只隐藏不卸载，回来不重挂', async () => {
    wrapper = mountWorkshop()
    await flushPromises()

    await goTab('market')
    expect(mountedPanels()).toContain('MarketPanel')

    await goTab(undefined)
    expect(lab.events).not.toContain('unmount:MarketPanel')
    expect(wrapper.find('[data-testid="MarketPanel"]').exists()).toBe(true)
    // happy-dom 下 isVisible() 读不出继承的 display，直接看 v-show 写的行内样式
    expect(wrapper.find('.market-pane').attributes('style')).toContain('display: none')

    await goTab('market')
    expect(mountedPanels().filter((name) => name === 'MarketPanel')).toHaveLength(1)
    expect(wrapper.find('.market-pane').attributes('style') ?? '').not.toContain('display: none')
  })

  it('技能与研究台离开 Tab 仍然整块卸掉（轮询必须停）', async () => {
    wrapper = mountWorkshop()
    await flushPromises()

    await goTab('skills')
    await goTab('research')
    expect(lab.events).toContain('unmount:QuantSkillsPanel')

    await goTab(undefined)
    expect(lab.events).toContain('unmount:ResearchPanel')
  })

  it('定时 Tab 首次进入不重复拉，回访才补刷一次', async () => {
    wrapper = mountWorkshop()
    await flushPromises()

    await goTab('jobs')
    expect(mountedPanels()).toContain('JobsTab')
    // 首次挂载是 JobsTab 自己的 onMounted 在拉，父级不该再打一枪
    expect(lab.events).not.toContain('load:JobsTab')

    await goTab(undefined)
    await goTab('jobs')
    expect(lab.events.filter((row) => row === 'load:JobsTab')).toHaveLength(1)
  })
})
