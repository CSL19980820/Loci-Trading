<script setup lang="ts">
import { formatCount } from '../composables/dataQueryFormat'

defineProps<{
  dataDir: string
  codes: number | undefined
  rows: number | undefined
  dateSpan: string
  boardAsOf: string
}>()
</script>

<template>
  <section class="path-tape" aria-label="数据目录状态">
    <div class="path-tape__main">
      <span class="path-tape__eyebrow">本机库</span>
      <code class="path-tape__path" :title="dataDir">{{ dataDir || '…' }}</code>
    </div>
    <div class="path-tape__stats">
      <div class="stat">
        <span class="stat__label">证券</span>
        <strong class="stat__value mono">{{ codes ?? '—' }}</strong>
      </div>
      <div class="stat">
        <span class="stat__label">日 K</span>
        <strong class="stat__value mono">{{ formatCount(rows) }}</strong>
      </div>
      <div class="stat">
        <span class="stat__label">区间</span>
        <strong class="stat__value mono">{{ dateSpan }}</strong>
      </div>
      <div class="stat">
        <span class="stat__label">刷新</span>
        <strong class="stat__value mono">{{ boardAsOf || '—' }}</strong>
      </div>
    </div>
    <div class="path-tape__actions">
      <RouterLink class="text-link" to="/ops">改目录</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.path-tape {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1.25rem;
  padding: 0.65rem 0.9rem;
  background: var(--sheet);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}
.path-tape__eyebrow {
  display: block;
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  color: var(--mist);
  text-transform: uppercase;
}
.path-tape__path {
  font-family: var(--mono);
  font-size: 0.78rem;
  color: var(--muted);
  word-break: break-all;
}
.path-tape__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem 1.1rem;
  margin-left: auto;
}
.stat__label {
  display: block;
  font-size: 0.72rem;
  color: var(--mist);
}
.stat__value {
  font-size: 0.92rem;
}
.path-tape__actions {
  flex-shrink: 0;
}
.text-link {
  color: var(--seal-ink);
  text-decoration: none;
  font-size: 0.85rem;
}
.text-link:hover {
  text-decoration: none;
  opacity: 0.9;
}
.mono {
  font-family: var(--mono);
}
</style>
