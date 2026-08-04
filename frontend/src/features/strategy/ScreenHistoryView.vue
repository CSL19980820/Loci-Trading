<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight, VideoPlay } from '@element-plus/icons-vue'

import { getMarketSession, getProviders } from '@/shared/api/quant'
import { strategyLabel } from '@/shared/lib/format'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import type { LlmProvider, ScreenResult } from '@/shared/types/quant'

import ScreenCatalogRail from './components/ScreenCatalogRail.vue'
import ScreenHistoryPanel from './components/ScreenHistoryPanel.vue'
import ScreenRunPanel from './components/ScreenRunPanel.vue'
import SkillDetailDialog from './components/SkillDetailDialog.vue'
import StrategyDetailDialog from './components/StrategyDetailDialog.vue'
import TradeDateRangeField from './components/TradeDateRangeField.vue'
import {
  clampTradeDateRange,
  isValidTradeDateRange,
  skillDateFromRange,
  type TradeDateRange,
} from './composables/tradeDateRange'
import { useScreenCatalog } from './composables/useScreenCatalog'
import { useScreenHistoryQuery } from './composables/useScreenHistoryQuery'
import { useWorkbenchSkillRun } from './composables/useWorkbenchSkillRun'

const route = useRoute()
const router = useRouter()

const {
  filtered,
  selected,
  selectedStrategy,
  selectedSkill,
  selectedId,
  kindFilter,
  loading: catalogLoading,
  error: catalogError,
  load: loadCatalog,
  select,
} = useScreenCatalog()

const screenRun = useScreenRunStore()
const {
  snap,
  running,
  busyStrategy,
  percent,
  result: runResult,
  lastError: screenLastError,
} = storeToRefs(screenRun)

const dateRange = ref<TradeDateRange | null>(null)
const lastTradingDay = ref<string | null>(null)
const recordCandidates = ref(true)
const lastResult = ref<ScreenResult | null>(null)
const runError = ref('')
let syncingQuery = false

const providers = ref<LlmProvider[]>([])
const skillProvider = ref('')

const historyOpen = ref(false)
/** 入库历史默认只看盘后真选；打开后可含区间回填 */
const historyIncludeBackfill = ref(false)
const strategyDetailOpen = ref(false)
const skillDetailOpen = ref(false)

const {
  skillBusy,
  skillRun,
  skillLog,
  skillReply,
  error: skillError,
  reset: resetSkill,
  start: startSkill,
  reply: sendSkillReply,
} = useWorkbenchSkillRun()

const {
  history,
  isPending: historyPending,
  error: historyError,
  refetch: refetchHistory,
} = useScreenHistoryQuery(() => ({
  strategy: selected.value?.kind === 'engine' ? selected.value.slug : selected.value?.slug || '',
  limit: 500,
  live_only: !historyIncludeBackfill.value,
}))

const pageError = computed(
  () => catalogError.value || runError.value || skillError.value || '',
)

const primaryLabel = computed(() => {
  if (!selected.value) return '选股'
  if (selected.value.kind === 'skill') {
    return skillBusy.value ? '技能运行中' : '跑技能'
  }
  if (running.value && busyStrategy.value === selected.value.slug) {
    return `选股中 ${percent.value}%`
  }
  if (running.value) return '其它选股进行中'
  const days =
    dateRange.value && dateRange.value[0] !== dateRange.value[1] ? '区间' : ''
  return days ? '区间选股' : '选股'
})

const primaryDisabled = computed(() => {
  if (!selected.value) return true
  if (dateRange.value && !isValidTradeDateRange(dateRange.value)) return true
  if (selected.value.kind === 'skill') {
    return !selected.value.enabled || skillBusy.value || !skillProvider.value
  }
  return running.value
})

const detailDisabled = computed(() => !selected.value)

const historyTitle = computed(() => {
  const name = selected.value?.name || '入库历史'
  const n = history.value?.dates?.length ?? 0
  if (n > 0) return `${name} · ${n} 次`
  return name
})

function readQueryState(): void {
  syncingQuery = true
  try {
    const selectQ = String(route.query.select || '')
    if (selectQ) select(selectQ)

    const kindQ = String(route.query.kind || '')
    if (kindQ === 'engine' || kindQ === 'skill' || kindQ === 'all') {
      kindFilter.value = kindQ
    }

    const from = String(route.query.from || '')
    const to = String(route.query.to || '')
    if (from && to) {
      dateRange.value = clampTradeDateRange([from, to])
    } else if (from) {
      dateRange.value = clampTradeDateRange([from, from])
    } else {
      dateRange.value = null
    }

    if (route.query.record === '0') recordCandidates.value = false
    else if (route.query.record === '1') recordCandidates.value = true
  } finally {
    syncingQuery = false
  }
}

