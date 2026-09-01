<script setup lang="ts">
/**
 * 个股工作台：行情。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ArchiveBatchDock from '@/features/ledger/components/ArchiveBatchDock.vue'
import ArchiveBatchRail from '@/features/ledger/components/ArchiveBatchRail.vue'
import DataQueryDetailPanel from '@/features/market/components/DataQueryDetailPanel.vue'
import { useQuotesQuery } from '@/features/market/composables/useQuotesQuery'
import { chgClass, fmtPct } from '@/features/market/composables/dataQueryFormat'
import { listCandidates } from '@/shared/api/palace'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import { toErrorMessage } from '@/shared/lib/errors'
import { strategyLabel } from '@/shared/lib/format'
import type { StrategySignalMark } from '@/shared/lib/klineStrategyMarks'
import type { IndicatorKind } from '@/shared/lib/klineConfig'
import type { KPeriod } from '@/shared/lib/indicators'

import './ArchiveView.css'

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
const strategySignals = ref<StrategySignalMark[]>([])

async function loadStrategySignals(targetCode: string): Promise<void> {
  const c = targetCode.trim()
  if (!c) {
    strategySignals.value = []
    return
  }
  try {
    const list = await listCandidates({ code: c, limit: 500, include_backfill: true })
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

const lastClose = computed(() => {
  const bars = quote.value?.bars
  if (!bars?.length) return '—'
  const c = bars[bars.length - 1]?.close
  return c == null ? '—' : Number(c).toFixed(2)
})

const detailPct = computed(() => {
  const bars = quote.value?.bars
  if (!bars || bars.length < 2) return null
  const a = Number(bars[bars.length - 2]?.close)
  const b = Number(bars[bars.length - 1]?.close)
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return null
  return ((b - a) / a) * 100
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
  return Boolean(document.querySelector('.el-overlay'))
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
    <header class="sw-top">
      <div class="sw-id-row">
        <el-button v-if="!hasBatch" size="small" class="sw-back" @click="goBack">返回</el-button>
        <div class="sw-id">
          <strong class="sw-name">{{ stockName }}</strong>
          <span class="mono sw-code">{{ code }}</span>
          <template v-if="quote">
            <span class="mono sw-last" :class="chgClass(detailPct)">{{ lastClose }}</span>
            <span class="mono sw-pct" :class="chgClass(detailPct)">{{ fmtPct(detailPct) }}</span>
          </template>
        </div>
        <div v-if="boardTag || industryTag" class="sw-tags" aria-label="板块与行业">
          <el-tag v-if="boardTag" size="small" effect="plain" type="info">{{ boardTag }}</el-tag>
          <el-tag v-if="industryTag" size="small" effect="plain">{{ industryTag }}</el-tag>
        </div>
        <ArchiveBatchRail
          v-if="hasBatch"
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
      </div>
    </header>

    <div class="sw-split">
      <ArchiveBatchDock
        v-if="showDock"
        mode="dock"
        :source="batch.session?.source || '本批'"
        :items="batch.items"
        :active-code="code"
        @select="selectBatchCode"
      />
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
      <div class="sw-split__main">
        <div class="sw-body sw-body--quote">
          <el-alert
            v-if="quoteErrorText"
            :title="quoteErrorText"
            type="error"
            show-icon
            :closable="false"
          >
            <el-button size="small" @click="retryQuotes">重试</el-button>
          </el-alert>
          <DataQueryDetailPanel
            v-else
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
</template>
