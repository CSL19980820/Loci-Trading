<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/**
 * UiCard —— shadcn Card 构造：Card / CardHeader / CardTitle / CardDescription /
 * CardContent / CardFooter / CardAction 七件套，一次配齐。
 * 皮肤对齐本仓 D3：无阴影、1px hairline、圆角 --radius；颜色走令牌，不写死。
 * 存量 Sheet 保持不动，新卡片与需要「头+动作」构造的区块优先用这套。
 */
withDefaults(
  defineProps<{
    padded?: boolean
    plain?: boolean
  }>(),
  { padded: true, plain: false },
)
</script>

<template>
  <section
    :class="
      cn(
        'flex min-w-0 flex-col overflow-hidden rounded-md shadow-none',
        plain ? 'border-0 bg-transparent' : 'border-line bg-surface border',
      )
    "
  >
    <slot />
  </section>
</template>
