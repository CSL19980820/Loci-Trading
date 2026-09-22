
import { type FormRules } from '@/shared/components/ui/app/context'

import type { h as VueH, VNode } from 'vue'

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

/** 表单列数：1 单列（默认）/ 2 / 3 / 4。栅格由 CSS Grid 直接作用在 `el-form` 上。 */
export type BasicFormColumns = 1 | 2 | 3 | 4
export type BasicFormSchema = {
  field: string
  label?:
    | string
    | ((h: typeof VueH, ctx: { model: Record<string, unknown>; field: string }) => VNode | string)
  component?: BasicFormComponent
  componentProps?: Record<string, unknown>
  componentEvents?: Record<string, (...args: unknown[]) => void>
  defaultValue?: unknown
  hidden?: boolean
  /**
   * 字段说明。≤20 字渲染在控件下方（12px / --mist，左缘与控件对齐）；
   * >20 字自动沉到 label 旁的 `el-tooltip` 图标，不占版面高度。
   */
  hint?: string
  /** 强制走 label 旁的 tooltip（长口径说明、示例串）；给了它就不再渲染行内 hint */
  tooltip?: string
  /** 占满整行（textarea / 长文本 / 一行放不下的组合控件） */
  fullRow?: boolean
  /** 必填状态；省略时由当前字段的规则推导。 */
  required?: boolean
  /**
   * 24 栅格跨列数。**兼容入口**：只服务尚未迁到 `columns` 的存量筛选条
   * （`features/{ledger,market,strategy}` 的 5 处搜索栏，由各域 agent 迁移）。
   * 新表单一律用 BasicForm 的 `columns` + `fullRow`。
   */
  colSpan?: number
  rules?: FormRules[string]
  slotName?: string
  labelWidth?: string | number
  render?: (
    h: typeof VueH,
    ctx: { model: Record<string, unknown>; field: string },
  ) => VNode | string | number | null
}
