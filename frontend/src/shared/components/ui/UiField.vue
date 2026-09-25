<script setup lang="ts">
import { computed, provide, useId } from 'vue'
import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from './field'
import { fieldContextKey } from './app/context'
const props = withDefaults(defineProps<{ label?: string; description?: string; error?: string; required?: boolean; inline?: boolean; for?: string }>(), { required: false, inline: false })
const controlId = props.for || `ui-field-${useId()}`
const labelId = `${controlId}-label`
provide(fieldContextKey, {
  id: controlId, name: computed(() => ''), error: computed(() => props.error || ''),
  required: computed(() => props.required), describedBy: computed(() => props.description ? `${controlId}-description` : undefined),
})
</script>
<template>
  <Field :orientation="inline ? 'horizontal' : 'vertical'" :data-invalid="Boolean(error)" :aria-labelledby="label || $slots.label ? labelId : undefined" class="gap-1">
    <FieldLabel v-if="label || $slots.label" :id="labelId" :for="controlId" class="text-xs text-muted-foreground"><slot name="label">{{ label }}</slot><span v-if="required" class="text-destructive" aria-hidden="true">*</span></FieldLabel>
    <FieldContent class="min-w-0"><slot :id="controlId" /><FieldDescription v-if="description && !error" :id="`${controlId}-description`"><slot name="description">{{ description }}</slot></FieldDescription><FieldError v-if="error" :id="`${controlId}-error`"><slot name="error">{{ error }}</slot></FieldError></FieldContent>
  </Field>
</template>
