import type { FormRules } from 'element-plus'
import type { VNode } from 'vue'

export type BasicFormComponent =
  | 'input'
  | 'input-number'
  | 'select'
  | 'date-picker'
  | 'switch'
  | 'RadioGroup'
  | 'CheckboxGroup'
  | 'checkbox'
  | 'tree-select'
  | 'cascader'

export type BasicFormOption = { label: string; value: unknown; disabled?: boolean }

export type BasicFormSchema = {
  field: string
  label?: string | ((h: typeof import('vue').h, ctx: { model: Record<string, unknown>; field: string }) => VNode | string)
  component?: BasicFormComponent
  componentProps?: Record<string, unknown>
  componentEvents?: Record<string, (...args: unknown[]) => void>
  defaultValue?: unknown
  hidden?: boolean
  colSpan?: number
  rules?: FormRules[string]
  slotName?: string
  labelWidth?: string | number
  render?: (
    h: typeof import('vue').h,
    ctx: { model: Record<string, unknown>; field: string },
  ) => VNode | string | number | null
}
