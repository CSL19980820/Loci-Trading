<script setup lang="ts">
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { TriangleAlert } from '@lucide/vue'

import EquityLineChart from '@/shared/components/charts/EquityLineChart.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import { Button } from '@/shared/components/ui/button'
import SegmentSwitch from '@/shared/components/ui/SegmentSwitch.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import StatCard from '@/shared/components/ui/StatCard.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { copyText } from '@/shared/lib/clipboard'
import type { BacktestResult } from '@/shared/types/quant'

import { buildTradeSummaryText } from '../composables/quantBacktestSummary'
import { exitReasonLabel, pnlTone, signed } from '../composables/quantFormat'
import QuantBacktestDistBars from './QuantBacktestDistBars.vue'

const props = defineProps<{
  result: BacktestResult
  strategyLabel?: string
  rangeLabel?: string
}>()

const metrics = computed(() => props.result.metrics)
const performance = computed(() => props.result.performance)
const trades = computed(() => props.result.trades ?? [])
const tradeFilter = ref<string>('all')
const reasonFilter = ref<string | 'all'>('all')

const equityDates = computed(() => performance.value?.equity_curve?.map((p) => p.date) ?? [])
const equityValues = computed(() => performance.value?.equity_curve?.map((p) => p.equity) ?? [])
const ddDates = computed(() => performance.value?.drawdown_curve?.map((p) => p.date) ?? [])
const ddValues = computed(() =>
  performance.value?.drawdown_curve?.map((p) => p.drawdown_pct) ?? [],
)

const mddOverlay = computed(() => {
  const mdd = performance.value?.max_drawdown_pct
  if (mdd == null || !Number.isFinite(mdd)) return ''
  return `最大回撤 ${mdd.toFixed(2)}%`
})

const costText = computed(() => {
  const cfg = props.result.config || {}
  const c = Number(cfg.commission_bps ?? 3)
  const s = Number(cfg.stamp_duty_bps ?? 10)
  const slip = Number(cfg.slippage_bps ?? 5)
  const trip = (c * 2 + s + slip * 2) / 100
  return `成本：佣金单边 ${c}bps · 印花税 ${s}bps · 滑点单边 ${slip}bps · 一趟约 ${trip.toFixed(2)}%`
})

const reasonOptions = computed(() => {
  const reasons = metrics.value.exit_reasons || {}
  return Object.keys(reasons).map((key) => ({
    value: key,
    label: `${exitReasonLabel(key)} (${reasons[key]})`,
  }))
})

const tradeFilterItems = computed(() => [
  { name: 'all', label: `全部 ${trades.value.length}` },
  { name: 'win', label: '盈利' },
  { name: 'loss', label: '亏损' },
])

const filteredTrades = computed(() => {
  return trades.value.filter((row) => {
    if (tradeFilter.value === 'win' && !(row.net_return_pct > 0)) return false
    if (tradeFilter.value === 'loss' && !(row.net_return_pct <= 0)) return false
    if (reasonFilter.value !== 'all' && row.exit_reason !== reasonFilter.value) return false
    return true
  })
})

/**
 * 表格行先摊平成 `Record<string, unknown>[]` 再交给 BasicTable。
 * `BacktestTrade` 是 interface（没有隐式索引签名），直接传会被表格的
 * `dataSource?: Record<string, unknown>[]` 拒收；这里按本地列定义显式列出字段，
 * 列与字段的对应关系就留在同一屏内。
 */
const tradeRows = computed<Record<string, unknown>[]>(() =>
  filteredTrades.value.map((row) => ({
    code: row.code,
    signal_date: row.signal_date,
    entry_date: row.entry_date,
    exit_date: row.exit_date,
    hold_days: row.hold_days,
    net_return_pct: row.net_return_pct,
    mfe_pct: row.mfe_pct,
    mae_pct: row.mae_pct,
    exit_reason: row.exit_reason,
  })),
)

const monthBars = computed(() => {
  const rows = metrics.value.by_month || []
  if (!rows.length) return []
  const maxAbs = Math.max(0.01, ...rows.map((r) => Math.abs(Number(r.avg) || 0)))
  return rows.map((r) => ({
    period: r.period,
    n: r.n,
    avg: r.avg,
    win_rate: r.win_rate,
    height: Math.max(4, Math.round((Math.abs(Number(r.avg) || 0) / maxAbs) * 48)),
    up: Number(r.avg) > 0,
  }))
})

function fmtRatio(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v === Infinity) return '∞'
  if (!Number.isFinite(v)) return '—'
  return v.toFixed(2)
}

