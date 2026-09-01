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
  <div class="admin-view page-fill">
    <!-- 非管理员权限拦截空态 -->
    <div v-if="!isAdmin" class="admin-forbidden">
      <EmptyState description="仅管理员可访问">
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
      <main class="admin-content">
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

<style scoped>
/* .page-fill 已给 flex 列 + 满高 + overflow:hidden；这里只补主体的收缩位，不再重复定高 */
.admin-forbidden {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.admin-layout {
  display: grid;
  grid-template-columns: 12rem minmax(0, 1fr);
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

/*
 * 断点必须跟全站一致（980px = 侧栏消失、底栏出现的那条线）。
 * 原来写 768 时，769~980px 这段区间里左栏仍占 13rem 而侧栏已经收掉，
 * 右侧 8 列的用户表被挤爆。
 */
@media (max-width: 980px) {
  .admin-layout {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }
}

.admin-rail {
  background: var(--sheet);
  border-right: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.rail-header {
  height: var(--head-h);
  display: flex;
  align-items: center;
  padding: 0 var(--gap-3);
  border-bottom: 1px solid var(--rule);
}

/* 字号/字距/等宽由全局 .kicker 提供，这里只补颜色与不换行 */
.rail-title {
  color: var(--seal-ink);
  white-space: nowrap;
}

.rail-nav {
  --el-menu-bg-color: var(--sheet);
  --el-menu-text-color: var(--muted);
  --el-menu-hover-bg-color: var(--sheet-alt);
  --el-menu-hover-text-color: var(--ink);
  --el-menu-active-color: var(--seal-ink);
  --el-menu-item-height: calc(var(--row-h) + var(--gap-1));
  --el-menu-base-level-padding: var(--gap-3);
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  border-right: none;
  padding: var(--gap-1) 0;
}

/*
 * 选中态与主侧栏（AppSidebar 的 .side-menu .is-active）保持同一种表达：
 * 淡印章底 + 印章字 + 加粗。**不再画左侧 2px 竖条**——全站到处都是这种
 * 左竖条时，它就不再是「选中」的信号，只是噪声（用户点名要去掉）。
 */
.rail-nav :deep(.el-menu-item) {
  font-size: var(--fs-body);
  margin: 0 var(--gap-1);
  border-radius: var(--radius);
}

.rail-nav :deep(.el-menu-item .el-icon) {
  color: var(--mist);
  margin-right: var(--gap-2);
}

.rail-nav :deep(.el-menu-item.is-active) {
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
}

.rail-nav :deep(.el-menu-item.is-active .el-icon) {
  color: var(--seal-ink);
}

.rail-nav :deep(.el-menu-item:focus-visible) {
  outline: 2px solid var(--seal);
  outline-offset: -2px;
}

/* 窄屏：左栏折成一条横向分区条；选中态沿用同一套底色，不额外画线 */
@media (max-width: 980px) {
  .admin-rail {
    flex-direction: row;
    align-items: stretch;
    border-right: none;
    border-bottom: 1px solid var(--rule);
  }

  .rail-header {
    border-bottom: none;
    border-right: 1px solid var(--rule);
    flex: 0 0 auto;
  }

  .rail-nav {
    display: flex;
    flex-direction: row;
    overflow-x: auto;
    padding: var(--gap-1);
  }

  .rail-nav :deep(.el-menu-item) {
    flex: 0 0 auto;
  }
}

/*
 * 分区面板自己吃满剩余高度并在内层滚（.admin-pane / .admin-pane__scroll）。
 * 这里若留 overflow-y:auto，表格分区就会出现「外层也能滚」的双滚动条。
 */
.admin-content {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--paper);
}
</style>
