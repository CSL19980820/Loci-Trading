<script setup lang="ts">
import {
  Brush,
  Collection,
  Cpu,
  DataAnalysis,
  DataBoard,
  EditPen,
  Expand,
  Fold,
  Flag,
  Histogram,
  MagicStick,
  Notebook,
  Odometer,
  Opportunity,
  QuestionFilled,
  Search,
  Setting,
  Stamp,
  TrendCharts,
} from '@element-plus/icons-vue'
import { computed, ref, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import type { RecordKind } from '@/shared/components/dialogs/RecordDialog.vue'
import ThemeDialog from '@/shared/components/dialogs/ThemeDialog.vue'
import { createDesktopShortcut, getDataLocation } from '@/shared/api/quant'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'

defineProps<{
  archivePath?: string | null
}>()

const emit = defineEmits<{
  record: [kind: RecordKind]
}>()

const brandName = BRAND_NAME
const brandMark = BRAND_MARK

const route = useRoute()
const collapsed = ref(false)
const themeOpen = ref(false)

type NavLeaf = { path: string; label: string; icon: Component }
type NavGroup = { id: string; label: string; icon: Component; items: NavLeaf[] }

const navGroups: NavGroup[] = [
  {
    id: 'daily',
    label: '日常',
    icon: Collection,
    items: [
      { path: '/', label: '盘面', icon: Odometer },
      { path: '/ledger', label: '账本', icon: Notebook },
      { path: '/journal', label: '交割', icon: EditPen },
      { path: '/pool', label: '候选池', icon: Opportunity },
      { path: '/reviews', label: '绩效', icon: Stamp },
      { path: '/winrate', label: '胜率', icon: TrendCharts },
    ],
  },
  {
    id: 'strat',
    label: '战法',
    icon: Flag,
    items: [
      { path: '/screen-history', label: '选股', icon: Search },
      { path: '/insights', label: '体检', icon: DataAnalysis },
    ],
  },
  {
    id: 'sys',
    label: '本机',
    icon: Cpu,
    items: [
      { path: '/quant', label: '工坊', icon: Histogram },
      { path: '/data', label: '行情', icon: DataBoard },
      { path: '/strategy-converter', label: '策稿', icon: MagicStick },
      { path: '/ops', label: '设置', icon: Setting },
    ],
  },
]

const recordEntries: { kind: RecordKind; label: string }[] = [
  { kind: 'candidate', label: '候选' },
  { kind: 'plan', label: '预案' },
  { kind: 'review', label: '复盘' },
  { kind: 'snapshot', label: '资产' },
  { kind: 'cashflow', label: '出入金' },
]

const openeds = computed(() => navGroups.map((g) => g.id))

const active = computed(() => {
  if (route.path.startsWith('/archive')) return route.path
  if (route.path.startsWith('/reviews')) return '/reviews'
  return route.path
})

function onRecord(kind: RecordKind): void {
  emit('record', kind)
}

function openTheme(): void {
  themeOpen.value = true
}

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
    <div class="brand-row">
      <RouterLink class="brand" to="/" aria-label="首页">
        <span class="brand-mark" aria-hidden="true">{{ brandMark }}</span>
        <strong v-if="!collapsed" class="brand-name">{{ brandName }}</strong>
      </RouterLink>
    </div>

    <div class="brand-rule" aria-hidden="true" />

    <el-menu
      :default-active="active"
      :default-openeds="openeds"
      :collapse="collapsed"
      :collapse-transition="false"
      popper-class="side-menu-popup"
      router
      class="side-menu"
    >
      <el-sub-menu v-for="group in navGroups" :key="group.id" :index="group.id">
        <template #title>
          <el-icon><component :is="group.icon" /></el-icon>
          <span>{{ group.label }}</span>
        </template>
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-sub-menu>
    </el-menu>

    <div class="tool-rail" :class="{ 'tool-rail--collapsed': collapsed }">
      <div v-if="!collapsed" class="tool-rail-label">工具</div>

      <el-dropdown trigger="click" class="tool-dropdown" @command="onRecord">
        <el-button text class="tool-row" :title="collapsed ? '记一笔' : undefined">
          <el-icon><EditPen /></el-icon>
          <span v-if="!collapsed" class="tool-row-label">记一笔</span>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item
              v-for="entry in recordEntries"
              :key="entry.kind"
              :command="entry.kind"
            >
              {{ entry.label }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-dropdown trigger="click" class="tool-dropdown" @command="onHelpCommand">
        <el-button text class="tool-row" :title="collapsed ? '帮助' : undefined">
          <el-icon><QuestionFilled /></el-icon>
          <span v-if="!collapsed" class="tool-row-label">帮助</span>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="shortcut">创建桌面快捷方式</el-dropdown-item>
            <el-dropdown-item command="data">打开数据目录</el-dropdown-item>
            <el-dropdown-item divided command="readme">使用说明</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-button
        text
        class="tool-row"
        :title="collapsed ? '主题' : undefined"
        @click="openTheme"
      >
        <el-icon><Brush /></el-icon>
        <span v-if="!collapsed" class="tool-row-label">主题</span>
      </el-button>

      <el-button
        text
        class="tool-row"
        :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
        :title="collapsed ? '展开' : '收起侧栏'"
        @click="collapsed = !collapsed"
      >
        <el-icon>
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
        <span v-if="!collapsed" class="tool-row-label">收起侧栏</span>
      </el-button>
    </div>
  </aside>

  <ThemeDialog v-model="themeOpen" />
</template>

<style scoped>
.app-sidebar {
  height: 100%;
  min-height: 0;
  width: 13.5rem;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0.75rem 0.55rem 0.55rem;
  border-right: 1px solid var(--rule);
  background: var(--sheet);
  transition: width 0.2s ease;
  overflow: hidden;
  box-sizing: border-box;
}

.app-sidebar.collapsed {
  width: 3.75rem;
  padding-inline: 0.4rem;
}

.brand-row {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 1.85rem;
  margin-bottom: 0.55rem;
}

.app-sidebar:not(.collapsed) .brand-row {
  justify-content: flex-start;
  padding-inline: 0.2rem;
}

.brand-rule {
  height: 1px;
  margin: 0 0.15rem 0.45rem;
  background: var(--rule);
  flex-shrink: 0;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.15rem 0.25rem;
  text-decoration: none;
  color: inherit;
  min-width: 0;
}

.app-sidebar.collapsed .brand {
  padding: 0.15rem 0;
  justify-content: center;
  width: 100%;
}

.brand-name {
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--ink);
  white-space: nowrap;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 1.65rem;
  height: 1.65rem;
  border-radius: var(--radius);
  background: var(--seal);
  color: #fff;
  font-family: var(--font-display);
  font-size: 0.82rem;
  font-weight: 700;
  flex-shrink: 0;
}

.side-menu {
  flex: 1 1 auto;
  min-height: 0;
  border-right: 0 !important;
  background: transparent !important;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  width: 100%;
  padding-bottom: 0.35rem;
}

.side-menu :deep(.el-sub-menu__title),
.side-menu :deep(.el-menu-item) {
  height: 2.125rem;
  line-height: 2.125rem;
  margin: 0 0.1rem 0.1rem;
  border-radius: var(--radius);
  border-left: 0 !important;
}

.side-menu :deep(.el-sub-menu__title) {
  color: var(--mist);
  font-weight: 550;
}

.side-menu :deep(.el-menu-item) {
  padding-left: 2.35rem !important;
}

.app-sidebar.collapsed .side-menu:deep(.el-menu--collapse) {
  width: 100% !important;
}

.app-sidebar.collapsed .side-menu :deep(.el-menu--collapse > .el-sub-menu) {
  width: 100%;
  display: flex;
  justify-content: center;
}

.app-sidebar.collapsed .side-menu :deep(.el-sub-menu__title) {
  box-sizing: border-box;
  padding: 0 !important;
  width: 2.35rem;
  height: 2.35rem;
  margin: 0.12rem 0;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
}

.app-sidebar.collapsed .side-menu :deep(.el-sub-menu__title > span) {
  display: none !important;
  width: 0 !important;
  height: 0 !important;
  overflow: hidden !important;
}

.app-sidebar.collapsed .side-menu :deep(.el-sub-menu__title .el-icon) {
  margin: 0 !important;
  width: 1rem;
  justify-content: center;
}

.app-sidebar.collapsed .side-menu :deep(.el-sub-menu__title .el-sub-menu__icon-arrow) {
  display: none !important;
}

.app-sidebar.collapsed .side-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  background: var(--seal-soft) !important;
  color: var(--seal-ink) !important;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--seal-soft) !important;
  color: var(--seal-ink) !important;
  /* 选中只靠底色，不要左侧竖线 */
  box-shadow: none !important;
  border-left: 0 !important;
}