function fmtNum(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}${suffix}`
}

async function copySummary(): Promise<void> {
  const text = buildTradeSummaryText({
    strategy: props.strategyLabel || props.result.strategy || 'strategy',
    range: props.rangeLabel || '',
    metrics: metrics.value,
    performance: performance.value,
  })
  if (await copyText(text)) toast.success('已复制摘要')
  else toast.error('复制失败，请手动选中摘要文本复制')
}

const tradeColumns: BasicTableColumn[] = [
  { slotName: 'code', label: '代码', width: 100 },
  { prop: 'signal_date', label: '信号日', width: 108 },
  { prop: 'entry_date', label: '入场', width: 108 },
  { prop: 'exit_date', label: '出场', width: 108 },
  { prop: 'hold_days', label: '持仓', width: 64 },
  { prop: 'net_return_pct', label: '净收益', width: 96, sortable: true },
  { prop: 'mfe_pct', label: 'MFE', width: 88 },
  { prop: 'mae_pct', label: 'MAE', width: 88 },
  { slotName: 'exit_reason', label: '原因', minWidth: 80 },
]
</script>

<template>
  <div class="tr">
    <div class="tr-toolbar">
      <!-- 「便于粘贴到笔记 / 对话」是常驻说明，不占版面：进按钮 tooltip -->
      <Tooltip>
        <TooltipTrigger as-child>
          <Button access="read" size="sm" @click="copySummary">复制摘要</Button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start">
          复制成纯文本摘要，便于粘贴到笔记或对话
        </TooltipContent>
      </Tooltip>
    </div>

    <Alert v-if="metrics.caution" class="tr-alert text-warn">
      <TriangleAlert />
      <AlertTitle class="line-clamp-none min-w-0">{{ metrics.caution }}</AlertTitle>
    </Alert>

    <div class="tr-hero">
      <StatCard label="成交笔数" :value="String(metrics.trades ?? 0)" layout="row" />
      <StatCard label="胜率" :value="fmtNum(metrics.win_rate, 1, '%')" layout="row" />
      <StatCard
        label="均值净收益"
        :value="metrics.avg_net_return == null ? '—' : signed(metrics.avg_net_return)"
        :tone="pnlTone(metrics.avg_net_return)"
        layout="row"
      />
      <StatCard label="盈亏比 PF" :value="fmtRatio(metrics.profit_factor)" layout="row" />
      <StatCard
        label="期望"
        :value="metrics.expectancy == null ? '—' : signed(metrics.expectancy)"
        :tone="pnlTone(metrics.expectancy)"
        layout="row"
      />
      <StatCard label="平均持仓" :value="fmtNum(metrics.avg_hold_days, 1, ' 日')" layout="row" />
    </div>

    <template v-if="performance?.available">
      <div class="tr-perf">
        <StatCard
          label="累计(诊断)"
          :value="performance.cumulative_return_pct == null ? '—' : signed(performance.cumulative_return_pct)"
          :tone="pnlTone(performance.cumulative_return_pct)"
          layout="row"
        />
        <StatCard label="CAGR" :value="fmtNum(performance.cagr_pct, 2, '%')" :tone="pnlTone(performance.cagr_pct)" layout="row" />
        <StatCard label="最大回撤" :value="fmtNum(performance.max_drawdown_pct, 2, '%')" tone="down" layout="row" />
        <StatCard label="夏普" :value="fmtNum(performance.sharpe, 2)" layout="row" />
        <StatCard label="索提诺" :value="fmtNum(performance.sortino, 2)" layout="row" />
        <StatCard label="Calmar" :value="fmtNum(performance.calmar, 2)" layout="row" />
      </div>

      <!--
        那条常驻的 info alert 删了：它永远在、不报任何异常，是被禁的常驻说明条。
        口径（顺序复利诊断曲线、非真实多仓净值）挂到它解释的那张图的标题上。
      -->
      <div class="tr-charts">
        <div class="tr-chart">
          <Tooltip>
            <TooltipTrigger as-child>
              <header tabindex="0">诊断资金曲线</header>
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
              {{ performance.assumption?.description || '顺序复利诊断曲线，非真实多仓账户净值' }}
            </TooltipContent>
          </Tooltip>
          <EquityLineChart
            :dates="equityDates"
            :values="equityValues"
            format-mode="index"
            color="var(--up)"
            :height="200"
            :overlay-text="mddOverlay"
            overlay-tone="down"
          />
        </div>
        <div class="tr-chart">
          <header>回撤曲线</header>
          <EquityLineChart
            :dates="ddDates"
            :values="ddValues"
            format-mode="index"
            color="var(--down)"
            :height="160"
          />
        </div>
      </div>
    </template>

    <div v-if="monthBars.length" class="tr-month">
      <header>分月均值净收益</header>
      <div class="tr-month__bars">
        <div v-for="bar in monthBars" :key="bar.period" class="tr-month__col" :title="`${bar.period} · n=${bar.n} · ${signed(bar.avg)}`">
          <span class="tr-month__val" :class="bar.up ? 'up' : 'down'">{{ signed(bar.avg) }}</span>
          <div class="tr-month__bar" :class="bar.up ? 'is-up' : 'is-down'" :style="{ height: `${bar.height}px` }" />
          <span class="tr-month__lab">{{ bar.period.slice(5) }}</span>
        </div>
      </div>
    </div>

    <div v-if="metrics.return_distribution?.length" class="tr-dist">
      <header>单笔净收益分布</header>
      <QuantBacktestDistBars :bins="metrics.return_distribution" :max-height="64" />
    </div>

    <p class="tr-cost">{{ costText }}</p>
    <p v-if="metrics.data_end_trades" class="tr-note">
      另有 {{ metrics.data_end_trades }} 笔 data_end 未纳入绩效（持有期未完整）。
    </p>

    <div class="tr-filters">
      <SegmentSwitch v-model="tradeFilter" :items="tradeFilterItems" aria-label="成交筛选" />
      <Select v-model="reasonFilter">
        <SelectTrigger size="sm" class="tr-filters__reason" aria-label="退出原因">
          <SelectValue placeholder="退出原因" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部原因</SelectItem>
          <SelectItem v-for="opt in reasonOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>
      <span class="tr-filters__n">显示 {{ filteredTrades.length }} 笔</span>
    </div>

    <EmptyState
      v-if="!trades.length"
      description="本次未返回成交明细（或无可评估交易）"
    />
    <EmptyState
      v-else-if="!filteredTrades.length"
      description="当前筛选下没有成交"
    />
    <BasicTable
      v-else
      :columns="tradeColumns"
      :data-source="tradeRows"
      :pagination="false"
      size="small"
      stripe
      max-height="320"
      class="tr-table"
    >
      <template #code="{ row }">
        <StockLink :code="String(row.code ?? '')" :date="String(row.signal_date ?? '')" stop />
      </template>
      <template #exit_reason="{ row }">
        {{ exitReasonLabel(String(row.exit_reason ?? '')) }}
      </template>
      <template #net_return_pct="{ row }">
        <span :class="pnlTone(Number(row.net_return_pct))">{{ signed(Number(row.net_return_pct)) }}</span>
      </template>
      <template #mfe_pct="{ row }">
        <span :class="pnlTone(Number(row.mfe_pct))">{{ signed(Number(row.mfe_pct)) }}</span>
      </template>
      <template #mae_pct="{ row }">
        <span :class="pnlTone(Number(row.mae_pct))">{{ signed(Number(row.mae_pct)) }}</span>
      </template>
    </BasicTable>
  </div>
</template>

<style scoped>
.tr {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.tr-toolbar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.tr-alert {
  margin: 0;
}
.tr-hero,
.tr-perf {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.45rem;
}
.tr-charts {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 0.75rem;
}
.tr-chart,
.tr-dist,
.tr-month {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 0.55rem 0.7rem 0.35rem;
  background: var(--paper);
  min-width: 0;
}
.tr-chart header,
.tr-dist header,
.tr-month header {
  margin: 0 0 0.35rem;
  font-size: var(--fs-aux);
  color: var(--mist);
}
.tr-month__bars {
  display: flex;
  align-items: flex-end;
  gap: 0.35rem;
  min-height: 4.5rem;
  overflow-x: auto;
  padding-bottom: 0.15rem;
}
.tr-month__col {
  flex: 0 0 auto;
  width: 2.6rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
}
.tr-month__val {
  font: 0.62rem/1 var(--mono);
}
.tr-month__val.up,
.tr-table :deep(.up) {
  color: var(--up);
}
.tr-month__val.down,
.tr-table :deep(.down) {
  color: var(--down);
}
.tr-month__bar {
  width: 1rem;
  border-radius: 2px 2px 0 0;
}
.tr-month__bar.is-up {
  background: color-mix(in oklab, var(--up) 70%, transparent);
}
.tr-month__bar.is-down {
  background: color-mix(in oklab, var(--down) 70%, transparent);
}
.tr-month__lab {
  font: 0.65rem/1 var(--mono);
  color: var(--mist);
}
.tr-cost,
.tr-note {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  line-height: 1.4;
}
.tr-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem 0.75rem;
}
.tr-filters__reason {
  width: 10rem;
}
.tr-filters__n {
  font-size: 0.75rem;
  color: var(--mist);
}
.tr-table {
  width: 100%;
}
@media (max-width: 960px) {
  .tr-hero,
  .tr-perf,
  .tr-charts {
    grid-template-columns: 1fr;
  }
}
</style>
