<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import HeaderActions from '@/shared/components/layout/HeaderActions.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import LlmTab from './components/LlmTab.vue'
import McpTab from './components/McpTab.vue'
import PackTab from './components/PackTab.vue'
import SignalRulesTab from './components/SignalRulesTab.vue'
import SettingsRail, {
  type SettingsRailGroup,
} from './components/SettingsRail.vue'
import SystemTab from './components/SystemTab.vue'
import { provideOpsFeedback } from './composables/useOpsFeedback'
import {
  type OpsTab,
  type RailSummary,
  useSettingsSummaries,
} from './composables/useSettingsSummaries'

type TabLoadable = { load: () => Promise<void> }
type SystemTabExpose = TabLoadable & {
  applyRecommendedSync: () => void
  isDirty: () => boolean
}

const TAB_NAMES = new Set<string>(['mcp', 'llm', 'system', 'signals', 'pack'])

const SYSTEM_LEGACY: Record<string, string> = {
  'data-dir': 'sys-location',
  'market-sync': 'sys-sync',
  notify: 'sys-notify',
  appearance: 'sys-appearance',
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
  skills: { path: '/quant', query: { tab: 'market', shelf: 'installed', kind: 'skill' } },
  lanes: { path: '/quant', query: { tab: 'sources' } },
  akshare: { path: '/quant', query: { tab: 'sources', view: 'interfaces' } },
  jobs: { path: '/quant', query: { tab: 'jobs' } },
  runs: { path: '/quant', query: { tab: 'jobs', runs: '1' } },
  'data-dir': { path: '/ops', query: { tab: 'system' }, hash: '#sys-location' },
  'market-sync': { path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' },
  notify: { path: '/ops', query: { tab: 'system' }, hash: '#sys-notify' },
  appearance: { path: '/ops', query: { tab: 'system' }, hash: '#sys-appearance' },
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
  signals: false,
  system: false,
  pack: false,
})
visited[activeTab.value] = true

/**
 * 「系统」页里的四个锚点段。
 *
 * 它们此前只存在于页面内部：rail 上只有一个「系统」，想配企微就得进去从头
 * 滚——四段里企微在第三段，滚过头就得往回找。摆到 rail 上才是能点的导航。
 */
const SYSTEM_ANCHORS: { label: string; anchor: string }[] = [
  { label: '数据目录', anchor: 'sys-location' },
  { label: '行情同步', anchor: 'sys-sync' },
  { label: '推送', anchor: 'sys-notify' },
  { label: '外观与窗口', anchor: 'sys-appearance' },
]

