<script setup lang="ts">
import { computed } from 'vue'

import type { ProgressSnap } from '@/features/review/composables/useHealthCheckup'

const props = defineProps<{
  progress: ProgressSnap
  title?: string
}>()

const pct = computed(() =>
  Math.min(100, Math.max(0, Math.round(props.progress.percent))),
)

const head = computed(() => {
  if (props.title) return props.title
  if (props.progress.status === 'done') return '完成'
  if (props.progress.status === 'error') return '失败'
  return '进行中'
})

const meterClass = computed(() => ({
  'seal-meter--done': props.progress.status === 'done',
  'seal-meter--err': props.progress.status === 'error',
}))
</script>

<template>
  <div class="scan-progress" aria-live="polite">
    <div class="scan-progress__kicker mono">体检进度</div>
    <div class="scan-progress__head">
      <strong>{{ head }}</strong>
      <span class="mono scan-progress__pct">{{ pct }}%</span>
    </div>
    <div class="seal-meter" :class="meterClass" :aria-label="`进度 ${pct}%`">
      <div class="seal-meter__track">
        <div class="seal-meter__fill" :style="{ width: `${pct}%` }" />
      </div>
    </div>
    <p class="scan-progress__msg">{{ progress.message }}</p>
    <p v-if="progress.detail" class="scan-progress__detail mono">{{ progress.detail }}</p>
  </div>
</template>

<style scoped>
.scan-progress {
  margin: 0 0 0.75rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid color-mix(in srgb, var(--seal) 28%, var(--rule));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--seal-soft) 35%, var(--sheet));
}

.scan-progress__kicker {
  margin: 0 0 0.35rem;
  color: var(--mist);
  font-size: 0.68rem;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.scan-progress__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  margin-bottom: 0.45rem;
}

.scan-progress__pct {
  font-size: 0.82rem;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.scan-progress__msg {
  margin: 0.45rem 0 0;
  font-size: 0.86rem;
  line-height: 1.4;
}

.scan-progress__detail {
  margin: 0.25rem 0 0;
  font-size: 0.78rem;
  color: var(--mist);
}

.seal-meter__track {
  height: 0.42rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--rule) 70%, var(--sheet));
  overflow: hidden;
}

.seal-meter__fill {
  height: 100%;
  border-radius: inherit;
  background: var(--seal);
  transition: width 0.28s ease-out;
}

.seal-meter--done .seal-meter__fill {
  background: var(--lake);
}

.seal-meter--err .seal-meter__fill {
  background: #c8a400;
}

@media (prefers-reduced-motion: reduce) {
  .seal-meter__fill {
    transition: none;
  }
}
</style>
