<script setup lang="ts">
import { cn } from '@/shared/lib/cn'


</script>

<template>
  <div :class="cn('flex min-w-0 flex-col gap-1')">
    <slot />
  </div>
</template>