function pushQueryState(): void {
  if (syncingQuery) return
  const query: Record<string, string | undefined> = {}
  for (const [key, value] of Object.entries(route.query)) {
    if (key === 'select' || key === 'kind' || key === 'from' || key === 'to' || key === 'record') {
      continue
    }
    const raw = Array.isArray(value) ? value[0] : value
    if (raw != null && raw !== '') query[key] = String(raw)
  }
  query.select = selectedId.value || undefined
  query.kind = kindFilter.value !== 'all' ? kindFilter.value : undefined
  if (dateRange.value?.[0] && dateRange.value?.[1]) {
    query.from = dateRange.value[0]
    query.to = dateRange.value[1]
  }
  query.record = recordCandidates.value ? undefined : '0'

  const same =
    String(route.query.select || '') === String(query.select || '') &&
    String(route.query.kind || '') === String(query.kind || '') &&
    String(route.query.from || '') === String(query.from || '') &&
    String(route.query.to || '') === String(query.to || '') &&
    String(route.query.record || '') === String(query.record || '')
  if (same) return

  void router.replace({ path: route.path, query })
}

watch(selectedId, () => {
  runError.value = ''
  resetSkill()
  lastResult.value = null
  pushQueryState()
})

watch(kindFilter, () => {
  pushQueryState()
})

watch(dateRange, () => {
  pushQueryState()
}, { deep: true })

watch(recordCandidates, () => {
  pushQueryState()
})

watch(
  () => route.fullPath,
  () => {
    if (syncingQuery) return
    readQueryState()
  },
)

watch(
  runResult,
  (value) => {
    if (value?.picks) lastResult.value = value
  },
  { immediate: true },
)

watch(running, (isRunning, wasRunning) => {
  if (wasRunning && !isRunning && snap.value?.status === 'done') {
    void refetchHistory()
    void loadCatalog()
  }
})

watch(historyError, (err) => {
  if (err) runError.value = err instanceof Error ? err.message : String(err)
})

async function refreshAll(): Promise<void> {
  await loadCatalog()
  readQueryState()
  if (selected.value?.kind === 'engine') void refetchHistory()
  try {
    const [providerList, session] = await Promise.all([
      getProviders(),
      getMarketSession().catch(() => null),
    ])
    providers.value = providerList
    lastTradingDay.value = session?.last_trading_day || session?.coverage_last_date || null
    if (!skillProvider.value) {
      skillProvider.value =
        providers.value.find((p) => p.is_default)?.name || providers.value[0]?.name || ''
    }
  } catch {
    providers.value = []
  }
}

async function runPrimary(): Promise<void> {
  const target = selected.value
  if (!target) return
  if (dateRange.value && !isValidTradeDateRange(dateRange.value)) {
    runError.value = '选股跨度不能超过一个月'
    ElMessage.warning(runError.value)
    return
  }
  if (target.kind === 'skill') {
    runError.value = ''
    const ok = await startSkill({
      slug: target.slug,
      name: target.name,
      provider: skillProvider.value,
      date: skillDateFromRange(dateRange.value),
    })
    if (!ok && skillError.value) runError.value = skillError.value
    return
  }
  await runEngine(target.slug)
}

async function runEngine(slug: string, override?: TradeDateRange | string): Promise<void> {
  runError.value = ''
  if (!screenRun.canStartEngine()) {
    runError.value =
      screenLastError.value ||
      `选股进行中：${busyStrategy.value ? strategyLabel(busyStrategy.value) : '…'}，请等待结束`
    ElMessage.warning(runError.value)
    if (busyStrategy.value) select(`engine:${busyStrategy.value}`)
    return
  }

  let start: string | undefined
  let end: string | undefined
  if (typeof override === 'string' && override) {
    start = override
    end = override
  } else if (Array.isArray(override)) {
    start = override[0]
    end = override[1]
  } else if (dateRange.value) {
    start = dateRange.value[0]
    end = dateRange.value[1]
  }

  const payload =
    start && end
      ? start === end
        ? { strategy: slug, date: start, record_candidates: recordCandidates.value }
        : { strategy: slug, start, end, record_candidates: recordCandidates.value }
      : { strategy: slug, record_candidates: recordCandidates.value }

  const outcome = await screenRun.start(payload)
  if (outcome === 'busy') {
    runError.value = screenLastError.value || '已有选股任务在跑'
    ElMessage.warning(runError.value)
    return
  }
  if (outcome === 'error') {
    runError.value = screenLastError.value || '启动选股失败'
    return
  }
  ElMessage.info(start && end && start !== end ? '区间选股已在后台进行' : '选股已在后台进行，进度见跑道')
}

async function onRerun(date: string): Promise<void> {
  dateRange.value = [date, date]
  historyOpen.value = false
  const target = selected.value
  if (!target || target.kind !== 'engine') {
    ElMessage.warning('请先选中战法再重跑')
    return
  }
  await runEngine(target.slug, date)
}

