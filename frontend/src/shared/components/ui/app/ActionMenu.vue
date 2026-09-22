<script setup lang="ts">
import { computed, provide } from 'vue'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent } from '../dropdown-menu'
import { actionMenuKey } from './menuContext'
const props = withDefaults(defineProps<{ disabled?: boolean; placement?: string; trigger?: string; teleported?: boolean }>(), { placement: 'bottom-end' })
const emit = defineEmits<{ command: [value: unknown] }>()
provide(actionMenuKey, command => emit('command', command))
const side = computed(() => props.placement.split('-')[0] as 'top' | 'bottom' | 'left' | 'right')
const align = computed(() => props.placement.endsWith('start') ? 'start' : props.placement.endsWith('end') ? 'end' : 'center')
</script>
<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child :disabled="disabled"><slot /></DropdownMenuTrigger>
    <DropdownMenuContent class="action-menu" :side="side" :align="align"><slot name="dropdown"><slot name="content" /></slot></DropdownMenuContent>
  </DropdownMenu>
</template>
