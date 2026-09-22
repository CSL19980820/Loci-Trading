<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from '@/shared/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
</script>

<template>
  <h3
    data-slot="card-title"
    :class="cn('text-title leading-tight font-semibold tracking-tight text-ink', props.class)"
  >
    <slot />
  </h3>
</template>
