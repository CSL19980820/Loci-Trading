/**
 * 侧栏的「有哪些入口、现在亮哪一条」。
 *
 * 拆出来是因为这份数据与 AppSidebar 的三段式版型完全无关：菜单增删、路由归并
 * （/reviews 与 /reviews/records 要各自亮）、管理员才出现的「管理后台」，改的都是
 * 这里，不该每次都去翻 400 行样式才找到那张表。
 *
 * 弹层开关（themeOpen / notifyOpen）也归这里：底部「消息」「主题」是**动作项**而非
 * 路由项，它们的分流就在 onFootClick 里，开关跟着分流走才不会两地对不上。
 */
import { computed, ref, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bell,
  Brush,
  DataAnalysis,
  DataBoard,
  Folder,
  Histogram,
  MagicStick,
  Management,
  Monitor,
  Odometer,
  Opportunity,
  Search,
  Setting,
  Stamp,
  Tickets,
  TrendCharts,
} from '@element-plus/icons-vue'

import { navMenuItem, type NavMenuItem } from '@/shared/lib/navLabels'
import { useUserStore } from '@/shared/stores/user'

/** 组名是分区（一级菜单），带自己的主 icon */
type NavGroup = { id: string; label: string; icon: Component; items: NavMenuItem[] }

const navGroups: NavGroup[] = [
  {
    id: 'market',
    label: '市场',
    icon: Odometer,
    items: [
      navMenuItem('pulse', Odometer),
      navMenuItem('live', Monitor),
      navMenuItem('data-query', DataBoard),
    ],
  },
  {
    id: 'mine',
    label: '我的',
    icon: Folder,
    items: [
      navMenuItem('pool', Opportunity),
      navMenuItem('screen-history', Search),
      navMenuItem('quant', Histogram),
      navMenuItem('strategy-converter', MagicStick),
      navMenuItem('reviews', Stamp),
      navMenuItem('review-records', Tickets),
      navMenuItem('winrate', TrendCharts),
      navMenuItem('insights', DataAnalysis),
    ],
  },
]

/**
 * 底部固定菜单。`path` 有值即是真路由项（选中态生效），否则是开弹层的动作项。
 * 顺序：消息 → 主题 → 设置 → 管理后台（仅管理员）。
 */
type FootItem = {
  id: string
  label: string
  icon: Component
  /** 路由项的目标路径；动作项没有 */
  path?: string
  /** 是否挂未读角标 */
  badge?: boolean
}

export function useSidebarNav() {
  const route = useRoute()
  const router = useRouter()
  const userStore = useUserStore()
  const themeOpen = ref(false)
  const notifyOpen = ref(false)

  const defaultOpeneds = ref(['market', 'mine'])

  const active = computed(() => {
    if (route.path.startsWith('/archive')) return route.path
    if (route.path === '/reviews/records') return '/reviews/records'
    if (route.path.startsWith('/reviews')) return '/reviews'
    return route.path
  })

  const opsActive = computed(() => route.path === '/ops' || route.path.startsWith('/ops/'))
  const adminActive = computed(() => route.path === '/admin' || route.path.startsWith('/admin/'))

  const footItems = computed<FootItem[]>(() => {
    const items: FootItem[] = [
      { id: 'notify', label: '消息', icon: Bell, badge: true },
      { id: 'theme', label: '主题', icon: Brush },
      { id: 'ops', label: '设置', icon: Setting, path: '/ops' },
    ]
    if (userStore.isAdmin) {
      items.push({ id: 'admin', label: '管理后台', icon: Management, path: '/admin' })
    }
    return items
  })

  /** 只有路由项会亮；动作项（消息 / 主题）永远不进选中态。 */
  const footActive = computed(() => {
    if (opsActive.value) return '/ops'
    if (adminActive.value) return '/admin'
    return ''
  })

  const unread = computed(() => userStore.unread)

  function onFootClick(item: FootItem): void {
    if (item.path) {
      if (route.path !== item.path) void router.push(item.path)
      return
    }
    if (item.id === 'notify') notifyOpen.value = true
    if (item.id === 'theme') themeOpen.value = true
  }

  return {
    navGroups,
    defaultOpeneds,
    active,
    footItems,
    footActive,
    unread,
    themeOpen,
    notifyOpen,
    onFootClick,
  }
}
