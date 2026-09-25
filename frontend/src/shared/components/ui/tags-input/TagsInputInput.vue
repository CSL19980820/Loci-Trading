<script setup lang="ts">
import type { TagsInputInputProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TagsInputInput as Primitive, useForwardProps } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<TagsInputInputProps & { class?: HTMLAttributes['class'] }>()
const forwarded = useForwardProps(reactiveOmit(props, 'class'))
</script>
<template>
  <Primitive v-bind="forwarded" :class="cn('min-w-24 flex-1 bg-transparent py-1 text-sm outline-none placeholder:text-muted-foreground', props.class)"></Primitive>
</template>
