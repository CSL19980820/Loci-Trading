<script setup lang="ts">
import { matchesWinRatePeriod } from '../lib/winRatePeriod'
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { Award, Search, ThumbsDown, ThumbsUp, Timer, X } from '@lucide/vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { price, signedPct } from '@/shared/lib/format'
import {
  sampleBadgeLabel,
  sampleConfidence,
  winRateDisplayTone,
  winRateText,
} from '@/shared/lib/winrate'
import type { WinRateSampleDetail, WinRateSummary } from '@/shared/types/quant'

/**
 * 一个战法的胜率证据：分母怎么来的、最好最坏是哪只票、该拿几天、逐条样本。
 *
 * 版面（卡内 bento）：
 *   公式条（胜率 = 盈利 ÷ 已结算；观察中不计入）
 *   三张洞察卡：最佳样本 / 最差样本 / 最佳持有期
 *   各持有期表现（1/3）| 样本明细（2/3，带分段 + 搜索；手机端卡片列表）
 *
 * 纯展示。数据由 WinRateView 拉好传进来——请求竞态与持有期切换归父级，
 * 组件挂载时不自己发请求。
 */
const props = defineProps<{
  tag: string
  summary: WinRateSummary | null
  detail: WinRateSampleDetail | null
  busy?: boolean
  pane?: string
  selectedPeriod?: string | null
}>()

const emit = defineEmits<{
  clearPeriod: []
  showSamples: []
}>()

const isMobile = useMediaQuery('(max-width: 640px)')
const fillDesktop = useMediaQuery('(min-width:1024px) and (min-height:600px)')

/** 观察窗全档；后端 HORIZONS 就这六个，多的少的都不画 */
const HORIZON_ORDER = [1, 3, 5, 10, 20, 60]

/** 快速筛选分段：全部 / 盈利 / 亏损 / 观察中 */
const filterTab = ref<'all' | 'win' | 'loss' | 'pending'>('all')

/** 搜索关键词（代码或名称） */
const searchQuery = ref('')

/** 选中的聚焦持有期（支持交互式高亮对应列） */
const activeHorizon = ref<number | null>(null)

/**
 * 「胜率是怎么算出来的」必须写在页面上：只给一个 41.7% 等于让人猜分母。
 * 观察中的样本单独交代——它们不进分母，否则同一批候选会算出两个胜率。
 */
const formula = computed(() => {
  const detail = props.detail
  if (!detail || !detail.settled) return ''
  const pending = detail.observing ? `；另有 ${detail.observing} 条还在窗口内，不计入` : ''
  return `胜率 ${winRateText(detail.win_rate)} = 盈利 ${detail.wins} ÷ 已走完 T+${detail.primary_horizon} 的 ${detail.settled} 条精选候选${pending}`
})

const bestSample = computed(() => props.summary?.best_sample ?? null)
const worstSample = computed(() => props.summary?.worst_sample ?? null)
const bestHorizon = computed(() => props.summary?.best_horizon ?? null)

const bestHorizonKey = computed(() => {
  const horizon = bestHorizon.value?.horizon
  return horizon ? `t${horizon}` : ''
})

const horizonRows = computed(() => {
  const rows: Record<string, unknown>[] = []
  const horizons = props.summary?.horizons
  if (!horizons) return rows
  for (const horizon of HORIZON_ORDER) {
    const stat = horizons[`t${horizon}`]
    if (!stat) continue
    rows.push({ key: `t${horizon}`, horizon, ...stat })
  }
  return rows
})

const sampleRows = computed(
  () => (props.detail?.samples ?? []) as unknown as Record<string, unknown>[],
)

const winSamplesCount = computed(() => sampleRows.value.filter((s) => s.win === true).length)
const lossSamplesCount = computed(() => sampleRows.value.filter((s) => s.win === false).length)
const pendingSamplesCount = computed(
  () => sampleRows.value.filter((s) => s.win === null || s.win === undefined).length,
)

const filterTabs = computed<PageTabItem[]>(() => [
  { name: 'all', label: '全部', badge: sampleRows.value.length },
  { name: 'win', label: '盈利', badge: winSamplesCount.value },
  { name: 'loss', label: '亏损', badge: lossSamplesCount.value },
  { name: 'pending', label: '观察中', badge: pendingSamplesCount.value },
])

