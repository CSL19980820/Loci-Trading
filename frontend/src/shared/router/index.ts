import { createRouter, createWebHistory } from 'vue-router'

import { getSession } from '@/shared/api/palace'
import { brandTitle } from '@/shared/lib/brand'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'pulse', component: () => import('@/features/market/PulseView.vue'), meta: { title: '盘面' } },
    { path: '/ledger', name: 'ledger', component: () => import('@/features/ledger/DashboardView.vue'), meta: { title: '账本' } },
    // 旧总览入口：持仓已迁至账本
    { path: '/dashboard', redirect: '/ledger' },
    { path: '/journal', name: 'journal', component: () => import('@/features/ledger/JournalView.vue'), meta: { title: '交割单' } },
    { path: '/pool', name: 'pool', component: () => import('@/features/ledger/PoolView.vue'), meta: { title: '候选池' } },
    { path: '/data', name: 'data-query', component: () => import('@/features/market/DataQueryView.vue'), meta: { title: '数据查询' } },
    { path: '/reviews', name: 'reviews', component: () => import('@/features/review/ReviewCenterView.vue'), meta: { title: '复盘中心' } },
    { path: '/reviews/records', name: 'review-records', component: () => import('@/features/review/ReviewsView.vue'), meta: { title: '复盘记录' } },
    { path: '/quant', name: 'quant', component: () => import('@/features/strategy/QuantView.vue'), meta: { title: '工坊' } },
    { path: '/strategy-converter', name: 'strategy-converter', component: () => import('@/features/strategy/StrategyConverterView.vue'), meta: { title: '量化技能工坊' } },
    { path: '/winrate', name: 'winrate', component: () => import('@/features/review/WinRateView.vue'), meta: { title: '胜率统计' } },
    { path: '/insights', name: 'insights', component: () => import('@/features/review/InsightsView.vue'), meta: { title: '洞察' } },
    { path: '/screen-history', name: 'screen-history', component: () => import('@/features/strategy/ScreenHistoryView.vue'), meta: { title: '选股' } },
    // 旧独立市场入口 → 工坊「市场」Tab（?tab=installed 映射为 ?shelf=）
    {
      path: '/market',
      redirect: (to) => {
        const legacyTab = String(to.query.tab || '')
        const shelf =
          legacyTab === 'installed' || legacyTab === 'publish'
            ? legacyTab
            : typeof to.query.shelf === 'string'
              ? to.query.shelf
              : undefined
        return {
          path: '/quant',
          query: {
            tab: 'market',
            ...(shelf ? { shelf } : {}),
            ...(to.query.kind ? { kind: to.query.kind } : {}),
          },
        }
      },
    },
    { path: '/ops', name: 'ops', component: () => import('@/features/ops/OpsView.vue'), meta: { title: '运维' } },
    // 旧运维「技能包」入口 → 工坊市场·已装
    {
      path: '/ops/skills',
      redirect: { path: '/quant', query: { tab: 'market', shelf: 'installed', kind: 'skill' } },
    },
    { path: '/archive/:code', name: 'archive', component: () => import('@/features/ledger/ArchiveView.vue'), meta: { title: '档案' } },
    { path: '/login', name: 'login', component: () => import('@/features/ledger/LoginView.vue'), meta: { title: '登录', public: true } },
    {
      path: '/auth-unavailable',
      name: 'auth-unavailable',
      component: () => import('@/features/ledger/AuthUnavailableView.vue'),
      meta: { title: '认证服务不可用', public: true },
    },
    { path: '/peek', name: 'peek', component: () => import('@/features/market/PeekView.vue'), meta: { title: '行情', public: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  // 失败页 / 行情 Peek：禁止等会话。Peek 是独立小窗，boot-splash 挂载后即卸；
  // 若这里再 await getSession，导航未完成时主区只剩 #eef2f6 白方块。
  if (to.name === 'auth-unavailable' || to.name === 'peek') return true

  let session
  try {
    session = await getSession()
  } catch {
    return {
      name: 'auth-unavailable',
      query: { redirect: to.fullPath },
    }
  }
  if (to.meta.public === true) {
    return session.authenticated ? { name: 'pulse' } : true
  }
  return session.authenticated ? true : { name: 'login' }
})

router.afterEach((to) => {
  document.title = brandTitle(String(to.meta.title ?? ''))
})

export default router
