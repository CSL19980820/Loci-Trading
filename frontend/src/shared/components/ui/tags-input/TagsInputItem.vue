<script setup lang="ts">
import type { TagsInputItemProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TagsInputItem as Primitive, useForwardProps } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<TagsInputItemProps & { class?: HTMLAttributes['class'] }>()
const forwarded = useForwardProps(reactiveOmit(props, 'class'))
</script>
<template>
  <Primitive v-bind="forwarded" :class="cn('flex items-center gap-1 rounded-sm bg-secondary text-secondary-foreground data-[state=active]:ring-2 data-[state=active]:ring-ring', props.class)"><slot /></Primitive>
</template>