const filterTabModel = computed({
  get: () => filterTab.value,
  set: (next: string) => {
    if (next === 'all' || next === 'win' || next === 'loss' || next === 'pending') filterTab.value = next
  },
})

const filteredSamples = computed(() => {
  let list = sampleRows.value

  // 1. 分段过滤
  if (filterTab.value === 'win') list = list.filter((s) => s.win === true)
  else if (filterTab.value === 'loss') list = list.filter((s) => s.win === false)
  else if (filterTab.value === 'pending') list = list.filter((s) => s.win === null || s.win === undefined)

  // 2. 周期过滤（如果点击了下方的月/周）
  if (props.selectedPeriod) {
    const period = props.selectedPeriod.trim()
    list = list.filter(s => matchesWinRatePeriod(String(s.base_date || ''), period))
  }

  // 3. 关键字过滤（代码或名称）
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter((s) => {
      const code = String(s.code || '').toLowerCase()
      const name = String(s.name || '').toLowerCase()
      return code.includes(q) || name.includes(q)
    })
  }

  return list
})

const horizonColumns: BasicTableColumn[] = [
  { prop: 'horizon', label: '持有期', width: 104, slotName: 'horizon' },
  { prop: 'n', label: '样本', width: 60, align: 'right', headerAlign: 'right' },
  { prop: 'win_rate', label: '胜率', width: 84, align: 'right', headerAlign: 'right', slotName: 'winRate' },
  { prop: 'avg', label: '均收益', width: 84, align: 'right', headerAlign: 'right', slotName: 'avg' },
  { prop: 'best', label: '最好', width: 80, align: 'right', headerAlign: 'right', slotName: 'best' },
  { prop: 'worst', label: '最差', minWidth: 80, align: 'right', headerAlign: 'right', slotName: 'worst' },
]

const sampleColumns: BasicTableColumn[] = [
  { prop: 'code', label: '标的', minWidth: 150, slotName: 'stock' },
  { prop: 'base_date', label: '选出日', width: 112, slotName: 'baseDate' },
  { prop: 'base_close', label: '基准价', width: 88, align: 'right', headerAlign: 'right', slotName: 'baseClose' },
  { prop: 't1', label: 'T+1', width: 84, align: 'right', headerAlign: 'right', slotName: 't1' },
  { prop: 't3', label: 'T+3', width: 84, align: 'right', headerAlign: 'right', slotName: 't3' },
  { prop: 't5', label: 'T+5', width: 84, align: 'right', headerAlign: 'right', slotName: 't5' },
  { prop: 'max_favorable_pct', label: '窗内最高', width: 96, align: 'right', headerAlign: 'right', slotName: 'maxFavorable' },
  { prop: 'win', label: '结果', width: 84, align: 'right', headerAlign: 'right', slotName: 'win' },
]

function horizonRowClass(data: { row: Record<string, unknown> }): string {
  const classes: string[] = ['horizon-clickable-row']
  if (data.row.key === bestHorizonKey.value) classes.push('is-best-horizon')
  if (data.row.horizon === activeHorizon.value) classes.push('is-active-horizon')
  return classes.join(' ')
}

const visibleSampleColumns = computed<BasicTableColumn[]>(() => activeHorizon.value && ![1,3,5].includes(activeHorizon.value)
  ? [...sampleColumns.slice(0,6), { prop:'focused_return', label:`T+${activeHorizon.value}`, width:92, align:'right', slotName:'focusedReturn' }, ...sampleColumns.slice(6)]
  : sampleColumns)
function toggleHorizon(horizon: unknown): void {
  const h = Number(horizon)
  if (!h) return
  activeHorizon.value = activeHorizon.value === h ? null : h
  emit('showSamples')
}

function returnAt(row: Record<string, unknown>, horizon: number): number | null {
  const returns = row.returns as Record<string, number | null> | undefined
  const value = returns?.[`t${horizon}`]
  return typeof value === 'number' ? value : null
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'sp-dim'
  return Number(value) >= 0 ? 'tone-up' : 'tone-down'
}

function outcomeLabel(win: unknown): string {
  if (win === true) return '盈利'
  if (win === false) return '亏损'
  return '观察中'
}

function outcomeVariant(win: unknown): 'up' | 'down' | 'secondary' {
  if (win === true) return 'up'
  if (win === false) return 'down'
  return 'secondary'
}

function sampleVariant(total: unknown): 'secondary' | 'warn' {
  return sampleConfidence(Number(total) || 0) === 'low' ? 'secondary' : 'warn'
}

