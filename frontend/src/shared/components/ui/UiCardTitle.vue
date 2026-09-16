<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/** UiCardTitle —— 中文标题 ≤16px/700/字距（D2：最大的字留给数字）。 */
</script>

<template>
  <h2 :class="cn('text-title text-ink m-0 leading-tight font-bold tracking-wide')">
    <slot />
  </h2>
</template>
