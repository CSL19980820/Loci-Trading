<script setup lang="ts">
/**
 * 壳的左栏。三段式，互不干扰：
 *
 *   brand-row（定高，不滚）
 *   .side-menu-wrap（flex:1，**独立内滚**）
 *   .sidebar-foot（钉底，永不滚）
 *
 * 底部那组「消息 / 主题 / 设置 / 管理后台」不是图标按钮条，而是与上方**同一套皮肤**
 * 的 el-menu-item（同一个 .side-menu 类，hover / is-active / 尺寸全部复用同一批规则）。
 * 用户要的就是「和市场 / 我的那种菜单一样，只是钉在左下角」，所以这里刻意不另起样式：
 * 任何时候改上面的菜单皮肤，下面自动跟着变。
 *
 * 底部菜单不开 el-menu 的 `router` 模式——「消息」「主题」是开弹层不是跳路由，
 * router 模式会把它们的 index 当路径 push 出去。所以统一走 onFootClick 分流，
 * 选中态由 `footActive` 显式给。
 */
import {
  Bell,
  Brush,
  DataAnalysis,
  DataBoard,
  Expand,
  Fold,
  Folder,
  Histogram,
  MagicStick,
  Management,
  Monitor,
  Odometer,
  Opportunity,
  QuestionFilled,
  Search,
  Setting,
  Stamp,
  Tickets,
  TrendCharts,
} from '@element-plus/icons-vue'
import { computed, onMounted, ref, type Component } from 'vue'
import { useRoute, useRouter, type RouteRecordNormalized } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import ThemeDialog from '@/shared/components/dialogs/ThemeDialog.vue'
import NotificationCenter from '@/shared/components/layout/NotificationCenter.vue'
import { createDesktopShortcut, getDataLocation } from '@/shared/api/quant'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import { navMenuItem, type NavMenuItem } from '@/shared/lib/navLabels'
import { useUserStore } from '@/shared/stores/user'
import UserAvatarMenu from '@/features/auth/UserAvatarMenu.vue'

const brandName = BRAND_NAME
const brandMark = BRAND_MARK

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const collapsed = ref(false)
const themeOpen = ref(false)
const notifyOpen = ref(false)

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

const defaultOpeneds = ref(['market', 'mine'])

const active = computed(() => {
  if (route.path.startsWith('/archive')) return route.path
  if (route.path === '/reviews/records') return '/reviews/records'
  if (route.path.startsWith('/reviews')) return '/reviews'
  return route.path
})

const opsActive = computed(() => route.path === '/ops' || route.path.startsWith('/ops/'))
const adminActive = computed(() => route.path === '/admin' || route.path.startsWith('/admin/'))

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

/*
 * —— 路由分片预取 ——
 *
 * 路由组件是 `() => import(...)`，vue-router 在**导航确认前**要把分片下完。
 * 首次点某个菜单于是先卡一下才切页。这里在悬停 / 聚焦时提前把工厂跑掉：
 * 等真点下去时分片已在内存，导航是同步的。
 *
 * 失败一律吞掉：预取是锦上添花，网络不好时不该冒出一条错误提示；真导航过去时
 * vue-router 会自己再试一次并走正常的错误处理。
 */
const prefetched = new Set<string>()

function prefetchRoute(path?: string): void {
  if (!path || prefetched.has(path)) return
  prefetched.add(path)
  // 测试里的 router 是个精简 mock，没有 resolve；这里不该炸。
  if (typeof router?.resolve !== 'function') return
  let records: readonly RouteRecordNormalized[]
  try {
    records = router.resolve(path).matched
  } catch {
    return
  }
  for (const record of records) {
    for (const loader of Object.values(record.components ?? {})) {
      if (typeof loader !== 'function') continue
      try {
        void Promise.resolve((loader as () => unknown)()).catch(() => undefined)
      } catch {
        /* 工厂同步抛错：预取失败不该影响任何交互 */
      }
    }
  }
}

/** 空闲时预取的高频页：盘面 / 候选池 / 选股 / 工坊。别把整张路由表都拉下来。 */
const IDLE_PREFETCH = ['/', '/pool', '/screen-history', '/quant']

onMounted(() => {
  const warmup = (): void => IDLE_PREFETCH.forEach((path) => prefetchRoute(path))
  // requestIdleCallback 必须挂在 window 上调（脱手调用某些内核会抛 Illegal invocation）；
  // happy-dom / 老 Safari 没有它，退回一个足够晚的 setTimeout。
  if (typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(warmup, { timeout: 3000 })
    return
  }
  window.setTimeout(warmup, 1200)
})

