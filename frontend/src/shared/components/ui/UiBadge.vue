<script setup lang="ts">
import { computed } from 'vue'

import { cn } from '@/shared/lib/cn'

/**
 * UiBadge —— 药片徽标（存量调用面很大，接口不变）。
 * 涨跌变体只给价格语义（up/down），等宽 tabular；状态走 warn/info/ok/stamp；默认主色浅底。
 */
const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'secondary' | 'outline' | 'up' | 'down' | 'warn' | 'info' | 'ok' | 'stamp'
    /** 左侧带一颗 6px 状态点 */
    dot?: boolean
  }>(),
  { variant: 'default', dot: false },
)

const cls = computed(() =>
  cn(
    'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-px text-kicker leading-[1.6] font-medium whitespace-nowrap',
    props.variant === 'default' && 'border-transparent bg-seal-soft text-seal-ink',
    props.variant === 'secondary' && 'border-transparent bg-sunken text-ink-2',
    props.variant === 'outline' && 'border-line-default bg-surface text-ink-2',
    props.variant === 'up' && 'border-transparent bg-up-soft text-up font-mono tabular-nums',
    props.variant === 'down' && 'border-transparent bg-down-soft text-down font-mono tabular-nums',
    props.variant === 'warn' && 'border-transparent bg-warn-soft text-warn-ink',
    props.variant === 'info' && 'border-transparent bg-info-soft text-info-ink',
    props.variant === 'ok' && 'border-transparent bg-ok-soft text-ok',
    props.variant === 'stamp' && 'border-transparent bg-stamp-soft text-stamp',
  ),
)

const dotCls = computed(() =>
  cn(
    'size-1.5 shrink-0 rounded-full',
    props.variant === 'default' && 'bg-seal',
    props.variant === 'secondary' && 'bg-mist',
    props.variant === 'outline' && 'bg-mist',
    props.variant === 'up' && 'bg-up',
    props.variant === 'down' && 'bg-down',
    props.variant === 'warn' && 'bg-warn',
    props.variant === 'info' && 'bg-info',
    props.variant === 'ok' && 'bg-ok',
    props.variant === 'stamp' && 'bg-stamp',
  ),
)
</script>

<template>
  <span :class="cls">
    <span v-if="dot" :class="dotCls" aria-hidden="true" />
    <slot />
  </span>
</template>
