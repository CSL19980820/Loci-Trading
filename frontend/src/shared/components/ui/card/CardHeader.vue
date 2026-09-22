<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from '@/shared/lib/utils'

/* 面板头：标题 + 描述在左，CardAction 在右；底边 hairline 与内容分区 */
const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
</script>

<template>
  <div
    data-slot="card-header"
    :class="cn('@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-1 px-4 py-3 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-3', props.class)"
  >
    <slot />
  </div>
</template>
