<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
/**
 * 胜率统计（路由 `/winrate`）。
 *
 * 两层：进来是**综合对比**（各战法横向比 + 同期对比 + 胜率分布），点一行 / 切一个 tab 才进
 * 那个战法自己的证据页（分母公式、最佳最差样本、该拿几天、逐条样本）。
 *
 * 版面：
 *   页头（眉题 = 口径 / 标题 / 分区 Tab：综合对比 + 各战法 / 动作：粒度 · ⓘ口径 · 刷新）
 *   KPI 卡带（综合：综合胜率 · 样本数 · T+5 均收益 · 最佳持有期；战法：该战法四项）
 *   综合：战法横向对比（满幅）→ bento：同期对比（2/3）| 胜率分布（1/3）
 *   战法：证据面板（自带 bento）→ 分周期卡
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CircleAlert, Info, RotateCw, X } from '@lucide/vue'

import {
  CapabilityUnavailableError,
  getWinRateSamples,
  getWinRateSummary,
  getWinRateTrend,
} from '@/shared/api/quant'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import WinRateMobileSummary from './components/WinRateMobileSummary.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'
import { signedPct, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, winRateStatTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateSampleDetail, WinRateSummary, WinRateTrendPoint } from '@/shared/types/quant'

import WinRateCompareTable from './components/WinRateCompareTable.vue'
import WinRatePeriodTable from './components/WinRatePeriodTable.vue'
import WinRateStrategyPanel from './components/WinRateStrategyPanel.vue'

/** 口径说明只写一份：页头 ⓘ 与表内说明共用，避免手抄出两个版本 */
const CALIBER_HINT =
  '胜率口径为精选候选 T+5（另列 T+1/T+3），无候选样本的战法回退手工复盘；盘后「候选T+N跟踪」每日重算 5 个交易日窗口。综合胜率为盈利样本数除以已结算样本数；综合均收益按有收益数据的已结算样本数加权，单战法均收益为已结算样本的算术平均。观察中的样本不计入。分周期按候选选出日聚合，与主表同源。'

const OVERVIEW = 'overview'
const mobile = useMobileLayout()

const summary = ref<WinRateSummary[]>([])
const chartData = ref<WinRateTrendPoint[]>([])
const detail = ref<WinRateSampleDetail | null>(null)
const view = ref<string>(OVERVIEW)
const evidencePane = ref('samples')
const overviewPane = ref('compare')
const granularity = ref<'month' | 'week'>('month')
const busy = ref(false)
const detailBusy = ref(false)
const error = ref('')
let active = true
let requestVersion = 0
let trendVersion = 0
let detailVersion = 0

/** 切回看过的战法不再等一次请求；「刷新」会连它一起清掉 */
const detailCache = new Map<string, WinRateSampleDetail>()

const allTags = computed(() => summary.value.map((row) => row.strategy_tag))
const strategyNames = computed(() => new Map(summary.value.map((row) =>
  [row.strategy_tag, row.strategy_name || '未命名战法'],
)))
const isOverview = computed(() => view.value === OVERVIEW)

const tabItems = computed<PageTabItem[]>(() => [
  { name: OVERVIEW, label: '综合对比' },
  ...summary.value.map((row) => ({
    name: row.strategy_tag,
    label: strategyShortLabel(row.strategy_tag, strategyNames.value),
    badge: Number(row.total) || undefined,
  })),
])

const activeSummary = computed(
  () => summary.value.find((row) => row.strategy_tag === view.value) ?? null,
)

const periodTitle = computed(() => {
  const source = chartData.value[0]?.source === 'reviews' ? '手工复盘' : '精选候选 T+5'
  return isOverview.value
    ? `同期对比（${source}，按选出日）`
    : `分周期（${source}，按选出日）`
})

const granularityLabel = computed(() => (granularity.value === 'month' ? '按月' : '按周'))

