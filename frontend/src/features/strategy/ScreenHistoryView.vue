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
import ScreenRunBanners from './components/ScreenRunBanners.vue'
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
import { useWorkbenchAbandon } from './composables/useWorkbenchAbandon'
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
  runningStrategies,
  runningLabels,
  atCapacity,
  lastError: screenLastError,
} = storeToRefs(screenRun)

/**
 * 当前选中的战法 slug（技能不占进度槽，给空串）。
 *
 * 页面上所有「在跑吗 / 到几 % / 日志 / 结果」都从**这个战法自己的槽**取：后端
 * 进度槽已经是「租户 × 战法」双层，别的战法在跑与本页无关。
 */
const engineSlug = computed(() =>
  selected.value?.kind === 'engine' ? selected.value.slug : '',
)
const engineSnap = computed(() => screenRun.runFor(engineSlug.value))
const engineRunning = computed(() => screenRun.isRunning(engineSlug.value))
const enginePercent = computed(() => screenRun.percentFor(engineSlug.value))
const engineResult = computed(() => screenRun.resultFor(engineSlug.value))
const engineElapsed = computed(() => screenRun.elapsedTextFor(engineSlug.value))
const engineAbandoned = computed(() => screenRun.abandonedFor(engineSlug.value))

/** 并行跑着的**其它**战法：只是告知，不阻塞本页开跑 */
const parallelRuns = computed(() =>
  runningStrategies.value
    .filter((slug) => slug !== engineSlug.value)
    .map((slug) => ({
      slug,
      label: strategyLabel(slug),
      percent: screenRun.percentFor(slug),
      detail: screenRun.detailFor(slug),
    })),
)

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
  skillActive,
  skillElapsedText,
  skillAbandoned,
  reply: sendSkillReply,
  abandon: abandonSkill,
} = useWorkbenchSkillRun()

const { abandonEngineRun, abandonActiveRun } = useWorkbenchAbandon({
  screenRun,
  engineSlug: () => engineSlug.value,
  engineRunning,
  skillActive,
  abandonSkill,
  selectedKind: () => selected.value?.kind ?? null,
})

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
    return skillActive.value ? '技能运行中' : '跑技能'
  }
  if (engineRunning.value) return `选股中 ${enginePercent.value}%`
  // 并发到顶才等；别的战法在跑不再挡住这一个（后端已是战法级多槽）
  if (atCapacity.value) return '等一个跑完'
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
  // 只禁「正在跑的这一个战法」+ 并发到顶；这就是多槽改造要的效果
  return !screenRun.canStart(engineSlug.value)
})

const detailDisabled = computed(() => !selected.value)

/**
 * 并发到顶时的提示。
 *
 * 这里**不再**说「引擎在跑，什么都点不了」——后端进度槽是战法级的，只有真的
 * 到了同时在跑的上限才需要等，而且要说清「谁在跑、先停哪一个」。
 */
const capacityNotice = computed(() =>
  atCapacity.value && !engineRunning.value
    ? `同时最多 ${screenRun.maxConcurrentRuns} 个选股在跑（${runningLabels.value}），先停一个或等一个跑完`
    : '',
)

const runPanelElapsed = computed(() =>
  selected.value?.kind === 'skill' ? skillElapsedText.value : engineElapsed.value,
)

const runPanelCanAbandon = computed(() =>
  selected.value?.kind === 'skill' ? skillActive.value : engineRunning.value,
)

/** 跳到某个并行跑着的战法去看它的进度 */
function focusRun(slug: string): void {
  if (!slug) return
  select(`engine:${slug}`)
}

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
  engineResult,
  (value) => {
    if (value?.picks) lastResult.value = value
  },
  { immediate: true },
)

// 只关心**本战法**跑完：并行的其它战法结束不该刷这一页的历史
watch(
  () => engineSnap.value?.status,
  (status, prev) => {
    if (prev === 'running' && status === 'done') {
      void refetchHistory()
      void loadCatalog()
    }
  },
)

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
  if (!screenRun.canStart(slug)) {
    // 「等一下」不是答复：说清是谁在跑、先停哪一个
    runError.value = screenRun.blockedReason(slug)
    ElMessage.warning(runError.value)
    if (screenRun.isRunning(slug)) focusRun(slug)
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

    <ScreenRunBanners
      :parallel-runs="parallelRuns"
      :capacity-notice="capacityNotice"
      :abandoned-percent="engineAbandoned?.percent ?? null"
      :abandoned-stopping="engineAbandoned?.stopping ?? false"
      :skill-abandoned="skillAbandoned && !skillActive"
      @focus-run="focusRun"
      @abandon-run="abandonEngineRun"
      @dismiss-abandoned="screenRun.dismissAbandoned(engineSlug)"
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
          :snap="engineSnap"
          :running="engineRunning"
          :percent="enginePercent"
          :last-result="lastResult"
          :skill-busy="skillBusy"
          :skill-log="skillLog"
          :skill-run="skillRun"
          v-model:skill-reply="skillReply"
          :skill-active="skillActive"
          :elapsed-text="runPanelElapsed"
          :can-abandon="runPanelCanAbandon"
          @abandon="abandonActiveRun"
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
      :running="engineRunning"
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

<style scoped src="./ScreenHistoryView.css"></style>

<style>
.screen-history-dialog.el-dialog {
  max-width: 96vw;
}

.screen-history-dialog .el-dialog__body {
  padding-top: 0.45rem;
  padding-bottom: 0.85rem;
}
</style>