async function onHelpCommand(cmd: string): Promise<void> {
  try {
    if (cmd === 'shortcut') {
      const result = await createDesktopShortcut()
      ElMessage.success(`已创建：${result.shortcut}`)
      return
    }
    if (cmd === 'data') {
      const loc = await getDataLocation()
      await ElMessageBox.alert(
        `当前数据目录：\n${loc.data_dir}\n\n可在资源管理器中打开该路径；或到「设置 → 数据目录」修改。`,
        '数据目录',
        { confirmButtonText: '知道了' },
      )
      return
    }
    if (cmd === 'readme') {
      window.open('/使用说明.txt', '_blank')
      ElMessage.info('也可查看程序目录下的「使用说明.txt」')
    }
  } catch (caught: unknown) {
    ElMessage.error(caught instanceof Error ? caught.message : '操作失败')
  }
}
</script>

<template>
  <aside class="app-sidebar" :class="{ collapsed }">
    <!-- 顶部 Brand：Logo与名称居左，折叠按钮移至最右顶边 -->
    <div class="brand-row">
      <RouterLink class="brand" to="/" aria-label="首页">
        <span class="brand-mark" aria-hidden="true">{{ brandMark }}</span>
        <strong v-if="!collapsed" class="brand-name">{{ brandName }}</strong>
      </RouterLink>
      <el-tooltip
        :content="collapsed ? '展开侧栏' : '收起侧栏'"
        placement="right"
        :show-after="300"
      >
        <el-button
          link
          class="icon-btn brand-toggle"
          :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
          @click="collapsed = !collapsed"
        >
          <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
        </el-button>
      </el-tooltip>
    </div>

    <!-- 中间菜单区：独立滚动，一级与二级支持折叠展开，一级带icon，展开收起完全对齐 -->
    <div class="side-menu-wrap">
      <el-menu
        :default-active="active"
        :default-openeds="defaultOpeneds"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="side-menu"
      >
        <template v-for="(group, gIdx) in navGroups" :key="group.id">
          <!-- 展开态：可折叠展开的一级/二级子菜单 -->
          <el-sub-menu v-if="!collapsed" :index="group.id" class="nav-sub-menu">
            <template #title>
              <el-icon class="sub-menu-icon"><component :is="group.icon" /></el-icon>
              <span class="nav-group-title">{{ group.label }}</span>
            </template>
            <el-menu-item
              v-for="item in group.items"
              :key="item.path"
              :index="item.path"
              class="sub-menu-item"
              @mouseenter="prefetchRoute(item.path)"
              @focusin="prefetchRoute(item.path)"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.label }}</template>
            </el-menu-item>
          </el-sub-menu>

          <!-- 收缩态：直接平铺展示icon项，并带精确Tooltip与统一居中对齐 -->
          <template v-else>
            <div v-if="gIdx > 0" class="nav-group-divider collapsed-divider" aria-hidden="true" />
            <el-menu-item
              v-for="item in group.items"
              :key="item.path"
              :index="item.path"
              class="collapsed-menu-item"
              @mouseenter="prefetchRoute(item.path)"
              @focusin="prefetchRoute(item.path)"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.label }}</template>
            </el-menu-item>
          </template>
        </template>
      </el-menu>
    </div>

    <!--
      底部固定区：①同款菜单项（消息 / 主题 / 设置 / 管理后台）②发丝分隔 ③用户行。
      整块 flex-shrink:0，上方菜单再长也压不到它，两边各自滚各自的。
    -->
    <div class="sidebar-foot">
      <el-menu
        :default-active="footActive"
        :collapse="collapsed"
        :collapse-transition="false"
        class="side-menu foot-menu"
      >
        <el-menu-item
          v-for="item in footItems"
          :key="item.id"
          :index="item.path || item.id"
          class="foot-menu-item"
          :class="`foot-menu-item--${item.id}`"
          :aria-label="item.label"
          @click="onFootClick(item)"
          @mouseenter="prefetchRoute(item.path)"
          @focusin="prefetchRoute(item.path)"
        >
          <el-badge v-if="item.badge" is-dot :hidden="unread <= 0" class="foot-badge">
            <el-icon><component :is="item.icon" /></el-icon>
          </el-badge>
          <el-icon v-else><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-menu>

      <div class="foot-hairline" aria-hidden="true" />

      <!-- 用户行：左头像菜单，右边只留「帮助」一颗图标 -->
      <div class="foot-user" :class="{ 'foot-user--collapsed': collapsed }">
        <UserAvatarMenu :collapsed="collapsed" />

        <div class="foot-actions">
          <el-dropdown
            trigger="click"
            :placement="collapsed ? 'right-end' : 'top-end'"
            @command="onHelpCommand"
          >
            <el-button link class="icon-btn" title="帮助" aria-label="帮助">
              <el-icon><QuestionFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="shortcut">创建桌面快捷方式</el-dropdown-item>
                <el-dropdown-item command="data">打开数据目录</el-dropdown-item>
                <el-dropdown-item divided command="readme">使用说明</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>
  </aside>

  <ThemeDialog v-model="themeOpen" />
  <NotificationCenter v-model="notifyOpen" />
