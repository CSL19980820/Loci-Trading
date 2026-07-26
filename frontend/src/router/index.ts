import { createRouter, createWebHistory } from 'vue-router'

import { getSession } from '@/api/palace'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览' } },
    { path: '/journal', name: 'journal', component: () => import('@/views/JournalView.vue'), meta: { title: '交割单' } },
    { path: '/pool', name: 'pool', component: () => import('@/views/PoolView.vue'), meta: { title: '候选池' } },
    { path: '/reviews', name: 'reviews', component: () => import('@/views/ReviewsView.vue'), meta: { title: '复盘' } },
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