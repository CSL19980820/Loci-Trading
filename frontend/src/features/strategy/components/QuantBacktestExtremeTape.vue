<script setup lang="ts">
import { computed } from 'vue'

import StockLink from '@/shared/components/ui/StockLink.vue'
import type { HorizonEventRef } from '@/shared/types/quant'

import { pnlTone, signed } from '../composables/quantFormat'

const props = defineProps<{
  kind: 'best' | 'worst'
  event: HorizonEventRef | null | undefined
}>()

const label = computed(() => (props.kind === 'best' ? '样本最佳' : '样本最差'))
const tone = computed(() => (props.event ? pnlTone(props.event.return_pct) : ''))

function archiveTo(date: string) {
  if (!props.event) return { path: '/' }
  return {
    path: `/archive/${props.event.code}`,
    query: { date },
  }
}
</script>

<template>
  <div
    class="extreme-tape"
    :class="kind === 'best' ? 'extreme-tape--best' : 'extreme-tape--worst'"
  >
    <div class="extreme-tape__tag">{{ label }}</div>
    <template v-if="event">
      <div
        class="extreme-tape__ret"
        :class="tone === 'up' ? 'tone-up' : tone === 'down' ? 'tone-down' : ''"
      >
        {{ signed(event.return_pct) }}
      </div>
      <div class="extreme-tape__who">
        <StockLink
          :code="event.code"
          :name="event.name || null"
          :date="event.signal_date"
          stop
        />
      </div>
      <div class="extreme-tape__dates">
        <RouterLink class="date-jump" :to="archiveTo(event.signal_date)">
          <em>选股</em> {{ event.signal_date }}
        </RouterLink>
        <span class="sep" aria-hidden="true">→</span>
        <RouterLink class="date-jump" :to="archiveTo(event.mark_date)">
          <em>标记</em> {{ event.mark_date }}
        </RouterLink>
      </div>
    </template>
    <p v-else class="extreme-tape__empty">无极端样本</p>
  </div>
</template>

<style scoped>
.extreme-tape {
  display: grid;
  grid-template-columns: auto minmax(5.5rem, auto) minmax(7rem, 1fr) minmax(11rem, 1.4fr);
  gap: 0.55rem 0.85rem;
  align-items: center;
  padding: 0.65rem 0.8rem;
  border-radius: var(--radius);
  border: 1px solid var(--rule);
  background: color-mix(in oklab, var(--sheet) 88%, var(--paper));
  min-width: 0;
}
.extreme-tape--best .extreme-tape__tag {
  color: var(--up);
}
.extreme-tape--worst .extreme-tape__tag {
  color: var(--down);
}
.extreme-tape__tag {
  font-size: var(--fs-kicker);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--mist);
  white-space: nowrap;
}
.extreme-tape__ret {
  font: 700 1.15rem/1 var(--mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.extreme-tape__ret.tone-up {
  color: var(--up);
}
.extreme-tape__ret.tone-down {
  color: var(--down);
}
.extreme-tape__who {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9rem;
}
.extreme-tape__dates {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.45rem;
  align-items: baseline;
  font: 0.78rem/1.35 var(--mono);
  color: var(--mist);
  justify-content: flex-end;
}
.extreme-tape__dates em {
  font-style: normal;
  opacity: 0.75;
  margin-right: 0.15rem;
}
.extreme-tape__dates .sep {
  opacity: 0.45;
}
.date-jump {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dashed color-mix(in oklab, var(--mist) 55%, transparent);
}
.date-jump:hover {
  color: var(--ink);
  border-bottom-color: var(--ink);
}
.extreme-tape__empty {
  grid-column: 2 / -1;
  margin: 0;
  color: var(--mist);
  font-size: var(--fs-body);
}
@container (max-width: 640px) {
  .extreme-tape {
    grid-template-columns: auto 1fr;
  }
  .extreme-tape__who,
  .extreme-tape__dates {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}
</style>