function primaryReturn(row: Record<string, unknown>): number | null {
  const value = row.primary_return
  return typeof value === 'number' ? value : returnAt(row, props.detail?.primary_horizon ?? 5)
}
</script>

<template>
  <div class="sp-panel" :aria-busy="busy">
    <PageBusy :busy="busy" overlay />

    <!-- 公式条：分母写在页面上 -->
    <p v-if="formula" class="sp-formula">
      <span class="sp-formula__k">口径</span>
      <span class="sp-formula__text">{{ formula }}</span>
    </p>
    <p v-else-if="detail && !detail.settled" class="sp-formula">
      <span class="sp-formula__k">口径</span>
      <span class="sp-formula__text">还没有走完 T+{{ detail.primary_horizon }} 的精选候选；观察中 {{ detail.observing }} 条，不计入胜率</span>
    </p>

    <!-- 三张洞察卡 -->
    <section v-if="pane === 'insights'" class="sp-insights" aria-label="样本洞察">
      <div class="sp-insight sp-insight--best">
        <div class="sp-insight__head">
          <span class="sp-insight__icon"><ThumbsUp aria-hidden="true" /></span>
          <span class="sp-insight__k">最佳样本</span>
          <span v-if="bestSample" class="sp-insight__meta sp-num">{{ bestSample.base_date }} 选出</span>
        </div>
        <div v-if="bestSample" class="sp-insight__body">
          <span class="sp-insight__target">
            <StockLink :code="bestSample.code" :name="bestSample.name" :show-code="false" class="sp-link" />
            <span class="sp-code">{{ bestSample.code }}</span>
          </span>
          <span class="sp-insight__metric">
            <span class="sp-insight__num sp-num" :class="tone(bestSample.return_pct)">{{ signedPct(bestSample.return_pct) }}</span>
            <span v-if="bestSample.max_favorable_pct != null" class="sp-insight__sub sp-num">最高冲幅 {{ signedPct(bestSample.max_favorable_pct) }}</span>
          </span>
        </div>
        <p v-else class="sp-insight__empty">尚无走完窗口的样本</p>
      </div>

      <div class="sp-insight sp-insight--worst">
        <div class="sp-insight__head">
          <span class="sp-insight__icon"><ThumbsDown aria-hidden="true" /></span>
          <span class="sp-insight__k">最差样本</span>
          <span v-if="worstSample" class="sp-insight__meta sp-num">{{ worstSample.base_date }} 选出</span>
        </div>
        <div v-if="worstSample" class="sp-insight__body">
          <span class="sp-insight__target">
            <StockLink :code="worstSample.code" :name="worstSample.name" :show-code="false" class="sp-link" />
            <span class="sp-code">{{ worstSample.code }}</span>
          </span>
          <span class="sp-insight__metric">
            <span class="sp-insight__num sp-num" :class="tone(worstSample.return_pct)">{{ signedPct(worstSample.return_pct) }}</span>
            <span v-if="worstSample.max_favorable_pct != null" class="sp-insight__sub sp-num">最高冲幅 {{ signedPct(worstSample.max_favorable_pct) }}</span>
          </span>
        </div>
        <p v-else class="sp-insight__empty">尚无走完窗口的样本</p>
      </div>

      <div class="sp-insight sp-insight--horizon">
        <div class="sp-insight__head">
          <span class="sp-insight__icon"><Timer aria-hidden="true" /></span>
          <span class="sp-insight__k">最佳持有期</span>
          <span v-if="bestHorizon" class="sp-insight__meta sp-num">n={{ bestHorizon.n }}</span>
        </div>
        <div v-if="bestHorizon" class="sp-insight__body">
          <span class="sp-insight__target">
            <span class="sp-horizon-pill">T+{{ bestHorizon.horizon }}</span>
            <span class="sp-dim sp-insight__tip">样本 ≥3 的持有期里胜率最高</span>
          </span>
          <span class="sp-insight__metric">
            <span class="sp-insight__num sp-num" :class="winRateDisplayTone(bestHorizon.win_rate, bestHorizon.n)">{{ winRateText(bestHorizon.win_rate) }}</span>
            <span class="sp-insight__sub sp-num" :class="tone(bestHorizon.avg)">均 {{ signedPct(bestHorizon.avg) }}</span>
          </span>
        </div>
        <p v-else class="sp-insight__empty">样本不足 3 条，不评最佳持有期</p>
      </div>
    </section>

    <!-- 持有期表现（1/3）| 样本明细（2/3） -->
    <div v-if="pane !== 'insights'" class="sp-grid">
      <section v-if="pane === 'horizons'" class="sp-block" aria-label="各持有期表现">
        <header class="sp-block__head">
          <h4 class="sp-block__title">各持有期表现</h4>
          <span class="sp-block__tip">点一行高亮样本里对应的收益列</span>
        </header>
        <BasicTable
          class="sp-table"
          :height="fillDesktop ? '100%' : undefined"
          :columns="horizonColumns"
          :data-source="horizonRows"
          :pagination="false"
          :row-class-name="horizonRowClass"
          row-key="key"
          empty-text="还没有可比的持有期"
          empty-reason="精选候选要先走完 T+1 才有第一档"
          @row-click="(row: Record<string, unknown>) => toggleHorizon(row.horizon)"
        >
          <template #horizon="{ row }">
            <span class="sp-horizon">
              <strong class="sp-num">T+{{ row.horizon }}</strong>
              <span v-if="row.key === bestHorizonKey" class="sp-horizon__best"><Award aria-hidden="true" />最佳</span>
            </span>
          </template>
          <template #winRate="{ row }">
            <span class="sp-num sp-strong" :class="winRateDisplayTone(Number(row.win_rate), Number(row.n))">
              {{ winRateText(row.win_rate as number | null) }}
            </span>
          </template>
          <template #avg="{ row }">
            <span class="sp-num" :class="tone(row.avg as number)">{{ signedPct(row.avg as number) }}</span>
          </template>
          <template #best="{ row }">
            <span class="sp-num" :class="tone(row.best as number)">{{ signedPct(row.best as number) }}</span>
          </template>
          <template #worst="{ row }">
            <span class="sp-num" :class="tone(row.worst as number)">{{ signedPct(row.worst as number) }}</span>
          </template>
        </BasicTable>
      </section>

      <section v-else class="sp-block sp-block--samples" aria-label="样本明细">
        <header class="sp-block__head sp-block__head--samples">
          <div class="sp-block__lead">
            <h4 class="sp-block__title">
              样本明细
              <span class="sp-block__count sp-num">{{ filteredSamples.length }}<span v-if="filteredSamples.length !== sampleRows.length"> / {{ sampleRows.length }}</span></span>
            </h4>
            <span v-if="detail?.truncated" class="sp-block__tip">仅显示最近 {{ sampleRows.length }} 条</span>
          </div>
          <div class="sp-block__tools">
