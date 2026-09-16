<script setup lang="ts">
import { computed } from 'vue'

/**
 * 页头行内读数：「小标签 + 等宽数字」一行排开，专供 PageToolbar 的 stats 槽。
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
  <!-- 页头行内读数：标签+等宽数字同行。D1：涨跌色只上到数值 -->
  <div class="header-stat inline-flex min-w-0 items-baseline gap-2">
    <span class="header-stat__label text-aux text-mist font-medium whitespace-nowrap">{{ label }}</span>
    <span class="header-stat__value text-body font-mono font-bold whitespace-nowrap tabular-nums" :class="[toneClass, lead ? 'text-hero' : '']"><slot>{{ value }}</slot></span>
  </div>
</template>
