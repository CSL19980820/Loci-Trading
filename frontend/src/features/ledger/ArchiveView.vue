<script setup lang="ts">
/** 全屏个股档案：单行报价、可收起批次栏和自适应图表，选股记录在弹窗阅读。 */
import { useMediaQuery } from '@vueuse/core'
import ArchiveMobileHeader from './components/ArchiveMobileHeader.vue'
import ArchiveMobileFacts from './components/ArchiveMobileFacts.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, History } from '@lucide/vue'

import ArchiveBatchDock from '@/features/ledger/components/ArchiveBatchDock.vue'
import ArchiveBatchRail from '@/features/ledger/components/ArchiveBatchRail.vue'
import StockTimeline from '@/features/ledger/components/StockTimeline.vue'
import DataQueryDetailPanel from '@/features/market/components/DataQueryDetailPanel.vue'
import { useQuotesQuery } from '@/features/market/composables/useQuotesQuery'
import { chgClass, fmtChange, fmtPct } from '@/features/market/composables/dataQueryFormat'
import { listCandidates } from '@/shared/api/palace'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import { toErrorMessage } from '@/shared/lib/errors'
import { compactNumber, strategyLabel } from '@/shared/lib/format'
import type { StrategySignalMark } from '@/shared/lib/klineStrategyMarks'
import type { IndicatorKind } from '@/shared/lib/klineConfig'
import type { KPeriod } from '@/shared/lib/indicators'
import type { TimelineEvent } from '@/shared/types/palace'

const mobile = useMediaQuery('(max-width:767px)')
function openAssistant(): void { window.dispatchEvent(new CustomEvent('loci:assistant-open')) }
const route = useRoute()
const router = useRouter()
const batch = useBatchBrowseStore()

const code = computed(() => String(route.params.code ?? '').trim())
/** 从选股/回测带入：锚定日 K 到该交易日 */
const focusDate = computed(() => {
  const d = String(route.query.date || '').trim()
  return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : ''
})

const adjust = ref<'qfq' | 'hfq' | 'none'>('qfq')
const period = ref<KPeriod>('day')
const indicator = ref<IndicatorKind>('macd')
const quotesLimit = ref(320)
const narrow = ref(false)
const drawerOpen = ref(false)
const historyOpen = ref(false)
let signalsRequest = 0
const strategySignals = ref<StrategySignalMark[]>([])

async function loadStrategySignals(targetCode: string): Promise<void> {
  const request = ++signalsRequest
  const c = targetCode.trim()
  if (!c) {
    strategySignals.value = []
    return
  }
  try {
    const list = await listCandidates({ code: c, limit: 500, include_backfill: true })
    if (request !== signalsRequest) return
    strategySignals.value = list.map((item) => {
      const rawName = item.rule_version || item.pool_id || '选股'
      const displayName = strategyLabel(rawName)
      return {
        date: item.date,
        strategyName: displayName,
        strategySlug: item.pool_id || item.rule_version,
        decision: item.decision,
        reason: item.reason,
        score: item.score,
      }
    })
  } catch {
    if (request !== signalsRequest) return
    strategySignals.value = []
  }
}
function quotesLimitFor(p: KPeriod): number {
  if (p === 'week') return Math.max(800, quotesLimit.value)
  if (p === 'month') return Math.max(1500, quotesLimit.value)
  return quotesLimit.value
}

const quotesEnabled = computed(() => Boolean(code.value))

const { quote, refetch, isPending, isLoading, error: quoteError, isError: quoteFailed } = useQuotesQuery(code, () => ({
  adjust: adjust.value,
  limit: quotesLimitFor(period.value),
  enabled: quotesEnabled.value,
}))

const quoteBusy = computed(() => isPending.value || isLoading.value)
const quoteErrorText = computed(() =>
  quoteFailed.value ? toErrorMessage(quoteError.value, '行情加载失败') : '',
)

const stockName = computed(() => quote.value?.name || code.value)

const adjustLabel = computed(() => ({ qfq: '前复权', hfq: '后复权', none: '不复权' })[adjust.value])

const lastBar = computed(() => {
  const bars = quote.value?.bars
  return bars?.length ? bars[bars.length - 1] : null
})

const prevBar = computed(() => {
  const bars = quote.value?.bars
  return bars && bars.length >= 2 ? bars[bars.length - 2] : null
})

