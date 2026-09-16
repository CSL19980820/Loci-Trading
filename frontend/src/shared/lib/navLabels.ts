import type { Component } from 'vue'

/**
 * 导航术语的单一来源：路由 `meta.title`、侧栏、底栏三处都从这里取值，
 * 同一个页面不再各处各起一个名字。
 *
 * - key 即路由 `name`（已有代码按 name 跳转，不可改）
 * - `title` 是全称，进 `meta.title` 与页内标题
 * - `short` 是侧栏/底栏窄位用的短名；不配 `short` 的页面不挂导航入口
 */
type NavEntry = { readonly path: string; readonly title: string; readonly short?: string }

export const NAV_LABELS = {
  pulse: { path: '/', title: '盘面', short: '盘面' },
  live: { path: '/live', title: '实时大屏', short: '大屏' },
  pool: { path: '/pool', title: '候选池', short: '候选池' },
  agents: { path: '/agents', title: '股票智能体', short: '智能体' },
  'agent-detail': { path: '/agents/:id', title: '智能体工作室' },
  reviews: { path: '/reviews', title: '复盘中心', short: '复盘' },
  'review-records': { path: '/reviews/records', title: '复盘记录', short: '记录' },
  winrate: { path: '/winrate', title: '胜率统计', short: '胜率' },
  'screen-history': { path: '/screen-history', title: '选股', short: '选股' },
  insights: { path: '/insights', title: '数据体检', short: '体检' },
  quant: { path: '/quant', title: '工坊', short: '工坊' },
  'data-query': { path: '/data', title: '行情', short: '行情' },
  'strategy-converter': { path: '/strategy-converter', title: '策稿台', short: '策稿' },
  ops: { path: '/ops', title: '设置', short: '设置' },
  archive: { path: '/archive/:code', title: '档案', short: '档案' },
  login: { path: '/login', title: '登录' },
  'auth-unavailable': { path: '/auth-unavailable', title: '认证服务暂不可用' },
  account: { path: '/account', title: '账号', short: '账号' },
  peek: { path: '/peek', title: '行情速览' },
  admin: { path: '/admin', title: '管理后台', short: '管理' },
} as const satisfies Record<string, NavEntry>

export type NavKey = keyof typeof NAV_LABELS

/** 只有配了 `short` 的页面能进侧栏/底栏 */
export type NavMenuKey = {
  [K in NavKey]: (typeof NAV_LABELS)[K] extends { short: string } ? K : never
}[NavKey]

/** 导航里允许出现的短名字面量；写一个表外的名字会在这里被类型挡回 */
export type NavShort = (typeof NAV_LABELS)[NavMenuKey]['short']

export type NavMenuItem = { path: string; label: NavShort; icon: Component }

export function navTitle(key: NavKey): string {
  return NAV_LABELS[key].title
}

/** 路由记录的 path / name / meta.title 一次取齐，避免路由表与本表各写一遍再走样 */
export function navRoute(
  key: NavKey,
  meta?: { public?: true },
): { path: string; name: NavKey; meta: { title: string; public?: true } } {
  return {
    path: NAV_LABELS[key].path,
    name: key,
    meta: { title: NAV_LABELS[key].title, ...meta },
  }
}

export function navMenuItem(key: NavMenuKey, icon: Component): NavMenuItem {
  return { path: NAV_LABELS[key].path, label: NAV_LABELS[key].short, icon }
}
