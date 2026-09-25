<script setup lang="ts">
import type { TagsInputItemDeleteProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TagsInputItemDelete as Primitive, useForwardProps } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
import { X } from '@lucide/vue'
const props = defineProps<TagsInputItemDeleteProps & { class?: HTMLAttributes['class'] }>()
const forwarded = useForwardProps(reactiveOmit(props, 'class'))
</script>
<template>
  <Primitive v-bind="{ ...forwarded, ...($attrs['aria-label'] ? { 'aria-labelledby': undefined } : {}) }" :class="cn('flex items-center rounded-r-sm px-1 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring', props.class)"><slot><X class="size-3.5" /></slot></Primitive>
</template>
