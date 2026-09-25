<script setup lang="ts">
import { computed, useAttrs, type Component } from 'vue'
import { Spinner } from '@/shared/components/ui/spinner'
import { Button, type ButtonVariants } from '../button'
import { useFieldControl } from './context'
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  tone?: string; variant?: ButtonVariants['variant']; size?: string; busy?: boolean;
  disabled?: boolean; icon?: Component; iconOnly?: boolean; plain?: boolean;
  type?: 'button' | 'submit' | 'reset'
}>(), { type: 'button' })
const attrs = useAttrs()
const field = useFieldControl()
const variant = computed(() => props.variant ?? (props.plain ? 'outline' : props.tone === 'danger' ? 'destructive' : props.tone === 'primary' ? 'default' : 'outline'))
const size = computed<ButtonVariants['size']>(() => {
  if (props.iconOnly) return props.size === 'small' || props.size === 'sm' ? 'icon-sm' : 'icon'
  return props.size === 'small' ? 'sm' : props.size === 'large' ? 'lg' : (props.size as ButtonVariants['size']) ?? 'default'
})
</script>
<template>
  <Button v-bind="attrs" class="action-button" :variant="variant" :size="size" :type="type"
    :disabled="disabled || busy || field.disabled.value" :aria-busy="busy || undefined" :data-tone="tone">
    <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
    <component :is="icon" v-else-if="icon" class="size-4" aria-hidden="true" />
    <slot />
  </Button>
</template>
