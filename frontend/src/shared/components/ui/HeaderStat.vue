<script setup lang="ts">
import { computed } from 'vue'

/**
 * 页头行内读数：「小标签 + 等宽数字」一行排开，专供 PageHeader 的 stats 槽。
 * 页头是单行的，所以标签与数值同行（旧版上下两行会把页头顶成两层）。
 * 数值一律等宽 + tabular-nums：同一列的读数换值时不会左右横跳（D2）。
 */
const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    tone?: 'up' | 'down' | 'neutral' | ''
    /** 主读数：字号抬到页标题档，一个页头至多用一次 */
    lead?: boolean
  }>(),
  { lead: false },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'tone-up'
  if (props.tone === 'down') return 'tone-down'
  if (props.tone === 'neutral') return 'tone-neutral'
  return ''
})
</script>

<template>
  <div class="hstat" :class="[toneClass, { 'hstat--lead': lead }]">
    <span class="hstat__k">{{ label }}</span>
    <span class="hstat__v"><slot>{{ value }}</slot></span>
  </div>
</template>

<style scoped>
.hstat {
  display: inline-flex;
  align-items: baseline;
  gap: var(--gap-1);
  min-width: 0;
}

.hstat__k {
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.06em;
  color: var(--mist);
  white-space: nowrap;
}

.hstat__v {
  font: 700 var(--fs-body) / 1.2 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  white-space: nowrap;
}

.hstat--lead .hstat__v {
  font-size: var(--fs-hero);
}

/* D1：只有涨跌语义才允许上红绿 */
.tone-up .hstat__v {
  color: var(--up);
}

.tone-down .hstat__v {
  color: var(--down);
}

.tone-neutral .hstat__v {
  color: var(--muted);
}
</style>
