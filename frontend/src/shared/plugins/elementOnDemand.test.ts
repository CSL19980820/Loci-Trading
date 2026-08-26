import { mount } from '@vue/test-utils'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { extname, join } from 'node:path'
import * as elementPlus from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import BasicTable from '@/shared/components/ui/BasicTable.vue'

/**
 * Element Plus 不再全量 `app.use`，改由 vite.config.ts 的
 * unplugin-vue-components + ElementPlusResolver 在编译期逐个 import。
 *
 * 这组测试守两件事：
 * 1. 管道真的通——组件与 `v-loading` 指令在**没有**任何全局注册的情况下也渲染得出来；
 * 2. 仓里出现的每个 `el-*` 标签都能落到 element-plus 的真实导出上，
 *    避免拼错或用了不存在的组件，只在用户点进那个页面时才白屏。
 */
describe('element-plus on-demand registration', () => {
  it('renders components and v-loading without any global app.use', async () => {
    // 注意：global.plugins 故意留空，不注册 ElementPlus。
    const wrapper = mount(BasicTable, {
      props: {
        loading: true,
        toolbarConfig: { refresh: true, zoom: true, custom: true },
        dataSource: [{ id: '1', code: '600519' }],
        columns: [{ prop: 'code', label: '代码' }],
      },
    })
    await nextTick()

    expect(wrapper.findComponent({ name: 'ElTable' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ElPagination' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ElButton' }).exists()).toBe(true)
    // v-loading 走的是 resolver 的 directive 分支，与组件分支是两条路，单独确认。
    expect(wrapper.html()).toContain('el-loading-mask')

    wrapper.unmount()
  })

  it('maps every el-* tag used in src to a real element-plus export', () => {
    const tags = new Set<string>()
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name)
        if (statSync(full).isDirectory()) {
          walk(full)
          continue
        }
        if (extname(full) !== '.vue') continue
        for (const match of readFileSync(full, 'utf8').matchAll(/<(el-[a-z0-9-]+)/g)) {
          tags.add(match[1])
        }
      }
    }
    walk(join(process.cwd(), 'src'))

    // 现状 55 个；给个下界，防止扫描逻辑哪天悄悄失灵后这条断言变成永远通过。
    expect(tags.size).toBeGreaterThan(40)

    const exports = elementPlus as unknown as Record<string, unknown>
    const unresolvable = [...tags]
      .map((tag) => tag.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join(''))
      .filter((name) => !(name in exports))

    expect(unresolvable).toEqual([])
  })
})
