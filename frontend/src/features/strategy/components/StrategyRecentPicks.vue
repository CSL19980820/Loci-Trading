<script setup lang="ts">
/**
 * 战法近期选出：按选出日分组，每天一行股票药片（色点 = 裁决）。
 * 只读账本候选，不含回填；点股票进档案。
 */
import { computed, ref, watch } from 'vue'

import { listCandidates } from '@/shared/api/palace'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { decisionLabel } from '@/shared/lib/format'
import type { Candidate } from '@/shared/types/palace'

const props = defineProps<{ slug: string }>()

const emit = defineEmits<{ count: [value: number] }>()

const rows = ref<Candidate[]>([])
const loading = ref(false)
const failed = ref(false)
let seq = 0

async function load(slug: string): Promise<void> {
  const request = ++seq
  if (!slug) {
    rows.value = []
    return
  }
  loading.value = true
  failed.value = false
  try {
    const list = await listCandidates({ strategy: slug, limit: 120 })
    if (request !== seq) return
    rows.value = list
  } catch {
    if (request !== seq) return
    rows.value = []
    failed.value = true
  } finally {
    if (request === seq) loading.value = false
  }
}

watch(() => props.slug, (slug) => void load(slug), { immediate: true })

function toneOf(decision: string): 'pick' | 'watch' | 'drop' {
  const label = decisionLabel(decision)
  if (label === '精选') return 'pick'
  if (label === '观察') return 'watch'
  return 'drop'
}

const days = computed(() => {
  const map = new Map<string, Candidate[]>()
  for (const row of rows.value) {
    const list = map.get(row.date) ?? []
    list.push(row)
    map.set(row.date, list)
  }
  const order = { pick: 0, watch: 1, drop: 2 }
  return [...map.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([date, list]) => ({
      date,
      picks: list.filter((row) => toneOf(row.decision) === 'pick').length,
      items: [...list].sort(
        (a, b) =>
          order[toneOf(a.decision)] - order[toneOf(b.decision)]
          || Number(b.score ?? 0) - Number(a.score ?? 0),
      ),
    }))
})

watch(() => rows.value.length, (value) => emit('count', value), { immediate: true })

function weekday(date: string): string {
  const time = Date.parse(`${date}T00:00:00`)
  if (!Number.isFinite(time)) return ''
  return `周${'日一二三四五六'[new Date(time).getDay()]}`
}
</script>

<template>
  <div class="picks">
    <div v-if="loading && !rows.length" class="picks__skeleton" aria-hidden="true">
      <Skeleton v-for="n in 4" :key="n" class="h-9 w-full" />
    </div>
    <EmptyState v-else-if="!days.length" compact :description="failed ? '读取失败' : '暂无选出记录'" />
    <ol v-else class="picks__days">
      <li v-for="day in days" :key="day.date" class="picks__day">
        <div class="picks__date">
          <b>{{ day.date.slice(5) }}</b>
          <span>{{ weekday(day.date) }}</span>
        </div>
        <ul class="picks__items">
          <li v-for="item in day.items" :key="item.id" class="picks__item" :class="`is-${toneOf(item.decision)}`">
            <i aria-hidden="true" />
            <StockLink :code="item.code" :name="item.name" :date="item.date" :show-code="false" class="picks__name" />
            <span class="picks__code">{{ item.code }}</span>
          </li>
        </ul>
        <span class="picks__count">{{ day.picks }}/{{ day.items.length }}</span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.picks {
  min-width: 0;
}

.picks__skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.picks__days {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.picks__day {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto;
  align-items: start;
  gap: 14px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.picks__day:last-child {
  border-bottom: 0;
}

.picks__date {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 3px;
}

.picks__date b {
  color: var(--text-primary);
  font: 600 var(--fs-ui) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
}

.picks__date span {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.picks__items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.picks__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 9px 0 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  font-size: var(--fs-aux);
}

.picks__item i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.picks__item.is-pick {
  border-color: var(--seal-border);
  background: color-mix(in oklab, var(--seal) 6%, var(--surface));
}

.picks__item.is-pick i { background: var(--seal); }
.picks__item.is-watch i { background: var(--warn); }
.picks__item.is-drop { opacity: 0.7; }

.picks__name {
  color: var(--text-primary);
  font-weight: 550;
}

.picks__code {
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
}

.picks__count {
  padding-top: 5px;
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
}
</style>