/** 页头读数：由主表已加载行汇总（wins/total 与行内胜率同口径），不另发请求 */
const overallSamples = computed(() =>
  summary.value.reduce((acc, row) => acc + (Number(row.total) || 0), 0),
)

const overallWinRate = computed(() => {
  if (!overallSamples.value) return null
  const wins = summary.value.reduce((acc, row) => acc + (Number(row.wins) || 0), 0)
  return Math.round((wins / overallSamples.value) * 1000) / 10
})

const overallAvgReturn = computed(() => {
  let weight = 0
  let acc = 0
  for (const row of summary.value) {
    const n = Number(row.total) || 0
    if (typeof row.avg_return === 'number' && n > 0) {
      acc += row.avg_return * n
      weight += n
    }
  }
  return weight > 0 ? acc / weight : null
})

const overallWinRateTone = computed(() => winRateStatTone(overallWinRate.value, overallSamples.value))

const overallObserving = computed(() =>
  summary.value.reduce((acc, row) => acc + (Number(row.observing) || 0), 0),
)

/**
 * 综合层的「最佳持有期」：把各战法同一档持有期的样本加权合并，样本 ≥3 的档里胜率最高者。
 * 只回答「整体上该拿几天」，不替代单个战法自己的最佳持有期。
 */
const overallBestHorizon = computed(() => {
  const buckets = new Map<number, { n: number; wins: number; avg: number }>()
  for (const row of summary.value) {
    for (const stat of Object.values(row.horizons ?? {})) {
      const horizon = Number(stat.horizon)
      const n = Number(stat.n) || 0
      if (!horizon || !n || typeof stat.win_rate !== 'number') continue
      const bucket = buckets.get(horizon) ?? { n: 0, wins: 0, avg: 0 }
      bucket.n += n
      bucket.wins += (stat.win_rate / 100) * n
      bucket.avg += (Number(stat.avg) || 0) * n
      buckets.set(horizon, bucket)
    }
  }
  let best: { horizon: number; n: number; win_rate: number; avg: number } | null = null
  for (const [horizon, bucket] of buckets) {
    if (bucket.n < 3) continue
    const win_rate = (bucket.wins / bucket.n) * 100
    if (!best || win_rate > best.win_rate) best = { horizon, n: bucket.n, win_rate, avg: bucket.avg / bucket.n }
  }
  return best
})

/** 战法层 KPI：优先用样本明细（分母口径一致），没拉到时退回主表那一行 */
const strategyKpi = computed(() => {
  const row = activeSummary.value
  const d = detail.value
  const horizon = d?.primary_horizon ?? row?.primary_horizon ?? 5
  const settled = d?.settled ?? (Number(row?.total) || 0)
  return {
    horizon,
    settled,
    observing: d?.observing ?? (Number(row?.observing) || 0),
    wins: d?.wins ?? (Number(row?.wins) || 0),
    winRate: d?.win_rate ?? row?.win_rate ?? null,
    avgReturn: d?.avg_return ?? row?.avg_return ?? null,
    best: row?.best_horizon ?? null,
  }
})

function returnTone(value: number | null): 'up' | 'down' | '' {
  if (value == null) return ''
  return value >= 0 ? 'up' : 'down'
}

/** 综合层侧卡：各战法胜率条（按胜率倒序） */
const distribution = computed(() =>
  [...summary.value]
    .map((row) => ({
      tag: row.strategy_tag,
      label: strategyShortLabel(row.strategy_tag, strategyNames.value),
      rate: typeof row.win_rate === 'number' ? row.win_rate : null,
      wins: Number(row.wins) || 0,
      total: Number(row.total) || 0,
      badge: sampleBadgeLabel(Number(row.total) || 0),
    }))
    .sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1)),
)

/**
 * 进某个战法就把它的样本明细拉下来。独立版本号：主表刷新与来回切 tab 会并发，
 * 用 summary 那条 requestVersion 会让「切战法」把整页的加载态一起翻掉。
 */
