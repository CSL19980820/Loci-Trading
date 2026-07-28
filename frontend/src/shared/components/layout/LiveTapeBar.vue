<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { getLiveTape, type LiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import { brandTitle } from '@/shared/lib/brand'

const indices = ref<LiveTapeItem[]>([])
const positions = ref<LiveTapeItem[]>([])
const asOf = ref('')
const error = ref('')
const titleLine = ref('')

const clock = computed(() => {
  const raw = asOf.value
  if (!raw) return '--:--'
  const part = raw.split(' ')[1]
  return part ? part.slice(0, 5) : raw
})

function tone(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return ''
  if (pct > 0) return 'is-up'
  if (pct < 0) return 'is-down'
  return 'is-flat'
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  return value >= 1000 ? value.toFixed(2) : value.toFixed(2)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function shortName(item: LiveTapeItem): string {
  const name = (item.name || item.label || item.code || '').trim()
  return name.length > 4 ? name.slice(0, 4) : name
}

function applyTitle(line: string): void {
  document.title = line ? brandTitle(line) : brandTitle()
}

async function tick(): Promise<void> {
  try {
    const tape: LiveTape = await getLiveTape()
    indices.value = tape.indices || []
    positions.value = tape.positions || []
    asOf.value = tape.as_of || ''
    error.value = tape.error || ''
    titleLine.value = tape.title || ''
    applyTitle(tape.title || '')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '行情拉取失败'
  }
}

useLivePolling({ intervalMs: 5000, tick })

onMounted(() => {
  void tick()
})

onUnmounted(() => {
  document.title = brandTitle()
})
</script>

<template>
  <div class="live-tape" :class="{ 'live-tape--error': !!error }" role="status" aria-live="polite">
    <div class="live-tape__track">
      <span class="live-tape__clock" :title="asOf">{{ clock }}</span>
      <template v-for="item in indices" :key="item.code">
        <span class="live-tape__item" :class="tone(item.pct)">
          <em>{{ item.label }}</em>
          <strong>{{ fmtPrice(item.price) }}</strong>
          <b>{{ fmtPct(item.pct) }}</b>
        </span>
      </template>
      <span v-if="positions.length" class="live-tape__sep" aria-hidden="true" />
      <template v-for="item in positions" :key="'p-' + item.code">
        <span class="live-tape__item live-tape__item--pos" :class="tone(item.pnl_pct ?? item.pct)">
          <em>{{ shortName(item) }}</em>
          <strong>{{ fmtPrice(item.price) }}</strong>
          <b>{{ fmtPct(item.pnl_pct ?? item.pct) }}</b>
        </span>
      </template>
      <span v-if="error" class="live-tape__err">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.live-tape {
  flex: 0 0 auto;
  border-bottom: 1px solid var(--rule);
  background:
    linear-gradient(180deg, #f4f7fb 0%, #eef2f6 100%);
  overflow: hidden;
}
.live-tape__track {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.45rem 0.9rem;
  overflow-x: auto;
  scrollbar-width: none;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.live-tape__track::-webkit-scrollbar {
  display: none;
}
.live-tape__clock {
  color: var(--mist);
  font: 500 0.75rem/1 var(--mono);
  min-width: 2.6rem;
}
.live-tape__item {
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
  font-size: 0.82rem;
}
.live-tape__item em {
  font-style: normal;
  color: var(--mist);
  font-weight: 500;
}
.live-tape__item strong {
  font-weight: 650;
  color: var(--ink);
  font-family: var(--mono);
  font-size: 0.92rem;
}
.live-tape__item b {
  font-weight: 650;
  font-family: var(--mono);
  font-size: 0.82rem;
}
.live-tape__item--pos em {
  max-width: 4.5em;
  overflow: hidden;
  text-overflow: ellipsis;
}
.is-up b,
.is-up strong {
  color: var(--up);
}
.is-down b,
.is-down strong {
  color: var(--down);
}
.is-flat b {
  color: var(--mist);
}
.live-tape__sep {
  width: 1px;
  align-self: stretch;
  background: var(--rule);
  margin: 0.1rem 0.15rem;
}
.live-tape__err {
  color: var(--seal-ink);
  font-size: 0.75rem;
}
.live-tape--error {
  background: #fff7f7;
}
</style>
