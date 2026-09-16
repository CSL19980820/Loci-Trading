<script setup lang="ts">
import { computed } from 'vue'

import {
  ASSISTANT_KLINE_MA,
  ASSISTANT_KLINE_MIN_VISIBLE,
  artifactShellTitle,
  parseKlineBars,
} from '../assistantArtifacts'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import KlineChart from '@/shared/components/charts/KlineChart.vue'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const bars = computed(() => parseKlineBars(props.artifact.data ?? {}))
const code = computed(() => {
  const data = props.artifact.data ?? {}
  return typeof data.code === 'string' ? data.code : typeof data.stock_code === 'string' ? data.stock_code : ''
})
const name = computed(() => {
  const data = props.artifact.data ?? {}
  return typeof data.name === 'string' ? data.name : typeof data.stock_name === 'string' ? data.stock_name : ''
})
const enough = computed(() => bars.value.length >= ASSISTANT_KLINE_MIN_VISIBLE)
const visibleBars = computed(() => Math.max(ASSISTANT_KLINE_MIN_VISIBLE, Math.min(60, bars.value.length)))
</script>

<template>
  <section class="assistant-kline-card assistant-card flex w-full min-w-0 flex-col" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-card__heading flex min-w-0 items-center justify-between gap-2">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
      <el-tag v-if="code" size="small" type="info">{{ name ? `${name} ${code}` : code }}</el-tag>
    </div>
    <el-alert
      v-if="bars.length > 0 && !enough"
      type="warning"
      :closable="false"
      show-icon
      :title="`数据不足 ${bars.length}/${ASSISTANT_KLINE_MIN_VISIBLE} 根`"
    />
    <div v-else-if="bars.length" class="assistant-kline-card__chart w-full">
      <KlineChart
        :bars="bars"
        :ma-periods="[...ASSISTANT_KLINE_MA]"
        :visible-bars="visibleBars"
        :stock-code="code"
        :stock-name="name"
        period="day"
        indicator="macd"
      />
    </div>
    <EmptyState v-else description="工具未返回 K 线" reason="换个标的或重问一次" />
  </section>
</template>

<style scoped>
/*
 * 单一高度来源：此前 height:16rem + min-height:14rem 写了三遍互相打架（体检 §4.2/§4.4）。
 * K 线改用宽高比定高，窄屏自动变矮，小卡片里不再留死白。
 */
.assistant-kline-card__chart {
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 16rem;
}
.assistant-kline-card__chart :deep(.kline-chart),
.assistant-kline-card__chart :deep(.kline-chart__canvas),
.assistant-kline-card__chart :deep([class*='chart']) {
  height: 100%;
}
</style>
