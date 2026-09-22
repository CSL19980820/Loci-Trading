<script setup lang="ts" generic="T extends object = Record<string, any>">
import type { GridColumn } from './gridTypes'
defineProps<GridColumn & { group?: boolean }>()
// Declarative columns have no data prop to infer T from. Callers may supply @vue-generic.
defineSlots<{
  default?: (scope: { row: T; $index: number; column: GridColumn }) => unknown
  header?: (scope: { column: GridColumn; $index: number }) => unknown
}>()
</script>
<template />
