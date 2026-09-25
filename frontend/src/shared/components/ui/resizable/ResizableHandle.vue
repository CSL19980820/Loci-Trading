<script setup lang="ts">
import type { SplitterResizeHandleProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { SplitterResizeHandle, useForwardProps } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<SplitterResizeHandleProps & { class?: HTMLAttributes['class'] }>()
const forwarded = useForwardProps(reactiveOmit(props, 'class'))
</script>
<template>
  <SplitterResizeHandle v-bind="forwarded" :class="cn('relative flex w-1 shrink-0 items-center justify-center rounded bg-border outline-none focus-visible:ring-2 focus-visible:ring-ring hover:bg-primary/40', props.class)"><slot /></SplitterResizeHandle>
</template>