async function loadDetail(tag: string): Promise<void> {
  const version = ++detailVersion
  const cached = detailCache.get(tag)
  if (cached) {
    detail.value = cached
    detailBusy.value = false
    return
  }
  detail.value = null
  detailBusy.value = true
  try {
    const body = await getWinRateSamples({ tag })
    if (!active || version !== detailVersion) return
    detailCache.set(tag, body)
    detail.value = body
  } catch (e: unknown) {
    if (!active || version !== detailVersion) return
    error.value = e instanceof Error ? e.message : '加载样本失败'
  } finally {
    if (active && version === detailVersion) detailBusy.value = false
  }
}

const selectedPeriod = ref<string | null>(null)

function openStrategy(tag: string): void {
  if (allTags.value.includes(tag)) onViewChange(tag)
}

function onViewChange(next: string): void {
  if (next !== OVERVIEW && !allTags.value.includes(next)) return
  view.value = next
  evidencePane.value = 'samples'
  selectedPeriod.value = null
  if (next !== OVERVIEW) void loadDetail(next)
  else {
    ++detailVersion
    detail.value = null
    detailBusy.value = false
  }
}

async function loadTrend(): Promise<void> {
  const version = ++trendVersion
  const tags = allTags.value
  if (!tags.length) {
    if (active && version === trendVersion) chartData.value = []
    return
  }
  const requestedGranularity = granularity.value
  try {
    const rows = await getWinRateTrend({
      granularity: requestedGranularity,
      tags: tags.join(','),
    })
    if (!active || version !== trendVersion) return
    chartData.value = rows
  } catch (e: unknown) {
    if (!active || version !== trendVersion) return
    error.value = e instanceof Error ? e.message : '加载明细失败'
  }
}

function refreshTrend(): void {
  selectedPeriod.value = null
  chartData.value = []
  void loadTrend()
}

async function reload(): Promise<void> {
  const version = ++requestVersion
  busy.value = true
  error.value = ''
  detailCache.clear()
  ++detailVersion
  ++trendVersion
  try {
    const rows = await getWinRateSummary({ current_only: true })
    if (!active || version !== requestVersion) return
    summary.value = rows
    // 刷新后当前战法可能已经不在表里（改判/换战法），回到综合层而不是空页
    if (!isOverview.value && !rows.some((row) => row.strategy_tag === view.value)) {
      onViewChange(OVERVIEW)
    } else if (!isOverview.value) {
      void loadDetail(view.value)
    }
    void loadTrend()
  } catch (e: unknown) {
    if (!active || version !== requestVersion) return
    error.value =
      e instanceof CapabilityUnavailableError ? e.message : e instanceof Error ? e.message : '加载失败'
  } finally {
    if (active && version === requestVersion) busy.value = false
  }
}

onMounted(reload)

onUnmounted(() => {
  active = false
})
</script>

