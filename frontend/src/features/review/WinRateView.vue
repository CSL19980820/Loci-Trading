<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { InfoFilled, RefreshRight } from '@element-plus/icons-vue'

import {
  CapabilityUnavailableError,
  getWinRateSamples,
  getWinRateSummary,
  getWinRateTrend,
} from '@/shared/api/quant'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { signedPct, strategyShortLabel } from '@/shared/lib/format'
import { winRateStatTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateSampleDetail, WinRateSummary, WinRateTrendPoint } from '@/shared/types/quant'

import WinRateCompareTable from './components/WinRateCompareTable.vue'
import WinRatePeriodTable from './components/WinRatePeriodTable.vue'
import WinRateStrategyPanel from './components/WinRateStrategyPanel.vue'

/**
 * 两层：进来是**综合对比**（各战法横向比 + 同期对比），点一行/切一个 tab 才进
 * 那个战法自己的证据页（分母公式、最佳最差样本、该拿几天、逐条样本）。
 *
 * 上一版把这四块全堆在一页，11 列的主表下面直接接三张表——既没有「切战法」这个
 * 动作，也没人能从中读出谁比谁强。
 */

/** 口径说明只写一份：顶栏 ⓘ 与表内说明共用，避免手抄出两个版本 */
const CALIBER_HINT =
  '胜率口径为精选候选 T+5（另列 T+1/T+3），无候选样本的战法回退手工复盘；盘后「候选T+N跟踪」每日重算 5 个交易日窗口。综合页横向比各战法，点任一行进该战法证据页：分母是哪几只票、最好最坏是哪只、该拿几天。分周期按候选**选出日**聚合，与主表同源。'

const OVERVIEW = 'overview'

const summary = ref<WinRateSummary[]>([])
const chartData = ref<WinRateTrendPoint[]>([])
const detail = ref<WinRateSampleDetail | null>(null)
const view = ref<string>(OVERVIEW)
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

const overallAvgTone = computed(() => {
  if (overallAvgReturn.value == null) return ''
  return overallAvgReturn.value >= 0 ? 'up' : 'down'
})

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
  <div class="page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
  <!-- 顶栏只剩「读数 + 操作」：页面标题由侧栏高亮的菜单项交代，口径全文沉进 ⓘ -->
  <PageToolbar :note="CALIBER_HINT">
    <template #stats>
      <HeaderStat label="综合胜率" lead :tone="overallWinRateTone">
        {{ winRateText(overallWinRate) }}
      </HeaderStat>
      <HeaderStat label="样本数" :value="overallSamples || '—'" />
      <HeaderStat label="T+5 均收益" :tone="overallAvgTone">{{ signedPct(overallAvgReturn) }}</HeaderStat>
    </template>
    <template #actions>
      <el-button size="small" :icon="RefreshRight" :loading="busy" @click="reload">刷新</el-button>
    </template>
  </PageToolbar>

  <PageTabs
    :model-value="view"
    :items="tabItems"
    aria-label="胜率视图"
    @update:model-value="onViewChange"
  >
    <template #trailing>
      <el-select
        v-model="granularity"
        size="small"
        class="w-26 shrink-0"
        aria-label="分周期粒度"
        @change="refreshTrend"
      >
        <el-option label="按月" value="month" />
        <el-option label="按周" value="week" />
      </el-select>
    </template>
  </PageTabs>

  <div class="winrate-content">
    <el-alert v-if="error" :title="error" type="error" show-icon closable class="shrink-0" @close="error = ''" />

    <template v-if="isOverview">
      <Sheet fill title="战法横向对比" class="winrate-primary">
        <template #actions>
          <el-tooltip content="点击战法行查看样本证据" placement="top">
            <el-icon tabindex="0" aria-label="点击战法行查看样本证据" class="text-mist"><InfoFilled /></el-icon>
          </el-tooltip>
        </template>
        <WinRateCompareTable :rows="summary" :names="strategyNames" :busy="busy" @select="openStrategy" />
      </Sheet>
      <Sheet fill :title="periodTitle" class="winrate-period">
        <WinRatePeriodTable :points="chartData" :names="strategyNames" :granularity="granularity" :tags="allTags" mode="matrix" />
      </Sheet>
    </template>

    <template v-else>
      <Sheet fill :title="`${strategyShortLabel(view, strategyNames)} · 胜率与证据`" class="winrate-primary">
        <WinRateStrategyPanel
          :tag="view"
          :summary="activeSummary"
          :detail="detail"
          :busy="detailBusy"
          :selected-period="selectedPeriod"
          @clear-period="selectedPeriod = null"
        />
      </Sheet>
      <Sheet fill :title="periodTitle" class="winrate-period">
        <WinRatePeriodTable
          :points="chartData"
          :names="strategyNames"
          :granularity="granularity"
          :tags="[view]"
          :selected-period="selectedPeriod"
          mode="single"
          @select-period="(p) => selectedPeriod = (selectedPeriod === p ? null : p)"
        />
      </Sheet>
    </template>
  </div>
  </div>
</template>


<style scoped src="./WinRateView.css" />
