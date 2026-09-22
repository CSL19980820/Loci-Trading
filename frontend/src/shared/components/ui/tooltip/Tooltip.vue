<script setup lang="ts">
import type { TooltipRootEmits, TooltipRootProps } from "reka-ui"
import { TooltipProvider, TooltipRoot, injectTooltipProviderContext, useForwardPropsEmits } from "reka-ui"

const props = defineProps<TooltipRootProps>()
const emits = defineEmits<TooltipRootEmits>()

const forwarded = useForwardPropsEmits(props, emits)
// Share app-level delay state when available; standalone widgets get a provider.
const provider = injectTooltipProviderContext(null)
</script>

<template>
  <TooltipProvider v-if="!provider" :delay-duration="300">
    <TooltipRoot v-slot="slotProps" data-slot="tooltip" v-bind="forwarded">
      <slot v-bind="slotProps" />
    </TooltipRoot>
  </TooltipProvider>
  <TooltipRoot v-else
    v-slot="slotProps"
    data-slot="tooltip"
    v-bind="forwarded"
  >
    <slot v-bind="slotProps" />
  </TooltipRoot>
</template>