</template>

<style scoped>
.app-sidebar {
  /*
   * 210px 太宽（用户原话「左侧菜单太宽了」）。176px 仍装得下「管理后台 / 策稿台」
   * 这一档四字短名，再窄就要开始截断了。收缩态维持 54px。
   */
  --sidebar-w: 176px;
  --sidebar-w-collapsed: 54px;
  --icon-btn: 26px;
  height: 100%;
  min-height: 0;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--rule);
  background: var(--sheet-alt);
  overflow: hidden;
  transition: width 180ms cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  z-index: 100;
}

.app-sidebar.collapsed {
  width: var(--sidebar-w-collapsed);
}

@media (prefers-reduced-motion: reduce) {
  .app-sidebar {
    transition: none;
  }
}

/* 顶部 Brand 栏：42px，Logo与名称居左，折叠按钮在最右顶边 */
.brand-row {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 42px;
  padding: 0 6px 0 10px;
  border-bottom: 1px solid var(--rule);
  background: var(--sheet);
}

.app-sidebar.collapsed .brand-row {
  justify-content: center;
  padding: 0 4px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1, 4px);
  min-width: 0;
  color: inherit;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: var(--radius, 6px);
  background: var(--seal);
  color: #fff;
  font-family: var(--mono);
  font-size: var(--fs-kicker, 11px);
  font-weight: 700;
  letter-spacing: 0.02em;
}

.brand-name {
  min-width: 0;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.brand-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border-radius: var(--radius, 6px);
  color: var(--mist);
  transition: all 180ms ease;
}

.brand-toggle:hover {
  background: var(--sheet-alt);
  color: var(--ink);
}

/* 中间菜单区域：自适应高度 + 独立滚动。min-height:0 是关键，否则内容会把底部顶出视口 */
.side-menu-wrap {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  padding: 6px 5px;
}

.side-menu {
  width: 100%;
  border-right: 0 !important;
  background: transparent !important;
}

/* 一级折叠标题与图标 */
.side-menu :deep(.el-sub-menu__title) {
  display: flex !important;
  align-items: center;
  height: 34px;
  line-height: 34px;
  padding: 0 8px !important;
  margin: 3px 0;
  border-radius: var(--radius, 6px);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  transition: all 180ms ease;
}

.side-menu :deep(.el-sub-menu__title:hover) {
  background: var(--sheet) !important;
  color: var(--ink);
}

.side-menu :deep(.el-sub-menu__title .sub-menu-icon),
.side-menu :deep(.el-sub-menu__title .el-icon) {
  width: 16px;
  font-size: 15px;
  margin-right: 8px;
  color: var(--mist);
  transition: color 180ms ease;
}

.side-menu :deep(.el-sub-menu__title:hover .el-icon) {
  color: var(--seal-ink);
}

.side-menu :deep(.el-sub-menu__title .el-sub-menu__icon-arrow) {
  margin-right: 0 !important;
  font-size: 12px;
  color: var(--mist);
}

/*
 * 二级菜单项。底部那组用的是**同一条规则**（.foot-menu 也带 .side-menu 类），
 * hover / is-active / 高度 / 缩进因此像素级一致——这正是「做成类似我的那种菜单」。
 * 左缩进从 32px 收到 26px：侧栏窄了，再吃 32px 会把四字短名挤到换行。
 */
.side-menu :deep(.el-menu-item) {
  display: flex !important;
  align-items: center;
  height: 32px;
  line-height: 32px;
  padding: 0 10px 0 26px !important;
  margin: 2px 0;
  border-radius: var(--radius, 6px);
  border-left: 0 !important;
  color: var(--muted);
  font-size: 13px;
  transition: all 180ms ease;
}

.side-menu :deep(.el-menu-item .el-icon) {
  width: 15px;
  margin-right: 8px;
  font-size: 14px;
  color: var(--mist);
  transition: color 180ms ease;
}

