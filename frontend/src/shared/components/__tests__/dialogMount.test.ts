import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import AkshareBatchProbeDialog from '@/features/datasource/components/AkshareBatchProbeDialog.vue'
import SourceDetailDrawer from '@/features/datasource/components/SourceDetailDrawer.vue'
import AssistantAgentThread from '@/features/ai/components/AssistantAgentThread.vue'
import PackTab from '@/features/ops/components/PackTab.vue'

/*
 * 「弹层能独立挂起来」冒烟。
 *
 * 为什么单独写这一份：对话框 / 抽屉默认不渲染，模板里的错要等用户点开才炸。
 * 路由级冒烟（`e2e/runtime-smoke.mjs`）覆盖了大部分，但少数弹层要有数据、有权限、
 * 或藏在非默认 Tab 里，脚本点不到。而 2026-08 有一次并行改动把 A 文件的 template
 * 写进了 B 文件——那类事故的兜底必须是**真的把组件挂起来跑一遍模板**。
 *
 * 关键手法：把 `el-dialog` / `el-drawer` 换成透传 slot 的壳。
 * happy-dom 驱不动 EP 的 transition + teleport，不换壳的话弹层 body 根本不渲染，
 * 断言「渲染出了自己的东西」就永远落空——那不是组件的问题，是宿主环境的问题。
 */

const SHELL = {
  template: '<div class="test-shell"><slot name="header" /><slot /><slot name="footer" /></div>',
}
const STUBS = { 'el-dialog': SHELL, 'el-drawer': SHELL }

/** EP 首次打开要过两轮 tick */
async function settle(): Promise<void> {
  await nextTick()
  await flushPromises()
  await nextTick()
}

vi.mock('@/shared/api/quant', async (importOriginal) => {
const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    getSharePackStatus: vi.fn().mockResolvedValue({
      version: 'v1.0.0',
      released_at: '2026-08-28',
      summary: '',
      can_pack: false,
      reason: '本机没有编译产物',
      bundle_root: null,
      runtime_bytes: 0,
      options: [],
  }),
  }
})

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('弹层组件能独立挂载（防跨文件串写）', () => {
  it('SourceDetailDrawer 渲染的是数据源详情抽屉', async () => {
    const wrapper = mount(SourceDetailDrawer, {
      props: {
        modelValue: true,
        // 抽屉头显示的是 row.label / row.id / row.baseUrl，不是 name
        row: {
          id: 'akshare',
          label: 'AkShare 数据源',
          baseUrl: 'https://akshare.example',
   masterEnabled: true,
        interfaceOnly: false,
        lanes: [],
          tools: [],
        } as never,
      busyKey: '',
      },
      global: { stubs: STUBS },
    })
    await settle()
  expect(wrapper.html()).toContain('AkShare 数据源')
 wrapper.unmount()
  })

  it('AkshareBatchProbeDialog 渲染的是批量探测进度', async () => {
    const wrapper = mount(AkshareBatchProbeDialog, {
   props: {
     modelValue: true,
 busy: true,
        progress: { done: 3, total: 10, ok: 2, failed: 1, skipped: 0 },
   results: [],
      },
      global: { stubs: STUBS },
})
    await settle()
    // done/total = 3/10 → 30%
    expect(wrapper.html()).toMatch(/30|3\s*\/\s*10/)
    wrapper.unmount()
  })

  it('AssistantAgentThread 渲染的是子进程时间线', async () => {
    const wrapper = mount(AssistantAgentThread, {
      props: {
        open: true,
      agent: {
          id: 'a1',
name: '选股复核',
          status: 'running',
          steps: [],
     summary: '正在比对候选',
        } as never,
      },
      global: { stubs: STUBS },
    })
    await settle()
    // 标题走 agentDisplayName(agent)，进度走 agent.progress
    expect(wrapper.html()).toMatch(/选股复核|42%/)
    wrapper.unmount()
  })

  /*
   * PackTab 是那次串写的**真实受害者**（template 被写成了 McpToolListDrawer 的）。
   * 这一条既验它能挂起来，也验它挂起来的是「一键打包」而不是别人的模板。
   */
  it('PackTab 渲染的是一键打包面板，不是别人的模板', async () => {
    const wrapper = mount(PackTab, { global: { stubs: STUBS } })
    await settle()
    const html = wrapper.html()
    expect(html).toMatch(/打包|封箱|编译/)
    expect(html).not.toMatch(/MCP 工具清单/)
    wrapper.unmount()
  })
})
