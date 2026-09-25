<script setup lang="ts">
import { Kbd } from '@/shared/components/ui/kbd'
import { ChevronRight, Search } from '@lucide/vue'
import { computed } from 'vue'
import ThemeDialog from '@/shared/components/dialogs/ThemeDialog.vue'
import { Button } from '@/shared/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarTrigger, useSidebar } from '@/shared/components/ui/sidebar'
import { BRAND_NAME, BRAND_TAGLINE } from '@/shared/lib/brand'
import { openCommandPalette, paletteHotkeyLabel } from '@/shared/lib/commandPalette'
import UserAvatarMenu from './UserAvatarMenu.vue'
import { useRoutePrefetch } from './composables/useRoutePrefetch'
import { useSidebarNav } from './composables/useSidebarNav'

const { state, isMobile, setOpenMobile } = useSidebar()
const collapsed = computed(() => state.value === 'collapsed' && !isMobile.value)
const { navGroups, defaultOpeneds, active, themeOpen } = useSidebarNav()
const { prefetchRoute: prefetch } = useRoutePrefetch()
function setGroupOpen(id: string, open: boolean): void {
  if (collapsed.value) return
  defaultOpeneds.value = open ? [...new Set([...defaultOpeneds.value, id])] : defaultOpeneds.value.filter(value => value !== id)
}
defineExpose({ themeOpen })
</script>

<template>
  <Sidebar collapsible="icon" class="app-sidebar" :class="{ 'is-collapsed': collapsed }" aria-label="侧边导航">
    <SidebarHeader class="sidebar-heading">
      <RouterLink to="/" class="brand" :aria-label="`${BRAND_NAME} ${BRAND_TAGLINE}`">
        <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.5 9.5 9l4 6 2.5-3.5L20 17.5" /></svg></span>
        <span v-if="!collapsed" class="brand-text"><strong>{{ BRAND_NAME }}</strong><span>{{ BRAND_TAGLINE }}</span></span>
      </RouterLink>
      <Button access="read" variant="outline" class="search-trigger" :class="{ 'search-trigger--collapsed': collapsed }" aria-label="搜索或跳转" @click="openCommandPalette()">
        <Search aria-hidden="true" /><template v-if="!collapsed"><span>搜索或跳转…</span><Kbd>{{ paletteHotkeyLabel() }}</Kbd></template>
      </Button>
    </SidebarHeader>
    <SidebarContent class="sidebar-navigation">
      <nav aria-label="功能导航">
        <Collapsible v-for="group in navGroups" :key="group.id" :open="collapsed || defaultOpeneds.includes(group.id)" @update:open="setGroupOpen(group.id, $event)">
          <SidebarGroup class="nav-group">
            <CollapsibleTrigger v-if="!collapsed" as-child>
              <SidebarGroupLabel as-child class="nav-group-trigger"><button type="button" :aria-label="group.label">
              <component :is="group.icon" aria-hidden="true" /><span>{{ group.label }}</span><ChevronRight class="nav-caret" aria-hidden="true" />
              </button></SidebarGroupLabel>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarGroupContent class="nav-group-content">
                <SidebarMenu>
                  <SidebarMenuItem v-for="item in group.items" :key="item.path">
                    <SidebarMenuButton as-child :is-active="active === item.path" :tooltip="item.label" class="nav-item">
                      <RouterLink :to="item.path" :aria-label="item.label" :aria-current="active === item.path ? 'page' : undefined" @pointerenter="prefetch(item.path)" @focus="prefetch(item.path)" @click="setOpenMobile(false)">
                        <span class="nav-item-icon" aria-hidden="true"><component :is="item.icon" /></span><span class="nav-item-label">{{ item.label }}</span>
                      </RouterLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </CollapsibleContent>
          </SidebarGroup>
        </Collapsible>
      </nav>
    </SidebarContent>
    <SidebarFooter class="sidebar-foot">
      <UserAvatarMenu :collapsed="collapsed" @theme="themeOpen = true" />
      <SidebarTrigger access="read" class="sidebar-toggle" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" :aria-expanded="!collapsed" />
    </SidebarFooter>
  </Sidebar>
  <ThemeDialog v-model="themeOpen" />
</template>

<style scoped src="./AppSidebar.css"></style>
