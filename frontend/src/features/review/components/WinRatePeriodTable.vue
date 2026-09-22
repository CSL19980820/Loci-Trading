<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { CalendarRange } from '@lucide/vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { signedPct, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, sampleConfidence, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateTrendPoint } from '@/shared/types/quant'

/**
 * 分周期表两种形态，同一份数据：
 *
 * - `matrix`：周期 × 战法，综合层用来横向比同一个月谁更强（手机端退成按周期分组的卡片）。
 * - `single`：一个战法的周期序列——均收益柱 + 胜率标签的迷你图，加一张周期明细表；
 *   点柱 / 点行把上方样本明细筛到那个周期。
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

const isMobile = useMediaQuery('(max-width: 640px)')
const fillDesktop = useMediaQuery('(min-width:1024px) and (min-height:600px)')

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
      { prop: 'period', label: periodLabel.value, width: 130, slotName: 'period' },
      { prop: 'win_rate', label: '胜率', minWidth: 160, slotName: 'singleRate' },
      { prop: 'distribution', label: '盈 / 亏', width: 120, align: 'right', headerAlign: 'right', slotName: 'distribution' },
      { prop: 'avg_return', label: '周期均收益', width: 120, align: 'right', headerAlign: 'right', slotName: 'avg' },
      { prop: 'action', label: '', width: 96, align: 'right', headerAlign: 'right', slotName: 'action' },
    ]
  }
  const cols: BasicTableColumn[] = [
    { prop: 'period', label: periodLabel.value, width: 120, slotName: 'period' },
  ]
  for (const tag of props.tags) {
    cols.push({
      prop: tag,
      label: strategyShortLabel(tag, props.names),
      align: 'right',
      headerAlign: 'right',
      minWidth: 150,
      slotName: `tag_${tag}`,
    })
  }
  return cols
})

function pointAt(row: Record<string, unknown>, tag: string): WinRateTrendPoint | undefined {
  const byTag = row.byTag as Record<string, WinRateTrendPoint> | undefined
  return byTag?.[tag]
}

function sampleVariant(total: unknown): 'secondary' | 'warn' {
  return sampleConfidence(Number(total) || 0) === 'low' ? 'secondary' : 'warn'
}

function toneOf(value: unknown): string {
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return 'pt-dim'
  return n >= 0 ? 'tone-up' : 'tone-down'
}

function heatStyle(rate: number | null | undefined): Record<string, string> {
  const n = Number(rate)
  if (!Number.isFinite(n) || n < 50) return {}
  return {
    backgroundColor: `color-mix(in oklab, var(--seal) ${Math.min(22, Math.round((n - 40) * 0.35))}%, transparent)`,
  }
}

function barHeight(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0%'
  return `${Math.min(50, Math.max(0, (Math.abs(n) / chartScale.value.maxAbs) * 50))}%`
}

function onSelectPeriod(period: unknown): void {
  const p = String(period || '')
  if (p) emit('selectPeriod', p)
}

function singleRowClass(data: { row: Record<string, unknown> }): string {
  return data.row.period === props.selectedPeriod ? 'period-active-row is-clickable' : 'is-clickable'
}
</script>

<template>
  <div class="period-container">
    <template v-if="mode === 'single'">
      <!-- 迷你图：每个周期一根均收益柱（正上负下）+ 顶部胜率标签；点柱筛样本 -->
      <section v-if="rows.length" class="pt-studio" aria-label="周期趋势概览">
        <div class="pt-studio__head">
          <span class="pt-studio__title">{{ periodLabel }}均收益</span>
          <span class="pt-studio__legend">
            <span class="pt-legend"><i class="pt-legend__dot tone-up-bg" />正收益</span>
            <span class="pt-legend"><i class="pt-legend__dot tone-down-bg" />负收益</span>
            <span class="pt-dim">点柱筛选样本</span>
          </span>
        </div>
        <div class="pt-chart-wrap">
          <div class="pt-chart">
            <Button access="read" variant="ghost"
              v-for="point in chronologicalSinglePoints"
              :key="String(point.period)"
              type="button"
              class="pt-col"
              :class="{ 'is-active': point.period === selectedPeriod }"
              :title="`点击筛选 ${point.period} 样本`"
              :aria-label="`${point.period}，均收益${signedPct(point.avg_return as number | null)}，胜率${winRateText(point.win_rate as number | null)}`"
              :aria-pressed="point.period === selectedPeriod"
              @click="onSelectPeriod(point.period)"
            >
              <span class="pt-col__rate pt-num" :class="winRateDisplayTone(Number(point.win_rate), Number(point.total))">
                {{ winRateText(point.win_rate as number | null) }}
              </span>
              <span class="pt-col__body">
                <span class="pt-col__zero" />
                <template v-if="typeof point.avg_return === 'number' && Number.isFinite(point.avg_return)">
                  <span
                    class="pt-bar"
                    :class="point.avg_return >= 0 ? 'pt-bar--up' : 'pt-bar--down'"
                    :style="{ height: barHeight(point.avg_return) }"
                  >
                    <span class="pt-bar__val pt-num" :class="toneOf(point.avg_return)">{{ signedPct(point.avg_return) }}</span>
                  </span>
                </template>
                <span v-else class="pt-col__missing pt-dim">—</span>
              </span>
              <span class="pt-col__label pt-num">{{ point.period }}</span>
            </Button>
          </div>
        </div>
      </section>

      <!-- 手机：周期卡片 -->
      <ul v-if="isMobile && rows.length" class="pt-cards" aria-label="分周期数据">
        <li
          v-for="row in rows"
          :key="String(row.period)"
          class="pt-card"
          :class="{ 'is-active': row.period === selectedPeriod }"
          tabindex="0"
          role="button"
          :aria-pressed="row.period === selectedPeriod"
          :aria-label="`筛选 ${row.period} 样本`"
          @click="onSelectPeriod(row.period)"
          @keydown.enter.prevent="onSelectPeriod(row.period)"
        >
          <div class="pt-card__main">
            <strong class="pt-num pt-card__period">{{ row.period }}</strong>
            <span class="pt-card__sub">
              <span class="pt-num"><span class="tone-up">{{ row.wins }} 盈</span> / <span class="tone-down">{{ row.losses }} 亏</span></span>
              <span class="pt-num" :class="toneOf(row.avg_return)">均 {{ signedPct(row.avg_return as number | null) }}</span>
              <UiBadge v-if="sampleBadgeLabel(Number(row.total))" :variant="sampleVariant(row.total)">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </UiBadge>
            </span>
          </div>
          <span class="pt-card__big pt-num" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
            {{ winRateText(row.win_rate as number | null) }}
          </span>
        </li>
      </ul>

      <!-- 桌面：明细表 -->
      <BasicTable
        v-else-if="!isMobile"
        class="pt-table"
        :columns="columns"
        :data-source="rows"
        :pagination="false" :height="fillDesktop ? '100%' : undefined"
        :row-class-name="singleRowClass"
        row-key="period"
        empty-text="还没有分周期样本"
        empty-reason="精选候选走完 T+5 后按选出日自动聚合"
        @row-click="(row: Record<string, unknown>) => onSelectPeriod(row.period)"
      >
        <template #period="{ row }">
          <span class="pt-period">
            <i v-if="row.period === selectedPeriod" class="pt-period__dot" aria-hidden="true" />
            <strong class="pt-num">{{ row.period }}</strong>
          </span>
        </template>
        <template #singleRate="{ row }">
          <span class="pt-rate">
            <strong class="pt-num pt-rate__val" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
              {{ winRateText(row.win_rate as number | null) }}
            </strong>
            <span class="pt-num pt-dim">{{ row.wins }}/{{ row.total }}</span>
            <UiBadge v-if="sampleBadgeLabel(Number(row.total))" :variant="sampleVariant(row.total)">
              {{ sampleBadgeLabel(Number(row.total)) }}
            </UiBadge>
          </span>
        </template>
        <template #distribution="{ row }">
          <span class="pt-num"><span class="tone-up">{{ row.wins }}</span><span class="pt-dim"> / </span><span class="tone-down">{{ row.losses }}</span></span>
        </template>
        <template #avg="{ row }">
          <strong class="pt-num" :class="toneOf(row.avg_return)">{{ signedPct(row.avg_return as number | null) }}</strong>
        </template>
        <template #action="{ row }">
          <span class="pt-action" :class="{ 'is-active': row.period === selectedPeriod }">
            {{ row.period === selectedPeriod ? '已聚焦' : '筛选样本' }}
          </span>
        </template>
        <template #empty>
          <EmptyState
            class="pt-empty"
            description="还没有分周期样本"
            reason="精选候选走完 T+5 后按选出日自动聚合"
            :icon="CalendarRange"
          />
        </template>
      </BasicTable>
      <EmptyState
        v-else
        class="pt-empty"
        description="还没有分周期样本"
        reason="精选候选走完 T+5 后按选出日自动聚合"
        :icon="CalendarRange"
      />
    </template>

    <template v-else>
      <!-- 手机：按周期分组的卡片，每张里列各战法 -->
      <ul v-if="isMobile && rows.length" class="pt-groups" aria-label="同期对比">
        <li v-for="row in rows" :key="String(row.period)" class="pt-group">
          <strong class="pt-num pt-group__period">{{ row.period }}</strong>
          <ul class="pt-group__list">
            <li v-for="tag in tags" :key="tag" class="pt-group__row">
              <span class="pt-group__name">{{ strategyShortLabel(tag, names) }}</span>
              <template v-if="pointAt(row, tag)">
                <span class="pt-num pt-dim">{{ pointAt(row, tag)?.wins }}/{{ pointAt(row, tag)?.total }}</span>
                <span class="pt-num" :class="toneOf(pointAt(row, tag)?.avg_return)">{{ signedPct(pointAt(row, tag)?.avg_return ?? null) }}</span>
                <strong class="pt-num pt-group__rate" :class="winRateDisplayTone(pointAt(row, tag)?.win_rate ?? null, pointAt(row, tag)?.total ?? 0)">
                  {{ winRateText(pointAt(row, tag)?.win_rate ?? null) }}
                </strong>
              </template>
              <span v-else class="pt-dim pt-group__rate">—</span>
            </li>
          </ul>
        </li>
      </ul>

      <BasicTable
        v-else-if="!isMobile"
        class="pt-table"
        :columns="columns"
        :data-source="rows"
        :pagination="false" :height="fillDesktop ? '100%' : undefined"
        row-key="period"
        empty-text="还没有分周期样本"
        empty-reason="精选候选走完 T+5 后按选出日自动聚合"
      >
        <template #period="{ row }">
          <strong class="pt-num">{{ row.period }}</strong>
        </template>
        <template v-for="tag in tags" :key="tag" #[`tag_${tag}`]="{ row }">
          <span v-if="pointAt(row, tag)" class="pt-matrix" :style="heatStyle(pointAt(row, tag)?.win_rate)">
            <strong
              class="pt-num pt-matrix__rate"
              :class="winRateDisplayTone(pointAt(row, tag)?.win_rate ?? null, pointAt(row, tag)?.total ?? 0)"
            >
              {{ winRateText(pointAt(row, tag)?.win_rate ?? null) }}
            </strong>
            <span class="pt-matrix__sub">
              <span class="pt-num pt-dim">{{ pointAt(row, tag)?.wins }}/{{ pointAt(row, tag)?.total }}</span>
              <span class="pt-num" :class="toneOf(pointAt(row, tag)?.avg_return)">
                {{ signedPct(pointAt(row, tag)?.avg_return ?? null) }}
              </span>
            </span>
          </span>
          <span v-else class="pt-dim">—</span>
        </template>
        <template #empty>
          <EmptyState
            class="pt-empty"
            description="还没有分周期样本"
            reason="精选候选走完 T+5 后按选出日自动聚合"
            :icon="CalendarRange"
          />
        </template>
      </BasicTable>
      <EmptyState
        v-else
        class="pt-empty"
        description="还没有分周期样本"
        reason="精选候选走完 T+5 后按选出日自动聚合"
        :icon="CalendarRange"
      />
    </template>
  </div>
</template>

<style scoped src="./WinRatePeriodTable.css"></style>
