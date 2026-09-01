<script setup lang="ts">
import {
  computed,
  h,
  inject,
  onMounted,
  onScopeDispose,
  onUnmounted,
  ref,
  watch,
  type Slots,
} from 'vue'

import type { BasicFormOption, BasicFormSchema } from './basicFormTypes'

const props = defineProps<{
  schema: BasicFormSchema
  model: Record<string, unknown>
  /** 文本输入防抖毫秒；≤0 关闭。默认 500 */
  inputDebounceMs?: number
}>()

const emit = defineEmits<{
  'update:field': [field: string, value: unknown]
}>()

const formSlots = inject<Slots>('basicFormSlots', {})
const remoteOptions = ref<BasicFormOption[]>([])
const remoteTree = ref<unknown[]>([])
const remoteCascader = ref<unknown[]>([])
const inputDraft = ref('')
let inputTimer: ReturnType<typeof setTimeout> | undefined
let requestGeneration = 0

const inputDebounce = computed(() => {
  const fromSchema = props.schema.componentProps?.debounceMs
  if (typeof fromSchema === 'number') return fromSchema
  return props.inputDebounceMs ?? 500
})

watch(
  () => props.model[props.schema.field],
  (value) => {
    if (!props.schema.component || props.schema.component === 'input') {
      inputDraft.value = String(value ?? '')
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  if (inputTimer) clearTimeout(inputTimer)
})

const staticOptions = computed(
  () => (props.schema.componentProps?.options as BasicFormOption[] | undefined) ?? [],
)

const options = computed(() => (remoteOptions.value.length ? remoteOptions.value : staticOptions.value))

function fieldProps(): Record<string, unknown> {
  const raw = { ...(props.schema.componentProps ?? {}) }
  delete raw.options
  delete raw.request
  delete raw.fieldValue
  delete raw.fieldLabel
  delete raw.immediate
  delete raw.data
  delete raw.debounceMs
  return raw
}

function bindEvents(): Record<string, (...args: unknown[]) => void> {
  const events = props.schema.componentEvents ?? {}
  const out: Record<string, (...args: unknown[]) => void> = {}
  for (const [name, fn] of Object.entries(events)) {
    out[name] = (...args: unknown[]) => fn(...args, props.model, props.schema)
  }
  return out
}

function setValue(value: unknown): void {
  emit('update:field', props.schema.field, value)
}

function onInputUpdate(value: unknown): void {
  const next = String(value ?? '')
  inputDraft.value = next
  const ms = inputDebounce.value
  if (ms <= 0) {
    setValue(next)
    return
  }
  if (inputTimer) clearTimeout(inputTimer)
  inputTimer = setTimeout(() => {
    inputTimer = undefined
    setValue(next)
  }, ms)
}

/**
 * 立刻落地防抖中的草稿。
 * el-input 的 `change`（失焦 / 回车）与父级 `submit()` 都会调：不然「打完字立刻点
 * 保存」会丢掉最后 500ms 的输入 —— 弹窗表单里这就是丢一整个字段。
 */
function flushInput(): void {
  if (!inputTimer) return
  clearTimeout(inputTimer)
  inputTimer = undefined
  setValue(inputDraft.value)
}

function slotVNode() {
  const name = props.schema.slotName
  if (!name) return null
  const fn = formSlots[name]
  if (!fn) return null
  return fn({
    model: props.model,
    field: props.schema.field,
    value: props.model[props.schema.field],
    schema: props.schema,
  })
}

async function loadRequest(): Promise<void> {
  const generation = ++requestGeneration
  const request = props.schema.componentProps?.request as
    | ((query?: Record<string, unknown>) => Promise<{ data?: unknown } | unknown[]>)
    | undefined
  if (!request) return
  const fieldValue = String(props.schema.componentProps?.fieldValue ?? 'value')
  const fieldLabel = String(props.schema.componentProps?.fieldLabel ?? 'label')
  const res = await request({})
  if (generation !== requestGeneration) return
  const list = Array.isArray(res)
    ? res
    : Array.isArray((res as { data?: unknown }).data)
      ? ((res as { data: unknown[] }).data)
      : []
  if (props.schema.component === 'tree-select') {
    remoteTree.value = list
    return
  }
  if (props.schema.component === 'cascader') {
    remoteCascader.value = list
    return
  }
  remoteOptions.value = list.map((item) => {
    const row = item as Record<string, unknown>
    return {
      label: String(row[fieldLabel] ?? ''),
      value: row[fieldValue],
      disabled: Boolean(row.disabled),
    }
  })
}

onScopeDispose(() => {
  requestGeneration += 1
})

defineExpose({ getRequest: loadRequest, flush: flushInput })

onMounted(() => {
  const immediate = props.schema.componentProps?.immediate
  if (props.schema.componentProps?.request && immediate !== false) void loadRequest()
})

watch(
  () => props.schema.componentProps?.request,
  () => {
    const immediate = props.schema.componentProps?.immediate
    if (props.schema.componentProps?.request && immediate !== false) void loadRequest()
  },
)

const treeData = computed(() => {
  if (remoteTree.value.length) return remoteTree.value
  return (props.schema.componentProps?.data as unknown[]) ?? []
})

const cascaderOptions = computed(() => {
  if (remoteCascader.value.length) return remoteCascader.value
  return (props.schema.componentProps?.options as unknown[]) ?? []
})

const isTextarea = computed(
  () =>
    props.schema.component === 'input' &&
    String(props.schema.componentProps?.type ?? '') === 'textarea',
)
</script>

<template>
  <component :is="{ render: () => slotVNode() }" v-if="schema.slotName" />
  <component
    :is="{ render: () => schema.render?.(h, { model, field: schema.field }) ?? null }"
    v-else-if="schema.render"
  />
  <el-input
    v-else-if="!schema.component || schema.component === 'input'"
    :model-value="inputDraft"
    v-bind="fieldProps()"
    :type="isTextarea ? 'textarea' : ((fieldProps().type as string) ?? 'text')"
    clearable
    class="basic-form__full"
    @update:model-value="onInputUpdate"
    @change="flushInput"
    v-on="bindEvents()"
  />
  <el-input-number
    v-else-if="schema.component === 'input-number'"
    :model-value="model[schema.field] as number"
    v-bind="fieldProps()"
    class="basic-form__full"
    @update:model-value="setValue"
    v-on="bindEvents()"
  />
  <el-select
    v-else-if="schema.component === 'select'"
    :model-value="model[schema.field]"
    v-bind="fieldProps()"
    clearable
    class="basic-form__full"
    @update:model-value="setValue"
    v-on="bindEvents()"
  >
    <el-option
      v-for="opt in options"
      :key="String(opt.value)"
      :label="opt.label"
      :value="opt.value"
      :disabled="opt.disabled"
    />
  </el-select>
  <el-date-picker
    v-else-if="schema.component === 'date-picker'"
    :model-value="model[schema.field]"
    v-bind="fieldProps()"
    class="basic-form__full"
    @update:model-value="setValue"
    v-on="bindEvents()"
  />
  <el-switch
    v-else-if="schema.component === 'switch'"
    :model-value="model[schema.field] as boolean"
    v-bind="fieldProps()"
    @update:model-value="setValue"
    v-on="bindEvents()"
  />
  <el-checkbox
    v-else-if="schema.component === 'checkbox'"
    :model-value="model[schema.field]"
    v-bind="fieldProps()"
    @update:model-value="setValue"
    v-on="bindEvents()"
  >
    {{ (schema.componentProps?.label as string) || '' }}
  </el-checkbox>
  <el-radio-group
    v-else-if="schema.component === 'RadioGroup'"
    :model-value="model[schema.field]"
    v-bind="fieldProps()"
    @update:model-value="setValue"
    v-on="bindEvents()"
  >
    <el-radio v-for="opt in options" :key="String(opt.value)" :value="opt.value">
      {{ opt.label }}
    </el-radio>
  </el-radio-group>
  <el-checkbox-group
    v-else-if="schema.component === 'CheckboxGroup'"
    :model-value="(model[schema.field] as unknown[]) ?? []"
    v-bind="fieldProps()"
    @update:model-value="setValue"
    v-on="bindEvents()"
  >
    <el-checkbox v-for="opt in options" :key="String(opt.value)" :label="opt.value">
      {{ opt.label }}
    </el-checkbox>
  </el-checkbox-group>
  <el-tree-select
    v-else-if="schema.component === 'tree-select'"
    :model-value="model[schema.field]"
    :data="treeData"
    v-bind="fieldProps()"
    class="basic-form__full"
    @update:model-value="setValue"
    v-on="bindEvents()"
  />
  <el-cascader
    v-else-if="schema.component === 'cascader'"
    :model-value="model[schema.field]"
    :options="cascaderOptions"
    v-bind="fieldProps()"
    class="basic-form__full"
    @update:model-value="setValue"
    v-on="bindEvents()"
  />
</template>
