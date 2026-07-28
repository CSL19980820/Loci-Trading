<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import TradesTable from '@/features/ledger/components/TradesTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import TradeDialog from '@/shared/components/dialogs/TradeDialog.vue'
import { actionLabel, money, shortTime } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import type { TimelineEvent } from '@/shared/types/palace'

const route = useRoute()
const store = usePalaceStore()
const tradeDialogOpen = ref(false)
const code = computed(() => String(route.params.code ?? ''))
const timeline = computed(() => (store.selectedCode === code.value ? store.selectedTimeline : []))
const trades = computed(() => store.trades.filter((item) => item.code === code.value))
const position = computed(() => store.dashboard?.positions.find((item) => item.code === code.value) ?? null)
const stockName = computed(
  () =>
    position.value?.name
    ?? trades.value[0]?.name
    ?? store.trades.find((trade) => trade.code === code.value)?.name
    ?? code.value,
)

function typeLabel(type: TimelineEvent['type']): string {
  return { trade: '成交', candidate: '候选', plan: '预案', review: '复盘' }[type] ?? type
}

function eventLabel(event: TimelineEvent): string {
  if (event.type === 'trade') return actionLabel(String(event.label))
  return event.label
}

function fmtDays(days: number | null | undefined): string {
  if (days == null) return '—'
  if (days <= 0) return '今'
  return String(days)
}

function positionAvailable(): number {
  const p = position.value
  if (!p) return 0
  const todayBuy = p.today_buy_shares ?? Math.max(0, p.shares - (p.available_shares ?? p.shares))
  return p.available_shares ?? Math.max(0, p.shares - todayBuy)
}

function summary(event: TimelineEvent): string {
  const detail = event.detail
  if (event.type === 'trade') {
    const pnl = detail.realized_pnl
    const pnlText = typeof pnl === 'number' && pnl !== 0 ? ` 盈亏${pnl > 0 ? '+' : ''}${pnl}` : ''
    return `${detail.shares ?? '-'}@${detail.price ?? '-'} 余${detail.shares_after ?? '-'} 成本${detail.cost_after ?? '-'}${pnlText}${detail.reason ? ` · ${String(detail.reason)}` : ''}`
  }
  if (event.type === 'candidate') {
    return `${detail.score ?? '—'} ${detail.timing ?? ''} ${detail.reason ?? ''}`.trim()
  }
  if (event.type === 'review') {
    const parts = [
      detail.return_pct != null ? `收益${detail.return_pct}%` : '',
      detail.lesson ? `训：${String(detail.lesson)}` : '',
      detail.next_rule ? `规：${String(detail.next_rule)}` : '',
    ].filter(Boolean)
    return parts.join(' · ') || String(event.label)
  }
  return `${detail.scenario ?? ''}${detail.invalidation ? ` · 失效 ${String(detail.invalidation)}` : ''}`
}
</script>

<template>
  <PageHeader :title="stockName" :subtitle="`${code} · ${trades.length} 笔 · ${timeline.length} 事`">
    <RouterLink to="/journal"><el-button>← 交割</el-button></RouterLink>
    <el-button @click="tradeDialogOpen = true">写入成交</el-button>
  </PageHeader>

  <section v-if="position" class="stat-strip mini">
    <StatCard label="当前仓" :value="position.shares.toLocaleString('zh-CN')" />
    <StatCard label="可卖" :value="positionAvailable().toLocaleString('zh-CN')" />
    <StatCard label="成本" :value="position.cost.toFixed(3)" />
    <StatCard label="成本金额" :value="money(position.cost_value)" />
    <StatCard label="天数" :value="fmtDays(position.holding_days)" />
  </section>

  <Sheet title="历史交割" :chip="trades.length" margin>
    <TradesTable v-if="trades.length" :trades="trades" />
    <EmptyState v-else description="无交割记录">
      <el-button type="primary" @click="tradeDialogOpen = true">写入成交</el-button>
    </EmptyState>
  </Sheet>

  <Sheet title="事件时间线" chip="新→旧">
    <ol v-if="timeline.length" class="timeline pad-list">
      <li v-for="event in timeline" :key="event.id" class="timeline-item" :class="`event-${event.type}`">
        <span class="timeline-dot" aria-hidden="true" />
        <article class="timeline-card">
          <div class="timeline-heading">
            <span class="mono">{{ event.date }}</span>
            <span class="tag">{{ typeLabel(event.type) }}</span>
            <strong>{{ eventLabel(event) }}</strong>
          </div>
          <p class="reason">{{ summary(event) }}</p>
          <div class="memory-foot mono dim">{{ event.id }} · {{ shortTime(event.created_at) }}</div>
        </article>
      </li>
    </ol>
    <EmptyState v-else description="无事件" :image-size="64" />
  </Sheet>

  <TradeDialog v-model="tradeDialogOpen" :preset-code="code" :preset-name="stockName" />
</template>
