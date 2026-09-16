<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/** UiCardHeader —— 卡片头：标题行 + 右侧动作区，hairline 收边。 */
</script>

<template>
  <header
    :class="
      cn(
        'border-line bg-surface flex min-h-[var(--head-h)] flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b px-[var(--pad-sheet-x)] py-1',
      )
    "
  >
    <div class="flex min-w-0 flex-wrap items-center gap-2">
      <slot />
    </div>
    <div v-if="$slots.action" class="flex min-w-0 flex-wrap items-center gap-1">
      <slot name="action" />
    </div>
  </header>
</template>