.side-menu :deep(.el-menu-item:hover) {
  background: var(--sheet) !important;
  color: var(--ink);
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--seal-soft) !important;
  color: var(--seal) !important;
  font-weight: 600;
}

.side-menu :deep(.el-menu-item.is-active .el-icon) {
  color: var(--seal-ink);
}

/* 收缩态下的菜单项 */
.app-sidebar.collapsed .side-menu-wrap {
  padding: 6px 4px;
}

.app-sidebar.collapsed .side-menu :deep(.el-menu-item) {
  display: flex !important;
  align-items: center;
  justify-content: center;
  padding: 0 !important;
  margin: 4px 0;
  height: 34px;
  width: 100%;
}

.app-sidebar.collapsed .side-menu :deep(.el-menu-item .el-icon) {
  margin: 0 !important;
  font-size: 16px;
}

.collapsed-divider {
  height: 1px;
  background: var(--rule);
  margin: 6px 4px;
}

/*
 * —— 底部固定区 ——
 * flex-shrink:0 + 不参与上方滚动容器：上面的菜单再长也不会把它顶走，
 * 它也不会跟着上面一起滚（用户原话：「两者互不影响」）。
 */
.sidebar-foot {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 5px 6px;
  border-top: 1px solid var(--rule);
  background: var(--sheet);
}

.app-sidebar.collapsed .sidebar-foot {
  padding: 4px 4px 6px;
}

/* 底部菜单容器只负责排版；皮肤全部由上面的 .side-menu 规则提供 */
.foot-menu {
  width: 100%;
}

.foot-menu :deep(.el-menu-item) {
  background: transparent;
}

/*
 * 「消息」「主题」是开弹层的动作项，不是页面。EP 的 el-menu 在非 router 模式下
 * 会把**任何**被点过的 item 记成 activeIndex，于是点一次消息，那一条就永久亮着，
 * 看起来像「当前页是消息」。这里按住不让它进选中态——选中态只属于真路由项。
 */
.foot-menu :deep(.el-menu-item.foot-menu-item--notify.is-active),
.foot-menu :deep(.el-menu-item.foot-menu-item--theme.is-active) {
  background: transparent !important;
  color: var(--muted) !important;
  font-weight: 400;
}

.foot-menu :deep(.el-menu-item.foot-menu-item--notify.is-active .el-icon),
.foot-menu :deep(.el-menu-item.foot-menu-item--theme.is-active .el-icon) {
  color: var(--mist);
}

.foot-menu :deep(.el-menu-item.foot-menu-item--notify.is-active:hover),
.foot-menu :deep(.el-menu-item.foot-menu-item--theme.is-active:hover) {
  background: var(--sheet) !important;
  color: var(--ink) !important;
}

/* 未读圆点跟着铃铛走：图标外面包了一层 el-badge，图标本身的间距规则照旧生效 */
.foot-badge {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.foot-badge :deep(.el-badge__content.is-dot) {
  width: 6px;
  height: 6px;
  padding: 0;
  border: 0;
  background: var(--stamp);
}

.foot-hairline {
  height: 1px;
  margin: 2px 4px;
  background: var(--rule);
}

.foot-user {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.foot-user--collapsed {
  flex-direction: column;
  justify-content: flex-start;
  gap: 4px;
}

.foot-user :deep(.user-menu-wrap) {
  flex: 1 1 auto;
  min-width: 0;
  padding-top: 0;
  border-top: 0;
}

.foot-user--collapsed :deep(.user-menu-wrap) {
  flex: 0 0 auto;
  width: 100%;
}

.foot-user :deep(.user-profile-btn) {
  height: 32px;
  padding: 0 4px;
  border-radius: var(--radius, 6px);
}

.foot-user--collapsed :deep(.user-profile-btn) {
  width: 34px;
  height: 34px;
  padding: 0;
  justify-content: center;
}

.foot-user :deep(.user-name) {
  font-size: 13px;
  font-weight: 600;
}

.foot-actions {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.foot-user--collapsed .foot-actions {
  flex-direction: column;
}

.icon-btn.el-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: var(--icon-btn);
  height: var(--icon-btn);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: var(--radius, 6px);
  background: transparent;
  color: var(--mist);
  text-decoration: none;
  transition: all 180ms ease;
}

.icon-btn.el-button + .icon-btn.el-button {
  margin-left: 0;
}

.icon-btn .el-icon {
  font-size: 15px;
}

.icon-btn.el-button:hover {
  background: var(--sheet-alt);
  color: var(--ink);
}

@media (max-width: 980px) {
  .app-sidebar {
    display: none;
  }
}
</style>
