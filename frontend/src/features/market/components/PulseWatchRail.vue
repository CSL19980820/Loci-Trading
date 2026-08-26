<script setup lang="ts">
/**
 * 盘面监控带：二波监测（当日现价）+ 短线情报。
 */
import { computed } from 'vue'

import type { IntelBrief } from '@/shared/api/quant_intel'
import type { SecondWaveLatest } from '@/shared/api/quant_ops'

import PulseIntelStrip from './PulseIntelStrip.vue'
import PulseSecondWaveStrip from './PulseSecondWaveStrip.vue'

const props = defineProps<{
  brief: IntelBrief | null
  briefLoading?: boolean
  briefError?: string
  wave: SecondWaveLatest | null
  waveLoading?: boolean
  waveError?: string
}>()

const intelVisible = computed(
  () =>
    Boolean(props.briefLoading) ||
    Boolean(props.briefError) ||
    Boolean(props.brief?.available),
)
</script>

<template>
  <section class="watch-rail" aria-label="盘面监控带">
    <PulseSecondWaveStrip
      class="watch-rail__wave"
      :snap="props.wave"
      :loading="props.waveLoading"
      :error="props.waveError"
    />
    <PulseIntelStrip
      v-if="intelVisible"
      class="watch-rail__intel"
      :brief="props.brief"
      :loading="props.briefLoading"
      :error="props.briefError"
      nested
    />
  </section>
</template>

<style scoped>
.watch-rail {
  flex-shrink: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.watch-rail__intel {
  border: none !important;
  border-radius: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  min-width: 0;
  min-height: 0;
  border-top: 1px solid var(--rule) !important;
}
</style>
