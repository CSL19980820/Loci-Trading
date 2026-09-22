<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { cn } from '@/shared/lib/cn'


withDefaults(
  defineProps<{
    label?: string
    description?: string
    error?: string
    required?: boolean
    /** 标签与控件同一行（筛选项这类窄条场景） */
    inline?: boolean
  }>(),
  { required: false, inline: false },
)
</script>

<template>
  <div :class="cn('flex min-w-0 flex-col gap-1', inline && 'flex-row items-center gap-2')">
    <Label
      v-if="label || $slots.label"
      :class="cn('text-aux text-mist shrink-0 leading-snug')"
    >
      <slot name="label">{{ label }}</slot>
      <span v-if="required" class="text-stamp" aria-hidden="true">*</span>
    </Label>
    <div :class="cn('min-w-0', inline ? 'flex-1' : 'w-full')">
      <slot />
    </div>
    <p v-if="description && !error" :class="cn('text-aux text-mist m-0 leading-snug')">
      <slot name="description">{{ description }}</slot>
    </p>
    <p v-if="error" :class="cn('text-aux text-stamp m-0 leading-snug font-medium')" role="alert">
      <slot name="error">{{ error }}</slot>
    </p>
  </div>
</template>
