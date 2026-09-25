<script setup lang="ts">
import { useFieldControl } from '../app/context'
import type { SelectTriggerProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { ChevronsUpDown } from "@lucide/vue"
import { reactiveOmit } from "@vueuse/core"
import { SelectIcon, SelectTrigger, useForwardProps } from "reka-ui"
import { cn } from '@/shared/lib/utils'

const props = withDefaults(
  defineProps<SelectTriggerProps & { class?: HTMLAttributes["class"], size?: "sm" | "default" }>(),
  { size: "default" },
)

const delegatedProps = reactiveOmit(props, "class", "size")
const forwardedProps = useForwardProps(delegatedProps)
const field = useFieldControl()
</script>

<template>
  <SelectTrigger
    data-slot="select-trigger"
    :data-size="size"
    v-bind="{ ...field.bindings.value, ...forwardedProps }"
    :class="cn(
      `border-input bg-surface text-ink data-[placeholder]:text-muted-foreground [&_svg:not([class*='text-'])]:text-muted-foreground flex w-fit items-center justify-between gap-2 rounded-md border px-3 py-2 text-ui whitespace-nowrap shadow-xs transition-[color,box-shadow,border-color] duration-150 outline-none hover:border-line-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 aria-invalid:border-destructive aria-invalid:ring-destructive/20 disabled:cursor-not-allowed disabled:opacity-50 data-[size=default]:h-[var(--ctl-h)] data-[size=sm]:h-[var(--ctl-h-sm)] data-[size=sm]:px-2.5 data-[size=sm]:text-aux *:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-2 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4`,
      props.class,
    )"
  >
    <slot />
    <SelectIcon as-child>
      <ChevronsUpDown class="size-3.5 opacity-60" />
    </SelectIcon>
  </SelectTrigger>
</template>
