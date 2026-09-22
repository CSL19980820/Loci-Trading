<script setup lang="ts">
import { CircleHelp as QuestionFilled } from '@lucide/vue'
import { type FormHandle, type FormRules } from '@/shared/components/ui/app/context'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { IconBox } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import {
  computed,
  h,
  provide,
  reactive,
  ref,
  useAttrs,
  useSlots,
  watch,
  type CSSProperties,
} from 'vue'



import BasicFormField from './BasicFormField.vue'
import { formRecordsEqual, formValuesEqual } from './basicFormEqual'
import type { BasicFormColumns, BasicFormSchema } from './basicFormTypes'

export type {
  BasicFormColumns,
  BasicFormComponent,
  BasicFormOption,
  BasicFormSchema,
} from './basicFormTypes'

/**
 * Schema-driven form built from local shadcn compositions.
 * Layout, label width and help placement are configurable presentation defaults,
 * not restrictions on future designs. Validation and draft flushing are shared.
 */

defineOptions({ inheritAttrs: false })

defineSlots<{
  [name: string]: ((props: {
    model: Record<string, unknown>
    field: string
    value: unknown
    schema: BasicFormSchema
  }) => unknown) | undefined
}>()

/** 说明文案超过这个字数就沉到 label 旁的 tooltip，别把版面顶高 */
const HINT_INLINE_MAX = 20

const props = withDefaults(
  defineProps<{
    schemas: BasicFormSchema[]
    modelValue?: Record<string, unknown>
    /** 表单级说明：渲染在首个字段之前，缩进与控件左缘一致 */
    hint?: string
    /** 列数：1 单列（默认）/ 2 / 3；窄容器自动退列，不留硬空格 */
    columns?: BasicFormColumns
    labelPosition?: 'right' | 'left' | 'top'
    labelWidth?: string | number
    size?: 'large' | 'default' | 'small'
    inline?: boolean
    disabled?: boolean
    /** 只显示第一行字段 + 「展开」按钮（长筛选条用） */
    collapse?: boolean
    /** 文本 input 防抖毫秒，默认 500；≤0 关闭。弹窗类表单建议传 0 */
    inputDebounceMs?: number
    /**
     * 24 栅格列宽。**兼容入口**，只服务尚未迁到 `columns` 的存量筛选条
     * （见 basicFormTypes.ts 的 `colSpan` 注释）；不传即走 `columns` 栅格。
     */
    colProps?: { span?: number }
  }>(),
  {
    modelValue: () => ({}),
    hint: '',
    columns: 1,
    labelPosition: 'right',
    labelWidth: 'var(--form-label-w)',
    size: 'small',
    collapse: false,
    inline: false,
    inputDebounceMs: 500,
  },
)

const emit = defineEmits<{
  'update:modelValue': [Record<string, unknown>]
}>()

type FieldExpose = { getRequest?: () => Promise<void>; flush?: () => void }

const attrs = useAttrs()
const slots = useSlots()
provide('basicFormSlots', slots)
const formRef = ref<FormHandle>()
const local = reactive<Record<string, unknown>>({})
const collapsed = reactive({ open: false })
const fieldRefs = ref<Record<string, FieldExpose>>({})

watch(
  () => props.schemas,
  (schemas) => {
    for (const schema of schemas) {
      if (!(schema.field in local)) {
        local[schema.field] =
          props.modelValue[schema.field] ?? schema.defaultValue ?? defaultFor(schema)
      }
    }
  },
  { immediate: true, deep: true },
)

watch(
  () => props.modelValue,
  (value) => {
    for (const key of Object.keys(value)) {
      // 数组/对象用结构相等；引用不等就回写会与下方 emit 组成死循环（daterange 卡死）
      if (!formValuesEqual(local[key], value[key])) local[key] = value[key]
    }
  },
  { deep: true },
)

watch(
  local,
  () => {
    const next = { ...local }
    if (formRecordsEqual(next, props.modelValue)) return
    emit('update:modelValue', next)
  },
  { deep: true },
)

const visibleSchemas = computed(() => props.schemas.filter((s) => !s.hidden))

const useCollapse = computed(() => props.collapse)

/** 存量筛选条仍按 24 栅格给列宽；两者互斥，避免同一张表单两种排布口径 */
const legacyGrid = computed(
  () => props.colProps !== undefined || props.schemas.some((s) => s.colSpan !== undefined),
)

const gridClass = computed(() => {
  if (props.inline) return ''
  if (legacyGrid.value) return 'basic-form--legacy'
  return `basic-form--c${props.columns}`
})

const displaySchemas = computed(() => {
  if (!useCollapse.value || collapsed.open) return visibleSchemas.value
  if (!legacyGrid.value) return visibleSchemas.value.slice(0, Math.max(1, props.columns))
  let used = 0
  const out: BasicFormSchema[] = []
  for (const schema of visibleSchemas.value) {
    const span = colSpanOf(schema)
    if (used + span > 24 && out.length) break
    out.push(schema)
    used += span
  }
  return out
})

