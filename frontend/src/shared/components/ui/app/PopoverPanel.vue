<script setup lang="ts">
import { computed } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '../popover'
import { cssLength } from './context'
const props = withDefaults(defineProps<{ width?: string | number; placement?: string; popperClass?: string; trigger?: string; contentLabel?: string }>(), { placement: 'bottom', trigger: 'click' })
const open = defineModel<boolean>('visible', { default: false })
const side = computed(() => props.placement.split('-')[0] as 'top' | 'bottom' | 'left' | 'right')
const align = computed(() => props.placement.endsWith('start') ? 'start' : props.placement.endsWith('end') ? 'end' : 'center')
function focusNamedContent(event: Event): void {
  if (!props.contentLabel) return
  event.preventDefault()
  if (event.target instanceof HTMLElement) event.target.focus()
}
</script>
<template>
  <Popover v-model:open="open"><PopoverTrigger as-child><slot name="reference" /></PopoverTrigger>
    <PopoverContent @open-auto-focus="focusNamedContent" :as-child="Boolean(contentLabel)" :class="popperClass" :side="side" :align="align" :style="{ width: cssLength(width), maxWidth: 'calc(100vw - 2rem)' }">
      <!-- Reka labels PopoverContent from its trigger; the as-child element owns an explicit content name. -->
      <div v-if="contentLabel" :aria-label="contentLabel" :aria-labelledby="undefined"><slot /></div>
      <slot v-else />
    </PopoverContent>
  </Popover>
</template>
