import { createRouter, createWebHistory } from 'vue-router'

import { getSession } from '@/shared/api/palace'
import { brandTitle } from '@/shared/lib/brand'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/features/ledger/DashboardView.vue'), meta: { title: '总览' } },
    { path: '/journal', name: 'journal', component: () => import('@/features/ledger/JournalView.vue'), meta: { title: '交割单' } },
    { path: '/pool', name: 'pool', component: () => import('@/features/ledger/PoolView.vue'), meta: { title: '候选池' } },
    { path: '/data', name: 'data-query', component: () => import('@/features/market/DataQueryView.vue'), meta: { title: '数据查询' } },
    { path: '/reviews', name: 'reviews', component: () => import('@/features/review/ReviewCenterView.vue'), meta: { title: '复盘中心' } },
    { path: '/reviews/records', name: 'review-records', component: () => import('@/features/review/ReviewsView.vue'), meta: { title: '复盘记录' } },
    { path: '/quant', name: 'quant', component: () => import('@/features/strategy/QuantView.vue'), meta: { title: '量化' } },
    { path: '/strategy-converter', name: 'strategy-converter', component: () => import('@/features/strategy/StrategyConverterView.vue'), meta: { title: 'AI 策略转换' } },
    { path: '/winrate', name: 'winrate', component: () => import('@/features/review/WinRateView.vue'), meta: { title: '胜率统计' } },
    { path: '/insights', name: 'insights', component: () => import('@/features/review/InsightsView.vue'), meta: { title: '洞察' } },
    { path: '/screen-history', name: 'screen-history', component: () => import('@/features/strategy/ScreenHistoryView.vue'), meta: { title: '选股' } },
    { path: '/ops', name: 'ops', component: () => import('@/features/ops/OpsView.vue'), meta: { title: '运维' } },
    { path: '/archive/:code', name: 'archive', component: () => import('@/features/ledger/ArchiveView.vue'), meta: { title: '档案' } },
    { path: '/login', name: 'login', component: () => import('@/features/ledger/LoginView.vue'), meta: { title: '登录', public: true } },
    { path: '/peek', name: 'peek', component: () => import('@/features/market/PeekView.vue'), meta: { title: '行情', public: true } },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const session = await getSession().catch(() => ({ authenticated: false, username: '' }))
  if (to.meta.public === true) {
    // peek 行情小窗：已登录也要能打开，不能踢回总览
    if (to.name === 'peek') return true
    return session.authenticated ? { name: 'dashboard' } : true
  }
  return session.authenticated ? true : { name: 'login' }
})

router.afterEach((to) => {
  document.title = brandTitle(String(to.meta.title ?? ''))
})

export default router