const lastClose = computed(() => {
  const c = lastBar.value?.close
  return c == null ? '—' : Number(c).toFixed(2)
})

const detailPct = computed(() => {
  const a = Number(prevBar.value?.close)
  const b = Number(lastBar.value?.close)
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return null
  return ((b - a) / a) * 100
})

const detailChange = computed(() => {
  const a = Number(prevBar.value?.close)
  const b = Number(lastBar.value?.close)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return b - a
})

/** 头部元信息：复权 · 最后一根 K 线日期 · 已载根数 */
const headMeta = computed(() => {
  const q = quote.value
  if (!q) return ''
  const parts = [adjustLabel.value]
  if (lastBar.value?.trade_date) parts.push(`${lastBar.value.trade_date} 收盘`)
  if (q.total_rows && q.total_rows > q.rows) parts.push(`${q.rows}/${q.total_rows} 根`)
  else if (q.rows) parts.push(`${q.rows} 根`)
  return parts.join(' · ')
})

function fmtPx(value: number | null | undefined): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2) : '—'
}

/** 与昨收比的涨跌语义：今开 / 最高 / 最低 用它上色 */
function toneVsPrev(value: number | null | undefined): 'up' | 'down' | 'neutral' | '' {
  const prev = Number(prevBar.value?.close)
  const n = Number(value)
  if (!Number.isFinite(prev) || !Number.isFinite(n) || prev === 0) return ''
  if (n > prev) return 'up'
  if (n < prev) return 'down'
  return 'neutral'
}

const amplitude = computed(() => {
  const prev = Number(prevBar.value?.close)
  const high = Number(lastBar.value?.high)
  const low = Number(lastBar.value?.low)
  if (!Number.isFinite(prev) || !Number.isFinite(high) || !Number.isFinite(low) || prev === 0) return ''
  return `振幅 ${(((high - low) / prev) * 100).toFixed(2)}%`
})

const turnoverText = computed(() => {
  const t = lastBar.value?.turnover
  if (t == null || !Number.isFinite(Number(t))) return '—'
  return `${(Number(t) * 100).toFixed(2)}%`
})

const boardTag = computed(() => {
  const q = quote.value
  if (!q) return ''
  const label = String(q.board_label || '').trim()
  if (label) return label
  const raw = String(q.board || '').trim()
  const map: Record<string, string> = {
    main: '主板',
    chi_next: '创业板',
    star: '科创板',
    bse: '北交所',
    主板: '主板',
    创业板: '创业板',
    科创板: '科创板',
    北交所: '北交所',
  }
  if (raw && map[raw]) return map[raw]
  // 无元数据时按代码兜底
  const c = code.value
  if (c.startsWith('688') || c.startsWith('689')) return '科创板'
  if (c.startsWith('300') || c.startsWith('301')) return '创业板'
  if (/^[489]/.test(c) || c.startsWith('92')) return '北交所'
  if (/^\d{6}$/.test(c)) return '主板'
  return raw
})

const industryTag = computed(() => String(quote.value?.industry || '').trim())

/** 选股记录时间线：把该票的候选信号按日倒序排成事件 */
const timelineEvents = computed<TimelineEvent[]>(() =>
  [...strategySignals.value]
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
    .map((mark, index) => ({
      id: `${mark.date}-${mark.strategySlug}-${index}`,
      date: mark.date,
      created_at: '',
      type: 'candidate' as const,
      label: mark.strategyName,
      detail: { score: mark.score, decision: mark.decision, reason: mark.reason },
    })),
)

const hasBatch = computed(() => batch.active)
const canPrev = computed(() => hasBatch.value && batch.index >= 1)
const canNext = computed(
  () => hasBatch.value && batch.index >= 0 && batch.index < batch.total - 1,
)
const showDock = computed(() => hasBatch.value && batch.dockOpen && !narrow.value)

function goBack(): void {
  if (hasBatch.value && batch.session?.sourcePath) {
    void router.push(batch.session.sourcePath)
    return
  }
  if (window.history.length > 1) {
    router.back()
    return
  }
  void router.push('/')
}

function goBatchStep(delta: number): void {
  const nextCode = batch.step(delta)
  if (!nextCode) return
  void router.replace({
    path: `/archive/${nextCode}`,
    query: { ...route.query },
  })
}

