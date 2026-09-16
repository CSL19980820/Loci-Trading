<script setup lang="ts">
import { computed } from 'vue'

import { cn } from '@/shared/lib/cn'

/**
 * UiBadge —— shadcn Badge 构造（cva 变体 + cn 收敛）。
 * D1：涨跌变体只给价格语义（up/down）；状态走 warn/info/ok；默认主色浅底。
 */
const props = withDefaults(
  defineProps<{ variant?: 'default' | 'secondary' | 'outline' | 'up' | 'down' | 'warn' | 'info' | 'ok' | 'stamp' }>(),
  { variant: 'default' },
)

const cls = computed(() =>
  cn(
    'inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-px font-mono text-[11px] leading-[1.5] font-semibold whitespace-nowrap tabular-nums',
    props.variant === 'default' && 'bg-seal-soft text-seal-ink border-seal-border border',
    props.variant === 'secondary' && 'bg-sunken text-mist border-line border',
    props.variant === 'outline' && 'bg-surface text-mist border-line-default border',
    props.variant === 'up' && 'bg-up-soft text-up border border-transparent',
    props.variant === 'down' && 'bg-down-soft text-down border border-transparent',
    props.variant === 'warn' && 'bg-warn-soft text-warn-ink border border-transparent',
    props.variant === 'info' && 'bg-info-soft text-info-ink border border-transparent',
    props.variant === 'ok' && 'bg-ok-soft text-ok border border-transparent',
    props.variant === 'stamp' && 'bg-surface text-stamp border border-[color-mix(in_oklab,var(--stamp)_38%,var(--rule))]',
  ),
)
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
