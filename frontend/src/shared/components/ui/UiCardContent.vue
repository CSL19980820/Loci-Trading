<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/** UiCardContent —— 卡片正文，默认带 sheet 内边距。 */
withDefaults(defineProps<{ padded?: boolean }>(), { padded: true })
</script>

<template>
  <div :class="cn('min-w-0', padded && 'p-[var(--pad-sheet-y)_var(--pad-sheet-x)]')">
    <slot />
  </div>
</template>
