<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { signedPct, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, sampleConfidence, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateTrendPoint } from '@/shared/types/quant'

/**
 * 分周期表两种形态，同一份数据：
 *
 * - `matrix`：周期 × 战法，综合层用来横向比同一个月谁更强。
 * - `single`：一个战法的周期序列，包含周期收益与胜率演进看板 + 战绩分布 + 100%全宽现代明细表。
 */
const props = defineProps<{
  points: WinRateTrendPoint[]
  granularity: 'month' | 'week'
  tags: string[]
  mode: 'matrix' | 'single'
  selectedPeriod?: string | null
}>()

const emit = defineEmits<{
  selectPeriod: [period: string]
}>()

const periodLabel = computed(() => (props.granularity === 'month' ? '月份' : '周'))

const byPeriod = computed(() => {
  const grouped = new Map<string, Record<string, WinRateTrendPoint>>()
  const wanted = new Set(props.tags)
  for (const point of props.points) {
    if (!wanted.has(point.strategy_tag)) continue
    let bucket = grouped.get(point.period)
    if (!bucket) {
      bucket = Object.create(null) as Record<string, WinRateTrendPoint>
      grouped.set(point.period, bucket)
    }
    bucket[point.strategy_tag] = point
  }
  return grouped
})

const rows = computed(() => {
  const periods = [...byPeriod.value.keys()].sort().reverse()
  if (props.mode === 'single') {
    const tag = props.tags[0] ?? ''
    return periods
      .filter((period) => byPeriod.value.get(period)![tag])
      .map((period) => {
        const point = byPeriod.value.get(period)![tag]
        const wins = Number(point.wins) || 0
        const total = Number(point.total) || 0
        const losses = Math.max(0, total - wins)
        return {
          period,
          total,
          wins,
          losses,
          win_rate: point.win_rate,
          avg_return: point.avg_return ?? null,
        } as Record<string, unknown>
      })
  }
  return periods.map(
    (period) => ({ period, byTag: byPeriod.value.get(period)! }) as Record<string, unknown>,
  )
})

/** 按时间正序排列的点，用于渲染趋势图 */
const chronologicalSinglePoints = computed(() => {
  if (props.mode !== 'single') return []
  return [...rows.value].reverse()
})

/** 周期统计洞察 */
const periodInsights = computed(() => {
  const list = rows.value
  if (!list.length) return null
  let maxWinRate = -1
  let bestRatePeriod = ''
  let maxAvgReturn = -Infinity
  let bestReturnPeriod = ''
  let winPeriods = 0

  for (const r of list) {
    const rate = Number(r.win_rate) || 0
    const avg = Number(r.avg_return) || 0
    if (rate > maxWinRate) {
      maxWinRate = rate
      bestRatePeriod = String(r.period)
    }
    if (avg > maxAvgReturn) {
      maxAvgReturn = avg
      bestReturnPeriod = String(r.period)
    }
    if (avg > 0) winPeriods++
  }

  return {
    total: list.length,
    bestRatePeriod,
    maxWinRate,
    bestReturnPeriod,
    maxAvgReturn: maxAvgReturn === -Infinity ? null : maxAvgReturn,
    winRateRatio: Math.round((winPeriods / list.length) * 100),
  }
})

/** 趋势图柱状高度与零轴映射 */
const chartScale = computed(() => {
  const pts = chronologicalSinglePoints.value
  if (!pts.length) return { maxAbs: 5 }
  let maxAbs = 1
  for (const p of pts) {
    const val = Math.abs(Number(p.avg_return) || 0)
    if (val > maxAbs) maxAbs = val
  }
  return { maxAbs: Math.max(3, Math.ceil(maxAbs * 1.2)) }
})

const columns = computed<BasicTableColumn[]>(() => {
  if (props.mode === 'single') {
    return [
      { prop: 'period', label: periodLabel.value, width: 140, slotName: 'period' },
      { prop: 'win_rate', label: '胜率表现', minWidth: 180, slotName: 'singleRate' },
      { prop: 'distribution', label: '战绩分布 (盈/亏)', minWidth: 180, slotName: 'distribution' },
      { prop: 'total', label: '盈利 / 样本', width: 120, align: 'right', headerAlign: 'right', slotName: 'total' },
      { prop: 'avg_return', label: '周期均收益', width: 130, align: 'right', headerAlign: 'right', slotName: 'avg' },
      { prop: 'action', label: '样本联动', width: 110, align: 'center', headerAlign: 'center', slotName: 'action' },
    ]
  }
  const cols: BasicTableColumn[] = [
    { prop: 'period', label: periodLabel.value, width: 140, slotName: 'period' },
  ]
  for (const tag of props.tags) {
    cols.push({
      prop: tag,
      label: strategyShortLabel(tag),
      align: 'right',
      headerAlign: 'right',
      minWidth: 160,
      slotName: `tag_${tag}`,
    })
  }
  return cols
})

