<script setup lang="ts">
import { cn } from '@/shared/lib/cn'

/**
 * UiField —— shadcn Field 构造：label + control + description + error 四件套。
 * label 12px 弱色（筛选条 inline 场景），error 走印章红 12px，description 12px 弱色。
 * EP 表单仍是校验与控件主体，这里只管「行版式」，不重复造校验。
 */
withDefaults(
  defineProps<{
    label?: string
    description?: string
    error?: string
    required?: boolean
    inline?: boolean
  }>(),
  { required: false, inline: false },
)
</script>

<template>
  <div :class="cn('flex min-w-0 flex-col gap-1', inline && 'flex-row items-center gap-2')">
    <label v-if="label || $slots.label" :class="cn('text-aux text-mist shrink-0 leading-snug font-medium')">
      <slot name="label">{{ label }}</slot>
      <span v-if="required" class="text-stamp ml-0.5" aria-hidden="true">*</span>
    </label>
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
