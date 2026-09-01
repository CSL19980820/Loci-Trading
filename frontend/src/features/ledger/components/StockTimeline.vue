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
/* D3：行高钉 --row-h，1px hairline 分隔 */
.sw-tl__item {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-height: var(--row-h);
  padding: 0 var(--gap-2);
  border-bottom: 1px solid var(--rule);
}
.sw-tl__item:last-child {
  border-bottom: 0;
}
/* 候选轨命中态：整行底色 + 印章字色（对齐 style.content.css 的 .day-item.active），不再画左侧色条 */
.sw-tl__item.is-cand {
  background: var(--seal-soft);
  color: var(--seal-ink);
}
.sw-tl__date {
  flex: 0 0 6.2rem;
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
  white-space: nowrap;
}
/* 描边徽章：不再用实心色块 + 白字，深色档下也不会糊成白块 */
.sw-tl__tag {
  flex: 0 0 auto;
  font-size: var(--fs-kicker);
  line-height: 1.4;
  padding: 0 var(--gap-1);
  border: 1px solid color-mix(in srgb, var(--seal) 42%, var(--rule));
  border-radius: var(--radius);
  background: var(--seal-soft);
  color: var(--seal-ink);
  white-space: nowrap;
}
.sw-tl__title {
  flex: 0 0 auto;
  max-width: 8rem;
  font-size: var(--fs-body);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sw-tl__body {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.35;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sw-tl__foot {
  flex: 0 0 auto;
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
@media (max-width: 720px) {
  .sw-tl__item {
    flex-wrap: wrap;
    gap: var(--gap-1) var(--gap-2);
    padding: var(--gap-1) var(--gap-2);
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
