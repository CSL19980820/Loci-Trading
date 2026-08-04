<script setup lang="ts">
import { computed } from 'vue'

/**
 * 耗时读数：一根量程 0~scale 的细条 + 等宽毫秒数。
 * 刻意不用涨跌红绿——那两个色在本仓表示行情方向，用在延迟上会读成「红=快」。
 */
const props = withDefaults(
  defineProps<{
    ms: number | null
    ok?: boolean
    /** 满量程毫秒；超出按满格显示 */
    scale?: number
    /** 慢阈值：越过后条子转琥珀 */
    slow?: number
  }>(),
  { ok: true, scale: 1200, slow: 600 },
)

const width = computed(() => {
  if (props.ms == null) return '0%'
  const ratio = Math.min(1, Math.max(0.04, props.ms / props.scale))
  return `${(ratio * 100).toFixed(1)}%`
})

const tone = computed(() => {
  if (!props.ok) return 'bad'
  if (props.ms != null && props.ms >= props.slow) return 'slow'
  return 'fine'
})

/** 超出量程：条子已满格，改成斜纹提示「读数在刻度之外」 */
const overScale = computed(() => props.ms != null && props.ms > props.scale)

const text = computed(() => (props.ms == null ? '—' : `${Math.round(props.ms)} ms`))
</script>

<template>
  <span class="lat" :class="[`lat--${tone}`, { 'lat--over': overScale }]">
    <span class="lat__track"><span class="lat__fill" :style="{ width }" /></span>
    <b class="lat__ms">{{ text }}</b>
  </span>
</template>

<style scoped>
.lat {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}

.lat__track {
  position: relative;
  flex: 1 1 auto;
  min-width: 2.5rem;
  height: 3px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--rule) 70%, transparent);
  overflow: hidden;
}

.lat__fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 2px;
  background: var(--ink);
  transition: width 0.18s ease-out;
}

.lat__ms {
  flex-shrink: 0;
  font: 600 0.76rem var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--muted);
}

.lat--slow .lat__fill {
  background: var(--el-color-warning);
}

.lat--slow .lat__ms {
  color: var(--el-color-warning);
}

.lat--bad .lat__fill {
  background: var(--el-color-danger);
}

.lat--bad .lat__ms {
  color: var(--el-color-danger);
}

.lat--over .lat__fill {
  background-image: repeating-linear-gradient(
    115deg,
    transparent 0 3px,
    color-mix(in srgb, var(--paper) 65%, transparent) 3px 5px
  );
}
</style>