function pointAt(row: Record<string, unknown>, tag: string): WinRateTrendPoint | undefined {
  const byTag = row.byTag as Record<string, WinRateTrendPoint> | undefined
  return byTag?.[tag]
}

function badgeClass(total: unknown): string {
  return sampleConfidence(Number(total) || 0) === 'low' ? 'sample-badge-low' : 'sample-badge-medium'
}

function toneOf(value: unknown): string {
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return 'dim'
  return n >= 0 ? 'tone-up' : 'tone-down'
}

function heatStyle(rate: number | null | undefined): Record<string, string> {
  const n = Number(rate)
  if (!Number.isFinite(n) || n <= 0) return {}
  if (n >= 50) {
    return {
      backgroundColor: `color-mix(in oklab, var(--seal) ${Math.min(22, Math.round((n - 40) * 0.35))}%, transparent)`,
    }
  }
  return {}
}

function onSelectPeriod(period: unknown): void {
  const p = String(period || '')
  if (p) emit('selectPeriod', p)
}

function singleRowClass(data: { row: Record<string, unknown> }): string {
  return data.row.period === props.selectedPeriod ? 'period-active-row' : ''
}
</script>

<template>
  <div class="period-container">
    <!-- 单战法模式：上层趋势演进工坊 + 下层 100% 满宽现代明细表 -->
    <template v-if="mode === 'single' && rows.length">
      <!-- 周期收益与胜率趋势工坊 (Period Studio) -->
      <section class="period-studio" aria-label="周期趋势概览">
        <div class="period-studio__header">
          <div class="period-studio__title-row">
                  <span class="period-studio__title">{{ periodLabel }}走势演进</span>
            <span class="period-studio__sub dim">各周期均收益阴阳柱与胜率走势（点击柱子可联动过滤样本）</span>
          </div>
          <div class="period-studio__legend">
            <span class="legend-item"><span class="legend-dot legend-dot--up" />正收益</span>
            <span class="legend-item"><span class="legend-dot legend-dot--down" />负收益</span>
            <span class="legend-item"><span class="legend-line" />胜率胶囊</span>
          </div>
        </div>

        <!-- 顶部周期速览指标 Bento -->
        <div v-if="periodInsights" class="period-studio__kpi-bar">
          <div class="period-kpi-item">
            <span class="period-kpi-k">覆盖{{ periodLabel }}数</span>
            <span class="period-kpi-v mono">{{ periodInsights.total }} 个{{ periodLabel }}</span>
          </div>
          <div class="period-kpi-item">
            <span class="period-kpi-k">最高胜率{{ periodLabel }}</span>
            <span class="period-kpi-v mono">
              {{ periodInsights.bestRatePeriod }} ({{ winRateText(periodInsights.maxWinRate) }})
            </span>
          </div>
          <div class="period-kpi-item">
            <span class="period-kpi-k">最佳均收益{{ periodLabel }}</span>
            <span class="period-kpi-v mono" :class="toneOf(periodInsights.maxAvgReturn)">
              {{ periodInsights.bestReturnPeriod }} ({{ signedPct(periodInsights.maxAvgReturn) }})
            </span>
          </div>
          <div class="period-kpi-item">
            <span class="period-kpi-k">盈利{{ periodLabel }}占比</span>
            <span class="period-kpi-v mono">{{ periodInsights.winRateRatio }}%</span>
          </div>
        </div>

        <div class="period-chart-wrap">
          <div class="period-chart">
            <div
              v-for="point in chronologicalSinglePoints"
              :key="String(point.period)"
              class="chart-col"
              :class="{ 'is-active': point.period === selectedPeriod }"
              :title="`点击筛选 ${point.period} 样本`"
              @click="onSelectPeriod(point.period)"
            >
              <!-- 顶部胜率胶囊 -->
              <div class="chart-col__top">
                <span
                  class="chart-rate-pill mono"
                  :class="winRateDisplayTone(Number(point.win_rate), Number(point.total))"
                >
                  {{ winRateText(point.win_rate as number | null) }}
                </span>
              </div>

              <!-- 中间柱状图区（带零基准线） -->
              <div class="chart-col__body">
                <div class="chart-zero-line" />
                <div
                  v-if="(Number(point.avg_return) || 0) >= 0"
                  class="chart-bar chart-bar--up"
                  :style="{
                    height: `${Math.min(100, Math.max(8, ((Number(point.avg_return) || 0) / chartScale.maxAbs) * 100))}%`,
                  }"
                >
                  <span class="chart-bar-val mono tone-up">{{ signedPct(point.avg_return as number) }}</span>
                </div>
                <div
                  v-else
                  class="chart-bar chart-bar--down"
                  :style="{
                    height: `${Math.min(100, Math.max(8, (Math.abs(Number(point.avg_return) || 0) / chartScale.maxAbs) * 100))}%`,
                  }"
                >
                  <span class="chart-bar-val mono tone-down">{{ signedPct(point.avg_return as number) }}</span>
                </div>
              </div>

              <!-- 底部周期标签 -->
              <div class="chart-col__label mono">
                {{ point.period }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 100% 全宽详细数据表 -->
      <section class="period-table-section" aria-label="分周期数据列表">
        <BasicTable
          :columns="columns"
          :data-source="rows"
          :pagination="false"
          :row-class-name="singleRowClass"
          row-key="period"
          @row-click="(row: Record<string, unknown>) => onSelectPeriod(row.period)"
        >
          <template #period="{ row }">
            <div class="row-period-cell">
              <span v-if="row.period === selectedPeriod" class="row-period-active-dot" />
              <strong class="mono row-period-badge">{{ row.period }}</strong>
            </div>
          </template>

          <template #singleRate="{ row }">
            <div class="row-rate-cell">
              <strong class="mono row-rate-val" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
                {{ winRateText(row.win_rate as number | null) }}
              </strong>
              <div class="row-rate-meter">
                <div
                  class="row-rate-fill"
                  :style="{ width: `${Math.max(0, Math.min(100, Number(row.win_rate) || 0))}%` }"
                />
              </div>
              <span v-if="sampleBadgeLabel(Number(row.total))" class="sample-badge" :class="badgeClass(row.total)">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </span>
            </div>
          </template>

          <!-- 战绩分布（盈/亏比例条） -->
          <template #distribution="{ row }">
            <div class="row-dist-cell">
              <div class="row-dist-bar">
                <div
                  class="row-dist-fill--win"
                  :style="{ width: `${Number(row.total) ? (Number(row.wins) / Number(row.total)) * 100 : 0}%` }"
                />
                <div
                  class="row-dist-fill--loss"
                  :style="{ width: `${Number(row.total) ? (Number(row.losses) / Number(row.total)) * 100 : 0}%` }"
                />
              </div>
              <span class="mono row-dist-text">
                <span class="tone-up">{{ row.wins }}盈</span> / <span class="tone-down">{{ row.losses }}亏</span>
              </span>
            </div>
          </template>

          <template #total="{ row }">
            <span class="mono row-count-val">{{ row.wins }} / {{ row.total }}</span>
          </template>

          <template #avg="{ row }">
            <strong class="mono row-avg-val" :class="toneOf(row.avg_return)">
              {{ signedPct(row.avg_return as number | null) }}
            </strong>
          </template>

          <template #action="{ row }">
            <button
              type="button"
              class="row-action-btn"
              :class="{ 'is-active': row.period === selectedPeriod }"
              @click.stop="onSelectPeriod(row.period)"
            >
              {{ row.period === selectedPeriod ? '已聚焦' : '筛选样本' }}
            </button>
          </template>
        </BasicTable>
      </section>
    </template>

    <!-- 综合对比矩阵模式（100% 全宽展开） -->
    <template v-else-if="rows.length">
      <BasicTable
        :columns="columns"
        :data-source="rows"
        :pagination="false"
        row-key="period"
      >
        <template #period="{ row }">
          <strong class="mono row-period-badge">{{ row.period }}</strong>
        </template>
        <template v-for="tag in tags" :key="tag" #[`tag_${tag}`]="{ row }">
          <div
            v-if="pointAt(row, tag)"
            class="matrix-cell"
            :style="heatStyle(pointAt(row, tag)?.win_rate)"
          >
            <div class="matrix-cell__top">
              <strong
                class="mono matrix-cell__rate"
                :class="winRateDisplayTone(pointAt(row, tag)?.win_rate ?? null, pointAt(row, tag)?.total ?? 0)"
              >
                {{ winRateText(pointAt(row, tag)?.win_rate ?? null) }}
              </strong>
            </div>
            <div class="matrix-cell__bottom">
              <span class="mono dim matrix-cell__count">{{ pointAt(row, tag)?.wins }}/{{ pointAt(row, tag)?.total }}</span>
              <span class="mono matrix-cell__avg" :class="toneOf(pointAt(row, tag)?.avg_return)">
                {{ signedPct(pointAt(row, tag)?.avg_return ?? null) }}
              </span>
            </div>
          </div>
          <span v-else class="dim">—</span>
        </template>
      </BasicTable>
    </template>

    <EmptyState
      v-else
      description="还没有分周期样本"
      reason="精选候选走完 T+5 后按选出日自动聚合"
      :image-size="64"
    />
  </div>
</template>

<style scoped src="./WinRatePeriodTable.css"></style>
