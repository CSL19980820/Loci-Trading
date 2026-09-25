import { computed, inject, nextTick, type ComputedRef, type InjectionKey, type Ref } from 'vue'
import type { RuleItem, Rules } from 'async-validator'

export type FieldRules = (RuleItem & { trigger?: string | string[] }) | (RuleItem & { trigger?: string | string[] })[]
export type FormRules = Record<string, FieldRules>
export interface FormHandle {
  validate: (callback?: (valid: boolean, errors?: Record<string, string>) => void) => Promise<boolean>
  validateField: (fields: string | string[]) => Promise<boolean>
  resetFields: (fields?: string | string[]) => void
  clearValidate: (fields?: string | string[]) => void
}
export interface FormContext {
  disabled: ComputedRef<boolean>
  model: ComputedRef<Record<string, unknown>>
  rules: ComputedRef<FormRules>
  errors: Ref<Record<string, string>>
  labelPosition: ComputedRef<string>
  labelWidth: ComputedRef<string | number>
  register: (name: string, rules: () => FieldRules | undefined) => () => void
  validateField: (name: string) => Promise<boolean>
}
export const formContextKey: InjectionKey<FormContext> = Symbol('form')
export const fieldContextKey: InjectionKey<{ id: string; name: ComputedRef<string>; error: ComputedRef<string>; required: ComputedRef<boolean>; describedBy?: ComputedRef<string | undefined> }> = Symbol('field')
export function useFieldControl() {
  const form = inject(formContextKey, undefined)
  const field = inject(fieldContextKey, undefined)
  const disabled = computed(() => Boolean(form?.disabled.value))
  const bindings = computed(() => ({
    id: field?.id,
    name: field?.name.value || undefined,
    'aria-invalid': field?.error.value ? true : undefined,
    'aria-describedby': field?.error.value ? `${field.id}-error` : field?.describedBy?.value,
    'aria-required': field?.required.value || undefined,
  }))
  function validate() {
    // Parent v-model updates are committed before a control validates the new value.
    const name = field?.name.value
    if (form && name) void nextTick(() => form.validateField(name)).catch(() => undefined)
  }
  return { disabled, bindings, validate }
}
export function cssLength(value: unknown, fallback?: string): string | undefined {
  if (value === undefined || value === null || value === '') return fallback
  return typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value)) ? `${value}px` : String(value)
}
export function encodeChoice(value: unknown): string { return JSON.stringify(value) ?? 'null' }
export function decodeChoice(value: string): unknown { try { return JSON.parse(value) } catch { return value } }
export function asRules(value: FieldRules | undefined): RuleItem[] { return value ? (Array.isArray(value) ? value : [value]) : [] }
export type ValidationDescriptor = Rules
