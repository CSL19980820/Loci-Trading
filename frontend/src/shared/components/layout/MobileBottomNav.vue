<script setup lang="ts">
import {
  DataAnalysis,
  DataBoard,
  Grid,
  Histogram,
  MagicStick,
  Management,
  Monitor,
  Odometer,
  Opportunity,
  Search,
  Setting,
  Stamp,
  SwitchButton,
  Tickets,
  TrendCharts,
  User,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { toErrorMessage } from '@/shared/lib/errors'
import { navMenuItem, type NavMenuItem } from '@/shared/lib/navLabels'
import { useUserStore } from '@/shared/stores/user'

const route = useRoute()
const router = useRouter()

const drawerOpen = ref(false)

/**
 * 底栏四个主位。社区下线后原「广场」空出来的位子给「选股」——它是这套软件里
 * 使用频次最高的日常动作（盘后一次、盘中随时），而不是再塞一个只读页。
 */
const primaryTabs: NavMenuItem[] = [
  navMenuItem('pulse', Odometer),
  navMenuItem('pool', Opportunity),
  navMenuItem('screen-history', Search),
  navMenuItem('reviews', Stamp),
]

/**
 * 窄屏（≤980px）侧栏整体 display:none，连头像菜单一起消失。抽屉不补齐这几项，
 * 手机上就**没有任何办法**打开账号页、管理后台，也无法退出登录。
 */
const moreItems: NavMenuItem[] = [
  navMenuItem('live', Monitor),
  navMenuItem('insights', DataAnalysis),
  navMenuItem('winrate', TrendCharts),
  navMenuItem('quant', Histogram),
  navMenuItem('data-query', DataBoard),
  navMenuItem('strategy-converter', MagicStick),
  navMenuItem('review-records', Tickets),
  navMenuItem('account', User),
  navMenuItem('ops', Setting),
]

const adminItem = navMenuItem('admin', Management)

const userStore = useUserStore()
const visibleMoreItems = computed<NavMenuItem[]>(() =>
  userStore.isAdmin ? [...moreItems, adminItem] : moreItems,
)

const morePaths = computed(() => visibleMoreItems.value.map((item) => item.path))
const moreActive = computed(() =>
  morePaths.value.some((path) => route.path === path || route.path.startsWith(`${path}/`)),
)

async function onLogout(): Promise<void> {
  drawerOpen.value = false
  try {
    await userStore.logout()
  } catch (caught: unknown) {
    // 会话在服务端可能已经失效，本地状态照样要清干净，否则界面停在「已登录」。
    ElMessage.warning(toErrorMessage(caught, '退出请求没送达，本地登录状态已清除'))
  }
  await router.replace({ name: 'login' })
}

function isPrimaryActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  if (path === '/reviews') {
    return route.path.startsWith('/reviews')
  }
  return route.path === path || route.path.startsWith(`${path}/`)
}

function isMoreItemActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<template>
  <nav class="mobile-bottom-nav" aria-label="主导航">
    <RouterLink
      v-for="tab in primaryTabs"
      :key="tab.path"
      :to="tab.path"
      class="nav-tab"
      :class="{ active: isPrimaryActive(tab.path) }"
    >
      <el-icon><component :is="tab.icon" /></el-icon>
      <span class="nav-label">{{ tab.label }}</span>
    </RouterLink>
    <el-button
      text
      class="nav-tab"
      :class="{ active: moreActive }"
      aria-label="更多导航"
      @click="drawerOpen = true"
    >
      <el-icon><Grid /></el-icon>
      <span class="nav-label">更多</span>
    </el-button>
  </nav>

  <el-drawer
    v-model="drawerOpen"
    title="更多"
    direction="btt"
    size="auto"
    class="mobile-more-drawer"
    append-to-body
  >
    <div class="more-drawer-body">
      <RouterLink
        v-for="item in visibleMoreItems"
        :key="item.path"
        :to="item.path"
        class="more-link"
        :class="{ active: isMoreItemActive(item.path) }"
        @click="drawerOpen = false"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </RouterLink>
      <el-button text class="more-link more-link--action" @click="onLogout">
        <el-icon><SwitchButton /></el-icon>
        <span>退出</span>
      </el-button>
    </div>
  </el-drawer>
