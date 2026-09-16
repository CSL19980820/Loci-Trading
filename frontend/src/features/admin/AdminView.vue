<script setup lang="ts">
import { computed, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, Coin, DocumentChecked, Key, Odometer, User } from '@element-plus/icons-vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { useUserStore } from '@/shared/stores/user'
import AnnouncementsTab from './components/AnnouncementsTab.vue'
import AuditTab from './components/AuditTab.vue'
import LoginsTab from './components/LoginsTab.vue'
import OverviewTab from './components/OverviewTab.vue'
import QuotaTab from './components/QuotaTab.vue'
import UsersTab from './components/UsersTab.vue'

type AdminTab = 'overview' | 'users' | 'quota' | 'logins' | 'audit' | 'announcements'

/** 左栏分区。顺序即视觉顺序；name 同时充当 el-menu 的 index 与右侧 Tab 的判据。 */
const RAIL_ITEMS: ReadonlyArray<{ name: AdminTab; label: string; icon: Component }> = [
  { name: 'overview', label: '平台总览', icon: Odometer },
  { name: 'users', label: '用户管理', icon: User },
  { name: 'quota', label: '配额管理', icon: Coin },
  { name: 'logins', label: '登录日志', icon: Key },
  { name: 'audit', label: '审计日志', icon: DocumentChecked },
  { name: 'announcements', label: '全站公告', icon: Bell },
]

const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

const activeTab = ref<AdminTab>('overview')

/** el-menu 的 index 是 string；这里收窄回联合类型，右侧 Tab 的 v-if 才有类型保障。 */
function onSelect(index: string): void {
  activeTab.value = index as AdminTab
}

function goHome(): void {
  void router.push('/')
}
</script>

<template>
  <div class="admin-view page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <!-- 非管理员权限拦截空态 -->
    <div v-if="!isAdmin" class="admin-forbidden flex min-h-0 flex-1 items-center justify-center">
      <EmptyState description="仅管理员可访问" reason="请联系管理员开通权限">
        <el-button type="primary" @click="goHome">返回首页</el-button>
      </EmptyState>
    </div>

    <!-- 管理后台主体 -->
    <div v-else class="admin-layout">
      <!-- 左侧导航 Rail：el-menu 自带 role=menu、方向键遍历与 focus 环 -->
      <aside class="admin-rail">
        <div class="rail-header">
          <span class="rail-title kicker">平台治理</span>
        </div>
        <el-menu
          class="rail-nav"
          :default-active="activeTab"
          :collapse-transition="false"
          aria-label="平台治理分区"
          @select="onSelect"
        >
          <el-menu-item v-for="item in RAIL_ITEMS" :key="item.name" :index="item.name">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </el-menu>
      </aside>

      <!-- 右侧主内容区 -->
      <main class="admin-content" :aria-label="RAIL_ITEMS.find(item => item.name === activeTab)?.label">
        <OverviewTab v-if="activeTab === 'overview'" />
        <UsersTab v-else-if="activeTab === 'users'" />
        <QuotaTab v-else-if="activeTab === 'quota'" />
        <LoginsTab v-else-if="activeTab === 'logins'" />
        <AuditTab v-else-if="activeTab === 'audit'" />
        <AnnouncementsTab v-else-if="activeTab === 'announcements'" />
      </main>
    </div>
  </div>
</template>

<style scoped src="./AdminView.css" />