const railGroups = computed((): SettingsRailGroup[] => [
  {
    title: '模型与工具',
    items: [
      // 缩写降为副标：主标说人话，MCP / LLM 仍留着，老用户才认得出是同一处
      { name: 'mcp', label: '工具连接', ...summaries.mcp, tail: `MCP · ${summaries.mcp.tail}` },
      { name: 'llm', label: 'AI 模型', ...summaries.llm, tail: `LLM · ${summaries.llm.tail}` },
      // 信号规则：大屏那条信号流按什么口径报，得能在系统里改，不能只活在后端代码里
      { name: 'signals', label: '信号规则', ...summaries.signals },
    ],
  },
  {
    title: '本机',
    items: [
      { name: 'system', label: '系统', ...summaries.system, children: SYSTEM_ANCHORS },
      { name: 'pack', label: '一键打包', ...summaries.pack },
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

const mcpTab = ref<TabLoadable | null>(null)
const llmTab = ref<TabLoadable | null>(null)
const signalsTab = ref<TabLoadable | null>(null)
const systemTab = ref<SystemTabExpose | null>(null)
const packTab = ref<TabLoadable | null>(null)

/** 规则面板自己知道「几条启用」，直接回填 rail，不走全局 summary 拉取。 */
function applySignalSummary(next: RailSummary): void {
  Object.assign(summaries.signals, next)
}

function tabLoader(tab: OpsTab): TabLoadable | null {
  const map: Record<OpsTab, { value: TabLoadable | null }> = {
    mcp: mcpTab,
    llm: llmTab,
    signals: signalsTab,
    system: systemTab,
    pack: packTab,
  }
  return map[tab].value
}

function systemIsDirty(): boolean {
  return Boolean(systemTab.value?.isDirty())
}

async function confirmLeaveDirty(): Promise<boolean> {
  if (!visited.system || !systemIsDirty()) return true
  try {
    await ElMessageBox.confirm('系统页有未保存改动，离开将丢失。', '未保存', {
      confirmButtonText: '离开',
      cancelButtonText: '留下',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
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
  await guard(async () => {
    await loadActiveTab()
    await refreshSummaries()
  })
}

function onAppearanceChanged(): void {
  refreshAppearanceLocal()
}

watch(activeTab, async (tab, prev) => {
  if (prev === 'system' && tab !== 'system' && !(await confirmLeaveDirty())) {
    activeTab.value = 'system'
    return
  }
  const next = { ...route.query, tab: tab === 'mcp' ? undefined : tab }
  void router.replace({ query: next, hash: tab === 'system' ? route.hash : '' })
  void reload()
})

watch(
  () => route.query.tab,
  (tab) => {
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
  <div class="page-fill ops-desk">
    <header class="ops-hero">
      <strong>设置</strong>
      <HeaderActions :actions="[{ key: 'reload', label: '刷新', disabled: busy, onClick: reload }]" />
    </header>

    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      show-icon
      closable
      class="ops-alert"
      @close="notice = ''"
    />
    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="ops-alert"
      @close="errorText = ''"
    />

    <div class="ops-mobile-tabs">
      <PageTabs
        v-model="activeTab"
        :items="mobileTabs"
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
        class="ops-body page-pane"
        role="tabpanel"
        :aria-label="railGroups.flatMap((g) => g.items).find((i) => i.name === activeTab)?.label || '设置'"
      >
        <PageBusy overlay :busy="busy" label="加载设置…" />
        <div v-if="visited.mcp" v-show="activeTab === 'mcp'" class="ops-pane">
          <McpTab ref="mcpTab" @changed="refreshSummaries" />
        </div>
        <div v-if="visited.llm" v-show="activeTab === 'llm'" class="ops-pane">
          <LlmTab ref="llmTab" @changed="refreshSummaries" />
        </div>
        <div v-if="visited.signals" v-show="activeTab === 'signals'" class="ops-pane">
          <SignalRulesTab ref="signalsTab" @summary="applySignalSummary" />
        </div>
        <div v-if="visited.system" v-show="activeTab === 'system'" class="ops-pane">
          <SystemTab
            ref="systemTab"
            @jobs-changed="refreshSummaries"
            @changed="() => { refreshSummaries(); onAppearanceChanged() }"
          />
        </div>
        <div v-if="visited.pack" v-show="activeTab === 'pack'" class="ops-pane">
          <PackTab ref="packTab" @changed="refreshSummaries" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ops-desk {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ops-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.85rem;
  flex-shrink: 0;
  border-bottom: 1px solid var(--rule);
}

.ops-hero strong {
  font-family: var(--font-display);
  font-size: 1.2rem;
  font-weight: 600;
}

.ops-alert {
  margin: 0.55rem 0.85rem 0;
  flex-shrink: 0;
}

.ops-mobile-tabs {
  display: none;
  flex-shrink: 0;
  border-bottom: 1px solid var(--rule);
}

.ops-mobile-tabs :deep(.page-tabs) {
  margin-bottom: 0;
  padding-left: 0.5rem;
  padding-right: 0.5rem;
}

.ops-layout {
  display: grid;
  grid-template-columns: 12rem minmax(0, 1fr);
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.ops-rail {
  min-height: 0;
}

.ops-body {
  position: relative;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ops-pane {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
}

.ops-pane :deep(.settings-panel) {
  flex: 1 1 auto;
  min-height: 0;
}

@media (max-width: 900px) {
  .ops-rail {
    display: none;
  }

  .ops-mobile-tabs {
    display: block;
  }

  .ops-layout {
    grid-template-columns: 1fr;
  }
}
</style>
