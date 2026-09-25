<script setup lang="ts">
import type { SplitterGroupProps, SplitterGroupEmits } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { SplitterGroup, useForwardPropsEmits } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<SplitterGroupProps & { class?: HTMLAttributes['class'] }>()
const emit = defineEmits<SplitterGroupEmits>()
const forwarded = useForwardPropsEmits(reactiveOmit(props, 'class'), emit)
</script>
<template>
  <SplitterGroup v-bind="forwarded" as-child :class="cn('flex h-full w-full min-h-0 min-w-0 data-[orientation=vertical]:flex-col', props.class)"><component :is="props.as || 'div'" :id="props.id || undefined"><slot /></component></SplitterGroup>
</template>
