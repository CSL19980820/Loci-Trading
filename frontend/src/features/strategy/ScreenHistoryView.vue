<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { Label } from '@/shared/components/ui/label'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/components/ui/dropdown-menu'
import { Ellipsis, SlidersHorizontal } from '@lucide/vue'
import { DialogDescription, DialogFooter } from '@/shared/components/ui/dialog'
import { CircleAlert, Clock, Info, ListFilter, Play, RefreshCw, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { getMarketSession, getProviders } from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import { Switch } from '@/shared/components/ui/switch'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { strategyLabel } from '@/shared/lib/format'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import type { LlmProvider, ScreenResult } from '@/shared/types/quant'
import { useUserStore } from '@/shared/stores/user'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
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

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const isMobile = useMobileLayout()
const conditionsOpen = ref(false)
const conditionRange = ref<TradeDateRange | null>(null)
const conditionRecord = ref(true)
const conditionProvider = ref('')
watch(conditionsOpen, open => {
  if (open) { conditionRange.value = dateRange.value ? [...dateRange.value] as TradeDateRange : null; conditionRecord.value = recordCandidates.value; conditionProvider.value = skillProvider.value }
})
function applyConditions(): void {
  dateRange.value = conditionRange.value
  if (userStore.canWrite) { recordCandidates.value = conditionRecord.value; skillProvider.value = conditionProvider.value }
  conditionsOpen.value = false
}
/** ≤640 目录不占左栏，从页头「目录」按钮拉出贴底 sheet */
const catalogOpen = ref(false)

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
/** 详情随选中变：战法详情/技能详情，未选中时说清先选 */
const detailLabel = computed(() => {
  if (selected.value?.kind === 'skill') return '技能详情'
  if (selected.value?.kind === 'engine') return '战法详情'
  return '详情'
})

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
  if (syncingQuery || route.name !== 'screen-history') return
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
    if (syncingQuery || route.name !== 'screen-history') return
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


async function refreshAll(): Promise<void> {
  await loadCatalog()
  readQueryState()
  if (selected.value?.kind === 'engine') void refetchHistory()
  try {
    const [providerList, session] = await Promise.all([
      userStore.canWrite ? getProviders() : Promise.resolve([]),
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
    toast.warning(runError.value)
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
    toast.warning(runError.value)
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
    toast.warning(runError.value)
    return
  }
  if (outcome === 'error') {
    runError.value = screenLastError.value || '启动选股失败'
    return
  }
  toast.info(start && end && start !== end ? '区间选股已在后台进行' : '选股已在后台进行，进度见跑道')
}

async function onRerun(date: string): Promise<void> {
  dateRange.value = [date, date]
  historyOpen.value = false
  const target = selected.value
  if (!target || target.kind !== 'engine') {
    toast.warning('请先选中战法再重跑')
    return
  }
  await runEngine(target.slug, date)
}

function openDetail(): void {
  const target = selected.value
  if (!target) return
  if (target.kind === 'engine') {
    if (!selectedStrategy.value) {
      toast.warning('战法详情尚未加载完，请刷新后再试')
      return
    }
    strategyDetailOpen.value = true
    return
  }
  if (!selectedSkill.value) {
    toast.warning('技能详情尚未加载完，请刷新后再试')
    return
  }
  skillDetailOpen.value = true
}

function openHistory(): void {
  if (selected.value?.kind === 'engine') void refetchHistory()
  historyOpen.value = true
}

/** 手机端从 sheet 里选完就收起，让结果区立刻露出来 */
function selectFromSheet(id: string): void {
  select(id)
  catalogOpen.value = false
}

const selectedKindLabel = computed(() =>
  selected.value?.kind === 'skill' ? '技能' : selected.value?.kind === 'engine' ? '战法' : '',
)

onMounted(() => {
  void screenRun.hydrate()
  void refreshAll()
})
</script>

<template>
  <div class="screen-workspace page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <header v-if="isMobile" class="screen-phone-header"><h1>选股</h1><div><Button access="read" variant="ghost" size="icon" aria-label="选股条件" @click="conditionsOpen = true"><SlidersHorizontal /></Button><DropdownMenu><DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="选股操作"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem access="read" :disabled="detailDisabled" @select="openDetail"><Info />{{ detailLabel }}</DropdownMenuItem><DropdownMenuItem access="read" :disabled="!selected" @select="openHistory"><Clock />入库历史</DropdownMenuItem><DropdownMenuItem access="read" :disabled="catalogLoading" @select="refreshAll"><RefreshCw />刷新目录</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div></header>
    <h1 v-else class="sr-only">选股</h1>
    <div v-if="isMobile" class="screen-phone-choice"><Button access="read" variant="outline" class="screen-phone-catalog" aria-haspopup="dialog" @click="catalogOpen = true"><ListFilter /><span>{{ selected?.name || '选择战法或技能' }}</span></Button><Button v-if="userStore.canWrite" :disabled="primaryDisabled" class="screen-phone-run" @click="runPrimary"><Spinner v-if="engineRunning || skillBusy" class="animate-spin" /><Play v-else />{{ primaryLabel }}</Button></div>
    <div v-if="isMobile" class="screen-phone-scope"><span>{{ dateRange ? `${dateRange[0]} — ${dateRange[1]}` : '默认交易日' }}</span><span v-if="userStore.canWrite">{{ recordCandidates && selected?.kind !== 'skill' ? '入库候选' : '不自动入库' }}</span></div>

    <PageToolbar v-if="!isMobile" dense class="screen-primary-toolbar">
      <TradeDateRangeField v-model="dateRange" :last-trading-day="lastTradingDay" />
      <Label v-if="userStore.canWrite" class="screen-toolbar__check">
        <Checkbox
          :model-value="recordCandidates"
          :disabled="selected?.kind === 'skill'"
          aria-label="入库候选"
          @update:model-value="(value) => (recordCandidates = value === true)"
        />
        <span>入库候选</span>
      </Label>
      <Select
        v-if="userStore.canWrite && selected?.kind === 'skill'"
        :model-value="skillProvider"
        @update:model-value="(value) => (skillProvider = String(value))"
      >
        <SelectTrigger size="sm" class="w-36" aria-label="技能模型供应商">
          <SelectValue placeholder="LLM" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="p in providers" :key="p.name" :value="p.name">{{ p.name }}</SelectItem>
        </SelectContent>
      </Select>
      <template #actions>
        <Button access="read" variant="outline" size="sm" :disabled="detailDisabled" @click="openDetail">
   <Info aria-hidden="true" />
          {{ detailLabel }}
        </Button>

        <Button access="read" v-if="isMobile" variant="outline" size="sm" class="screen-mobile-catalog" aria-haspopup="dialog" :aria-expanded="catalogOpen" @click="catalogOpen = true">
          <ListFilter aria-hidden="true" />
          {{ selected ? selected.name : '选目录' }}
        </Button>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="刷新目录" :disabled="catalogLoading" @click="refreshAll">
          <Spinner v-if="catalogLoading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <RefreshCw v-else aria-hidden="true" />
        </Button>
        <Button access="read" variant="outline" size="sm" :disabled="!selected" @click="openHistory">
          <Clock aria-hidden="true" />
          入库历史
        </Button>
        <Tooltip v-if="userStore.canWrite" :disabled="Boolean(selected)">
          <TooltipTrigger as-child>
            <Button class="screen-run-primary" size="sm" :disabled="primaryDisabled" @click="runPrimary">
              <Spinner
                v-if="selected?.kind === 'skill' && skillBusy"
                class="animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              <Play v-else aria-hidden="true" />
              {{ primaryLabel }}
            </Button>
          </TooltipTrigger>
          <TooltipContent v-if="!selected" side="bottom" align="end">
            先在目录里选一个战法或技能
          </TooltipContent>
        </Tooltip>
            </template>
    </PageToolbar>

    <Alert v-if="pageError" variant="destructive" class="screen-alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ pageError }}</AlertTitle>
        <Button access="read"
          variant="ghost"
          size="icon-xs"
          aria-label="关闭提示"
          class="shrink-0"
          @click="runError = ''"
        >
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

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

    <div class="screen-workspace-grid" :class="{ 'screen-workspace-grid--single': isMobile }">
      <aside v-if="!isMobile" class="screen-catalog" aria-label="战法与技能目录">
        <ScreenCatalogRail
          v-model:kind-filter="kindFilter"
          :rows="filtered"
          :selected-id="selectedId"
          :loading="catalogLoading"
          @select="select"
        />
      </aside>

      <div class="screen-workspace-run flex min-h-0 min-w-0 flex-col" role="region" aria-label="选股执行与结果">
        <ScreenRunPanel
          :kind="selected?.kind ?? null"
          :selected-name="selected?.name ?? ''"
          :kind-label="selectedKindLabel"
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

    <!-- 手机：目录从底部拉出 -->
    <Dialog v-model:open="conditionsOpen"><DialogContent class="screen-conditions-dialog sm:max-w-lg"><DialogHeader><DialogTitle>选股条件</DialogTitle><DialogDescription class="sr-only">交易日期、模型与候选入库方式</DialogDescription></DialogHeader><TradeDateRangeField v-model="conditionRange" :last-trading-day="lastTradingDay" /><Label v-if="userStore.canWrite" class="screen-condition-record"><Checkbox v-model="conditionRecord" :disabled="selected?.kind === 'skill'" />入库候选</Label><Select v-if="userStore.canWrite && selected?.kind === 'skill'" v-model="conditionProvider"><SelectTrigger aria-label="技能模型供应商"><SelectValue placeholder="选择模型供应商" /></SelectTrigger><SelectContent><SelectItem v-for="provider in providers" :key="provider.name" :value="provider.name">{{ provider.name }}</SelectItem></SelectContent></Select><DialogFooter><Button access="read" variant="outline" @click="conditionsOpen = false">取消</Button><Button access="read" @click="applyConditions">应用</Button></DialogFooter></DialogContent></Dialog>
    <Sheet v-if="isMobile" v-model:open="catalogOpen">
      <SheetContent side="left" class="screen-catalog-sheet gap-0 p-0">
        <SheetHeader class="border-b border-line px-4 py-3 text-left">
          <SheetTitle class="text-title">战法与技能目录</SheetTitle>
        </SheetHeader>
        <div class="screen-catalog-sheet__body">
          <ScreenCatalogRail
            v-model:kind-filter="kindFilter"
            :rows="filtered"
            :selected-id="selectedId"
            :loading="catalogLoading"
            @select="selectFromSheet"
          />
        </div>
      </SheetContent>
    </Sheet>

    <Dialog v-model:open="historyOpen">
      <DialogContent class="screen-history-dialog gap-3 sm:max-w-4xl">
        <DialogHeader class="gap-1 text-left">
          <DialogTitle>{{ historyTitle }}</DialogTitle>
        </DialogHeader>
        <div class="screen-history-dialog__body">
          <Alert v-if="historyError" variant="destructive">
            <CircleAlert />
            <div class="flex w-full min-w-0 items-start justify-between gap-2">
              <AlertTitle class="line-clamp-none min-w-0">
                {{ historyError instanceof Error ? historyError.message : String(historyError) }}
              </AlertTitle>
              <Button access="read" variant="outline" size="sm" class="shrink-0" @click="refetchHistory">
                重试
              </Button>
            </div>
          </Alert>
          <div class="screen-history-toolbar">
            <span class="text-aux text-mist">
              {{ historyIncludeBackfill ? '含回填' : '仅真选' }}
            </span>
            <Switch v-model="historyIncludeBackfill" aria-label="含区间回填" />
          </div>
          <ScreenHistoryPanel
            :capability-name="selected?.name ?? ''"
            :history="history"
            :loading="historyPending"
            :running="engineRunning"
            @rerun="onRerun"
            @refresh="refetchHistory"
          />
        </div>
      </DialogContent>
    </Dialog>

    <StrategyDetailDialog v-model="strategyDetailOpen" :strategy="selectedStrategy" />
    <SkillDetailDialog
      v-model="skillDetailOpen"
      :skill="selectedSkill"
      @open-screen="skillDetailOpen = false"
    />
  </div>
</template>

<style scoped src="./ScreenWorkspace.css"></style>
