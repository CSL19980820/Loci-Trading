<script setup lang="ts">
import type { ProgressRootProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import {
  ProgressIndicator,
  ProgressRoot,
} from "reka-ui"
import { cn } from '@/shared/lib/utils'

const props = withDefaults(
  defineProps<ProgressRootProps & { class?: HTMLAttributes["class"] }>(),
  {
    modelValue: 0,
  },
)

const delegatedProps = reactiveOmit(props, "class")
</script>

<template>
  <ProgressRoot
    data-slot="progress"
    v-bind="delegatedProps"
    :class="
      cn(
        'bg-primary/20 relative h-2 w-full overflow-hidden rounded-full',
        props.class,
      )
    "
  >
    <ProgressIndicator
      data-slot="progress-indicator"
      class="bg-primary h-full w-full flex-1 transition-all"
      :class="{ 'progress-indeterminate motion-reduce:animate-none': props.modelValue === null }"
      :style="props.modelValue === null ? undefined : `transform: translateX(-${100 - Math.max(0, Math.min(100, props.modelValue ?? 0))}%);`"
    />
  </ProgressRoot>
</template>

<style scoped>
.progress-indeterminate { width:28%; animation:progress-slide 1.1s linear infinite; }
@keyframes progress-slide { from { transform:translateX(-100%); } to { transform:translateX(460%); } }
@media(prefers-reduced-motion:reduce) { .progress-indeterminate { width:100%; animation:none; opacity:.55; } }
</style>
