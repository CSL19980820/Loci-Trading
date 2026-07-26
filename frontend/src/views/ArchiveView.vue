<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <RouterLink to="/journal" class="text-link">← 交割</RouterLink>
      <h1>{{ stockName }}</h1>
      <span class="code">{{ code }}</span>
      <span class="chip">{{ trades.length }} 笔 · {{ timeline.length }} 事</span>
    </div>
  </header>

  <section v-if="position" class="stat-strip mini">
    <div class="stat">
      <span class="stat-k">当前仓</span>
      <span class="stat-v">{{ position.shares.toLocaleString('zh-CN') }}</span>
    </div>
    <div class="stat">
      <span class="stat-k">成本</span>
      <span class="stat-v">{{ position.cost.toFixed(3) }}</span>
    </div>
    <div class="stat">
      <span class="stat-k">成本金额</span>
      <span class="stat-v">{{ money(position.cost_value) }}</span>
    </div>
  </section>

  <article class="panel mb">
    <div class="panel-bar">
      <h2>历史交割</h2>
      <span class="chip">{{ trades.length }}</span>
    </div>
    <div class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>日期</th>
            <th>动作</th>
            <th class="r">数量</th>
            <th class="r">价</th>
            <th class="r">额</th>
            <th class="r">余仓</th>
            <th class="r">成本</th>
            <th class="r">已实现</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in trades" :key="t.id">
            <td class="mono">{{ t.date }}</td>
            <td>
              <span class="action-chip" :class="`action-${t.action.toLowerCase()}`">{{ actionLabel(t.action) }}</span>
            </td>
            <td class="r mono">{{ t.shares.toLocaleString('zh-CN') }}</td>
            <td class="r mono">{{ t.price.toFixed(3) }}</td>
            <td class="r mono">{{ money(t.amount) }}</td>
            <td class="r mono">{{ t.shares_after.toLocaleString('zh-CN') }}</td>
            <td class="r mono">{{ t.cost_after ? t.cost_after.toFixed(3) : '—' }}</td>
            <td class="r mono" :class="toneClass(t.realized_pnl)">{{ signedMoney(t.realized_pnl) }}</td>
            <td class="clip">{{ t.reason || '—' }}</td>
          </tr>
          <tr v-if="!trades.length">
            <td colspan="9" class="empty">无交割记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </article>

  <section class="panel">
    <div class="panel-bar">
      <h2>事件时间线</h2>
      <span class="chip">新→旧</span>
    </div>
    <ol class="timeline pad-list">
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
      <li v-if="!timeline.length" class="empty pad">无事件</li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { actionLabel, money, shortTime, signedMoney, toneClass } from '@/lib/format'
import { usePalaceStore } from '@/stores/palace'
import type { TimelineEvent } from '@/types'

const route = useRoute()
const store = usePalaceStore()
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