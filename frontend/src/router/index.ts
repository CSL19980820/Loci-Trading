import { createRouter, createWebHistory } from 'vue-router'

import { getSession } from '@/api/palace'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览' } },
    { path: '/journal', name: 'journal', component: () => import('@/views/JournalView.vue'), meta: { title: '交割单' } },
    { path: '/pool', name: 'pool', component: () => import('@/views/PoolView.vue'), meta: { title: '候选池' } },
    { path: '/reviews', name: 'reviews', component: () => import('@/views/ReviewCenterView.vue'), meta: { title: '复盘中心' } },
    { path: '/reviews/records', name: 'review-records', component: () => import('@/views/ReviewsView.vue'), meta: { title: '复盘记录' } },
    { path: '/quant', name: 'quant', component: () => import('@/views/QuantView.vue'), meta: { title: '量化' } },
    { path: '/strategy-converter', name: 'strategy-converter', component: () => import('@/views/StrategyConverterView.vue'), meta: { title: 'AI 策略转换' } },
    { path: '/winrate', name: 'winrate', component: () => import('@/views/WinRateView.vue'), meta: { title: '胜率统计' } },
    { path: '/insights', name: 'insights', component: () => import('@/views/InsightsView.vue'), meta: { title: '洞察' } },
    { path: '/screen-history', name: 'screen-history', component: () => import('@/views/ScreenHistoryView.vue'), meta: { title: '选股记录' } },
    { path: '/ops', name: 'ops', component: () => import('@/views/OpsView.vue'), meta: { title: '运维' } },
    { path: '/archive/:code', name: 'archive', component: () => import('@/views/ArchiveView.vue'), meta: { title: '档案' } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录', public: true } },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const session = await getSession().catch(() => ({ authenticated: false, username: '' }))
  if (to.meta.public === true) return session.authenticated ? { name: 'dashboard' } : true
  return session.authenticated ? true : { name: 'login' }
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '潜龙记忆宫殿')}｜潜龙记忆宫殿`
})

export default router
