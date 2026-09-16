<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/**
 * UiSeparator —— shadcn Separator 构造：1px hairline 分隔。
 * horizontal=横线（默认），vertical=竖线（父容器需定高）。
 */
withDefaults(defineProps<{ vertical?: boolean }>(), { vertical: false })
</script>

<template>
  <div
    role="separator"
    :aria-orientation="vertical ? 'vertical' : 'horizontal'"
    :class="
      cn(
        'bg-line shrink-0',
        vertical ? 'mx-2 h-full min-h-4 w-px self-stretch' : 'h-px w-full',
      )
    "
  />
</template>
