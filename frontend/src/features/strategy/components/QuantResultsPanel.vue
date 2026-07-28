<script setup lang="ts">
import { computed } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { factorLabel } from '@/shared/lib/format'
import type { BacktestResult, ScreenResult } from '@/shared/types/quant'

import { exitReasonsText, formatFunnel, fmt, pnlTone, signed } from '../composables/quantFormat'

const props = defineProps<{
  screenResult: ScreenResult | null
  backtestResult: BacktestResult | null
}>()

const funnelText = computed(() => formatFunnel(props.screenResult?.universe_funnel))

const factorKeys = computed(() => {
  const keys = new Set<string>()
  for (const pick of props.screenResult?.picks ?? []) {
    for (const [key, value] of Object.entries(pick.factors)) {
      if (typeof value === 'number') keys.add(key)
    }
  }
  return [...keys]
})

const exitReasons = computed(() => exitReasonsText(props.backtestResult?.metrics.exit_reasons))

const profitGiveBack = computed(() => {
  const metrics = props.backtestResult?.metrics
  if (!metrics?.trades || metrics.avg_mfe === undefined || metrics.avg_net_return === undefined) return false
  return metrics.avg_mfe - metrics.avg_net_return > 2
})
</script>

<template>
  <Sheet v-if="screenResult" title="选股结果" :chip="screenResult.picks.length" margin>
    <template #actions>
      <span class="muted mono">
        {{ screenResult.trade_date }} · {{ screenResult.universe_size }} 只 ·
        {{ (screenResult.elapsed_seconds * 1000).toFixed(0) }} ms
      </span>
    </template>
    <p v-if="funnelText" class="form-hint mono">{{ funnelText }}</p>
    <el-table v-if="screenResult.picks.length" :data="screenResult.picks" size="small">
      <el-table-column label="代码" min-width="100">
        <template #default="{ row }">
          <StockLink :code="row.code" />
        </template>
      </el-table-column>
      <el-table-column label="名称" min-width="100" show-overflow-tooltip>
        <template #default="{ row }">{{ row.name || '—' }}</template>
      </el-table-column>
      <el-table-column label="板块" width="88">
        <template #default="{ row }">
          <span class="tag">{{ row.board_label || row.board_bucket || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="开" align="right" width="90">
        <template #default="{ row }">{{ fmt(row.open) }}</template>
      </el-table-column>
      <el-table-column label="收" align="right" width="90">
        <template #default="{ row }">{{ fmt(row.close) }}</template>
      </el-table-column>
      <el-table-column v-for="key in factorKeys" :key="key" :label="factorLabel(key)" align="right" min-width="90">
        <template #default="{ row }">{{ fmt(row.factors[key]) }}</template>
      </el-table-column>
    </el-table>
    <EmptyState
      v-else
      description="当日无标的满足条件"
      reason="公式在当前股票范围内没有信号"
      eta="可放宽板块或取消剔 ST 后再跑"
    />
  </Sheet>

  <Sheet v-if="backtestResult" title="回测" :chip="backtestResult.strategy" muted-chip>
    <EmptyState v-if="!backtestResult.metrics.trades" description="区间内没有可评估的交易" />
    <template v-else>
      <section class="stat-strip">
        <StatCard label="笔数" :value="backtestResult.metrics.trades" />
        <StatCard label="胜率" :value="`${backtestResult.metrics.win_rate?.toFixed(1)}%`" />
        <StatCard
          label="净收益均值"
          :value="signed(backtestResult.metrics.avg_net_return)"
          :tone="pnlTone(backtestResult.metrics.avg_net_return)"
        />
        <StatCard label="盈亏比" :value="backtestResult.metrics.profit_factor ?? '—'" />
      </section>
      <p v-if="profitGiveBack" class="form-hint">
        最大浮盈均值 {{ signed(backtestResult.metrics.avg_mfe) }}，净收益只有
        {{ signed(backtestResult.metrics.avg_net_return) }}——利润在回吐。
      </p>
      <p v-if="backtestResult.metrics.caution" class="form-error">{{ backtestResult.metrics.caution }}</p>
      <dl class="kv">
        <div><dt>退出原因</dt><dd>{{ exitReasons }}</dd></div>
        <div><dt>平均持有</dt><dd>{{ backtestResult.metrics.avg_hold_days }} 日</dd></div>
        <div v-if="backtestResult.metrics.avg_alpha !== undefined">
          <dt>相对基准超额</dt><dd>{{ signed(backtestResult.metrics.avg_alpha) }}</dd>
        </div>
      </dl>
    </template>
  </Sheet>

  <EmptyState v-if="!screenResult && !backtestResult" description="在「战法」里跑选股或回测后，结果会出现在这里" />
</template>
