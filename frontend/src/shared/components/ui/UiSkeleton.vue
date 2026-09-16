<script setup lang="ts">
import { computed } from 'vue'

import { cn } from '@/shared/lib/cn'

/**
 * UiSkeleton —— shadcn Skeleton 构造：加载占位，pulse 动画。
 * prefers-reduced-motion 时静止（全局 tail 层已处理 transition/animation，这里补 opacity 静态）。
 */
const props = withDefaults(defineProps<{ lines?: number }>(), { lines: 1 })

const rows = computed(() => Math.max(1, props.lines))
</script>

<template>
  <div :class="cn('flex min-w-0 flex-col gap-2')" aria-hidden="true">
    <div
      v-for="i in rows"
      :key="i"
      :class="cn('bg-sunken h-4 w-full animate-pulse rounded')"
    />
  </div>
</template>