const formRules = computed(() => {
  const rules: FormRules = {}
  for (const schema of props.schemas) {
    if (schema.rules) rules[schema.field] = schema.rules
  }
  return rules
})

function defaultFor(schema: BasicFormSchema): unknown {
  if (schema.component === 'CheckboxGroup') return []
  if (schema.component === 'switch' || schema.component === 'checkbox') return false
  if (schema.component === 'input-number') return undefined
  if (schema.component === 'cascader') return []
  if (
    schema.component === 'date-picker' &&
    String(schema.componentProps?.type ?? '').includes('range')
  ) {
    return null
  }
  return ''
}

function colSpanOf(schema: BasicFormSchema): number {
  return schema.colSpan ?? props.colProps?.span ?? 8
}

/** 24 栅格模式的跨列数走自定义属性，好让窄屏断点无 `!important` 覆盖 */
function itemStyle(schema: BasicFormSchema): CSSProperties | undefined {
  if (!legacyGrid.value || props.inline) return undefined
  return { '--bf-span': colSpanOf(schema) }
}

function itemClass(schema: BasicFormSchema): string {
  return schema.fullRow ? 'is-full-row' : ''
}

function charCount(text: string): number {
  return Array.from(text).length
}

/** 行内 hint：只有短说明才留在版面上 */
function inlineHintOf(schema: BasicFormSchema): string {
  if (schema.tooltip?.trim()) return ''
  const hint = schema.hint?.trim() ?? ''
  return hint && charCount(hint) <= HINT_INLINE_MAX ? hint : ''
}

/** tooltip 文案：显式 `tooltip`，或超长的 `hint` */
function tipOf(schema: BasicFormSchema): string {
  const tooltip = schema.tooltip?.trim() ?? ''
  if (tooltip) return tooltip
  const hint = schema.hint?.trim() ?? ''
  return charCount(hint) > HINT_INLINE_MAX ? hint : ''
}

function onFieldUpdate(field: string, value: unknown): void {
  local[field] = value
}

function setFieldRef(field: string, el: unknown): void {
  if (el) fieldRefs.value[field] = el as FieldExpose
  else delete fieldRefs.value[field]
}

function labelOf(schema: BasicFormSchema): string | undefined {
  if (typeof schema.label === 'function') return undefined
  return schema.label
}

function labelTextOf(schema: BasicFormSchema): string {
  return typeof schema.label === 'string' ? schema.label : ''
}

function labelRender(schema: BasicFormSchema) {
  const label = schema.label
  if (typeof label !== 'function') return null
  return { render: () => label(h, { model: local, field: schema.field }) ?? null }
}

/** 防抖中的文本草稿在校验前先落地，否则「打完字立刻点保存」会丢最后一次输入 */
function flushDrafts(): void {
  for (const field of Object.values(fieldRefs.value)) field.flush?.()
}

async function submit(): Promise<Record<string, unknown> | false> {
  flushDrafts()
  const form = formRef.value
  if (!form) return { ...local }
  try {
    await form.validate()
    return { ...local }
  } catch {
    return false
  }
}

function getFieldsValue(): Record<string, unknown> {
  flushDrafts()
  return { ...local }
}

function setFieldsValue(fields: Record<string, unknown>): void {
  Object.assign(local, fields)
}

function resetForm(): void {
  formRef.value?.resetFields()
  for (const schema of props.schemas) {
    local[schema.field] = schema.defaultValue ?? defaultFor(schema)
  }
}

function setProps(patch: Record<string, Partial<BasicFormSchema>>): void {
  for (const [field, next] of Object.entries(patch)) {
    const schema = props.schemas.find((s) => s.field === field)
    if (schema) Object.assign(schema, next)
  }
}

defineExpose({
  submit,
  getFieldsValue,
  setFieldsValue,
  resetForm,
  setProps,
  getFormRef: () => formRef.value,
  /** For linkage: refresh a field's request options, e.g. fieldRefs.positionId.getRequest() */
  getFieldRef: (field: string) => fieldRefs.value[field],
})
</script>