function openDetail(): void {
  const target = selected.value
  if (!target) return
  if (target.kind === 'engine') {
    if (!selectedStrategy.value) {
      ElMessage.warning('战法详情尚未加载完，请刷新后再试')
      return
    }
    strategyDetailOpen.value = true
    return
  }
  if (!selectedSkill.value) {
    ElMessage.warning('技能详情尚未加载完，请刷新后再试')
    return
  }
  skillDetailOpen.value = true
}

function openHistory(): void {
  if (selected.value?.kind === 'engine') void refetchHistory()
  historyOpen.value = true
}

onMounted(() => {
  void screenRun.hydrate()
  void refreshAll()
})
</script>

<template>
  <div class="page-fill screen-desk">
    <header class="screen-desk__bar">
      <div class="screen-desk__bar-left">
        <TradeDateRangeField v-model="dateRange" :last-trading-day="lastTradingDay" />
        <el-checkbox v-model="recordCandidates" :disabled="selected?.kind === 'skill'">
          入库候选
        </el-checkbox>
        <el-select
          v-if="selected?.kind === 'skill'"
          v-model="skillProvider"
          placeholder="LLM"
          size="small"
          filterable
          style="width: 8.5rem"
        >
          <el-option v-for="p in providers" :key="p.name" :label="p.name" :value="p.name" />
        </el-select>
      </div>
      <div class="screen-desk__bar-spacer" />
      <div class="screen-desk__bar-right">
        <el-button :disabled="detailDisabled" @click="openDetail">详情</el-button>
        <el-button :disabled="!selected" @click="openHistory">入库历史</el-button>
        <el-button :icon="RefreshRight" :loading="catalogLoading" @click="refreshAll">
          刷新
        </el-button>
        <el-button
          type="primary"
          :icon="VideoPlay"
          :loading="selected?.kind === 'skill' && skillBusy"
          :disabled="primaryDisabled"
          @click="runPrimary"
        >
          {{ primaryLabel }}
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="pageError"
      :title="pageError"
      type="error"
      show-icon
      closable
      class="screen-desk__alert"
      @close="runError = ''"
    />

    <div class="screen-desk__body">
      <aside class="screen-desk__rail">
        <ScreenCatalogRail
          v-model:kind-filter="kindFilter"
          :rows="filtered"
          :selected-id="selectedId"
          :loading="catalogLoading"
          @select="select"
        />
      </aside>

      <div class="screen-desk__main">
        <ScreenRunPanel
          :kind="selected?.kind ?? null"
          :selected-name="selected?.name ?? ''"
          :snap="snap"
          :running="running"
          :percent="percent"
          :last-result="lastResult"
          :skill-busy="skillBusy"
          :skill-log="skillLog"
          :skill-run="skillRun"
          v-model:skill-reply="skillReply"
          @reply="sendSkillReply"
        />
      </div>
    </div>

    <el-dialog
      v-model="historyOpen"
      :title="historyTitle"
      width="56rem"
      top="6vh"
      destroy-on-close
      append-to-body
      class="screen-history-dialog"
    >
      <div class="screen-history-toolbar mb">
        <el-switch
          v-model="historyIncludeBackfill"
          inline-prompt
          active-text="含回填"
          inactive-text="仅真选"
        />
      </div>
      <ScreenHistoryPanel
        :capability-name="selected?.name ?? ''"
        :history="history"
        :loading="historyPending"
        :running="running"
        @rerun="onRerun"
        @refresh="refetchHistory"
      />
    </el-dialog>

    <StrategyDetailDialog v-model="strategyDetailOpen" :strategy="selectedStrategy" />
    <SkillDetailDialog
      v-model="skillDetailOpen"
      :skill="selectedSkill"
      @open-screen="skillDetailOpen = false"
    />
  </div>
</template>

<style scoped>
.screen-desk {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-height: 0;
}

.screen-history-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

.screen-desk__bar {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.45rem;
  padding: 0.3rem 0.1rem;
  border-bottom: 1px solid var(--rule);
  min-height: 2.4rem;
  overflow: visible;
}

.screen-desk__bar-left,
.screen-desk__bar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.screen-desk__bar-spacer {
  display: none;
}

.screen-desk__alert {
  flex-shrink: 0;
  margin: 0;
}

.screen-desk__body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(200px, 260px) minmax(0, 1fr);
  gap: 0.55rem;
  overflow: hidden;
}

.screen-desk__rail {
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.screen-desk__main {
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 900px) {
  .screen-desk__body {
    grid-template-columns: 1fr;
  }

  .screen-desk__rail {
    max-height: 12rem;
  }

  .screen-desk__bar {
    grid-template-columns: 1fr;
  }

  .screen-desk__bar-left {
    width: 100%;
  }

  .screen-desk__bar-right {
    justify-content: flex-start;
  }
}
</style>

<style>
.screen-history-dialog.el-dialog {
  max-width: 96vw;
}

.screen-history-dialog .el-dialog__body {
  padding-top: 0.45rem;
  padding-bottom: 0.85rem;
}
</style>
