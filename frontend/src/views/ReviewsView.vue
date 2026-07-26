<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>复盘</h1>
      <span class="chip">{{ store.reviews.length }}</span>
      <span class="muted mono">
        样本 {{ withReturn }} · 均 {{ avgReturn === null ? '—' : `${avgReturn > 0 ? '+' : ''}${avgReturn.toFixed(1)}%` }}
        · {{ store.dashboard?.evolution.review_count ?? store.reviews.length }}/{{ store.dashboard?.evolution.gate ?? 5 }}
      </span>
    </div>
  </header>

  <div v-if="returnSeries.length" class="panel chart-box mb">
    <Sparkline
      :values="returnSeries"
      :height="56"
      :color="(returnSeries[returnSeries.length - 1] ?? 0) >= 0 ? 'var(--up)' : 'var(--down)'"
      label="收益"
    />
  </div>

  <ul class="memory-list">
    <li v-for="item in store.reviews" :key="item.id" class="panel memory-card">
      <div class="memory-head">
        <div class="row-main">
          <span class="mono dim">{{ item.date }}</span>
          <span class="tag">{{ entityLabel(item.entity_type) }}</span>
          <strong>{{ item.outcome }}</strong>
        </div>
        <div class="memory-metrics mono">
          <span :class="toneClass(item.return_pct)">{{ pct(item.return_pct) }}</span>
          <span class="dim">M{{ pct(item.max_favorable_pct) }}</span>
          <span class="dim">A{{ pct(item.max_adverse_pct) }}</span>
        </div>
      </div>
      <p v-if="item.lesson" class="reason"><b>训</b> {{ item.lesson }}</p>
      <p v-if="item.next_rule" class="reason"><b>规</b> {{ item.next_rule }}</p>
      <div class="memory-foot mono dim">{{ item.id }} · {{ item.entity_id }}</div>
    </li>
  </ul>
  <p v-if="!store.reviews.length" class="empty pad">无复盘</p>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import Sparkline from '@/components/Sparkline.vue'
import { entityLabel, pct, toneClass } from '@/lib/format'
import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()

const withReturn = computed(() => store.reviews.filter((item) => item.return_pct !== null).length)
const avgReturn = computed(() => {
  const values = store.reviews.map((item) => item.return_pct).filter((value): value is number => value !== null)
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
})
const returnSeries = computed(
  () => store.reviews.map((item) => item.return_pct).filter((value): value is number => value !== null).reverse(),
)
</script>