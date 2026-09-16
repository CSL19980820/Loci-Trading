<script setup lang="ts">
import { computed } from 'vue'

import { cn } from '@/shared/lib/cn'

/**
 * UiButton —— shadcn Button 构造（cva 变体 + cn 收敛）。
 * 颜色全部指回本仓令牌：default=主色实心，destructive=印章红，绝不用 shadcn 默认蓝。
 * 尺寸对齐 --ctl-h（30px），不引入 shadcn 的 h-9/h-10 尺度。
 */
const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
    size?: 'default' | 'sm' | 'lg' | 'icon'
    disabled?: boolean
    loading?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'default', size: 'default', disabled: false, loading: false, type: 'button' },
)

const emit = defineEmits<{ click: [event: MouseEvent] }>()

const cls = computed(() =>
  cn(
    'ui-button inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors motion-reduce:transition-none',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--seal)]',
    'disabled:pointer-events-none disabled:opacity-50',
    props.variant === 'default' && 'bg-seal text-[var(--on-primary)] hover:bg-seal-hover active:bg-seal-active',
    /* --stamp 无 -ink 变体：压在印章红上的字规范就是白（ui-spec §2.1） */
    props.variant === 'destructive' && 'bg-stamp text-white hover:opacity-90',
    props.variant === 'outline' &&
      'border-line-default bg-surface text-ink hover:bg-sunken border hover:text-ink',
    props.variant === 'secondary' && 'bg-sunken text-ink hover:bg-hover',
    props.variant === 'ghost' && 'text-ink hover:bg-sunken',
    props.variant === 'link' && 'text-seal-ink underline-offset-4 hover:underline',
    props.size === 'default' && 'h-[var(--ctl-h)] px-3 text-body',
    props.size === 'sm' && 'h-[var(--ctl-h)] px-2 text-aux',
    props.size === 'lg' && 'h-[calc(var(--ctl-h)+var(--gap-1))] px-4 text-body',
    props.size === 'icon' && 'h-[var(--ctl-h)] w-[var(--ctl-h)] p-0',
    props.loading && 'pointer-events-none opacity-70',
  ),
)
</script>

<template>
  <button :type="type" :class="cls" :disabled="disabled || loading" :aria-busy="loading || undefined" @click.stop="emit('click', $event)">
    <span v-if="loading" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none" aria-hidden="true" />
    <slot />
  </button>
</template>