<template>
  <FormLayout
    ref="formRef"
    :model="local"
    :rules="formRules"
    :label-position="labelPosition"
    :label-width="labelWidth"
    :inline="inline"
    :size="size"
    :disabled="disabled"
    require-asterisk-position="right"
    class="basic-form w-full items-start gap-x-3"
    :class="gridClass"
    v-bind="attrs"
    @submit.prevent
  >
    <!-- 表单说明与字段共享布局；标签宽度由当前 FormLayout 传递。 -->
    <FormField v-if="hint" class="basic-form__lead is-full-row">
      <p class="basic-form__hint">{{ hint }}</p>
    </FormField>

    <FormField
      v-for="schema in displaySchemas"
      :key="schema.field"
      :label="labelOf(schema)"
      :prop="schema.field"
      :label-width="schema.labelWidth"
      :required="schema.required"
      :class="itemClass(schema)"
      :style="itemStyle(schema)"
    >
      <template v-if="typeof schema.label === 'function'" #label>
        <component :is="labelRender(schema)" />
      </template>
      <template v-else-if="tipOf(schema)" #label>
        <span class="basic-form__label">
          {{ labelTextOf(schema) }}
          <HintTooltip :content="tipOf(schema)" placement="top" :show-after="120">
            <IconBox
              class="basic-form__tip"
              tabindex="0"
              role="note"
              :aria-label="`${labelTextOf(schema)}说明：${tipOf(schema)}`"
              @click.prevent
            >
              <QuestionFilled />
            </IconBox>
          </HintTooltip>
        </span>
      </template>
      <BasicFormField
        :ref="(el) => setFieldRef(schema.field, el)"
        :schema="schema"
        :model="local"
        :input-debounce-ms="inputDebounceMs"
        @update:field="onFieldUpdate"
      />
      <p v-if="inlineHintOf(schema)" class="basic-form__hint">{{ inlineHintOf(schema) }}</p>
    </FormField>

    <ActionButton access="read"
      v-if="useCollapse && visibleSchemas.length > displaySchemas.length"
      class="basic-form__collapse"
      variant="link"
      tone="primary"
      @click="collapsed.open = !collapsed.open"
    >
      {{ collapsed.open ? '收起' : '展开' }}
    </ActionButton>
  </FormLayout>
</template>

<style scoped>
.basic-form--c1,
.basic-form--c2,
.basic-form--c3,
.basic-form--c4,
.basic-form--legacy {
  display: grid;
  align-items: start;
  column-gap: var(--gap-3, 12px);
  row-gap: var(--gap-4, 16px);
}

/* Grid gaps separate rows without leaving an invisible trailing row under filters. */
.basic-form > :deep(.form-field) {
  margin-bottom: 0;
}

.basic-form--c1 {
  grid-template-columns: minmax(0, 1fr);
}

.basic-form--c2 {
  grid-template-columns: repeat(auto-fit, minmax(max(240px, (100% - var(--gap-3, 12px)) / 2), 1fr));
}

.basic-form--c3 {
  grid-template-columns: repeat(
    auto-fit,
    minmax(max(220px, (100% - 2 * var(--gap-3, 12px)) / 3), 1fr)
  );
}

.basic-form--c4 {
  grid-template-columns: repeat(
    auto-fit,
    minmax(max(180px, (100% - 3 * var(--gap-3, 12px)) / 4), 1fr)
  );
}
.basic-form--legacy {
  grid-template-columns: repeat(24, minmax(0, 1fr));
}

.basic-form--legacy :deep(.form-field) {
  grid-column: span var(--bf-span, 24);
}

.basic-form--legacy .basic-form__collapse {
  grid-column: span 6;
}

.basic-form :deep(.form-field.is-full-row) {
  grid-column: 1 / -1;
}
.basic-form:not(.form-layout--top):not(.form-layout--inline) :deep(.form-field__label) {
  height: var(--ctl-h);
  line-height: var(--ctl-h);
}

.basic-form :deep(.form-field__content) {
  align-items: center;
  row-gap: 2px;
}
.basic-form :deep(.form-field__error) {
  max-width: 100%;
  overflow: hidden;
  line-height: 1.1;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.basic-form :deep(.basic-form__full) {
  width: 100%;
}

.basic-form :deep(.date-field.text-field),
.basic-form :deep(.date-field.text-field__body),
.basic-form :deep(.choice-field) {
  width: 100%;
}

/* 说明文案：挂在 content 里跟随控件左缘（不是 label 列外），独占一行 */
.basic-form__hint {
  flex: 0 0 100%;
  margin: 0;
  color: var(--mist);
  font-size: var(--fs-aux);
  line-height: 1.4;
}

.basic-form__lead :deep(.form-field__content) {
  min-height: 0;
}

.basic-form__label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.basic-form__tip {
  color: var(--mist);
  cursor: help;
}

.basic-form__tip:hover,
.basic-form__tip:focus-visible {
  color: var(--seal-ink);
}

.basic-form__tip:focus-visible {
  outline: 1px solid var(--seal);
  outline-offset: 1px;
}

.basic-form__collapse {
  justify-self: start;
  align-self: center;
}

/* 窄屏：栅格退单列，label 回控件上方，避免 6.5em 标签把输入挤成一条缝 */
@media (max-width: 640px) {
  .basic-form--c2,
  .basic-form--c3,
  .basic-form--c4,
  .basic-form--legacy {
    grid-template-columns: minmax(0, 1fr);
    row-gap: var(--gap-3, 12px);
  }

  .basic-form--legacy :deep(.form-field) {
    grid-column: 1 / -1;
  }
}
</style>
