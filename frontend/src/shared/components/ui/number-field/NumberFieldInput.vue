<script setup lang="ts">
import { useFieldControl } from '../app/context'
import type { HTMLAttributes } from "vue"
import { NumberFieldInput } from "reka-ui"
import { cn } from '@/shared/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
const field = useFieldControl()
</script>

<template>
  <NumberFieldInput
    v-bind="field.bindings.value"
    data-slot="input"
    :class="cn('flex h-[var(--ctl-h)] w-full rounded-md border border-input bg-transparent py-1 text-ui text-center shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50', props.class)"
  />
</template>
