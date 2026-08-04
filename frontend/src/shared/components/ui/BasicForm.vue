<script setup lang="ts">
import { computed, h, provide, reactive, ref, useAttrs, useSlots, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import BasicFormField from './BasicFormField.vue'
import { formRecordsEqual, formValuesEqual } from './basicFormEqual'
import type { BasicFormSchema } from './basicFormTypes'

export type { BasicFormComponent, BasicFormOption, BasicFormSchema } from './basicFormTypes'

defineOptions({ inheritAttrs: false })

defineSlots<{
  [name: string]: ((props: {
    model: Record<string, unknown>
    field: string
    value: unknown
    schema: BasicFormSchema
  }) => unknown) | undefined
}>()

const props = withDefaults(
  defineProps<{
    schemas: BasicFormSchema[]
    modelValue?: Record<string, unknown>
    rowProps?: Record<string, unknown>
    colProps?: { span?: number }
    labelWidth?: string | number
    collapse?: boolean | string
    inline?: boolean
    size?: 'large' | 'default' | 'small'
    disabled?: boolean
    /** 文本 input 防抖毫秒，默认 500；≤0 关闭 */
    inputDebounceMs?: number
  }>(),
  {
    modelValue: () => ({}),
    rowProps: () => ({}),
    colProps: () => ({ span: 8 }),
    labelWidth: 'auto',
    collapse: '',
    inline: false,
    inputDebounceMs: 500,
  },
)

const emit = defineEmits<{
  'update:modelValue': [Record<string, unknown>]
}>()

const attrs = useAttrs()
const slots = useSlots()
provide('basicFormSlots', slots)
const formRef = ref<FormInstance>()
const local = reactive<Record<string, unknown>>({})
const collapsed = reactive({ open: false })
const fieldRefs = ref<Record<string, { getRequest?: () => Promise<void> }>>({})

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

const useCollapse = computed(() => props.collapse !== '')

const displaySchemas = computed(() => {
  if (!useCollapse.value || collapsed.open) return visibleSchemas.value
  let used = 0
  const out: BasicFormSchema[] = []
  for (const schema of visibleSchemas.value) {
    const span = schema.colSpan ?? props.colProps.span ?? 8
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
  return schema.colSpan ?? props.colProps.span ?? 8
}

function onFieldUpdate(field: string, value: unknown): void {
  local[field] = value
}

function setFieldRef(field: string, el: unknown): void {
  if (el) fieldRefs.value[field] = el as { getRequest?: () => Promise<void> }
  else delete fieldRefs.value[field]
}

function labelOf(schema: BasicFormSchema): string | undefined {
  if (typeof schema.label === 'function') return undefined
  return schema.label
}

function labelRender(schema: BasicFormSchema) {
  const label = schema.label
  if (typeof label !== 'function') return null
  return { render: () => label(h, { model: local, field: schema.field }) ?? null }
}

async function submit(): Promise<Record<string, unknown> | false> {
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
  <el-form
    ref="formRef"
    :model="local"
    :rules="formRules"
    :label-width="labelWidth"
    :inline="inline"
    :size="size"
    :disabled="disabled"
    class="basic-form"
    v-bind="attrs"
    @submit.prevent
  >
    <el-row :gutter="12" v-bind="rowProps">
      <el-col
        v-for="schema in displaySchemas"
        :key="schema.field"
        :span="colSpanOf(schema)"
      >
        <el-form-item
          :label="labelOf(schema)"
          :prop="schema.field"
          :label-width="schema.labelWidth"
        >
          <template v-if="typeof schema.label === 'function'" #label>
            <component :is="labelRender(schema)" />
          </template>
          <BasicFormField
            :ref="(el) => setFieldRef(schema.field, el)"
            :schema="schema"
            :model="local"
            :input-debounce-ms="inputDebounceMs"
            @update:field="onFieldUpdate"
          />
        </el-form-item>
      </el-col>
      <el-col v-if="useCollapse && visibleSchemas.length > displaySchemas.length" :span="6">
        <el-button link type="primary" @click="collapsed.open = !collapsed.open">
          {{ collapsed.open ? '收起' : '展开' }}
        </el-button>
      </el-col>
    </el-row>
  </el-form>
</template>

<style scoped>
.basic-form {
  width: 100%;
}

.basic-form :deep(.basic-form__full) {
  width: 100%;
}

.basic-form :deep(.el-form-item) {
  margin-bottom: 0.65rem;
}

.basic-form :deep(.el-date-editor.el-input),
.basic-form :deep(.el-date-editor.el-input__wrapper),
.basic-form :deep(.el-cascader) {
  width: 100%;
}
</style>
