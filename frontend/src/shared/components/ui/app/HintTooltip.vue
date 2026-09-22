<script setup lang="ts">
import { computed } from 'vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../tooltip'
const props = withDefaults(defineProps<{ content?: string; disabled?: boolean; showAfter?: number; placement?: string; popperClass?: string; trigger?: string }>(), { placement: 'top', showAfter: 250 })
const side = computed(() => props.placement.split('-')[0] as 'top' | 'right' | 'bottom' | 'left')
</script>
<template>
  <slot v-if="disabled || (!content && !$slots.content)" />
  <TooltipProvider v-else :delay-duration="showAfter">
    <Tooltip>
      <TooltipTrigger as-child><span class="hint-tooltip__trigger" tabindex="0"><slot /></span></TooltipTrigger>
      <TooltipContent :side="side" :class="['hint-tooltip__content', popperClass]"><slot name="content">{{ content }}</slot></TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
