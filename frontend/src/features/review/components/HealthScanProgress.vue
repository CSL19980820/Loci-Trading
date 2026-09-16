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
    <div class="scan-progress__head">
      <strong>{{ head }}</strong>
      <span class="mono scan-progress__pct">{{ pct }}%</span>
    </div>
    <div class="seal-meter" :class="meterClass" role="progressbar" :aria-valuenow="pct" :aria-valuemin="0" :aria-valuemax="100" :aria-label="head">
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
  margin: 0 0 var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}
.scan-progress__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin-bottom: var(--gap-1);
}

.scan-progress__pct {
  font-family: var(--mono);
  font-size: var(--fs-body);
  font-weight: 700;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.scan-progress__msg {
  margin: var(--gap-1) 0 0;
  font-size: var(--fs-body);
  line-height: 1.4;
}

.scan-progress__detail {
  margin: var(--gap-1) 0 0;
  overflow-wrap: anywhere;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.seal-meter__track {
  height: var(--gap-1);
  border-radius: 999px;
  background: color-mix(in oklab, var(--rule) 70%, var(--sheet));
  overflow: hidden;
}

.seal-meter__fill {
  height: 100%;
  border-radius: inherit;
  background: var(--seal);
  transition: width 0.28s ease-out;
}

.seal-meter--done .seal-meter__fill {
  background: var(--ok);
}

.seal-meter--err .seal-meter__fill {
  background: var(--warn);
}

@media (prefers-reduced-motion: reduce) {
  .seal-meter__fill {
    transition: none;
  }
}
</style>
