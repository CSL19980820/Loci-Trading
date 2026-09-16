<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/** UiCardDescription —— 12px 弱色口径/时间戳，永远不抢标题。 */
</script>

<template>
  <p :class="cn('text-aux text-mist m-0 leading-snug font-mono tabular-nums')">
    <slot />
  </p>
</template>
