<script setup lang="ts">
import { inject } from 'vue'
import { DropdownMenuItem, DropdownMenuSeparator } from '../dropdown-menu'
import { actionMenuKey } from './menuContext'
defineProps<{ command?: unknown; disabled?: boolean; divided?: boolean }>()
const select = inject(actionMenuKey, undefined)
</script>
<template><DropdownMenuSeparator v-if="divided" /><DropdownMenuItem :disabled="disabled" @select="select?.(command)"><slot /></DropdownMenuItem></template>
