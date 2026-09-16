import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * 顶栏纪律（用户截图②/③）：路由页正文顶上不再印一遍页面标题。
 * PageHeader 已下线；读数/操作/口径必须并进 PageToolbar / 筛选栏 / PageTabs / 表格工具栏。
 */
const PAGES = {
  'ledger/PoolView.vue': '候选池',
  'review/ReviewCenterView.vue': '复盘中心',
  'review/ReviewsView.vue': '复盘记录',
  'review/WinRateView.vue': '胜率统计',
  'ops/OpsView.vue': '设置',
  'market/PulseView.vue': '盘面',
  'strategy/ScreenHistoryView.vue': '选股',
  'review/InsightsView.vue': '体检',
  'auth/AccountView.vue': '账号',
} as const
/* Vite 会把 `new URL(x, import.meta.url)` 当静态资源改写，动态路径会被写成 undefined，
   所以这里直接按 vitest 的工作目录（frontend/）解析。 */
function readPage(rel: string): string {
  return readFileSync(resolve(process.cwd(), 'src/features', rel), 'utf8')
}

describe('路由页顶栏', () => {
  for (const rel of Object.keys(PAGES) as (keyof typeof PAGES)[]) {
    it(`${rel} 不再使用 PageHeader`, () => {
      const source = readPage(rel)
      expect(source).not.toContain('layout/PageHeader.vue')
      expect(source).not.toMatch(/<PageHeader[\s/>]/)
      expect(source).not.toContain('</PageHeader>')
    })

    it(`${rel} 不再把页面名当块级标题印出来`, () => {
      const source = readPage(rel)
      // 注释里可以解释「标题已删」，模板里不许再把页面名摆成标题或独立文本节点
      const template = source.slice(source.indexOf('<template>'))
      const withoutComments = template.replace(/<!--[\s\S]*?-->/g, '')
      const title = PAGES[rel]
      expect(withoutComments).not.toContain(`title="${title}"`)
      expect(withoutComments).not.toContain(`>${title}<`)
      expect(withoutComments).not.toMatch(new RegExp(`<h[1-3][^>]*>\\s*${title}`))
    })
  }

  it('候选池把三条横栏压成一条：表格不再另起工具栏', () => {
    const source = readPage('ledger/PoolView.vue')
    expect(source).not.toContain('toolbar-config')
    expect(source).not.toContain('toolbarButtons')
    // 读数、批量删除、主动作、口径 ⓘ 全在筛选行里
    const searchBar = source.slice(
      source.indexOf('<template #search>'),
      source.indexOf('<template #main>'),
    )
    expect(searchBar).toContain('HeaderStat label="精选"')
    expect(searchBar).toContain('<ListToolbar :config="listToolbar" />')
    expect(searchBar).toContain('记一条候选')
    expect(searchBar).toContain('PAGE_NOTE')
  })

  it('复盘记录把主动作并进表格自带的工具行', () => {
    const source = readPage('review/ReviewsView.vue')
    expect(source).toContain('<template #toolbarButtons>')
    expect(source).toContain('补记一笔')
  })

  it('复盘中心把预案条数挂到 Tab 徽标，不再另起 Sheet 标题', () => {
    const source = readPage('review/ReviewCenterView.vue')
    expect(source).toContain("badge: plans.value.length || undefined")
    expect(source).not.toContain('Sheet title=')
    expect(source).not.toContain('brief-title')
  })

  it('盘面/选股/设置/体检/账号走 PageToolbar，不再自绘重复标题条', () => {
    expect(readPage('market/PulseView.vue')).toContain('<PageToolbar')
    expect(readPage('strategy/ScreenHistoryView.vue')).toContain('<PageToolbar')
    expect(readPage('ops/OpsView.vue')).toContain('<PageToolbar')
    expect(readPage('review/InsightsView.vue')).toContain('<PageToolbar')
    expect(readPage('auth/AccountView.vue')).toContain('<PageToolbar')
    expect(readPage('ops/OpsView.vue')).not.toContain('>设置<')
  })

})
