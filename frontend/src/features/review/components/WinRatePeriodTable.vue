<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import UiButton from '@/shared/components/ui/UiButton.vue'
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
  names?: Map<string, string>
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
      { prop: 'distribution', label: '盈利 / 亏损', minWidth: 180, slotName: 'distribution' },
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
      label: strategyShortLabel(tag, props.names),
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
    <!-- 周期图与明细共用同一组过滤后的数据。 -->
    <template v-if="mode === 'single'">
      <!-- 周期收益与胜率趋势工坊 (Period Studio) -->
      <section v-if="rows.length" class="period-studio" aria-label="周期趋势概览">
        <div class="period-studio__header">
          <div class="period-studio__title-row">
                  <span class="period-studio__title">{{ periodLabel }}均收益</span>
            <span class="period-studio__sub dim">点击柱形筛选样本</span>
          </div>
          <div class="period-studio__legend">
            <span class="legend-item"><span class="legend-dot legend-dot--up" />正收益</span>
            <span class="legend-item"><span class="legend-dot legend-dot--down" />负收益</span>
            <span class="legend-item"><span class="legend-line" />胜率</span>
          </div>
        </div>

        <div class="period-chart-wrap">
          <div class="period-chart">
            <el-button
              text
              v-for="point in chronologicalSinglePoints"
              :key="String(point.period)"
              class="chart-col"
              :class="{ 'is-active': point.period === selectedPeriod }"
              :title="`点击筛选 ${point.period} 样本`"
              :aria-label="`${point.period}，均收益${signedPct(point.avg_return as number | null)}，胜率${winRateText(point.win_rate as number | null)}`"
              :aria-pressed="point.period === selectedPeriod"
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
                  v-if="typeof point.avg_return === 'number' && Number.isFinite(point.avg_return) && point.avg_return >= 0"
                  class="chart-bar chart-bar--up"
                  :style="{
                    height: `${Math.min(50, Math.max(0, (Number(point.avg_return) / chartScale.maxAbs) * 50))}%`,
                  }"
                >
                  <span class="chart-bar-val mono tone-up">{{ signedPct(point.avg_return as number) }}</span>
                </div>
                <div
                  v-else-if="typeof point.avg_return === 'number' && Number.isFinite(point.avg_return)"
                  class="chart-bar chart-bar--down"
                  :style="{
                    height: `${Math.min(50, Math.max(0, (Math.abs(Number(point.avg_return)) / chartScale.maxAbs) * 50))}%`,
                  }"
                >
                  <span class="chart-bar-val mono tone-down">{{ signedPct(point.avg_return as number) }}</span>
                </div>
                <span v-else class="chart-missing dim">—</span>
              </div>

              <!-- 底部周期标签 -->
              <div class="chart-col__label mono">
                {{ point.period }}
              </div>
            </el-button>
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
          height="100%"
          row-key="period"
          empty-text="还没有分周期样本"
          empty-reason="精选候选走完 T+5 后按选出日自动聚合"
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
              <span v-if="sampleBadgeLabel(Number(row.total))" class="sample-badge" :class="badgeClass(row.total)">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </span>
            </div>
          </template>

          <!-- 战绩分布（盈/亏比例条） -->
          <template #distribution="{ row }">
            <div class="row-dist-cell">
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
            <UiButton
              size="sm"
              :variant="row.period === selectedPeriod ? 'default' : 'outline'"
              :aria-pressed="row.period === selectedPeriod"
              @click.stop="onSelectPeriod(row.period)"
            >
              {{ row.period === selectedPeriod ? '已聚焦' : '筛选样本' }}
            </UiButton>
          </template>
        </BasicTable>
      </section>
    </template>

    <template v-else>
      <BasicTable
        :columns="columns"
        :data-source="rows"
        :pagination="false"
        height="100%"
        row-key="period"
        empty-text="还没有分周期样本"
        empty-reason="精选候选走完 T+5 后按选出日自动聚合"
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
  </div>
</template>

<style scoped src="./WinRatePeriodTable.css"></style>
