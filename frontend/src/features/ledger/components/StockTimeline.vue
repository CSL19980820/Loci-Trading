<script setup lang="ts">
import { actionLabel, shortTime } from '@/shared/lib/format'
import type { TimelineEvent } from '@/shared/types/palace'

const props = defineProps<{
  events: TimelineEvent[]
  mode: 'trade' | 'candidate'
}>()

function typeLabel(type: TimelineEvent['type']): string {
  return { trade: '成交', candidate: '候选', plan: '预案', review: '复盘' }[type] ?? type
}

function eventLabel(event: TimelineEvent): string {
  if (event.type === 'trade') return actionLabel(String(event.label))
  return event.label
}

function candidateSummary(event: TimelineEvent): string {
  const d = event.detail
  return `${d.score ?? '—'} ${d.timing ?? ''} ${d.reason ?? ''}`.trim()
}

function tradeSummary(event: TimelineEvent): string {
  const d = event.detail
  const pnl = d.realized_pnl
  const pnlText = typeof pnl === 'number' && pnl !== 0 ? ` 盈亏${pnl > 0 ? '+' : ''}${pnl}` : ''
  const action = String(event.label).toUpperCase()
  const cost =
    action === 'SELL'
      ? (d.cost_before ?? d.cost_after)
      : (d.cost_after ?? d.cost_before)
  return `${d.shares ?? '-'}@${d.price ?? '-'} 余${d.shares_after ?? '-'} 成本${cost ?? '-'}${pnlText}${d.reason ? ` · ${String(d.reason)}` : ''}`
}

function tradeToneClass(event: TimelineEvent): string {
  const label = String(event.label).toUpperCase()
  if (label === 'BUY') return 'is-buy'
  if (label === 'SELL') return 'is-sell'
  return ''
}

function rowClass(event: TimelineEvent): string {
  if (props.mode === 'candidate') return 'is-cand'
  return tradeToneClass(event)
}

function bodyText(event: TimelineEvent): string {
  return props.mode === 'candidate' ? candidateSummary(event) : tradeSummary(event)
}
</script>

<template>
  <ol class="sw-tl">
    <li
      v-for="event in events"
      :key="event.id"
      class="sw-tl__item"
      :class="rowClass(event)"
    >
      <span class="sw-tl__date mono">{{ event.date }}</span>
      <span class="sw-tl__tag">
        {{ mode === 'candidate' ? typeLabel(event.type) : eventLabel(event) }}
      </span>
      <strong v-if="mode === 'candidate'" class="sw-tl__title">{{ eventLabel(event) }}</strong>
      <span class="sw-tl__body">{{ bodyText(event) }}</span>
      <span class="sw-tl__foot mono dim">{{ shortTime(event.created_at) }}</span>
    </li>
  </ol>
</template>

<style scoped>
.sw-tl {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.sw-tl__item {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-height: 2rem;
  padding: 0.35rem 0.55rem;
  border-bottom: 1px solid var(--rule);
  border-left: 2px solid transparent;
}

.sw-tl__item:last-child {
  border-bottom: 0;
}

.sw-tl__item.is-buy {
  border-left-color: var(--up);
}

.sw-tl__item.is-sell {
  border-left-color: var(--down);
}

.sw-tl__item.is-cand {
  border-left-color: #2563eb;
}

.sw-tl__date {
  flex: 0 0 6.2rem;
  font-size: 0.78rem;
  color: var(--mist);
  white-space: nowrap;
}

.sw-tl__tag {
  flex: 0 0 auto;
  font-size: 0.7rem;
  line-height: 1.2;
  padding: 0.08rem 0.35rem;
  border-radius: 3px;
  background: var(--mist);
  color: #fff;
  white-space: nowrap;
}

.sw-tl__item.is-buy .sw-tl__tag {
  background: var(--up);
}

.sw-tl__item.is-sell .sw-tl__tag {
  background: var(--down);
}

.sw-tl__item.is-cand .sw-tl__tag {
  background: #2563eb;
}

.sw-tl__title {
  flex: 0 0 auto;
  max-width: 8rem;
  font-size: 0.84rem;
  font-weight: 650;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sw-tl__body {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.35;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sw-tl__foot {
  flex: 0 0 auto;
  font-size: 0.7rem;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .sw-tl__item {
    flex-wrap: wrap;
    gap: 0.2rem 0.45rem;
    padding: 0.45rem 0.5rem;
  }

  .sw-tl__date {
    flex-basis: auto;
  }

  .sw-tl__body {
    flex: 1 1 100%;
    order: 4;
    white-space: normal;
  }

  .sw-tl__foot {
    margin-left: auto;
  }
}
</style>
