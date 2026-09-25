<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onMounted, ref, useId, watch } from 'vue'
import { Database, RefreshCw, TriangleAlert, Wrench, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

import AkshareToolTable from './components/AkshareToolTable.vue'
import LanePurposeBoard from './components/LanePurposeBoard.vue'
import McpToolListDrawer from './components/McpToolListDrawer.vue'
import SourceCardGrid from './components/SourceCardGrid.vue'
import SourceDetailDrawer from './components/SourceDetailDrawer.vue'
import { useAkshareTools } from './composables/useAkshareTools'
import { useDataSources } from './composables/useDataSources'

const props = defineProps<{
  /** 深链进来时的初始视图（sources / purpose / interfaces） */
  initialView?: string
}>()

const emit = defineEmits<{
  /** 数据源家数，给工坊 Tab 的角标用（只数源，不数工具） */
  'count-changed': [count: number]
}>()

const {
  loading,
  error,
  notice,
  busyKey,
  code,
  runs,
  stats,
  sources,
  laneRows,
  brokenRequiredLanes,
  load,
  probeSource,
  probeLane,
  probeAll,
  downloadTest,
  toggleSource,
  toggleTool,
  savePolicy,
} = useDataSources()

const {
  catalog: akshareCatalog,
  versionInfo: akshareVersion,
  loading: akshareLoading,
  busy: akshareBusy,
  error: akshareError,
  notice: akshareNotice,
  probeResult: akshareProbeResult,
  batchOpen: akshareBatchOpen,
  batchProgress: akshareBatchProgress,
  batchResults: akshareBatchResults,
  load: loadAkshare,
  checkVersion: checkAkshareVersion,
  probeAll: probeAllAkshare,
  stopBatch: stopAkshareBatch,
  probe: probeAkshare,
} = useAkshareTools()

type PanelView = 'sources' | 'purpose' | 'interfaces'

const VIEWS: PanelView[] = ['sources', 'purpose', 'interfaces']

function parseView(raw: string | undefined): PanelView {
  return VIEWS.includes(raw as PanelView) ? (raw as PanelView) : 'sources'
}

const view = ref<PanelView>(parseView(props.initialView))
/** PageTabs 只认 string，这里做一次窄化 */
const viewTab = computed({
  get: () => view.value as string,
  set: (next: string) => {
    view.value = parseView(next)
  },
})
const detailId = ref('')
const detailOpen = ref(false)
const mcpOpen = ref(false)
const interfaceSource = ref('')

const viewItems = [
  { name: 'sources', label: '按数据源' },
  { name: 'purpose', label: '按用途' },
  { name: 'interfaces', label: '按接口' },
]

const detailRow = computed(() => sources.value.find((row) => row.id === detailId.value) ?? null)

function openInterfaces(id: string): void {
  // 目录里的 provider 就是来源 id（东财=eastmoney…），可以直接当筛选值
  interfaceSource.value = id
  view.value = 'interfaces'
  detailOpen.value = false
}

const brokenText = computed(() =>
  brokenRequiredLanes.value.map((row) => row.label).join('、'),
)

function openDetail(id: string): void {
  detailId.value = id
  detailOpen.value = true
}

// 成功回执是一次性反馈，不配占一条常驻横条：弹 toast 后立刻把 notice 清干净
watch([notice, akshareNotice], ([main, akshare]) => {
  const text = main || akshare
  if (!text) return
  toast.success(text)
  notice.value = ''
  akshareNotice.value = ''
})

watch(
  () => stats.value.total,
  (total) => emit('count-changed', total),
  { immediate: true },
)

// 目录有几千条，进「按接口」再拉，别拖慢首屏
watch(
  view,
  (next) => {
    if (next === 'interfaces' && !akshareCatalog.value) void loadAkshare()
  },
  { immediate: true },
)

watch(
  () => props.initialView,
  (next) => {
    view.value = parseView(next)
  },
)

onMounted(() => {
  void load()
})

function setAkshareBatchOpen(open: boolean): void {
  akshareBatchOpen.value = open
}
const panelId = `datasource-panel-${useId()}`
</script>

<template>
  <div class="ds-panel min-w-0 overflow-hidden" aria-label="数据源控制台">
    <header class="ds-head">
      <div class="ds-head__lead">
        <PageTabs
          v-model="viewTab"
          :panel-id="panelId"
          class="ds-views"
          :items="viewItems"
          variant="pill"
          dense
          :sticky="false"
          aria-label="数据源视图"
        />
        <p class="ds-readout" aria-label="数据源统计">
          <Database class="ds-readout__icon" aria-hidden="true" />
          <span>数据源 <b>{{ stats.total }}</b></span>
          <UiBadge variant="ok" dot>启用 {{ stats.enabled }}</UiBadge>
          <UiBadge v-if="stats.disabled" variant="secondary" dot>停用 {{ stats.disabled }}</UiBadge>
        </p>
      </div>

      <div class="ds-bar__tools">
        <Button variant="ghost" size="sm" class="ds-mcp" @click="mcpOpen = true">
          <Wrench />
          MCP 工具清单
        </Button>
        <template v-if="view !== 'interfaces'">
          <Input
            v-model="code"
            class="ds-code"
            size="sm"
            maxlength="6"
            inputmode="numeric"
            placeholder="样例代码"
            aria-label="探测用样例代码"
          />
          <Select v-model="runs">
            <SelectTrigger size="sm" class="ds-runs" aria-label="探测次数">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem :value="1">1 次</SelectItem>
              <SelectItem :value="2">2 次</SelectItem>
              <SelectItem :value="3">3 次</SelectItem>
            </SelectContent>
          </Select>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button size="sm" :disabled="busyKey === 'all'" @click="probeAll()">
                <Spinner v-if="busyKey === 'all'" class="size-4 animate-spin" aria-hidden="true" />
                探测线路
              </Button>
            </TooltipTrigger>
            <TooltipContent>探测所有行情线路的连通性（不是 AkShare 接口全测）</TooltipContent>
          </Tooltip>
        </template>
        <Button access="read" variant="outline" size="sm" :disabled="loading" aria-label="刷新" @click="view === 'interfaces' ? loadAkshare() : load()">
          <RefreshCw :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>
    </header>

    <!-- 常驻故障条：标题压到 8 字，后果与线路名进 tooltip（不写 description） -->
    <Tooltip v-if="brokenRequiredLanes.length">
      <TooltipTrigger as-child>
        <Alert class="ds-alert">
          <TriangleAlert />
          <AlertTitle class="line-clamp-none min-w-0">必需线路无可用源</AlertTitle>
        </Alert>
      </TooltipTrigger>
      <TooltipContent>{{ brokenText }}：这几条线路已无可用源，同步与选股会直接失败</TooltipContent>
    </Tooltip>
    <Alert v-if="error" variant="destructive" class="ds-alert">
      <TriangleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <Alert v-if="akshareError" class="ds-alert text-warn">
      <TriangleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ akshareError }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="akshareError = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <div :id="panelId" class="ds-body" role="tabpanel" tabindex="0" :aria-labelledby="`${panelId}-tab-${viewTab}`">
      <AkshareToolTable
        v-if="view === 'interfaces'"
        :catalog="akshareCatalog"
        :busy="akshareBusy || akshareLoading"
        :probe-result="akshareProbeResult"
        :version-info="akshareVersion"
        :batch-open="akshareBatchOpen"
        :batch-progress="akshareBatchProgress"
        :batch-results="akshareBatchResults"
        :source="interfaceSource"
        @probe="probeAkshare"
        @probe-all="probeAllAkshare()"
        @stop-batch="stopAkshareBatch()"
        @check-version="checkAkshareVersion()"
        @update:batch-open="setAkshareBatchOpen"
      />
      <PageBusy v-else-if="loading && !sources.length" label="加载数据源…" />
      <template v-else-if="sources.length">
        <SourceCardGrid
          v-if="view === 'sources'"
          :rows="sources"
          :busy-key="busyKey"
          @open="openDetail"
          @probe="probeSource"
          @toggle="({ id, enabled }) => toggleSource(id, enabled)"
          @interfaces="openInterfaces"
        />
        <LanePurposeBoard
          v-else
          :rows="laneRows"
          :busy-key="busyKey"
          @toggle-tool="({ id, lane, enabled }) => toggleTool(id, lane, enabled)"
          @probe="probeLane"
          @download="downloadTest"
          @save-policy="({ lane, policy }) => savePolicy(lane, policy)"
        />
      </template>
      <EmptyState
        v-else
        description="暂无数据源"
        reason="刷新后检查服务配置"
        :icon="Database"
        class="ds-empty"
      >
        <Button access="read" @click="load()">刷新</Button>
      </EmptyState>
    </div>

    <McpToolListDrawer v-model="mcpOpen" />

    <SourceDetailDrawer
      v-model="detailOpen"
      :row="detailRow"
      :busy-key="busyKey"
      @probe="probeSource"
      @toggle-source="({ id, enabled }) => toggleSource(id, enabled)"
      @toggle-tool="({ id, lane, enabled }) => toggleTool(id, lane, enabled)"
      @interfaces="openInterfaces"
    />
  </div>
</template>

<style scoped>
.ds-panel {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

/* 顶部一行：左侧视图药片 + 读数，右侧工具；透明底坐在画布上 */
.ds-head {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-3);
  margin-bottom: var(--gap-3);
}

.ds-head__lead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  min-width: 0;
}

.ds-readout {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.ds-readout__icon {
  width: 14px;
  height: 14px;
}

.ds-readout b {
  color: var(--text-primary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.ds-bar__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
  margin-left: auto;
}

.ds-mcp {
  color: var(--text-secondary);
}

.ds-code {
  width: 6.5rem;
  font-family: var(--mono);
}

.ds-runs {
  width: 5.5rem;
}

.ds-alert {
  flex-shrink: 0;
  margin-bottom: var(--gap-2);
}

.ds-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  padding: 2px 2px var(--gap-4);
  overflow: auto;
  scrollbar-width: thin;
}

.ds-empty {
  min-height: 260px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

@media (max-width: 640px) {
  .ds-bar__tools {
    width: 100%;
    margin-left: 0;
  }

  .ds-bar__tools > :deep(button) {
    min-height: 36px;
  }
}
</style>
