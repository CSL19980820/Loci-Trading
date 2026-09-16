<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/** UiCardFooter —— 卡片脚：操作行，hairline 收边。 */
</script>

<template>
  <footer
    :class="
      cn(
        'border-line flex flex-wrap items-center gap-2 border-t px-[var(--pad-sheet-x)] py-2',
      )
    "
  >
    <slot />
  </footer>
</template>
