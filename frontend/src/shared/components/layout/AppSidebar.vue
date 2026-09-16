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
 *
 * 本文件只剩版型编排。菜单数据与选中态在 composables/useSidebarNav.ts，
 * 悬停预取在 composables/useRoutePrefetch.ts，帮助菜单三条命令在 sidebarHelp.ts，
 * 皮肤在同目录 AppSidebar.css（`<style scoped src>`，仍是 scoped）。
 */
import { ref } from 'vue'
import { Expand, Fold, QuestionFilled } from '@element-plus/icons-vue'

import ThemeDialog from '@/shared/components/dialogs/ThemeDialog.vue'
import NotificationCenter from '@/shared/components/layout/NotificationCenter.vue'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import UserAvatarMenu from '@/features/auth/UserAvatarMenu.vue'
import { useRoutePrefetch } from './composables/useRoutePrefetch'
import { useSidebarNav } from './composables/useSidebarNav'
import { runHelpCommand } from './sidebarHelp'

const brandName = BRAND_NAME
const brandMark = BRAND_MARK

const collapsed = ref(false)

const {
  navGroups,
  defaultOpeneds,
  active,
  footItems,
  footActive,
  unread,
  themeOpen,
  notifyOpen,
  onFootClick,
} = useSidebarNav()

const { prefetchRoute } = useRoutePrefetch()
</script>

<template>
  <aside class="app-sidebar flex h-full min-h-0 flex-col overflow-hidden" :class="{ collapsed }" aria-label="工作台导航">
    <!-- 顶部 Brand：Logo与名称居左，折叠按钮移至最右顶边 -->
    <div class="brand-row flex shrink-0 items-center justify-between">
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
          :aria-expanded="!collapsed"
          :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
          @click="collapsed = !collapsed"
        >
          <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
        </el-button>
      </el-tooltip>
    </div>

    <!-- 中间菜单区：独立滚动，一级与二级支持折叠展开，一级带icon，展开收起完全对齐 -->
    <div class="side-menu-wrap min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
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
      底部固定区：同款菜单项（消息 / 主题 / 设置 / 管理后台）+ 用户行。
      整块 flex-shrink:0，上方菜单再长也压不到它，两边各自滚各自的。
    -->
    <div class="sidebar-foot shrink-0">
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
      <!-- 用户行：左头像菜单，右边只留「帮助」一颗图标 -->
      <div class="foot-user flex min-w-0 items-center gap-2" :class="{ 'foot-user--collapsed': collapsed }">
        <UserAvatarMenu :collapsed="collapsed" />

        <div class="foot-actions">
          <el-dropdown
            trigger="click"
            :placement="collapsed ? 'right-end' : 'top-end'"
            @command="runHelpCommand"
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

<style scoped src="./AppSidebar.css"></style>
