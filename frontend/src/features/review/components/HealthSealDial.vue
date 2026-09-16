<script setup lang="ts">
import { computed } from 'vue'

import type { HealthPhase } from '@/features/review/composables/useHealthCheckup'

const props = withDefaults(
  defineProps<{
    score: number | null
    grade: string
    phase: HealthPhase
    /** 0–100：idle 虚线待检环 / 扫描进度 / 结果分数 */
    progress?: number
  }>(),
  { progress: 0 },
)

const R = 54
const CX = 64
const CY = 64
const CIRC = 2 * Math.PI * R

const display = computed(() => {
  if (props.phase === 'idle') return '待检'
  if (props.phase === 'scanning') return '···'
  if (props.score == null) return '—'
  return String(props.score)
})

const tone = computed<'idle' | 'busy' | 'ok' | 'bad'>(() => {
  if (props.phase === 'scanning' || props.phase === 'repairing') return 'busy'
  if (props.score != null && props.score >= 90) return 'ok'
  if (props.phase === 'healthy') return 'ok'
  if (props.score != null && props.score < 70) return 'bad'
  if (props.phase === 'result') return 'bad'
  return 'idle'
})

/** idle 时整环虚线（还没盖的印）；其余态用 dashoffset 表达进度 */
const arcDasharray = computed(() => (props.phase === 'idle' ? '2.5 5.5' : CIRC))

const dashOffset = computed(() => {
  if (props.phase === 'idle') return 0
  const pct = Math.min(100, Math.max(0, props.progress)) / 100
  return CIRC * (1 - pct)
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
  <div class="seal-dial" :class="`seal-dial--${tone}`" aria-live="polite">
    <svg class="seal-dial__svg" viewBox="0 0 128 128" aria-hidden="true">
      <circle class="seal-dial__track" :cx="CX" :cy="CY" :r="R" fill="none" />
      <circle
        class="seal-dial__arc"
        :cx="CX"
        :cy="CY"
        :r="R"
        fill="none"
        :stroke-dasharray="arcDasharray"
        :stroke-dashoffset="dashOffset"
        transform="rotate(-90 64 64)"
      />
    </svg>
    <div class="seal-dial__core">
      <span class="seal-dial__kicker">体检分</span>
      <strong class="seal-dial__score mono" :class="{ 'seal-dial__score--word': phase === 'idle' }">
        {{ display }}
      </strong>
      <span v-if="showGrade" class="seal-dial__grade">{{ grade }}</span>
    </div>
  </div>
</template>

<style scoped>
.seal-dial {
  position: relative;
  width: calc(var(--gap-4) * 8);
  height: calc(var(--gap-4) * 8);
  flex-shrink: 0;
}

.seal-dial__svg {
  display: block;
  width: 100%;
  height: 100%;
}

.seal-dial__track {
  stroke: color-mix(in oklab, var(--rule) 85%, var(--sheet));
  stroke-width: 6;
}

.seal-dial__arc {
  stroke: var(--seal);
  stroke-width: 6;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.35s ease-out, stroke 0.2s ease;
}

/*
 * 三态一律用语义色，不用品牌色：--success 是静态绿，而 --seal 在「湖绿」主色下也是同一个绿，
 * 曾导致「体检通过」和「体检失败」渲染成完全相同的颜色，只剩中心文字能区分。
 */
.seal-dial--ok .seal-dial__arc {
  stroke: var(--ok);
}

.seal-dial--bad .seal-dial__arc {
  stroke: var(--warn);
}

.seal-dial--busy .seal-dial__arc {
  stroke: var(--seal);
}

.seal-dial--idle .seal-dial__arc {
  stroke: color-mix(in oklab, var(--mist) 62%, var(--rule));
}

.seal-dial__core {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-1);
  pointer-events: none;
}

.seal-dial__kicker {
  font-size: var(--fs-kicker);
  letter-spacing: 0.12em;
  color: var(--mist);
  font-weight: 500;
}

.seal-dial__score {
  font-family: var(--mono);
  font-size: var(--fs-tape);
  font-weight: 700;
  line-height: 1.05;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.seal-dial__score--word {
  font-family: var(--font);
  font-size: var(--fs-hero);
  letter-spacing: 0.08em;
  color: var(--mist);
}

.seal-dial__grade {
  font-size: var(--fs-kicker);
  font-weight: 700;
  padding: 0 var(--gap-1);
  border-radius: var(--radius);
  background: color-mix(in oklab, var(--seal-soft) 70%, var(--sheet));
  color: var(--seal-ink);
}

.seal-dial--ok .seal-dial__grade {
  background: var(--ok-soft);
  color: var(--info-ink);
}

@media (prefers-reduced-motion: reduce) {
  .seal-dial__arc {
    transition: none;
    animation: none !important;
  }
}

</style>
