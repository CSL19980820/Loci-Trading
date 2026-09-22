<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { computed } from 'vue'
import { Switch } from '../switch'
import { useFieldControl } from './context'
defineOptions({ inheritAttrs: false })
const props = defineProps<{ modelValue?: boolean; disabled?: boolean; busy?: boolean; activeText?: string; inactiveText?: string; inlinePrompt?: boolean; size?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; change: [value: boolean] }>()
const field = useFieldControl()
const label = computed(() => props.modelValue ? props.activeText : props.inactiveText)
function update(value: boolean) { emit('update:modelValue', value); emit('change', value); field.validate() }
</script>
<template>
  <Label class="toggle-switch" :class="$attrs.class">
    <Switch v-bind="{ ...field.bindings.value, ...$attrs }" :model-value="Boolean(modelValue)"
      :disabled="disabled || busy || field.disabled.value" :aria-busy="busy || undefined" @update:model-value="update" />
    <span v-if="label" class="toggle-switch__label">{{ label }}</span>
  </Label>
</template>
