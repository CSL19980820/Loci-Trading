<script setup lang="ts">
import type { DropdownMenuItemProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { DropdownMenuItem, useForwardProps } from "reka-ui"
import { cn } from '@/shared/lib/utils'
import { useVisitorMode, type ControlAccess } from '@/shared/composables/useAccess'

const props = withDefaults(defineProps<DropdownMenuItemProps & {
  access?: ControlAccess
  class?: HTMLAttributes["class"]
  inset?: boolean
  variant?: "default" | "destructive"
}>(), {
  variant: "default",
})

const visitor = useVisitorMode()
const delegatedProps = reactiveOmit(props, "inset", "variant", "class", "access")

const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
  <DropdownMenuItem
    v-if="!visitor || access === 'read'"
    data-slot="dropdown-menu-item"
    :data-inset="inset ? '' : undefined"
    :data-variant="variant"
    v-bind="forwardedProps"
    :class="cn(`relative flex min-h-8 cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-ui outline-hidden select-none transition-colors duration-100 focus:bg-hover focus:text-ink data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[inset]:pl-8 data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-stamp-soft data-[variant=destructive]:focus:text-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-muted-foreground data-[variant=destructive]:*:[svg]:text-destructive!`, props.class)"
  >
    <slot />
  </DropdownMenuItem>
</template>