<UiBadge v-if="activeHorizon" variant="secondary">聚焦 T+{{ activeHorizon }}</UiBadge>
            <UiBadge v-if="selectedPeriod" variant="default" class="sp-period-chip">
              周期 {{ selectedPeriod }}
              <Button access="read" variant="ghost" type="button" class="sp-period-chip__x" aria-label="清除周期筛选" @click="emit('clearPeriod')">
                <X aria-hidden="true" />
              </Button>
            </UiBadge>
            <div class="sp-search">
              <Search class="sp-search__icon" aria-hidden="true" />
              <Input
                v-model="searchQuery"
                size="sm"
                placeholder="搜代码 / 名称"
                aria-label="筛选样本代码或名称"
                class="sp-search__input"
              />
              <Button access="read"
                v-if="searchQuery"
                variant="ghost"
                size="icon-xs"
                class="sp-search__clear"
                aria-label="清除搜索"
                @click="searchQuery = ''"
              >
                <X class="size-3.5" aria-hidden="true" />
              </Button>
            </div>
            <PageTabs
              v-model="filterTabModel"
              :items="filterTabs"
              variant="pill"
              :sticky="false"
              aria-label="样本筛选"
              class="sp-filter-tabs"
            />
          </div>
        </header>

        <!-- 手机：样本卡片 -->
        <template v-if="isMobile">
          <ul v-if="filteredSamples.length" class="sp-cards" aria-label="样本明细">
            <li v-for="row in filteredSamples" :key="String(row.candidate_id)" class="sp-card">
              <div class="sp-card__main">
                <span class="sp-card__name">
                  <StockLink :code="String(row.code || '')" :name="String(row.name || '')" :show-code="false" class="sp-link" />
                  <span class="sp-code">{{ row.code }}</span>
                </span>
                <span class="sp-card__sub">
                  <span class="sp-num">{{ row.base_date }}</span>
                  <span v-if="activeHorizon && ![1,3,5].includes(activeHorizon)" class="sp-num">T+{{ activeHorizon }} <span :class="tone(returnAt(row, activeHorizon))">{{ signedPct(returnAt(row, activeHorizon)) }}</span></span>
                  <span class="sp-num">基准 {{ price(row.base_close as number | null) }}</span>
                  <span class="sp-num">T+1 <span :class="tone(returnAt(row, 1))">{{ signedPct(returnAt(row, 1)) }}</span></span>
                  <span class="sp-num">T+3 <span :class="tone(returnAt(row, 3))">{{ signedPct(returnAt(row, 3)) }}</span></span>
                </span>
              </div>
              <div class="sp-card__num">
                <span class="sp-card__big sp-num" :class="tone(primaryReturn(row))">{{ signedPct(primaryReturn(row)) }}</span>
                <UiBadge :variant="outcomeVariant(row.win)">{{ outcomeLabel(row.win) }}</UiBadge>
              </div>
            </li>
          </ul>
          <EmptyState
            v-else-if="!busy"
            class="sp-empty"
            :description="sampleRows.length ? '当前筛选下无匹配样本' : '这个战法还没有精选样本'"
            :reason="sampleRows.length ? '换个分段或清掉搜索 / 周期筛选' : '只有裁决为「精选」的候选才进胜率'"
          />
        </template>

        <!-- 桌面：样本表 -->
        <BasicTable
          v-else
          class="sp-table"
          :columns="visibleSampleColumns"
          :data-source="filteredSamples"
          :pagination="false"
          :height="fillDesktop ? '100%' : undefined"
          :loading="busy"
          row-key="candidate_id"
          empty-text="这个战法还没有精选样本"
          empty-reason="只有裁决为「精选」的候选才进胜率"
        >
          <template #stock="{ row }">
            <span class="sp-cell-name">
              <span class="sp-name">
                <StockLink :code="String(row.code || '')" :name="String(row.name || '')" :show-code="false" class="sp-link" />
              </span>
              <span class="sp-code">{{ row.code }}</span>
            </span>
          </template>
          <template #baseDate="{ row }">
            <span class="sp-num sp-dim">{{ row.base_date }}</span>
          </template>
          <template #baseClose="{ row }">
            <span class="sp-num">{{ price(row.base_close as number | null) }}</span>
          </template>
          <template #t1="{ row }">
            <span class="sp-num sp-ret" :class="[tone(returnAt(row, 1)), { 'is-active-col': activeHorizon === 1 }]">
              {{ signedPct(returnAt(row, 1)) }}
            </span>
          </template>
          <template #t3="{ row }">
            <span class="sp-num sp-ret" :class="[tone(returnAt(row, 3)), { 'is-active-col': activeHorizon === 3 }]">
              {{ signedPct(returnAt(row, 3)) }}
            </span>
          </template>
          <template #t5="{ row }">
            <span class="sp-num sp-ret sp-strong" :class="[tone(returnAt(row, 5)), { 'is-active-col': activeHorizon === 5 }]">
              {{ signedPct(returnAt(row, 5)) }}
            </span>
          </template>
          <template #focusedReturn="{ row }"><span class="sp-num sp-ret is-active-col" :class="tone(returnAt(row, activeHorizon || 5))">{{ signedPct(returnAt(row, activeHorizon || 5)) }}</span></template>
          <template #maxFavorable="{ row }">
            <span class="sp-num sp-dim">{{ signedPct(row.max_favorable_pct as number | null) }}</span>
          </template>
          <template #win="{ row }">
            <UiBadge :variant="outcomeVariant(row.win)">{{ outcomeLabel(row.win) }}</UiBadge>
          </template>
          <template #empty>
            <EmptyState v-if="busy" class="sp-empty" description="加载样本…" />
            <EmptyState
              v-else-if="!sampleRows.length"
              class="sp-empty"
              description="这个战法还没有精选样本"
              reason="只有裁决为「精选」的候选才进胜率"
            />
            <EmptyState
              v-else
              class="sp-empty"
              description="当前筛选下无匹配样本"
              reason="换个分段或清掉搜索 / 周期筛选"
            />
          </template>
        </BasicTable>
      </section>
    </div>
  </div>
</template>

<style scoped src="./WinRateStrategyPanel.css"></style>
