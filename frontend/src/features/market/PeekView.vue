<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getLiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'

const indices = ref<LiveTapeItem[]>([])
const positions = ref<LiveTapeItem[]>([])
const asOf = ref('')
const error = ref('')
function tone(pct: number | null | undefined): string {
  if (pct == null) return ''
  if (pct > 0) return 'is-up'
  if (pct < 0) return 'is-down'
  return ''
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toFixed(2)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

async function tick(): Promise<void> {
  try {
    const tape = await getLiveTape()
    indices.value = tape.indices || []
    positions.value = tape.positions || []
    asOf.value = tape.as_of || ''
    error.value = tape.error || ''
    if (tape.title) document.title = tape.title
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '行情失败'
  }
}

useLivePolling({ intervalMs: 4000, tick })

onMounted(() => {
  void tick()
})
</script>

<template>
  <main class="peek">
    <header class="peek-head">
      <strong>Loci</strong>
      <span>{{ asOf || '连接中…' }}</span>
    </header>
    <section class="peek-grid">
      <article
        v-for="item in indices"
        :key="item.code"
        class="peek-card"
        :class="tone(item.pct)"
      >
        <span class="label">{{ item.label }}</span>
        <strong>{{ fmtPrice(item.price) }}</strong>
        <b>{{ fmtPct(item.pct) }}</b>
      </article>
    </section>
    <section v-if="positions.length" class="peek-pos">
      <h2>持仓</h2>
      <div
        v-for="item in positions"
        :key="item.code"
        class="peek-row"
        :class="tone(item.pnl_pct ?? item.pct)"
      >
        <span>{{ item.name || item.label }}</span>
        <strong>{{ fmtPrice(item.price) }}</strong>
        <b>{{ fmtPct(item.pnl_pct ?? item.pct) }}</b>
      </div>
    </section>
    <p v-if="error" class="peek-err">{{ error }}</p>
  </main>
</template>

<style scoped>
.peek {
  min-height: 100%;
  padding: 1rem 1.1rem 1.4rem;
  background: linear-gradient(165deg, #e8eef4, #eef2f6 55%, #e4ebf2);
  color: var(--ink);
}
.peek-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.9rem;
}
.peek-head strong {
  font-family: var(--font-display);
  font-size: 1.35rem;
}
.peek-head span {
  color: var(--mist);
  font: 500 0.8rem/1 var(--mono);
}
.peek-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
}
.peek-card {
  padding: 0.75rem 0.8rem;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
  display: grid;
  gap: 0.2rem;
}
.peek-card .label {
  color: var(--mist);
  font-size: 0.78rem;
}
.peek-card strong {
  font: 650 1.35rem/1.1 var(--mono);
}
.peek-card b {
  font: 650 0.95rem/1 var(--mono);
}
.peek-pos {
  margin-top: 1rem;
}
.peek-pos h2 {
  margin: 0 0 0.45rem;
  font-size: 0.8rem;
  color: var(--mist);
  font-weight: 600;
}
.peek-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.6rem;
  align-items: baseline;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--rule);
  font-size: 0.9rem;
}
.peek-row strong,
.peek-row b {
  font-family: var(--mono);
  font-weight: 650;
}
.is-up strong,
.is-up b {
  color: var(--up);
}
.is-down strong,
.is-down b {
  color: var(--down);
}
.peek-err {
  margin-top: 0.8rem;
  color: var(--seal-ink);
  font-size: 0.85rem;
}
</style>
