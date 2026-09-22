<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { CircleAlert, CircleCheck, RefreshCw, X } from '@lucide/vue'

import PageHeader from '@/shared/components/layout/PageHeader.vue'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { confirmAction } from '@/shared/lib/confirm'
import LlmTab from './components/LlmTab.vue'
import McpTab from './components/McpTab.vue'
import SettingsRail, {
  type SettingsRailGroup,
} from './components/SettingsRail.vue'
import SystemTab from './components/SystemTab.vue'
import RetentionSettingsTab from './components/RetentionSettingsTab.vue'
import { provideOpsFeedback } from './composables/useOpsFeedback'
import {
  type OpsTab,
  useSettingsSummaries,
} from './composables/useSettingsSummaries'

type TabLoadable = { load: () => Promise<void> }
type SystemTabExpose = TabLoadable & {
  applyRecommendedSync: () => void
  isDirty: () => boolean
}

const TAB_NAMES = new Set<string>(['mcp', 'llm', 'system', 'retention'])
const mobile = useMobileLayout()

const SYSTEM_LEGACY: Record<string, string> = {
  'data-dir': 'sys-sync',
  'market-sync': 'sys-sync',
  notify: 'sys-notify',
  appearance: 'sys-sync',
}

function normalizeTab(raw: unknown): OpsTab {
  const value = String(raw || 'mcp')
  if (value in SYSTEM_LEGACY) return 'system'
  return (TAB_NAMES.has(value) ? value : 'mcp') as OpsTab
}

const { busy, notice, errorText, guard } = provideOpsFeedback()
const { summaries, refresh: refreshSummaries, refreshAppearanceLocal } =
  useSettingsSummaries()
const route = useRoute()
const router = useRouter()

