<script setup lang="ts">
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { SidebarGroup, SidebarMenu, SidebarMenuItem, SidebarMenuButton } from '@/shared/components/ui/sidebar' 
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { ChevronRight, FileCheck, Gauge, KeyRound, Logs, ShieldCheck, Users } from '@lucide/vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { useUserStore } from '@/shared/stores/user'
import OverviewTab from './components/OverviewTab.vue'
import UsersTab from './components/UsersTab.vue'
import LoginsTab from './components/LoginsTab.vue'
import AuditTab from './components/AuditTab.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const mobile = useMobileLayout()
const compactNavigation = useMediaQuery('(max-width: 980px)')
const groups = [
  { name: 'platform', label: '用量', icon: Gauge, items: [{ name: 'overview', label: '大模型用量', icon: Gauge }] },
  { name: 'accounts', label: '账号', icon: Users, items: [{ name: 'users', label: '账号管理', icon: Users }] },
  { name: 'logs', label: '日志', icon: Logs, items: [{ name: 'logins', label: '登录日志', icon: KeyRound }, { name: 'audit', label: '审计日志', icon: FileCheck }] },
]
const items = groups.flatMap(group => group.items)
const collapsed = ref<string[]>([])
const active = computed({
  get: () => items.some(item => item.name === route.query.tab) ? String(route.query.tab) : 'overview',
  set: (tab: string) => { if (items.some(item => item.name === tab)) void router.replace({ query: { ...route.query, tab } }) },
})
function toggle(name: string): void { collapsed.value = collapsed.value.includes(name) ? collapsed.value.filter(item => item !== name) : [...collapsed.value, name] }
</script>
<template>
  <div class="admin-view page-fill">
    <MobilePageHeader v-if="mobile" title="管理后台" />
    <h1 v-else class="sr-only">管理后台</h1>
    <EmptyState v-if="!userStore.isAdmin" description="仅管理员可访问" :icon="ShieldCheck"><Button access="read" as-child variant="outline"><RouterLink to="/">返回首页</RouterLink></Button></EmptyState>
    <template v-else>
      <PageTabs v-if="compactNavigation" panel-id="admin-main-panel" v-model="active" :items="items" variant="pill" :sticky="false" class="admin-mobile-tabs" aria-label="管理分区" />
      <div class="admin-layout">
        <nav v-if="!compactNavigation" class="admin-rail" aria-label="管理后台导航">
          <Collapsible v-for="group in groups" :key="group.name" :open="!collapsed.includes(group.name)" @update:open="toggle(group.name)">
            <SidebarGroup class="admin-group">
              <CollapsibleTrigger class="admin-group__trigger"><component :is="group.icon" /><span>{{ group.label }}</span><ChevronRight class="admin-group__caret" :class="{ 'is-open': !collapsed.includes(group.name) }" /></CollapsibleTrigger>
              <CollapsibleContent><SidebarMenu class="admin-group__items"><SidebarMenuItem v-for="item in group.items" :key="item.name"><SidebarMenuButton :is-active="active === item.name" class="admin-item" :class="{ 'is-active': active === item.name }" :aria-current="active === item.name ? 'page' : undefined" @click="active = item.name"><component :is="item.icon" /><span>{{ item.label }}</span></SidebarMenuButton></SidebarMenuItem></SidebarMenu></CollapsibleContent>
            </SidebarGroup>
          </Collapsible>
        </nav>
        <main id="admin-main-panel" class="admin-content" :role="compactNavigation ? 'tabpanel' : undefined" :tabindex="compactNavigation ? 0 : undefined" :aria-labelledby="compactNavigation ? `admin-main-panel-tab-${active}` : undefined" :aria-label="items.find(item => item.name === active)?.label">
          <OverviewTab v-if="active === 'overview'" />
          <UsersTab v-else-if="active === 'users'" />
          <LoginsTab v-else-if="active === 'logins'" />
          <AuditTab v-else-if="active === 'audit'" />
        </main>
      </div>
    </template>
  </div>
</template>
<style scoped src="./AdminView.css" />
