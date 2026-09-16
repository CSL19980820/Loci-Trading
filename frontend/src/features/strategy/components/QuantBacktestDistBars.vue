<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  bins: Array<{ lo: number; hi: number; n: number }>
  /** 柱条最大高度 px */
  maxHeight?: number
}>()

const maxN = computed(() => Math.max(1, ...props.bins.map((b) => b.n)))

const bars = computed(() => {
  const h = props.maxHeight ?? 56
  return props.bins.map((bin) => ({
    ...bin,
    height: Math.max(2, Math.round((bin.n / maxN.value) * h)),
    mid: (bin.lo + bin.hi) / 2,
    label: `${bin.lo.toFixed(0)}~${bin.hi.toFixed(0)}`,
  }))
})
</script>

<template>
  <div v-if="bins.length" class="dist" role="img" aria-label="收益分布">
    <div class="dist__bars">
      <div
        v-for="(bar, i) in bars"
        :key="i"
        class="dist__col"
        :title="`${bar.label}% · ${bar.n} 笔`"
      >
        <span class="dist__n">{{ bar.n || '' }}</span>
        <div
          class="dist__bar"
          :class="{ 'is-up': bar.mid > 0, 'is-down': bar.mid < 0, 'is-zero': bar.mid === 0 }"
          :style="{ height: `${bar.height}px` }"
        />
      </div>
    </div>
    <div class="dist__axis">
      <span>{{ bins[0]?.lo.toFixed(0) }}%</span>
      <span>0</span>
      <span>{{ bins[bins.length - 1]?.hi.toFixed(0) }}%</span>
    </div>
  </div>
</template>

<style scoped>
.dist {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.dist__bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  min-height: 3.5rem;
  padding: 0 0.1rem;
}
.dist__col {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 0.1rem;
}
.dist__n {
  font: 0.62rem/1 var(--mono);
  color: var(--mist);
  min-height: 0.7rem;
}
.dist__bar {
  width: 100%;
  max-width: 14px;
  border-radius: 2px 2px 0 0;
  background: color-mix(in oklab, var(--mist) 45%, transparent);
}
.dist__bar.is-up {
  background: color-mix(in oklab, var(--up) 70%, transparent);
}
.dist__bar.is-down {
  background: color-mix(in oklab, var(--down) 70%, transparent);
}
.dist__bar.is-zero {
  background: color-mix(in oklab, var(--mist) 55%, transparent);
}
.dist__axis {
  display: flex;
  justify-content: space-between;
  font: 0.68rem/1.2 var(--mono);
  color: var(--mist);
}
</style>