.tool-rail {
  flex-shrink: 0;
  min-height: 11.5rem;
  margin-top: auto;
  padding: 0.55rem 0.1rem 0.15rem;
  border-top: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.tool-rail--collapsed {
  min-height: 10.5rem;
  align-items: center;
  padding-inline: 0;
}

.tool-rail-label {
  font-size: 0.62rem;
  font-weight: 550;
  letter-spacing: 0.1em;
  color: var(--mist);
  opacity: 0.85;
  padding: 0.1rem 0.55rem 0.35rem;
}

.tool-dropdown {
  width: 100%;
  display: block;
}

.tool-rail--collapsed .tool-dropdown {
  width: auto;
}

.tool-row.el-button {
  box-sizing: border-box;
  width: 100%;
  height: 2.125rem;
  margin: 0;
  padding: 0 0.65rem;
  display: inline-flex;
  justify-content: flex-start;
  align-items: center;
  gap: 0.5rem;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--mist);
  font: inherit;
  font-size: 0.82rem;
  font-weight: 500;
  text-align: left;
}

.tool-rail--collapsed .tool-row.el-button {
  width: 2.25rem;
  padding: 0;
  justify-content: center;
}

.tool-row.el-button:hover,
.tool-row.el-button:focus {
  color: var(--ink);
  background: var(--panel-2);
}

