<script setup lang="ts">
import { computed, provide, ref, toRaw, watch } from 'vue'
import Schema from 'async-validator'
import { asRules, cssLength, formContextKey, type FieldRules, type FormHandle, type FormRules, type ValidationDescriptor } from './context'

const props = withDefaults(defineProps<{
  model?: Record<string, unknown>; rules?: FormRules; disabled?: boolean;
  labelPosition?: string; labelWidth?: string | number; inline?: boolean; size?: string
}>(), { model: () => ({}), rules: () => ({}), labelPosition: 'right', labelWidth: 'var(--form-label-w)' })
const errors = ref<Record<string, string>>({})
const registered = new Map<string, () => FieldRules | undefined>()
const initial = new Map<string, unknown>()
const generations = new Map<string, number>()
function copy(value: unknown): unknown {
  if (value === undefined) return value
  try { return structuredClone(toRaw(value)) } catch { return JSON.parse(JSON.stringify(value)) }
}
function register(name: string, rules: () => FieldRules | undefined) {
  registered.set(name, rules)
  if (!initial.has(name)) initial.set(name, copy(props.model[name]))
  return () => {
    registered.delete(name)
    generations.set(name, (generations.get(name) ?? 0) + 1)
    delete errors.value[name]
  }
}
function descriptor(fields: string[]): ValidationDescriptor {
  const result: ValidationDescriptor = {}
  for (const name of fields) {
    const rules = [...asRules(props.rules[name]), ...asRules(registered.get(name)?.())]
    if (rules.length) result[name] = rules
  }
  return result
}
async function validateFields(fields?: string[]): Promise<boolean> {
  const names = fields ?? [...new Set([...Object.keys(props.rules), ...registered.keys()])]
  const runs = new Map(names.map(name => {
    const run = (generations.get(name) ?? 0) + 1
    generations.set(name, run)
    return [name, run]
  }))
  const nextErrors: Record<string, string> = {}
  try {
    await new Schema(descriptor(names)).validate(props.model, { firstFields: true })
  } catch (failure) {
    const items = (failure as { errors?: { field?: string; message?: string }[] }).errors
    if (!items) throw failure
    for (const item of items) if (item.field) nextErrors[item.field] = item.message || '请检查此字段'
  }
  for (const name of names) {
    if (runs.get(name) !== generations.get(name)) continue
    if (nextErrors[name]) errors.value[name] = nextErrors[name]
    else delete errors.value[name]
  }
  if (Object.keys(nextErrors).length) throw nextErrors
  return true
}
const validate: FormHandle['validate'] = async (callback) => {
  try {
    await validateFields()
  } catch (error) {
    if (!callback) throw error
    callback(false, error as Record<string, string>)
    return false
  }
  // A consumer callback failure is not a failed field validation. Invoke it once.
  callback?.(true)
  return true
}
function validateField(fields: string | string[]) { return validateFields(Array.isArray(fields) ? fields : [fields]) }
function clearValidate(fields?: string | string[]) {
  const names = fields ? (Array.isArray(fields) ? fields : [fields]) : [...new Set([...generations.keys(), ...Object.keys(errors.value)])]
  for (const name of names) { generations.set(name, (generations.get(name) ?? 0) + 1); delete errors.value[name] }
}
function resetFields(fields?: string | string[]) {
  const names = fields ? (Array.isArray(fields) ? fields : [fields]) : [...initial.keys()]
  for (const name of names) props.model[name] = copy(initial.get(name))
  clearValidate(fields)
}
provide(formContextKey, {
  model: computed(() => props.model), rules: computed(() => props.rules), disabled: computed(() => Boolean(props.disabled)),
  errors, labelPosition: computed(() => props.labelPosition), labelWidth: computed(() => props.labelWidth), register, validateField,
})
watch(() => props.model, () => clearValidate())
defineExpose({ validate, validateField, clearValidate, resetFields } satisfies FormHandle)
</script>

<template>
  <form class="form-layout" :class="{ 'form-layout--inline': inline, 'form-layout--top': labelPosition === 'top' }"
    :style="{ '--form-label-width': cssLength(labelWidth), '--form-label-align': labelPosition === 'right' ? 'right' : 'left' }"
    :aria-disabled="disabled || undefined" @submit.prevent><slot /></form>
</template>
