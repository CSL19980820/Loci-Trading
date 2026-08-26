<script setup lang="ts">
import { shortTime } from '@/shared/lib/format'
import type { TimelineEvent } from '@/shared/types/palace'

defineProps<{
  events: TimelineEvent[]
}>()

function typeLabel(type: TimelineEvent['type']): string {
  return { candidate: '候选', plan: '预案', review: '复盘' }[type] ?? type
}

function candidateSummary(event: TimelineEvent): string {
  const d = event.detail
  return `${d.score ?? '—'} ${d.timing ?? ''} ${d.reason ?? ''}`.trim()
}
</script>

<template>
  <ol class="sw-tl">
    <li v-for="event in events" :key="event.id" class="sw-tl__item is-cand">
      <span class="sw-tl__date mono">{{ event.date }}</span>
      <span class="sw-tl__tag">{{ typeLabel(event.type) }}</span>
      <strong class="sw-tl__title">{{ event.label }}</strong>
      <span class="sw-tl__body">{{ candidateSummary(event) }}</span>
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
  background: #2563eb;
  color: #fff;
  white-space: nowrap;
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