function selectBatchCode(nextCode: string): void {
  if (!nextCode || nextCode === code.value) return
  batch.goTo(nextCode)
  void router.replace({
    path: `/archive/${nextCode}`,
    query: { ...route.query },
  })
}

function toggleDock(): void {
  if (narrow.value) {
    drawerOpen.value = !drawerOpen.value
    return
  }
  batch.toggleDock()
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return target.isContentEditable
}

/** 有弹层打开时把按键让给它：否则档案里关个对话框会顺手把整个档案也退掉 */
function hasOpenOverlay(): boolean {
  return Boolean(document.querySelector('[role="dialog"]:not(.archive-overlay), [role="alertdialog"]'))
}

function onKeydown(event: KeyboardEvent): void {
  if (isTypingTarget(event.target)) return
  if (hasOpenOverlay()) return
  if (event.key === 'Escape') {
    event.preventDefault()
    goBack()
    return
  }
  if (!hasBatch.value) return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    goBatchStep(-1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    goBatchStep(1)
  }
}

function updateNarrow(): void {
  narrow.value = window.matchMedia('(max-width: 959px)').matches
}

function extendHistory(): void {
  const q = quote.value
  const total = q?.total_rows ?? 0
  const rows = q?.rows ?? 0
  if (!total || rows >= total) return
  quotesLimit.value = Math.min(total, Math.max(quotesLimit.value, rows) + 240)
}

function retryQuotes(): void {
  void refetch()
}

function barHasFocusDate(q: NonNullable<typeof quote.value>, d: string): boolean {
  return q.bars.some((b) => String(b.trade_date || '').slice(0, 10) === d)
}

watch(
  () => code.value,
  (c) => {
    if (c) {
      batch.syncCode(c)
      void loadStrategySignals(c)
    } else {
      strategySignals.value = []
    }
  },
  { immediate: true },
)

watch(
  () => [quote.value, focusDate.value] as const,
  ([q, d]) => {
    if (!q || !d || period.value !== 'day') return
    if (barHasFocusDate(q, d)) return
    extendHistory()
  },
)

watch(
  () => [adjust.value, period.value, quotesLimit.value] as const,
  () => {
    if (code.value) void refetch()
  },
)

