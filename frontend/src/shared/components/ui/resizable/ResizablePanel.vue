<script setup lang="ts">
import type { SplitterPanelProps, SplitterPanelEmits } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { SplitterPanel, useForwardPropsEmits } from 'reka-ui'
import { cn } from '@/shared/lib/utils'
const props = defineProps<SplitterPanelProps & { class?: HTMLAttributes['class'] }>()
const emit = defineEmits<SplitterPanelEmits>()
const forwarded = useForwardPropsEmits(reactiveOmit(props, 'class'), emit)
</script>
<template>
  <SplitterPanel v-bind="forwarded" :class="cn('min-h-0 min-w-0', props.class)"><slot /></SplitterPanel>
</template>
