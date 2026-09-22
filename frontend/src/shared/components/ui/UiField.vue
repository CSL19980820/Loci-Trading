<script setup lang="ts">
import { useId } from 'vue'
import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from '@/shared/components/ui/field'
withDefaults(defineProps<{ label?: string; description?: string; error?: string; required?: boolean; inline?: boolean; for?: string }>(), {required:false,inline:false})
const labelId = `ui-field-${useId()}`
</script>
<template>
  <Field :orientation="inline ? 'horizontal' : 'vertical'" :data-invalid="Boolean(error)" :aria-labelledby="label || $slots.label ? labelId : undefined" class="gap-1">
    <FieldLabel v-if="label || $slots.label" :id="labelId" :for="$props.for" class="text-xs text-muted-foreground"><slot name="label">{{ label }}</slot><span v-if="required" class="text-destructive" aria-hidden="true">*</span></FieldLabel>
    <FieldContent class="min-w-0"><slot /><FieldDescription v-if="description && !error"><slot name="description">{{ description }}</slot></FieldDescription><FieldError v-if="error"><slot name="error">{{ error }}</slot></FieldError></FieldContent>
  </Field>
</template>
