<script setup lang="ts">
import { computed, inject, useAttrs, useId, type StyleValue } from 'vue'
import { Checkbox } from '../checkbox'
import { Label } from '../label'
import { checkboxContextKey } from './selectionContext'
import { useFieldControl } from './context'
defineOptions({ inheritAttrs: false })
const props = defineProps<{ modelValue?: unknown; value?: unknown; label?: unknown; disabled?: boolean; indeterminate?: boolean; size?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; change: [value: boolean] }>()
const group = inject(checkboxContextKey, undefined)
const field = useFieldControl()
const attrs = useAttrs()
const ownId = `check-${useId()}`
const id = computed(() => String(attrs.id || (!group && field.bindings.value.id) || ownId))
const checked = computed(() => props.indeterminate ? 'indeterminate' : group
  ? group.value.value.some(item => Object.is(item, props.value ?? props.label)) : Boolean(props.modelValue))
function update(value: boolean | 'indeterminate') {
  const next = value === true
  if (group) group.toggle(props.value ?? props.label, next)
  else { emit('update:modelValue', next); emit('change', next); field.validate() }
}
</script>
<template>
  <span :class="['checkbox-field', attrs.class]" :style="attrs.style as StyleValue">
    <Checkbox v-bind="{ ...field.bindings.value, ...attrs }" :id="id" :model-value="checked"
      :disabled="disabled || group?.disabled.value || field.disabled.value" @update:model-value="update" />
    <Label v-if="$slots.default || (!group && label)" :for="id"><slot>{{ label }}</slot></Label>
  </span>
</template>