</template>

<style scoped>
.mobile-bottom-nav {
  display: none;
}

/*
 * 断点必须与侧栏的隐藏点（AppSidebar 980px）一致。此前底栏卡在 768px，
 * 769–980px 之间侧栏已隐藏、底栏还没出现，平板竖屏与桌面半屏完全没有跨页入口。
 */
@media (max-width: 980px) {
  .mobile-bottom-nav {
    /*
     * 52px + 安全区。壳的避让（.app-shell--with-mobile-nav）与 FAB 偏移读的是
     * 全局 --mobile-nav-h，那边现在由 App.vue 就地覆写成同一个 52px；
     * 令牌层把 --mobile-nav-h 落到 52px 后，这行与 App.vue 里那段一起删。
     */
    --mobile-nav-h: 52px;
    display: flex;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 35;
    height: calc(var(--mobile-nav-h) + env(safe-area-inset-bottom, 0));
    padding-bottom: env(safe-area-inset-bottom, 0);
    border-top: 1px solid var(--rule);
    background: var(--sheet-alt);
  }

  .nav-tab {
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    height: auto;
    padding: var(--gap-1) 2px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--mist);
    font: inherit;
    font-size: var(--fs-micro, 10px);
    font-weight: 500;
    line-height: 1.1;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .nav-tab.el-button {
    margin: 0;
  }

  /* EP 把默认插槽包一层 <span>：不接管它，图标与文字会横排，跟相邻 RouterLink 页签对不齐 */
  .nav-tab.el-button > :deep(span) {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    min-width: 0;
  }

  .nav-tab.el-button:hover,
  .nav-tab.el-button:focus {
    background: transparent;
    color: var(--mist);
  }

  .nav-tab .el-icon {
    margin: 0;
    font-size: 18px;
  }

  .nav-label {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* 选中态是品牌靛，不是红：底栏和涨跌没有关系（D1） */
  .nav-tab.active {
    color: var(--seal-ink);
    font-weight: 600;
  }

  .nav-tab.active.el-button:hover,
  .nav-tab.active.el-button:focus {
    color: var(--seal-ink);
    background: transparent;
  }

  .nav-tab.active .el-icon {
    color: var(--seal-ink);
  }
}

.more-drawer-body {
  display: grid;
  /* 10+ 项在 360px 屏上单列会顶到抽屉高度上限；两列既不横向溢出也不吃滚动 */
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-1);
  padding-bottom: calc(var(--gap-2) + env(safe-area-inset-bottom, 0));
}

.more-link {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-2);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: var(--fs-body);
  text-decoration: none;
  cursor: pointer;
  width: 100%;
  text-align: left;
}

.more-link:hover,
.more-link:focus-visible {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.more-link.active {
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--seal);
}

.more-link--action {
  justify-content: flex-start;
  color: var(--muted);
}

/* EP 的 text button 自带内边距与最小高度，不压平会比相邻 RouterLink 高一截 */
.more-link--action.el-button {
  height: auto;
  margin: 0;
  padding: var(--gap-2);
}
</style>

<style>
@media (max-width: 980px) {
  .mobile-more-drawer.el-drawer {
    max-height: 70vh;
  }

  .mobile-more-drawer .el-drawer__header {
    margin-bottom: var(--gap-2);
    padding-bottom: var(--gap-2);
    border-bottom: 1px solid var(--rule);
  }

  .mobile-more-drawer .el-drawer__title {
    color: var(--ink);
    font-size: var(--fs-title);
    font-weight: 700;
    letter-spacing: 0.03em;
  }

  .mobile-more-drawer .el-drawer__body {
    padding-top: var(--gap-1);
  }
}
</style>
