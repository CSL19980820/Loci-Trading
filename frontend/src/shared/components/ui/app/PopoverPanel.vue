<script setup lang="ts">
import { computed } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '../popover'
import { cssLength } from './context'
const props = withDefaults(defineProps<{ width?: string | number; placement?: string; popperClass?: string; trigger?: string }>(), { placement: 'bottom', trigger: 'click' })
const open = defineModel<boolean>('visible', { default: false })
const side = computed(() => props.placement.split('-')[0] as 'top' | 'bottom' | 'left' | 'right')
const align = computed(() => props.placement.endsWith('start') ? 'start' : props.placement.endsWith('end') ? 'end' : 'center')
</script>
<template>
  <Popover v-model:open="open"><PopoverTrigger as-child><slot name="reference" /></PopoverTrigger>
    <PopoverContent :class="popperClass" :side="side" :align="align" :style="{ width: cssLength(width), maxWidth: 'calc(100vw - 2rem)' }"><slot /></PopoverContent>
  </Popover>
</template>