<template>
  <div class="page-fill wr-page">
    <MobilePageHeader v-if="mobile" title="胜率统计">
      <template #actions>
        <Popover><PopoverTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="口径说明"><Info /></Button></PopoverTrigger><PopoverContent class="wr-caliber" align="end">{{ CALIBER_HINT }}</PopoverContent></Popover>
        <Button access="read" variant="ghost" size="icon" aria-label="刷新胜率统计" :disabled="busy" @click="reload"><RotateCw :class="{ 'animate-spin': busy }" /></Button>
      </template>
    </MobilePageHeader>
    <div v-if="mobile" class="wr-mobile-scope">
      <Select :model-value="view" @update:model-value="value => onViewChange(String(value))"><SelectTrigger aria-label="选择统计战法"><SelectValue /></SelectTrigger><SelectContent><SelectItem v-for="item in tabItems" :key="item.name" :value="item.name">{{ item.label }}</SelectItem></SelectContent></Select>
      <Select v-model="granularity" @update:model-value="refreshTrend"><SelectTrigger aria-label="分周期粒度"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="month">按月</SelectItem><SelectItem value="week">按周</SelectItem></SelectContent></Select>
    </div>
    <PageHeader v-else
      title="胜率统计"
      :tabs="tabItems"
      :tab="view"
      seamless
      @update:tab="onViewChange"
    >
      <template #actions>
        <Select v-model="granularity" @update:model-value="refreshTrend">
          <SelectTrigger class="wr-granularity" size="sm" aria-label="分周期粒度">
            <SelectValue :placeholder="granularityLabel" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="month">按月</SelectItem>
            <SelectItem value="week">按周</SelectItem>
          </SelectContent>
        </Select>
        <Popover>
          <PopoverTrigger as-child>
            <Button variant="ghost" size="icon-sm" aria-label="口径说明">
              <Info aria-hidden="true" />
            </Button>
          </PopoverTrigger>
          <PopoverContent side="bottom" align="end" class="wr-caliber" aria-label="胜率统计口径">{{ CALIBER_HINT }}</PopoverContent>
        </Popover>
        <Button access="read" size="sm" :disabled="busy" @click="reload">
          <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
          <RotateCw v-else class="size-4" aria-hidden="true" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <div class="page-scroll wr-body">
      <Alert v-if="error" variant="destructive" class="shrink-0">
        <CircleAlert />
        <div class="flex w-full min-w-0 items-start justify-between gap-2">
          <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
          <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
            <X class="size-3.5" />
          </Button>
        </div>
      </Alert>

      <!-- KPI：综合层看整体，战法层看这一个 -->
      <WinRateMobileSummary v-if="mobile"
        :label="isOverview ? '综合胜率' : `T+${strategyKpi.horizon} 胜率`"
        :horizon="isOverview ? 5 : strategyKpi.horizon"
        :rate="isOverview ? overallWinRate : strategyKpi.winRate"
        :settled="isOverview ? overallSamples : strategyKpi.settled"
        :observing="isOverview ? overallObserving : strategyKpi.observing"
        :average="isOverview ? overallAvgReturn : strategyKpi.avgReturn"
        :best="(isOverview ? overallBestHorizon : strategyKpi.best)?.horizon"
        :loading="busy || detailBusy"
      />
      <div v-else-if="isOverview" class="stat-strip cols-4 wr-stats" aria-label="综合读数">
        <StatCard
          label="综合胜率"
          :tone="overallWinRateTone"
          :hint="overallSamples ? `${summary.length} 个战法` : '暂无结算样本'"
          :loading="busy && !summary.length"
        >
          {{ winRateText(overallWinRate) }}
        </StatCard>
        <StatCard
          label="已结算样本"
          :value="overallSamples || '—'"
          :hint="overallObserving ? `观察中 ${overallObserving} 条` : undefined"
          :loading="busy && !summary.length"
        />
        <StatCard
          label="T+5 均收益"
          :tone="returnTone(overallAvgReturn)"
          :loading="busy && !summary.length"
        >
          {{ signedPct(overallAvgReturn) }}
        </StatCard>
        <StatCard
          label="最佳持有期"
          :hint="overallBestHorizon ? `胜率 ${winRateText(overallBestHorizon.win_rate)} · 均 ${signedPct(overallBestHorizon.avg)} · ${overallBestHorizon.n} 样本` : '样本不足 3 条'"
          :loading="busy && !summary.length"
        >
          {{ overallBestHorizon ? `T+${overallBestHorizon.horizon}` : '—' }}
        </StatCard>
      </div>
      <div v-else class="stat-strip cols-4 wr-stats" aria-label="战法读数">
        <StatCard
          :label="`T+${strategyKpi.horizon} 胜率`"
          :tone="winRateStatTone(strategyKpi.winRate, strategyKpi.settled)"
          :hint="sampleBadgeLabel(strategyKpi.settled) ? `${sampleBadgeLabel(strategyKpi.settled)} · 盈利 ${strategyKpi.wins} 条` : `盈利 ${strategyKpi.wins} 条`"
          :loading="detailBusy && !detail"
        >
          {{ winRateText(strategyKpi.winRate) }}
        </StatCard>
        <StatCard
          label="已结算样本"
          :value="strategyKpi.settled || '—'"
          :hint="strategyKpi.observing ? `观察中 ${strategyKpi.observing} 条（不计入）` : undefined"
          :loading="detailBusy && !detail"
        />
        <StatCard
          :label="`T+${strategyKpi.horizon} 均收益`"
          :tone="returnTone(strategyKpi.avgReturn)"
          :loading="detailBusy && !detail"
        >
          {{ signedPct(strategyKpi.avgReturn) }}
        </StatCard>
        <StatCard
          label="最佳持有期"
          :hint="strategyKpi.best ? `胜率 ${winRateText(strategyKpi.best.win_rate)} · 均 ${signedPct(strategyKpi.best.avg)} · ${strategyKpi.best.n} 样本` : '样本不足 3 条，不评'"
        >
          {{ strategyKpi.best?.horizon ? `T+${strategyKpi.best.horizon}` : '—' }}
        </StatCard>
      </div>

      <template v-if="isOverview">
        <PageTabs v-model="overviewPane" variant="pill" :sticky="false" aria-label="综合统计视图" :items="[{name:'compare',label:'战法对比'},{name:'period',label:'同期表现'},{name:'distribution',label:'胜率分布'}]" />
        <div class="wr-stage">
          <WinRateCompareTable v-if="overviewPane === 'compare'" :rows="summary" :names="strategyNames" :busy="busy" @select="openStrategy" />
          <WinRatePeriodTable v-else-if="overviewPane === 'period'" :points="chartData" :names="strategyNames" :granularity="granularity" :tags="allTags" mode="matrix" />
          <div v-else class="wr-distribution">
            <ul v-if="distribution.length" class="wr-bars" aria-label="各战法胜率">
              <li v-for="item in distribution" :key="item.tag" class="wr-bar">
                <Button access="read" variant="ghost" type="button" class="wr-bar__btn" @click="openStrategy(item.tag)">
                  <span class="wr-bar__row"><span class="wr-bar__label">{{ item.label }}</span><span class="wr-bar__value"><b>{{ winRateText(item.rate) }}</b><span class="wr-dim">{{ item.wins }}/{{ item.total }} · {{ item.badge }}</span></span></span>
                  <span class="wr-bar__track"><span class="wr-bar__fill" :class="{ 'is-weak': item.badge === '样本不足' }" :style="{width:`${Math.max(0,Math.min(100,item.rate ?? 0))}%`}" /></span>
                </Button>
              </li>
            </ul>
            <EmptyState v-else compact description="还没有可比的战法" />
          </div>
        </div>
      </template>
      <template v-else>
        <PageTabs v-model="evidencePane" variant="pill" :sticky="false" aria-label="战法证据视图" :items="[{name:'samples',label:'样本明细'},{name:'horizons',label:'持有期'},{name:'insights',label:'样本洞察'},{name:'period',label:'周期表现'}]" />
        <div class="wr-stage">
          <WinRateStrategyPanel v-show="evidencePane !== 'period'" :tag="view" :summary="activeSummary" :detail="detail" :busy="detailBusy" :pane="evidencePane" :selected-period="selectedPeriod" @clear-period="selectedPeriod = null" @show-samples="evidencePane = 'samples'" />
          <WinRatePeriodTable v-if="evidencePane === 'period'" :points="chartData" :names="strategyNames" :granularity="granularity" :tags="[view]" :selected-period="selectedPeriod" mode="single" @select-period="p => { selectedPeriod = selectedPeriod === p ? null : p; evidencePane = 'samples' }" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped src="./WinRateView.css" />

<style>
/* 口径全文气泡经 teleport 挂到 body，scoped 够不着；限宽换行 */
.wr-caliber {
  max-width: 26rem;
  white-space: normal;
  word-break: break-word;
  line-height: 1.55;
}
</style>
