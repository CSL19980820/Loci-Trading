<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import SegmentSwitch from '@/shared/components/ui/SegmentSwitch.vue'

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
  ElMessage.success(text)
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
</script>

<template>
  <div class="ds-panel">
    <header class="ds-bar">
      <SegmentSwitch
        v-model="view"
        class="ds-views"
        :items="viewItems"
        aria-label="数据源视图"
      />

      <p class="ds-readout" aria-label="数据源统计">
        数据源<b>{{ stats.total }}</b>
        <span class="ds-readout__sep" />
        启用<b>{{ stats.enabled }}</b>
        <span class="ds-readout__sep" />
        停用<b>{{ stats.disabled }}</b>
      </p>

      <div class="ds-bar__tools">
        <el-button class="ds-mcp" link type="primary" @click="mcpOpen = true">MCP 工具清单</el-button>
        <template v-if="view !== 'interfaces'">
          <el-input
            v-model="code"
            class="ds-code"
            size="small"
            maxlength="6"
            inputmode="numeric"
            placeholder="样例代码"
            aria-label="探测用样例代码"
          />
          <el-select v-model="runs" size="small" class="ds-runs" aria-label="探测次数">
            <el-option :value="1" label="1 次" />
            <el-option :value="2" label="2 次" />
            <el-option :value="3" label="3 次" />
          </el-select>
          <el-tooltip content="探测所有行情线路的连通性（不是 AkShare 接口全测）" placement="bottom">
            <el-button
              size="small"
              type="primary"
              :loading="busyKey === 'all'"
              @click="probeAll()"
            >
              探测线路
            </el-button>
          </el-tooltip>
        </template>
        <el-button size="small" :disabled="loading" @click="view === 'interfaces' ? loadAkshare() : load()">
          刷新
        </el-button>
      </div>
    </header>

    <!-- 常驻故障条：标题压到 8 字，后果与线路名进 tooltip（不写 description） -->
    <el-tooltip
      v-if="brokenRequiredLanes.length"
      :content="`${brokenText}：这几条线路已无可用源，同步与选股会直接失败`"
      placement="bottom-start"
    >
      <el-alert type="error" show-icon :closable="false" class="ds-alert" title="必需线路无可用源" />
    </el-tooltip>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      class="ds-alert"
      @close="error = ''"
    />

    <el-alert
      v-if="akshareError"
      :title="akshareError"
      type="warning"
      show-icon
      closable
      class="ds-alert"
      @close="akshareError = ''"
    />

    <div class="ds-body">
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
        description="这台机器上没有报出任何数据源"
        reason="点下面的「刷新」重读一次；仍为空说明程序里的取数源没装上。"
      >
        <el-button type="primary" @click="load()">刷新</el-button>
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
  flex-direction: column;
  min-height: 0;
  /* flex:1 已经吃满父级高度；再写 height:100% 会与它互相打架（体检 §4.4） */
  flex: 1 1 auto;
}

.ds-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  flex-shrink: 0;
  padding: 0 var(--gap-1) var(--gap-2);
}

/* 视图切换是这一页的主导航，比工具条更该被一眼看到 */
.ds-views {
  --el-segmented-padding: 0.2rem;
  --el-segmented-item-selected-bg-color: var(--paper);
  padding: 0.2rem;
  border: 1px solid var(--rule);
  border-radius: calc(var(--radius) + 2px);
  box-shadow: inset 0 1px 2px color-mix(in srgb, var(--ink) 6%, transparent);
}

.ds-views :deep(.el-segmented__item) {
  padding: 0 var(--gap-3);
  font-size: var(--fs-body);
  line-height: var(--ctl-h);
}

.ds-views :deep(.el-segmented__item.is-selected) {
  box-shadow: 0 1px 3px color-mix(in srgb, var(--ink) 12%, transparent);
}

.ds-readout {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.ds-readout b {
  margin-left: 2px;
  font: 700 var(--fs-hero)/1 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.ds-mcp {
  font-size: var(--fs-aux);
}

.ds-readout__sep {
  width: 1px;
  height: 0.85rem;
  margin: 0 var(--gap-1);
  background: var(--rule);
}

.ds-bar__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
  margin-left: auto;
}

.ds-code {
  width: 6.5rem;
}

.ds-runs {
  width: 5.5rem;
}

.ds-alert {
  margin-bottom: var(--gap-2);
  flex-shrink: 0;
}

.ds-body {
  flex: 1 1 auto;
  min-height: 0;
  /* 按用途/按数据源卡片高于视口时在此内滚；按接口表仍靠自身吃满高度 */
  overflow: auto;
  display: flex;
  flex-direction: column;
  padding: var(--gap-1) var(--gap-1) var(--gap-2);
}
</style>
