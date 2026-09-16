<script setup lang="ts">
import { computed, ref } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import UiButton from '@/shared/components/ui/UiButton.vue'
import { price, signedPct } from '@/shared/lib/format'
import {
  sampleBadgeLabel,
  sampleConfidence,
  winRateDisplayTone,
  winRateStatTone,
  winRateText,
} from '@/shared/lib/winrate'
import type { WinRateSampleDetail, WinRateSummary } from '@/shared/types/quant'

/**
 * 一个战法的胜率证据：分母怎么来的、最好最坏是哪只票、该拿几天、逐条样本。
 *
 * 纯展示。数据由 WinRateView 拉好传进来——请求竞态与持有期切换归父级，
 * 组件挂载时不自己发请求（前端手册 §3.3.1 封装契约 4）。
 */
const props = defineProps<{
  tag: string
  summary: WinRateSummary | null
  detail: WinRateSampleDetail | null
  busy?: boolean
  selectedPeriod?: string | null
}>()

const emit = defineEmits<{
  clearPeriod: []
}>()

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

const filteredSamples = computed(() => {
  let list = sampleRows.value

  // 1. 分段过滤
  if (filterTab.value === 'win') list = list.filter((s) => s.win === true)
  else if (filterTab.value === 'loss') list = list.filter((s) => s.win === false)
  else if (filterTab.value === 'pending') list = list.filter((s) => s.win === null || s.win === undefined)

  // 2. 周期过滤（如果点击了下方的月/周）
  if (props.selectedPeriod) {
    const period = props.selectedPeriod.trim()
    if (!period.includes('-W')) {
      list = list.filter((s) => String(s.base_date || '').startsWith(period))
    }
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

/* 六列固定宽合计 ≤ 左栅格（32rem），避免挤压 */
const horizonColumns: BasicTableColumn[] = [
  { prop: 'horizon', label: '持有期', width: 92, slotName: 'horizon' },
  { prop: 'n', label: '样本', width: 56, align: 'right', headerAlign: 'right' },
  { prop: 'win_rate', label: '胜率', width: 110, align: 'right', headerAlign: 'right', slotName: 'winRate' },
  { prop: 'avg', label: '均收益', width: 80, align: 'right', headerAlign: 'right', slotName: 'avg' },
  { prop: 'best', label: '最好', width: 76, align: 'right', headerAlign: 'right', slotName: 'best' },
  { prop: 'worst', label: '最差', minWidth: 76, align: 'right', headerAlign: 'right', slotName: 'worst' },
]

const sampleColumns: BasicTableColumn[] = [
  { prop: 'base_date', label: '选出日', width: 104, slotName: 'baseDate' },
  { prop: 'code', label: '标的', minWidth: 140, slotName: 'stock' },
  { prop: 'base_close', label: '基准价', width: 84, align: 'right', headerAlign: 'right', slotName: 'baseClose' },
  { prop: 't1', label: 'T+1', width: 80, align: 'right', headerAlign: 'right', slotName: 't1' },
  { prop: 't3', label: 'T+3', width: 80, align: 'right', headerAlign: 'right', slotName: 't3' },
  { prop: 't5', label: 'T+5', width: 80, align: 'right', headerAlign: 'right', slotName: 't5' },
  { prop: 'max_favorable_pct', label: '窗内最高', width: 92, align: 'right', headerAlign: 'right', slotName: 'maxFavorable' },
  { prop: 'win', label: '裁决结果', width: 92, align: 'center', headerAlign: 'center', slotName: 'win' },
]

function horizonRowClass(data: { row: Record<string, unknown> }): string {
  const classes: string[] = ['horizon-clickable-row']
  if (data.row.key === bestHorizonKey.value) classes.push('is-best-horizon')
  if (data.row.horizon === activeHorizon.value) classes.push('is-active-horizon')
  return classes.join(' ')
}

function toggleHorizon(horizon: unknown): void {
  const h = Number(horizon)
  if (!h) return
  activeHorizon.value = activeHorizon.value === h ? null : h
}

function returnAt(row: Record<string, unknown>, horizon: number): number | null {
  const returns = row.returns as Record<string, number | null> | undefined
  const value = returns?.[`t${horizon}`]
  return typeof value === 'number' ? value : null
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'dim'
  return Number(value) >= 0 ? 'tone-up' : 'tone-down'
}

function outcomeLabel(win: unknown): string {
  if (win === true) return '盈利'
  if (win === false) return '亏损'
  return '观察中'
}

function outcomeTone(win: unknown): string {
  if (win === true) return 'outcome-win'
  if (win === false) return 'outcome-loss'
  return 'outcome-pending'
}

function badgeClass(total: unknown): string {
  return sampleConfidence(Number(total) || 0) === 'low' ? 'sample-badge-low' : 'sample-badge-medium'
}
</script>

<template>
  <div class="wr-panel" v-loading="busy" :aria-busy="busy">
    <!-- 结论行：主数字 + 口径注脚 + 推导公式。四项注脚原来各带一圈边框占掉
         一整行，把下面两张表挤出视口——它们是胜率的注脚，不是四个 KPI。 -->
    <section class="wr-summary" aria-label="战法战绩总览">
      <div class="wr-summary__rate">
        <span class="wr-summary__label">T+{{ detail?.primary_horizon ?? 5 }} 核心胜率</span>
        <span
          class="wr-summary__val"
          :class="winRateStatTone(detail?.win_rate ?? null, detail?.settled ?? 0)"
        >
          {{ winRateText(detail?.win_rate ?? null) }}
        </span>
        <span
          v-if="sampleBadgeLabel(detail?.settled ?? 0)"
          class="sample-badge"
          :class="badgeClass(detail?.settled)"
        >
          {{ sampleBadgeLabel(detail?.settled ?? 0) }}
        </span>
      </div>

      <div class="wr-summary__facts">
        <div class="wr-fact">
          <span class="wr-fact__k">计算口径</span>
          <span class="wr-fact__v">精选候选 T+{{ detail?.primary_horizon ?? 5 }}</span>
        </div>
        <div class="wr-fact">
          <span class="wr-fact__k">结算进分母</span>
          <span class="wr-fact__v">{{ detail ? `${detail.settled} 条` : "—" }}</span>
        </div>
        <div class="wr-fact">
          <span class="wr-fact__k">盈利样本</span>
          <span class="wr-fact__v tone-up">{{ detail ? `${detail.wins} 条` : "—" }}</span>
        </div>
        <div class="wr-fact">
          <span class="wr-fact__k">窗口观察中</span>
          <span class="wr-fact__v dim">{{ detail ? `${detail.observing} 条` : "—" }}</span>
        </div>
      </div>

      <p v-if="formula" class="wr-formula">
        <span class="wr-formula__text">{{ formula }}</span>
      </p>
    </section>

    <!-- 三大关键洞察 Bento 卡片 -->
    <section class="wr-cards" aria-label="样本洞察">
      <!-- 最佳样本 -->
      <div class="wr-card wr-card--best">
        <div class="wr-card__head">
          <span class="wr-card__k">
                        最佳样本
          </span>
          <span v-if="bestSample" class="wr-card__date mono dim">{{ bestSample.base_date }} 选出</span>
        </div>
        <div v-if="bestSample" class="wr-card__body">
          <div class="wr-card__target">
            <StockLink
              :code="bestSample.code"
              :name="bestSample.name"
              class="wr-card__stock-link"
            />
          </div>
          <div class="wr-card__metric">
            <span class="wr-card__num mono" :class="tone(bestSample.return_pct)">{{ signedPct(bestSample.return_pct) }}</span>
            <span v-if="bestSample.max_favorable_pct != null" class="wr-card__sub mono dim">
              最高冲幅 {{ signedPct(bestSample.max_favorable_pct) }}
            </span>
          </div>
        </div>
        <div v-else class="wr-card__empty dim">尚无走完窗口的样本</div>
      </div>

      <!-- 最差样本 -->
      <div class="wr-card wr-card--worst">
        <div class="wr-card__head">
          <span class="wr-card__k">
                        最差样本
          </span>
          <span v-if="worstSample" class="wr-card__date mono dim">{{ worstSample.base_date }} 选出</span>
        </div>
        <div v-if="worstSample" class="wr-card__body">
          <div class="wr-card__target">
            <StockLink
              :code="worstSample.code"
              :name="worstSample.name"
              class="wr-card__stock-link"
            />
          </div>
          <div class="wr-card__metric">
            <span class="wr-card__num mono" :class="tone(worstSample.return_pct)">{{ signedPct(worstSample.return_pct) }}</span>

          </div>
        </div>
        <div v-else class="wr-card__empty dim">尚无走完窗口的样本</div>
      </div>

      <!-- 最佳持有期 -->
      <div class="wr-card wr-card--horizon">
        <div class="wr-card__head">
          <span class="wr-card__k">
                        最佳持有期
          </span>
          <span v-if="bestHorizon" class="wr-card__date mono dim">样本容量 n={{ bestHorizon.n }}</span>
        </div>
        <div v-if="bestHorizon" class="wr-card__body">
          <div class="wr-card__target">
            <span class="wr-horizon-pill mono">T+{{ bestHorizon.horizon }}</span>
            <span class="wr-horizon-tip dim">历史样本比较</span>
          </div>
          <div class="wr-card__metric">
            <span class="wr-card__num mono" :class="winRateDisplayTone(bestHorizon.win_rate, bestHorizon.n)">
              {{ winRateText(bestHorizon.win_rate) }}
            </span>
            <span class="wr-card__sub mono" :class="tone(bestHorizon.avg)">
              均 {{ signedPct(bestHorizon.avg) }}
            </span>
          </div>
        </div>
        <div v-else class="wr-card__empty dim">样本不足 3 条，不评最佳持有期</div>
      </div>
    </section>

    <!-- 双栏表格区域：左侧持有期表现，右侧样本明细 -->
    <div class="wr-tables-grid">
      <!-- 各持有期表现 -->
      <section class="wr-block" aria-label="各持有期表现">
        <div class="wr-block__header">
          <div class="wr-block__title-wrap">
            <h4 class="wr-block__title">各持有期表现</h4>
            <span class="wr-block__tip dim">点击行可高亮对应收益</span>
          </div>
        </div>
        <BasicTable
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
            <el-button text size="small" class="wr-horizon-badge" :aria-pressed="activeHorizon === row.horizon" :aria-label="`高亮 T+${row.horizon} 收益`" @click.stop="toggleHorizon(row.horizon)">
              <strong class="mono">T+{{ row.horizon }}</strong>
              <span v-if="row.key === bestHorizonKey" class="wr-best-badge">最佳</span>
            </el-button>
          </template>
          <template #winRate="{ row }">
            <span class="mono" :class="winRateDisplayTone(Number(row.win_rate), Number(row.n))">
              {{ winRateText(row.win_rate as number | null) }}
            </span>
          </template>
          <template #avg="{ row }">
            <span class="mono" :class="tone(row.avg as number)">{{ signedPct(row.avg as number) }}</span>
          </template>
          <template #best="{ row }">
            <span class="mono" :class="tone(row.best as number)">{{ signedPct(row.best as number) }}</span>
          </template>
          <template #worst="{ row }">
            <span class="mono" :class="tone(row.worst as number)">{{ signedPct(row.worst as number) }}</span>
          </template>
        </BasicTable>
      </section>

      <!-- 样本明细（支持快捷过滤与个股穿透） -->
      <section class="wr-block" aria-label="样本明细">
        <div class="wr-block__header">
          <div class="wr-block__title-wrap">
            <h4 class="wr-block__title">
              样本明细
              <span class="wr-block__count mono dim">({{ sampleRows.length }})</span>
            </h4>
            <span v-if="detail?.truncated" class="wr-block__tip dim">仅显示最近 {{ sampleRows.length }} 条</span>
          </div>

          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <UiBadge v-if="selectedPeriod" variant="default">
              周期: {{ selectedPeriod }}
              <UiButton size="sm" variant="ghost" aria-label="清除周期筛选" @click="emit('clearPeriod')">✕</UiButton>
            </UiBadge>
            <el-input
              v-model="searchQuery"
              size="small"
              placeholder="搜代码/名称"
              aria-label="筛选样本代码或名称"
              clearable
              class="w-30 shrink-0"
            />
            <div class="bg-sunken border-line inline-flex items-center gap-0.5 rounded-md border p-0.5" role="group" aria-label="样本筛选">
              <UiButton size="sm" :variant="filterTab === 'all' ? 'secondary' : 'ghost'" :aria-pressed="filterTab === 'all'" @click="filterTab = 'all'">
                全部 ({{ sampleRows.length }})
              </UiButton>
              <UiButton size="sm" :variant="filterTab === 'win' ? 'secondary' : 'ghost'" :aria-pressed="filterTab === 'win'" @click="filterTab = 'win'">
                盈利 ({{ winSamplesCount }})
              </UiButton>
              <UiButton size="sm" :variant="filterTab === 'loss' ? 'secondary' : 'ghost'" :aria-pressed="filterTab === 'loss'" @click="filterTab = 'loss'">
                亏损 ({{ lossSamplesCount }})
              </UiButton>
              <UiButton size="sm" :variant="filterTab === 'pending' ? 'secondary' : 'ghost'" :aria-pressed="filterTab === 'pending'" @click="filterTab = 'pending'">
                观察中 ({{ pendingSamplesCount }})
              </UiButton>
            </div>
          </div>
        </div>

        <BasicTable
          :columns="sampleColumns"
          :data-source="filteredSamples"
          :pagination="false"
          max-height="380"
          :loading="busy"
          row-key="candidate_id"
          empty-text="这个战法还没有精选样本"
          empty-reason="只有裁决为「精选」的候选才进胜率"
        >
          <template #baseDate="{ row }">
            <span class="mono dim">{{ row.base_date }}</span>
          </template>
          <template #stock="{ row }">
            <StockLink
              :code="String(row.code || '')"
              :name="String(row.name || '')"
              class="wr-table-stock-link"
            />
          </template>
          <template #baseClose="{ row }">
            <span class="mono">{{ price(row.base_close as number | null) }}</span>
          </template>
          <template #t1="{ row }">
            <span
              class="mono"
              :class="[tone(returnAt(row, 1)), { 'is-active-col': activeHorizon === 1 }]"
            >
              {{ signedPct(returnAt(row, 1)) }}
            </span>
          </template>
          <template #t3="{ row }">
            <span
              class="mono"
              :class="[tone(returnAt(row, 3)), { 'is-active-col': activeHorizon === 3 }]"
            >
              {{ signedPct(returnAt(row, 3)) }}
            </span>
          </template>
          <template #t5="{ row }">
            <span
              class="mono"
              :class="[tone(returnAt(row, 5)), { 'is-active-col': activeHorizon === 5 }]"
            >
              {{ signedPct(returnAt(row, 5)) }}
            </span>
          </template>
          <template #maxFavorable="{ row }">
            <span class="mono dim">{{ signedPct(row.max_favorable_pct as number | null) }}</span>
          </template>
          <template #win="{ row }">
            <span class="wr-outcome-tag" :class="outcomeTone(row.win)">
              {{ outcomeLabel(row.win) }}
            </span>
          </template>
          <template #empty>
            <EmptyState
              v-if="busy"
              description="加载样本…"
              :image-size="64"
            />
            <EmptyState
              v-else-if="!sampleRows.length"
              description="这个战法还没有精选样本"
              reason="只有裁决为「精选」的候选才进胜率"
              :image-size="64"
            />
            <EmptyState
              v-else
              description="当前筛选下无匹配样本"
              reason="请切换筛选标签查看全部"
              :image-size="64"
            />
          </template>
        </BasicTable>
      </section>
    </div>
  </div>
</template>

<style scoped src="./WinRateStrategyPanel.css"></style>
