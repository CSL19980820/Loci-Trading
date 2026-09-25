<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from './badge'
const props = withDefaults(defineProps<{
  variant?: 'default' | 'secondary' | 'outline' | 'up' | 'down' | 'warn' | 'info' | 'ok' | 'stamp'
  dot?: boolean
}>(), { variant: 'default', dot: false })
const variant = computed(() => props.variant === 'default' ? 'soft' : props.variant === 'stamp' ? 'destructive' : props.variant)
</script>
<template>
  <Badge :variant="variant"><span v-if="dot" class="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" /><slot /></Badge>
</template>
