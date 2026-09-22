<script setup lang="ts">
import { computed } from 'vue'

/**
 * 页头 / 工具行内读数：「小标签 + 等宽数字」一行排开。
 * 数值等宽 + tabular-nums：同一列换值时不横跳。`lead` 把数值抬到 20px，一个页头至多一次。
 */
const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    tone?: 'up' | 'down' | 'neutral' | ''
    /** 主读数：字号抬到页标题档 */
    lead?: boolean
  }>(),
  { lead: false },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'text-up'
  if (props.tone === 'down') return 'text-down'
  if (props.tone === 'neutral') return 'text-mist'
  return 'text-ink'
})
</script>

<template>
  <div class="header-stat inline-flex min-w-0 items-baseline gap-1.5 rounded-md bg-sunken px-2.5 py-1">
    <span class="header-stat__label text-kicker text-mist font-medium whitespace-nowrap">{{ label }}</span>
    <span
      class="header-stat__value font-mono font-semibold whitespace-nowrap tabular-nums"
      :class="[toneClass, lead ? 'text-hero tracking-tight' : 'text-ui']"
    ><slot>{{ value }}</slot></span>
  </div>
</template>