/** 旧 Tab 迁走：技能→市场；线路/AkShare→数据源；定时/执行历史→工坊定时；四联→系统 */
const LEGACY_TAB_TARGETS: Record<string, { path: string; query: Record<string, string>; hash?: string }> = {
  guardian: { path: '/agents/guardian', query: {} },
  pack: { path: '/ops', query: { tab: 'system' } },
  signals: { path: '/ops', query: { tab: 'system' } },
  skills: { path: '/quant', query: { tab: 'market', shelf: 'installed', kind: 'skill' } },
  lanes: { path: '/quant', query: { tab: 'sources' } },
  akshare: { path: '/quant', query: { tab: 'sources', view: 'interfaces' } },
  jobs: { path: '/quant', query: { tab: 'jobs' } },
  runs: { path: '/quant', query: { tab: 'jobs', runs: '1' } },
  'data-dir': { path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' },
  'market-sync': { path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' },
  notify: { path: '/ops', query: { tab: 'system' }, hash: '#sys-notify' },
  appearance: { path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' },
}

function redirectLegacyTab(raw: unknown): boolean {
  const target = LEGACY_TAB_TARGETS[String(raw || '')]
  if (!target) return false
  void router.replace(target)
  return true
}

redirectLegacyTab(route.query.tab)

const activeTab = ref<OpsTab>(normalizeTab(route.query.tab))
const visited = reactive<Record<OpsTab, boolean>>({
  mcp: false,
  llm: false,
  system: false,
  retention: false,
})
visited[activeTab.value] = true

/** 「系统」页里的四个锚点段，摆到 rail 上才是能点的导航。 */
const railGroups = computed((): SettingsRailGroup[] => [
  {
    title: '模型与工具',
    items: [
      { name: 'mcp', label: '工具连接', ...summaries.mcp, tail: summaries.mcp.tail },
      { name: 'llm', label: 'AI 模型', ...summaries.llm, tail: summaries.llm.tail },
    ],
  },
  {
    title: '系统管理',
    items: [
      { name: 'system', label: '系统', ...summaries.system, children: undefined },
      { name: 'retention', label: '日志与数据', ...summaries.retention },
    ],
  },
])

const activeAnchor = computed(() => route.hash.replace(/^#/, ''))

/** 点二级项：切到系统页 + 落到那一段，并把 hash 写进地址栏（可分享、可回退）。 */
async function goAnchor(anchor: string): Promise<void> {
  if (activeTab.value !== 'system') {
    activeTab.value = 'system'
    // 先让 activeTab 的 watcher 把它那次 router.replace 打完，否则它会把 hash 抹掉
    await nextTick()
  }
  await router.replace({ query: { ...route.query, tab: 'system' }, hash: `#${anchor}` })
  await nextTick()
  document.getElementById(anchor)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

const mobileTabs = computed(() =>
  railGroups.value.flatMap((g) => g.items.map((i) => ({ name: i.name, label: i.label }))),
)

const activeLabel = computed(
  () => railGroups.value.flatMap((g) => g.items).find((i) => i.name === activeTab.value)?.label || '设置',
)

const mcpTab = ref<TabLoadable | null>(null)
const llmTab = ref<TabLoadable | null>(null)
const systemTab = ref<SystemTabExpose | null>(null)
const retentionTab = ref<(TabLoadable & { isDirty: () => boolean }) | null>(null)

function tabLoader(tab: OpsTab): TabLoadable | null {
  const map: Record<OpsTab, { value: TabLoadable | null }> = {
    mcp: mcpTab,
    llm: llmTab,
    system: systemTab,
    retention: retentionTab,
  }
  return map[tab].value
}

function systemIsDirty(): boolean {
  return Boolean(systemTab.value?.isDirty())
}

async function confirmLeaveDirty(): Promise<boolean> {
  if (!systemIsDirty() && !retentionTab.value?.isDirty()) return true
  return confirmAction({
    message: '设置有未保存改动，离开将丢失。',
    title: '未保存',
    confirmText: '离开',
    cancelText: '留下',
  })
}

async function loadActiveTab(): Promise<void> {
  visited[activeTab.value] = true
  await nextTick()
  await tabLoader(activeTab.value)?.load()
  if (activeTab.value === 'system' && route.hash) {
    await nextTick()
    document.getElementById(route.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }
}

async function reload(): Promise<void> {
  if (!(await confirmLeaveDirty())) return
  // 首次/手动刷新才更新轻量侧栏摘要，切换分区只读取对应内容。
  void refreshSummaries().catch(() => undefined)
  await guard(loadActiveTab)
}

function onAppearanceChanged(): void {
  refreshAppearanceLocal()
}

let restoringTab = false
watch(activeTab, async (tab, prev) => {
  if (restoringTab) { restoringTab = false; return }
  if (route.name !== 'ops') return
  if (['system', 'retention'].includes(prev) && tab !== prev && !(await confirmLeaveDirty())) {
    restoringTab = true
    activeTab.value = prev
    return
  }
  const next = { ...route.query, tab: tab === 'mcp' ? undefined : tab }
  void router.replace({ query: next, hash: tab === 'system' ? route.hash : '' })
  void guard(loadActiveTab)
})

watch(
  () => route.query.tab,
  (tab) => {
    // KeepAlive 中的设置页离开后仍有 watcher；不能消费其他页面的 tab。
    if (route.name !== 'ops') return
    if (redirectLegacyTab(tab)) return
    const next = normalizeTab(tab)
    if (next !== activeTab.value) activeTab.value = next
  },
)

onBeforeRouteLeave(async (_to, _from, next) => {
  if (await confirmLeaveDirty()) next()
  else next(false)
})

onMounted(() => {
  void reload()
})
</script>

<template>
  <div class="page-fill ops-page">
    <MobilePageHeader v-if="mobile" title="设置">
      <template #actions><Button access="read" variant="ghost" size="icon" aria-label="刷新设置" :disabled="busy" @click="reload"><RefreshCw :class="{ 'animate-spin': busy }" /></Button></template>
    </MobilePageHeader>
    <PageHeader v-else
      title="设置"
      seamless
      class="ops-page__head"
    >
      <template #actions>
        <Button access="read" variant="outline" size="sm" :disabled="busy" @click="reload">
          <RefreshCw :class="busy ? 'animate-spin' : ''" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <Alert v-if="notice" class="ops-page__alert">
      <CircleCheck />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ notice }}</AlertTitle>
        <Button variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="notice = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>
    <Alert v-if="errorText" variant="destructive" class="ops-page__alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ errorText }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="errorText = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <div class="ops-mobile-tabs">
      <PageTabs
        v-model="activeTab"
        :items="mobileTabs"
        variant="pill"
        dense
        :sticky="false"
        aria-label="设置分区"
      />
    </div>

    <div class="ops-layout">
      <SettingsRail
        v-model="activeTab"
        class="ops-rail"
        :groups="railGroups"
        :active-anchor="activeAnchor"
        @select-anchor="goAnchor"
      />

      <div
        class="ops-content"
        role="tabpanel"
        :aria-label="activeLabel"
      >
        <PageBusy overlay :busy="busy" label="加载设置…" />
        <div v-if="visited.mcp" v-show="activeTab === 'mcp'" class="ops-pane">
          <McpTab ref="mcpTab" @changed="refreshSummaries" />
        </div>
        <div v-if="visited.llm" v-show="activeTab === 'llm'" class="ops-pane">
          <LlmTab ref="llmTab" @changed="refreshSummaries" />
        </div>
        <div v-if="visited.system" v-show="activeTab === 'system'" class="ops-pane">
          <SystemTab
            ref="systemTab"
            @jobs-changed="refreshSummaries"
            @changed="() => { refreshSummaries(); onAppearanceChanged() }"
          />
        </div>
        <div v-if="visited.retention" v-show="activeTab === 'retention'" class="ops-pane"><RetentionSettingsTab ref="retentionTab" /></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ops-page {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.ops-page__head {
  padding-bottom: var(--gap-3);
}

.ops-page__alert {
  flex-shrink: 0;
  margin-bottom: var(--gap-3);
}

.ops-layout {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.ops-rail {
  min-height: 0;
}

.ops-content {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.ops-pane {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  padding-right: var(--gap-1);
}

.ops-mobile-tabs {
  display: none;
  flex-shrink: 0;
  margin-bottom: var(--gap-3);
}

.ops-mobile-tabs :deep(.page-tabs__list) {
  width: 100%;
}

.ops-mobile-tabs :deep(.page-tabs__item) {
  flex: 1 1 auto;
  justify-content: center;
  height: 32px;
}

@media (max-width: 980px) {
  .ops-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }

  .ops-rail {
    display: none;
  }

  .ops-mobile-tabs {
    display: block;
  }
}

@media (max-width: 640px) {
  .ops-pane {
    padding-right: 0;
  }

  /* 手机上页头只留眉题 + 标题 + 动作，描述让位给内容 */
  .ops-page__head :deep(.page-header__desc) {
    display: none;
  }

  .ops-page__head :deep(.page-header__row) {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}
@media(max-width:767px) {
  .ops-mobile-tabs { margin-bottom:8px; }
  .ops-mobile-tabs :deep(.page-tabs__item) { height:38px; font-size:12px; }
  .ops-layout { flex:1 1 0%; }
  .ops-pane { padding:0 0 12px; }
  .ops-pane :deep(.mcp-stats) { display:none; }
}
</style>
