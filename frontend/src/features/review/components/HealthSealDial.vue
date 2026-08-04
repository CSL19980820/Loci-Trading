<script setup lang="ts">
import { computed } from 'vue'

import type { HealthPhase } from '@/features/review/composables/useHealthCheckup'

const props = defineProps<{
  score: number | null
  grade: string
  phase: HealthPhase
  subtitle: string
}>()

const display = computed(() => {
  if (props.phase === 'idle') return '—'
  if (props.phase === 'scanning') return '···'
  if (props.score == null) return '—'
  return String(props.score)
})

const dialClass = computed(() => {
  if (props.phase === 'scanning' || props.phase === 'repairing') return 'seal-dial--busy'
  if (props.score != null && props.score >= 90) return 'seal-dial--ok'
  if (props.phase === 'healthy') return 'seal-dial--ok'
  if (props.score != null && props.score < 70) return 'seal-dial--bad'
  return ''
})

const showGrade = computed(
  () =>
    props.score != null &&
    props.phase !== 'scanning' &&
    props.phase !== 'idle' &&
    Boolean(props.grade),
)
</script>

<template>
  <div class="seal-dial-wrap">
    <div class="seal-dial" :class="dialClass" aria-live="polite">
      <div class="seal-dial__inner" />
      <span class="seal-dial__kicker">印鉴分</span>
      <strong class="seal-dial__score mono">{{ display }}</strong>
      <span v-if="showGrade" class="seal-dial__grade">{{ grade }}</span>
    </div>
    <p class="seal-dial__sub">{{ subtitle }}</p>
  </div>
</template>

<style scoped>
.seal-dial-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.65rem;
  padding: 0.35rem 0 0.15rem;
}

.seal-dial {
  position: relative;
  width: 9.25rem;
  height: 9.25rem;
  border-radius: 50%;
  border: 3px solid var(--seal);
  background: var(--sheet);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.15rem;
}

.seal-dial--ok {
  border-color: var(--lake);
}

.seal-dial--bad {
  border-color: var(--seal);
}

.seal-dial--busy .seal-dial__inner {
  animation: seal-spin 4s linear infinite;
}

.seal-dial__inner {
  position: absolute;
  inset: 0.45rem;
  border-radius: 50%;
  border: 1px solid var(--rule);
  pointer-events: none;
}

.seal-dial__kicker {
  position: relative;
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--mist);
  font-weight: 500;
}

.seal-dial__score {
  position: relative;
  font-size: 2.55rem;
  font-weight: 700;
  line-height: 1.05;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.seal-dial__grade {
  position: relative;
  font-size: 0.78rem;
  font-weight: 650;
  padding: 0.08rem 0.45rem;
  border-radius: 3px;
  background: color-mix(in srgb, var(--seal-soft) 70%, var(--sheet));
  color: var(--seal-ink);
}

.seal-dial--ok .seal-dial__grade {
  background: var(--lake-soft);
  color: var(--lake);
}

.seal-dial__sub {
  margin: 0;
  text-align: center;
  font-size: 0.88rem;
  font-weight: 600;
  line-height: 1.4;
  color: var(--ink);
  max-width: 26rem;
}

@media (prefers-reduced-motion: reduce) {
  .seal-dial--busy .seal-dial__inner {
    animation: none;
  }
}

@keyframes seal-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
