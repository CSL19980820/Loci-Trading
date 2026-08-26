import { createRouter, createWebHistory } from 'vue-router'

import { getSession } from '@/shared/api/palace'
import { brandTitle } from '@/shared/lib/brand'
import { navRoute } from '@/shared/lib/navLabels'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { ...navRoute('pulse'), component: () => import('@/features/market/PulseView.vue') },
    { ...navRoute('pool'), component: () => import('@/features/ledger/PoolView.vue') },
    { ...navRoute('data-query'), component: () => import('@/features/market/DataQueryView.vue') },
    { ...navRoute('reviews'), component: () => import('@/features/review/ReviewCenterView.vue') },
    { ...navRoute('review-records'), component: () => import('@/features/review/ReviewsView.vue') },
    { ...navRoute('quant'), component: () => import('@/features/strategy/QuantView.vue') },
    {
      ...navRoute('strategy-converter'),
      component: () => import('@/features/strategy/StrategyConverterView.vue'),
    },
    { ...navRoute('winrate'), component: () => import('@/features/review/WinRateView.vue') },
    { ...navRoute('insights'), component: () => import('@/features/review/InsightsView.vue') },
    {
      ...navRoute('screen-history'),
      component: () => import('@/features/strategy/ScreenHistoryView.vue'),
    },
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
    { ...navRoute('ops'), component: () => import('@/features/ops/OpsView.vue') },
    // 旧运维「技能包」入口 → 工坊市场·已装
    {
      path: '/ops/skills',
      redirect: { path: '/quant', query: { tab: 'market', shelf: 'installed', kind: 'skill' } },
    },
    { ...navRoute('archive'), component: () => import('@/features/ledger/ArchiveView.vue') },
    {
      ...navRoute('login', { public: true }),
      component: () => import('@/features/ledger/LoginView.vue'),
    },
    {
      ...navRoute('auth-unavailable', { public: true }),
      component: () => import('@/features/ledger/AuthUnavailableView.vue'),
    },
    {
      ...navRoute('peek', { public: true }),
      component: () => import('@/features/market/PeekView.vue'),
    },
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
