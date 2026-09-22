<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { useVModel } from "@vueuse/core"
import { cn } from '@/shared/lib/utils'

/*
 * 聚焦仅改变控件自身边框，不叠加全局描边或外圈，避免双层边框。
 * 高度走 --ctl-h；`size="sm"` 走 --ctl-h-sm 给工具行。
 */
const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  class?: HTMLAttributes["class"]
  size?: "sm" | "default"
}>()

const emits = defineEmits<{
  (e: "update:modelValue", payload: string | number): void
}>()

const modelValue = useVModel(props, "modelValue", emits, {
  passive: true,
  defaultValue: props.defaultValue,
})
</script>

<template>
  <input
    v-model="modelValue"
    data-slot="input"
    :data-size="size ?? 'default'"
    :class="cn(
      'file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground border-input w-full min-w-0 rounded-md border bg-surface px-3 py-1 text-ui text-ink shadow-xs transition-[color,box-shadow,border-color] duration-150 outline-none',
      'data-[size=default]:h-[var(--ctl-h)] data-[size=sm]:h-[var(--ctl-h-sm)] data-[size=sm]:px-2.5 data-[size=sm]:text-aux',
      'file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-ui file:font-medium',
      'hover:border-line-strong',
      'focus-visible:border-ring focus-visible:shadow-none',
      'aria-invalid:border-destructive aria-invalid:ring-destructive/20',
      'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-sunken',
      props.class,
    )"
  >
</template>
