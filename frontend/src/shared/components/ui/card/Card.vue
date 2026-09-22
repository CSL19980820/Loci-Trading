<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from '@/shared/lib/utils'

/*
 * Card：面板的基础壳。圆角 12、hairline、极淡投影；不带默认 padding 与 gap ——
 * 让 CardHeader / CardContent 自己控制密度（数据面板 12px、说明卡 20px 都可以）。
 * `interactive` 给可点击卡：悬停抬边框 + 投影，按下微沉。
 */
const props = defineProps<{
  class?: HTMLAttributes["class"]
  interactive?: boolean
}>()
</script>

<template>
  <div
    data-slot="card"
    :data-interactive="interactive ? '' : undefined"
    :class="
      cn(
        'bg-card text-card-foreground flex min-w-0 flex-col rounded-lg border border-line shadow-xs transition-[border-color,box-shadow,transform] duration-150',
 interactive && 'cursor-pointer hover:border-line-default hover:shadow-sm active:translate-y-px',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
