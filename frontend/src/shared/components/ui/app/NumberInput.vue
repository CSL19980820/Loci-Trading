<script setup lang="ts" generic="T = number">
import { computed, useAttrs, type StyleValue } from 'vue'
import { NumberField, NumberFieldContent, NumberFieldInput, NumberFieldIncrement, NumberFieldDecrement } from '../number-field'
import { useFieldControl } from './context'
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ modelValue?: T; min?: number; max?: number; step?: number; precision?: number; disabled?: boolean; controls?: boolean; size?: string }>(), { controls: true, step: 1 })
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const field = useFieldControl()
const attrs = useAttrs()
const value = computed(() => typeof props.modelValue === 'number' ? props.modelValue : undefined)
const controlAttrs = computed(() => { const { class: _class, style: _style, ...rest } = attrs; return { ...field.bindings.value, ...rest } })
function update(next: number) {
  const value = (Number.isFinite(next) ? next : undefined) as T
  emit('update:modelValue', value)
  emit('change', value)
  field.validate()
}
</script>
<template>
  <NumberField class="number-input" :class="attrs.class" :style="attrs.style as StyleValue" :model-value="value" :min="min" :max="max" :step="step"
    :disabled="disabled || field.disabled.value" :format-options="precision === undefined ? undefined : { minimumFractionDigits: precision, maximumFractionDigits: precision }" @update:model-value="update">
    <NumberFieldContent>
      <NumberFieldDecrement v-if="controls" aria-label="减少" />
      <NumberFieldInput v-bind="controlAttrs" :class="{ 'px-3': !controls }" @blur="field.validate" />
      <NumberFieldIncrement v-if="controls" aria-label="增加" />
    </NumberFieldContent>
  </NumberField>
</template>
