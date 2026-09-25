<script setup lang="ts">
import type { TagsInputRootProps, TagsInputRootEmits } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TagsInputRoot, useForwardPropsEmits } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<TagsInputRootProps & { class?: HTMLAttributes['class'] }>()
const emit = defineEmits<TagsInputRootEmits>()
const forwarded = useForwardPropsEmits(reactiveOmit(props, 'class'), emit)
</script>
<template>
  <TagsInputRoot v-bind="forwarded" data-slot="tags-input" :class="cn('flex min-h-9 flex-wrap items-center gap-2 rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30 data-[disabled]:opacity-50', props.class)"><slot /></TagsInputRoot>
</template>
