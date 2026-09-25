<script setup lang="ts">
import type { TagsInputItemTextProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TagsInputItemText as Primitive, useForwardProps } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<TagsInputItemTextProps & { class?: HTMLAttributes['class'] }>()
const forwarded = useForwardProps(reactiveOmit(props, 'class'))
</script>
<template>
  <Primitive v-bind="forwarded" :class="cn('px-2 py-1 text-sm', props.class)"><slot /></Primitive>
</template>
