import { createRouter, createWebHistory } from 'vue-router'
import { recoverLazyRoute } from '@/shared/lib/chunkRecovery'

import { useUserStore } from '@/shared/stores/user'
import { brandTitle } from '@/shared/lib/brand'
import { navRoute } from '@/shared/lib/navLabels'
import { navigationPending } from '@/shared/stores/navigation'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { ...navRoute('pulse'), component: () => import('@/features/market/PulseView.vue') },
    { ...navRoute('live'), redirect: '/' },
    { ...navRoute('pool'), component: () => import('@/features/ledger/PoolView.vue') },
    { ...navRoute('data-query'), component: () => import('@/features/market/DataQueryView.vue') },
    { ...navRoute('reviews'), redirect: '/agents' },
    { ...navRoute('review-records'), redirect: '/agents' },
    { ...navRoute('agents'), component: () => import('@/features/agents/AgentsView.vue') },
    { ...navRoute('agent-detail'), component: () => import('@/features/agents/AgentDetailView.vue') },
    { ...navRoute('quant'), component: () => import('@/features/strategy/QuantView.vue') },
    {
      ...navRoute('strategy-converter'),
      component: () => import('@/features/strategy/StrategyConverterView.vue'),
    },
    { ...navRoute('winrate'), component: () => import('@/features/review/WinRateView.vue') },
    { ...navRoute('insights'), redirect: '/winrate' },
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
    { ...navRoute('account'), component: () => import('@/features/auth/AccountView.vue') },
    { ...navRoute('admin'), component: () => import('@/features/admin/AdminView.vue') },
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

router.beforeEach(async (to, from) => {
  navigationPending.value = to.name !== from.name || to.params.id !== from.params.id
  // 失败页 / 行情 Peek：禁止等会话。Peek 是独立小窗，boot-splash 挂载后即卸；
  // 若这里再 await 会话，导航未完成时主区只剩 #eef2f6 白方块。
  if (to.name === 'auth-unavailable' || to.name === 'peek') return true

  // 会话真相只有一处：userStore。
  //
  // 以前守卫走 palace.getSession()（窄契约，只回 authenticated/username），
  // 而 userStore 走 /auth/session 的完整契约，两条腿互不连通且没人在启动时
  // 调 load()。后果是刷新一次用户态全丢：头像变「未登录」、isAdmin 归 false
  // 让管理后台入口整个消失、强制改密提示条永不出现。
  // 守卫本来就要在首屏渲染前等一次会话，顺手水合是零额外成本的。
  //
  // 但**只有首屏那一次**该等。旧写法每次导航都 `await load()`，而 load() 除了
  // inflight 去重没有任何缓存短路——于是每点一次菜单，导航就被一次
  // GET /api/auth/session 的网络往返吊住，页面停在旧页等后端答话（用户原话：
  // 「点之前先卡一会儿」）。现在：已水合就走 ensureLoaded()（命中缓存、零请求），
  // 过期由后台 fire-and-forget 补，导航不为它等。
  const userStore = useUserStore()
  // `available === false` 表示上一次探测根本没打通。这一档不能吃缓存：失败页的
  // 「重试」就是一次 router.replace，吃了缓存它会永远弹回失败页。
  const cached = userStore.initialized && userStore.available
  const authed = cached ? await userStore.ensureLoaded() : await userStore.load()
  // 低频重验：缓存超过 60s 才补一次，且绝不 await——它只影响**下一次**导航的判定。
  userStore.revalidateStale()
  if (!userStore.available) {
    return { name: 'auth-unavailable', query: { redirect: to.fullPath } }
  }
  if (to.meta.public === true) {
    return authed ? { name: 'pulse' } : true
  }
  if (authed) {
    if (!userStore.isAdmin && ['/ops', '/admin', '/account'].some(path => to.path === path || to.path.startsWith(path + '/'))) return { name: 'pulse' }
    return true
  }
  return { name: 'login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined }
})

router.afterEach((to) => {
  navigationPending.value = false
  document.title = brandTitle(String(to.meta.title ?? ''))
})

router.onError((error, target) => {
  navigationPending.value = false
  recoverLazyRoute(error, target.fullPath)
})
export default router