onMounted(() => {
  updateNarrow()
  window.addEventListener('resize', updateNarrow)
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateNarrow)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="page-fill stock-workbench" :class="{ 'stock-workbench--batch': hasBatch }">
    <ArchiveMobileHeader v-if="mobile" :name="stockName" :code="code" :board="boardTag" :industry="industryTag" :price="lastClose" :pct="detailPct" :change="detailChange" :history-count="timelineEvents.length" :batch-position="hasBatch ? batch.positionLabel : undefined" :can-prev="canPrev" :can-next="canNext" @back="goBack" @history="historyOpen = true" @prev="goBatchStep(-1)" @next="goBatchStep(1)" @batch="toggleDock" @chat="openAssistant" />
    <header v-else class="sw-top">
      <div class="sw-top__row">
        <Button access="read"
          variant="ghost"
          size="icon-sm"
          class="sw-back"
          :aria-label="hasBatch ? '返回本批来源' : '返回'"
          aria-keyshortcuts="Escape"
          @click="goBack"
        >
          <ArrowLeft aria-hidden="true" />
        </Button>

        <div class="sw-id">
          <div class="sw-id__row">
            <h1 class="sw-name">{{ stockName }}</h1>
            <span class="sw-code">{{ code }}</span>
            <UiBadge v-if="boardTag" variant="info">{{ boardTag }}</UiBadge>
            <UiBadge v-if="industryTag" variant="outline">{{ industryTag }}</UiBadge>
          </div>
          <p v-if="headMeta" class="sw-meta" :title="headMeta">{{ headMeta }}</p>
        </div>

        <div v-if="quote" class="sw-price" aria-label="最新收盘">
          <span class="sw-last" :class="chgClass(detailPct)">{{ lastClose }}</span>
          <span class="sw-chip" :class="chgClass(detailPct)">
            <span>{{ fmtChange(detailChange) }}</span>
            <span>{{ fmtPct(detailPct) }}</span>
          </span>
        </div>

        <ArchiveBatchRail
          v-if="hasBatch"
          class="sw-rail"
          :position-label="batch.positionLabel"
          :source="batch.session?.source || '本批'"
          :can-prev="canPrev"
          :can-next="canNext"
          :dock-open="narrow ? drawerOpen : batch.dockOpen"
          @prev="goBatchStep(-1)"
          @next="goBatchStep(1)"
          @return-batch="goBack"
          @toggle-dock="toggleDock"
        />
        <Button access="read" variant="outline" size="sm" class="sw-history" @click="historyOpen = true"><History aria-hidden="true" />选股记录<span v-if="timelineEvents.length" class="tabular-nums">{{ timelineEvents.length }}</span></Button>
      </div>
    </header>

    <div class="sw-split">
      <div v-if="hasBatch && !narrow" class="sw-dock" :class="{ 'is-open': showDock }" :inert="!showDock">
      <ArchiveBatchDock
        mode="dock"
        :source="batch.session?.source || '本批'"
        :items="batch.items"
        :active-code="code"
        @select="selectBatchCode"
      />
      </div>
      <ArchiveBatchDock
        v-if="hasBatch && narrow"
        mode="drawer"
        :drawer-open="drawerOpen"
        :source="batch.session?.source || '本批'"
        :items="batch.items"
        :active-code="code"
        @update:drawer-open="drawerOpen = $event"
        @select="selectBatchCode"
      />

      <div class="sw-body">
        <Alert v-if="quoteErrorText" variant="destructive" class="sw-quote-error">
          <AlertTitle class="line-clamp-none min-w-0">{{ quoteErrorText }}</AlertTitle>
          <AlertDescription>
            <Button access="read" variant="outline" size="sm" @click="retryQuotes">重试</Button>
          </AlertDescription>
        </Alert>

        <ArchiveMobileFacts v-if="mobile && (quote || quoteBusy)" :bar="lastBar" :previous="prevBar" />
        <div v-else-if="quote || quoteBusy" class="stat-strip stat-strip--plain sw-kpis" aria-label="最后一根 K 线读数">
          <StatCard layout="row"
            label="昨收"
            :value="fmtPx(prevBar?.close)"
            :title="prevBar?.trade_date || ''"
            :loading="quoteBusy && !lastBar"
          />
          <StatCard layout="row"
            label="今开"
            :value="fmtPx(lastBar?.open)"
            :tone="toneVsPrev(lastBar?.open)"
            :title="lastBar?.trade_date || ''"
            :loading="quoteBusy && !lastBar"
          />
          <StatCard layout="row"
            label="最高"
            :value="fmtPx(lastBar?.high)"
            :tone="toneVsPrev(lastBar?.high)"
            :loading="quoteBusy && !lastBar"
          />
          <StatCard layout="row"
            label="最低"
            :value="fmtPx(lastBar?.low)"
            :tone="toneVsPrev(lastBar?.low)"
            :hint="amplitude"
            :loading="quoteBusy && !lastBar"
          />
          <StatCard layout="row"
            label="成交额"
            :value="compactNumber(lastBar?.amount)"
            :hint="lastBar?.volume != null ? `量 ${compactNumber(lastBar.volume)}` : ''"
            :loading="quoteBusy && !lastBar"
          />
          <StatCard layout="row" label="换手率" :value="turnoverText" :loading="quoteBusy && !lastBar" />
        </div>

        <div class="sw-grid">
          <div class="sw-chart">
            <DataQueryDetailPanel
              embedded
              :detail-code="code"
              :detail-name="stockName"
              :quote="quote"
              :busy="quoteBusy"
              v-model:period="period"
              v-model:indicator="indicator"
              v-model:adjust="adjust"
              :adjust-label="adjustLabel"
              :last-close="lastClose"
              :detail-pct="detailPct"
              :focus-date="focusDate"
              :strategy-signals="strategySignals"
              @adjust-change="refetch"
              @need-history="extendHistory"
            />
          </div>


        </div>
      </div>
    </div>
    <Dialog v-model:open="historyOpen">
      <DialogContent class="sw-history-dialog sm:max-w-3xl">
        <DialogHeader><DialogTitle>{{ stockName }} · 选股记录</DialogTitle><DialogDescription>{{ timelineEvents.length }} 条 · 按选出日倒序</DialogDescription></DialogHeader>
        <div class="sw-history-body">
          <StockTimeline v-if="timelineEvents.length" :events="timelineEvents" :focus-date="focusDate" />
          <EmptyState v-else compact description="还没有选股记录" :icon="History" />
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped src="./ArchiveView.css"></style>
<style scoped src="./ArchiveView.mobile.css"></style>
