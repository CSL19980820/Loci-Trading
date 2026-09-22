<script setup lang="ts">
import { computed, inject, onBeforeUnmount, provide, useId, watch } from 'vue'
import { Field, FieldLabel, FieldContent, FieldError } from '../field'
import { asRules, cssLength, fieldContextKey, formContextKey, type FieldRules } from './context'
const props = defineProps<{ label?: string; prop?: string; required?: boolean; labelWidth?: string | number; error?: string; rules?: FieldRules }>()
const form = inject(formContextKey, undefined)
const id = `field-${useId()}`
const message = computed(() => props.error || (props.prop ? form?.errors.value[props.prop] : '') || '')
const required = computed(() => props.required ?? [...asRules(props.rules), ...asRules(props.prop ? form?.rules.value[props.prop] : undefined)].some(rule => rule.required))
provide(fieldContextKey, { id, name: computed(() => props.prop || ''), error: message, required })
let unregister: (() => void) | undefined
watch(() => props.prop, name => {
  unregister?.()
  if (form && name) unregister = form.register(name, () => props.rules ?? (props.required ? { required: true, message: `请填写${props.label || name}` } : undefined))
}, { immediate: true })
onBeforeUnmount(() => unregister?.())
</script>
<template>
  <Field :data-invalid="Boolean(message)" :orientation="form?.labelPosition.value === 'top' ? 'vertical' : 'horizontal'" class="form-field" :class="{ 'form-field--top': form?.labelPosition.value === 'top', 'form-field--error': message, 'is-required': required }"
    :style="labelWidth !== undefined ? { '--form-label-width': cssLength(labelWidth) } : undefined">
    <FieldLabel v-if="label || $slots.label" :for="id" class="form-field__label"><slot name="label">{{ label }}</slot><span v-if="required" aria-hidden="true" class="text-destructive">*</span></FieldLabel>
    <FieldContent class="form-field__content"><slot /><FieldError v-if="message" :id="`${id}-error`" class="form-field__error">{{ message }}</FieldError></FieldContent>
  </Field>
</template>
