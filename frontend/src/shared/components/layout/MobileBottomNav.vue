<script setup lang="ts">
import {
  DataAnalysis,
  DataBoard,
  Grid,
  Histogram,
  MagicStick,
  Odometer,
  Opportunity,
  Search,
  Setting,
  Stamp,
  TrendCharts,
} from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { navMenuItem, type NavMenuItem } from '@/shared/lib/navLabels'

const route = useRoute()
const drawerOpen = ref(false)

const primaryTabs: NavMenuItem[] = [
  navMenuItem('pulse', Odometer),
  navMenuItem('pool', Opportunity),
  navMenuItem('reviews', Stamp),
]

const moreItems: NavMenuItem[] = [
  navMenuItem('screen-history', Search),
  navMenuItem('insights', DataAnalysis),
  navMenuItem('winrate', TrendCharts),
  navMenuItem('quant', Histogram),
  navMenuItem('data-query', DataBoard),
  navMenuItem('strategy-converter', MagicStick),
  navMenuItem('ops', Setting),
]

const morePaths = moreItems.map((item) => item.path)

const moreActive = computed(() =>
  morePaths.some((path) => route.path === path || route.path.startsWith(`${path}/`)),
)

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
        v-for="item in moreItems"
        :key="item.path"
        :to="item.path"
        class="more-link"
        :class="{ active: isMoreItemActive(item.path) }"
        @click="drawerOpen = false"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </RouterLink>
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
    display: flex;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 35;
    height: var(--mobile-nav-h, 3.5rem);
    padding-bottom: env(safe-area-inset-bottom, 0);
    border-top: 1px solid var(--rule);
    background: var(--sheet);
    box-shadow: 0 -1px 4px rgba(20, 32, 51, 0.06);
  }

  .nav-tab {
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.15rem;
    min-width: 0;
    height: auto;
    padding: 0.35rem 0.15rem 0.25rem;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--mist);
    font: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.1;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .nav-tab.el-button {
    margin: 0;
  }

  .nav-tab.el-button:hover,
  .nav-tab.el-button:focus {
    background: transparent;
    color: var(--mist);
  }

  .nav-tab .el-icon {
    font-size: 1.25rem;
    margin: 0;
  }

  .nav-label {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

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
    color: var(--seal);
  }
}

.more-drawer-body {
  display: grid;
  gap: 0.25rem;
  padding-bottom: calc(0.5rem + env(safe-area-inset-bottom, 0));
}

.more-link {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 0.5rem;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: 0.92rem;
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
</style>

<style>
@media (max-width: 980px) {
  .mobile-more-drawer.el-drawer {
    max-height: 70vh;
  }

  .mobile-more-drawer .el-drawer__header {
    margin-bottom: 0.5rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--rule);
  }

  .mobile-more-drawer .el-drawer__title {
    color: var(--ink);
    font-weight: 700;
  }

  .mobile-more-drawer .el-drawer__body {
    padding-top: 0.25rem;
  }
}
</style>
