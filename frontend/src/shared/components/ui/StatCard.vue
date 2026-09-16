<script setup lang="ts">
import { computed } from 'vue'

/**
 * 读数卡 —— 数字主导版式（D2）：数值是卡上最大的字，等宽 + tabular-nums；
 * 标签 11px/--mist，副信息 12px。无阴影、1px hairline、圆角 3px（D3）。
 *
 * 卡高由内容决定：不写 min-height —— 一排卡里只有一张有副信息时，靠 grid 的
 * `align-items: start` 收边，不要用定高把空卡撑成死白。
 * D1：涨跌色只上到数值那一行，标签与副信息永远是墨色梯度。
 */
const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    hint?: string
    tone?: 'up' | 'down' | 'neutral' | ''
    /** stack=上下（默认，数值 26px）；row=左右一行（标签左、数值右，17px） */
    layout?: 'stack' | 'row'
  }>(),
  { layout: 'stack' },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'tone-up'
  if (props.tone === 'down') return 'tone-down'
  if (props.tone === 'neutral') return 'tone-neutral'
  return ''
})
</script>

<template>
  <!-- row=左右一行（标签左、数值右）；默认 stack=上下。D2：数值是卡上最大的字，等宽 -->
  <div
    class="stat-card border-line bg-surface min-w-0 rounded-md border shadow-none"
    :class="layout === 'row' ? 'flex flex-wrap items-baseline justify-between gap-x-2 gap-y-px px-2 py-1' : 'grid gap-px px-3 py-2'"
  >
    <span class="stat-card__label text-aux text-mist font-medium">{{ label }}</span>
    <span
      class="stat-card__value min-w-0 font-mono font-bold tabular-nums"
      :class="[toneClass, layout === 'row' ? 'text-hero inline-flex flex-wrap items-baseline gap-1 leading-snug' : 'text-tape inline-flex flex-wrap items-baseline gap-1 leading-tight']"
    ><slot>{{ value }}</slot></span>
    <span v-if="hint" class="stat-card__hint text-aux text-mist font-mono tabular-nums" :class="layout === 'row' ? 'basis-full' : ''">{{ hint }}</span>
  </div>
</template>