.tool-row .el-icon {
  font-size: 1rem;
  flex-shrink: 0;
  margin: 0;
}

.tool-row-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 980px) {
  .app-sidebar {
    display: none;
  }
}
</style>

<style>
/* 折叠侧栏 flyout：仅 side-menu-popup，不污染全站 el-menu */
.el-popper.is-light.side-menu-popup {
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
}

.side-menu-popup.el-menu--popup-container {
  padding: 0;
  background: transparent;
  border: none;
  box-shadow: none;
}

.side-menu-popup .el-menu.el-menu--popup {
  min-width: 9.5rem !important;
  width: max-content;
  max-width: 11rem;
  padding: 0.28rem !important;
  border: 1px solid var(--rule) !important;
  border-radius: var(--radius) !important;
  background: var(--sheet) !important;
  box-shadow: var(--shadow) !important;
}

.side-menu-popup .el-menu--popup .el-menu-item {
  height: 2.125rem !important;
  line-height: 2.125rem !important;
  margin: 0.06rem 0 !important;
  padding: 0 0.6rem 0 0.5rem !important;
  border-radius: var(--radius) !important;
  color: var(--ink) !important;
  font-size: 0.82rem;
  font-family: var(--font);
  display: flex !important;
  align-items: center;
  gap: 0.45rem;
}

.side-menu-popup .el-menu--popup .el-menu-item .el-icon {
  margin: 0 !important;
  font-size: 1rem;
  color: var(--mist);
  flex-shrink: 0;
}

.side-menu-popup .el-menu--popup .el-menu-item:hover,
.side-menu-popup .el-menu--popup .el-menu-item:focus {
  background: var(--panel-2) !important;
  color: var(--ink) !important;
}

.side-menu-popup .el-menu--popup .el-menu-item.is-active {
  background: var(--seal-soft) !important;
  color: var(--seal-ink) !important;
  box-shadow: none !important;
  font-weight: 550;
}

.side-menu-popup .el-menu--popup .el-menu-item.is-active .el-icon {
  color: var(--seal-ink);
}
</style>
