<script setup lang="ts">
import { ChartColumn, Cpu, Gauge, LayoutDashboard, LayoutGrid, MessageCircle, Search, Sparkles, Target, TrendingUp } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import ThemeDialog from '@/shared/components/dialogs/ThemeDialog.vue'
import { Button } from '@/shared/components/ui/button'
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/shared/components/ui/drawer'
import { openCommandPalette } from '@/shared/lib/commandPalette'
import { navMenuItem, type NavMenuItem } from '@/shared/lib/navLabels'
import UserAvatarMenu from './UserAvatarMenu.vue'

const route = useRoute()
const drawerOpen = ref(false)
const themeOpen = ref(false)
const primaryTabs: NavMenuItem[] = [
  navMenuItem('pulse', Gauge),
  navMenuItem('pool', Target),
  navMenuItem('screen-history', Search),
  navMenuItem('agents', Cpu),
]
const moreItems: NavMenuItem[] = [
  navMenuItem('winrate', TrendingUp),
  navMenuItem('quant', ChartColumn),
  navMenuItem('data-query', LayoutDashboard),
  navMenuItem('strategy-converter', Sparkles),
]
const moreActive = computed(() =>
  [...moreItems.map((item) => item.path), '/account', '/ops', '/admin'].some(isActive),
)
function isActive(path: string): boolean {
  return path === '/' ? route.path === '/' : route.path === path || route.path.startsWith(`${path}/`)
}
function openAssistant(): void {
  drawerOpen.value = false
  window.dispatchEvent(new CustomEvent('loci:assistant-open'))
}
function openSearch(): void {
  drawerOpen.value = false
  openCommandPalette()
}
function openTheme(): void {
  drawerOpen.value = false
  themeOpen.value = true
}
</script>

<template>
  <nav class="mobile-bottom-nav" aria-label="主导航">
    <RouterLink v-for="tab in primaryTabs" :key="tab.path" :to="tab.path" class="nav-tab" :class="{ active: isActive(tab.path) }" :aria-current="isActive(tab.path) ? 'page' : undefined">
      <span class="nav-tab__icon-wrap"><component :is="tab.icon" class="nav-tab__icon" aria-hidden="true" /></span>
      <span class="nav-label">{{ tab.label }}</span>
    </RouterLink>
    <Button access="read" variant="ghost" type="button" class="nav-tab" :class="{ active: moreActive }" :aria-expanded="drawerOpen" aria-label="更多导航" @click="drawerOpen = true">
      <span class="nav-tab__icon-wrap"><LayoutGrid class="nav-tab__icon" aria-hidden="true" /></span>
      <span class="nav-label">更多</span>
    </Button>
  </nav>

  <Drawer v-model:open="drawerOpen">
    <DrawerContent class="mobile-more-drawer">
      <DrawerHeader class="mobile-more-drawer__head">
        <DrawerTitle class="sr-only">更多</DrawerTitle>
        <DrawerDescription class="sr-only">账号菜单与其余页面</DrawerDescription>
        <UserAvatarMenu class="more-user-menu" data-vaul-no-drag @theme="openTheme" @navigate="drawerOpen = false" />
        <Button access="read" variant="outline" class="more-search" @click="openSearch"><Search aria-hidden="true" />搜索或跳转</Button>
      </DrawerHeader>
      <div class="more-drawer-body">
        <Button access="read" variant="ghost" type="button" class="more-link more-link--assistant" @click="openAssistant"><span class="more-link__icon-wrap"><MessageCircle class="more-link__icon" aria-hidden="true" /></span><span class="more-link__label">AI 助手</span></Button>
        <RouterLink v-for="item in moreItems" :key="item.path" :to="item.path" class="more-link" :class="{ active: isActive(item.path) }" @click="drawerOpen = false">
          <span class="more-link__icon-wrap"><component :is="item.icon" class="more-link__icon" aria-hidden="true" /></span>
          <span class="more-link__label">{{ item.label }}</span>
        </RouterLink>
      </div>
    </DrawerContent>
  </Drawer>
  <ThemeDialog v-model="themeOpen" />
</template>

<style scoped>
.mobile-bottom-nav { display: none; }
@media (max-width: 767px) {
  .mobile-bottom-nav { position: fixed; inset: auto 0 0; z-index: var(--z-mobile-nav); display: flex; height: calc(var(--mobile-nav-h) + env(safe-area-inset-bottom, 0)); padding: 0 8px env(safe-area-inset-bottom, 0); border-top: 1px solid var(--border-subtle); background: color-mix(in oklab, var(--surface-raised) 92%, transparent); backdrop-filter: blur(12px); }
  .nav-tab { display: flex; flex: 1 1 0; flex-direction: column; align-items: center; justify-content: center; gap: 3px; min-width: 0; min-height: 44px; padding: 6px 2px; border: 0; background: transparent; color: var(--text-tertiary); font: 500 var(--fs-micro)/1.2 var(--font); text-decoration: none; -webkit-tap-highlight-color: transparent; transition: color var(--dur-fast) var(--ease); }
  .nav-tab__icon-wrap { display: grid; place-items: center; width: 44px; height: 28px; border-radius: var(--radius-pill); transition: background-color var(--dur-fast) var(--ease); }
  .nav-tab__icon { width: 22px; height: 22px; stroke-width: 1.8; }
  .nav-tab.active { color: var(--seal-ink); font-weight: 600; }
  .nav-tab.active .nav-tab__icon-wrap { background: var(--seal-soft); }
  .nav-label { max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
}
.mobile-more-drawer { max-height: 88dvh; }
.mobile-more-drawer__head { display: flex; flex-direction: column; gap: 10px; padding: 8px 16px 12px; border-bottom: 1px solid var(--border-subtle); text-align: left; }
.more-user-menu :deep(.user-profile-btn) { min-height: 48px; padding: 6px 8px; }
.more-user-menu :deep(.user-avatar) { width: 36px; height: 36px; }
.more-search { justify-content: flex-start; width: 100%; height: 44px; color: var(--text-tertiary); font-weight: 400; }
.more-drawer-body { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; padding: 16px 16px calc(20px + env(safe-area-inset-bottom, 0)); }
.more-link { display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 8px; height: auto; min-width: 0; min-height: 44px; padding: 6px 0; border-radius: var(--radius-lg); color: var(--text-secondary); font-size: var(--fs-aux); text-decoration: none; }
.more-link__icon-wrap { flex-shrink: 0; display: grid; place-items: center; width: 48px; height: 48px; border: 1px solid var(--border-subtle); border-radius: 12px; background: var(--surface); transition: background-color var(--dur-fast) var(--ease); }
.more-link__icon { width: 21px; height: 21px; stroke-width: 1.8; }
.more-link.active { color: var(--seal-ink); }
.more-link.active .more-link__icon-wrap { background: var(--seal-soft); border-color: var(--seal-border); }
.more-link--assistant { border:0; background:transparent; cursor:pointer; }
.more-link:active .more-link__icon-wrap { background: var(--surface-hover); }
.more-link__label { flex-shrink: 0; max-width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
/* Keep the whole selector global: scoped CSS drops anything after :global(...). */
:global(html[data-mobile-keyboard] .mobile-bottom-nav) { display:none; }
@media (prefers-reduced-motion: reduce) { .nav-tab, .nav-tab__icon-wrap, .more-link__icon-wrap { transition: none; } }
</style>
