<script setup lang="ts">
import type { TooltipContentEmits, TooltipContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TooltipContent, TooltipPortal, useForwardPropsEmits } from "reka-ui"
import { cn } from '@/shared/lib/utils'

/* Tooltip：深色小卡（明档墨色、暗档浮层色），无箭头，6px 偏移，12px 字 */
defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<TooltipContentProps & { class?: HTMLAttributes["class"] }>(), {
  sideOffset: 6,
})

const emits = defineEmits<TooltipContentEmits>()

const delegatedProps = reactiveOmit(props, "class")
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <TooltipPortal>
    <TooltipContent
      data-slot="tooltip-content"
      v-bind="{ ...forwarded, ...$attrs }"
      :class="cn('ui-tooltip animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-1 data-[side=left]:slide-in-from-right-1 data-[side=right]:slide-in-from-left-1 data-[side=top]:slide-in-from-bottom-1 z-[var(--z-popup)] w-fit max-w-[min(20rem,calc(100vw-2rem))] rounded-md px-2.5 py-1.5 text-aux leading-snug text-balance shadow-md', props.class)"
    >
      <slot />
    </TooltipContent>
  </TooltipPortal>
</template>

<style scoped>
.ui-tooltip {
  background: oklch(0.22 0.02 255);
  color: oklch(0.97 0.005 255);
  border: 1px solid oklch(0.32 0.02 255);
}

:global(html.dark) .ui-tooltip {
  background: var(--surface-raised);
  color: var(--text-primary);
  border-color: var(--border-default);
}
</style>
