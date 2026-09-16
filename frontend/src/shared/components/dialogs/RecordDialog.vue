<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { createCandidate, createPlan, createReview } from '@/shared/api/palace'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import { BUILTIN_STRATEGY_OPTIONS, localToday } from '@/shared/lib/format'

export type RecordKind = 'candidate' | 'plan' | 'review'

interface SchemaSpec {
  title: string
  /** 表单级说明：一行，跟随控件左缘（长口径说明请进字段 tooltip，别写介绍段落） */
  hint?: string
  /** 主操作文案：动词短语，不用「确定/提交」 */
  submitLabel: string
  fields: BasicFormSchema[]
  submit: (values: Record<string, unknown>) => Promise<{ id: string }>
}

const today = (): string => localToday()

const CODE_FIELD: BasicFormSchema = {
  field: 'code',
  label: '代码',
  componentProps: { maxlength: 6, inputmode: 'numeric', placeholder: '6 位数字' },
  rules: [
    { required: true, message: '填 6 位代码', trigger: 'change' },
    { pattern: /^\d{6}$/, message: '代码须为 6 位数字', trigger: 'change' },
  ],
}

/*
 * 战法选择：**下拉显示中文名，落库仍是 slug**。
 *
 * 以前这里是裸 input + placeholder="qianlong-close-v3"，等于要求用户背内部编码；
 * 界面上任何位置都不该露出英文 slug。filterable + allowCreate 保住自定义 skill
 * 的手填能力——装了工坊技能的用户仍可直接敲自己的 slug 回车。
 */
const STRATEGY_FIELD: BasicFormSchema = {
  field: 'strategy_tag',
  label: '战法',
  component: 'select',
  tooltip: '内置三档直接选；自定义技能可输入其 slug 后回车',
  componentProps: {
    placeholder: '选一个战法',
    filterable: true,
    allowCreate: true,
    defaultFirstOption: true,
    options: [...BUILTIN_STRATEGY_OPTIONS],
  },
  rules: [{ required: true, message: '选一个战法', trigger: 'change' }],
}

const TEXTAREA_ROWS = 3

function textarea(field: string, label: string, rows = TEXTAREA_ROWS): BasicFormSchema {
  return {
    field,
    label,
    componentProps: { type: 'textarea', rows },
    fullRow: true,
  }
}

const SCHEMAS: Record<RecordKind, SchemaSpec> = {
  candidate: {
    title: '记候选',
    hint: '同日同池同标的会覆盖上次裁决',
    submitLabel: '记下候选',
    fields: [
      CODE_FIELD,
      { field: 'name', label: '名称' },
      {
        field: 'decision',
        label: '裁决',
        component: 'select',
        defaultValue: '精选',
        rules: [{ required: true, message: '选一个裁决', trigger: 'change' }],
        componentProps: {
          options: [
            { label: '精选', value: '精选' },
            { label: '观察', value: '观察' },
            { label: '落选', value: '落选' },
          ],
        },
      },
      {
        field: 'score',
        label: '评分',
        component: 'input-number',
        componentProps: { min: 0, max: 100, step: 1, controls: false },
      },
      {
        field: 'timing',
        label: '时点',
        componentProps: { placeholder: '尾盘 / 低吸 / 平开 / 高开回踩' },
      },
      {
        field: 'pool_id',
        label: '池',
        componentProps: { placeholder: '默认按日期归池' },
      },
      {
        field: 'occurred_on',
        label: '日期',
        component: 'date-picker',
        defaultValue: today(),
        componentProps: { type: 'date', 'value-format': 'YYYY-MM-DD' },
      },
      {
        ...textarea('reason', '理由'),
        rules: [{ required: true, message: '写下理由', trigger: 'change' }],
      },
    ],
    submit: (values) =>
    createCandidate({
        code: String(values.code),
        name: String(values.name ?? ''),
        decision: String(values.decision),
        reason: String(values.reason),
        score: numberOrNull(values.score),
        timing: String(values.timing ?? ''),
        pool_id: String(values.pool_id ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
    }),
  },
  plan: {
    title: '写预案',
    hint: '止损 / 止盈 / 层数事后逐条核对',
    submitLabel: '保存预案',
    fields: [
      CODE_FIELD,
      {
        field: 'title',
        label: '标题',
        rules: [{ required: true, message: '填个标题', trigger: 'change' }],
      },
      {
        field: 'entry_zone',
        label: '买点区间',
        componentProps: { placeholder: '如 12.30-12.80' },
      },
      {
        field: 'stop_price',
        label: '止损价',
        component: 'input-number',
        componentProps: { min: 0, step: 0.001, controls: false },
      },
      {
        field: 'target_price',
        label: '目标价',
        component: 'input-number',
        componentProps: { min: 0, step: 0.001, controls: false },
      },
      {
        field: 'layers',
        label: '分批层数',
        component: 'input-number',
        componentProps: { min: 1, max: 10, step: 1, controls: false },
      },
      {
        field: 'occurred_on',
        label: '日期',
        component: 'date-picker',
        defaultValue: today(),
        componentProps: { type: 'date', 'value-format': 'YYYY-MM-DD' },
      },
      {
        ...textarea('scenario', '情景'),
        rules: [{ required: true, message: '写下情景', trigger: 'change' }],
      },
      textarea('invalidation', '失效条件', 2),
    ],
    submit: (values) =>
    createPlan({
        code: String(values.code),
        title: String(values.title),
        scenario: String(values.scenario),
        entry_zone: String(values.entry_zone ?? ''),
        stop_price: numberOrNull(values.stop_price),
        target_price: numberOrNull(values.target_price),
        layers: numberOrNull(values.layers),
        invalidation: String(values.invalidation ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
    }),
  },
  review: {
    title: '写复盘',
    hint: '浮盈 / 浮亏取持有期内极值',
    submitLabel: '保存复盘',
    fields: [
      {
        field: 'entity_type',
        label: '对象',
        component: 'select',
        defaultValue: 'candidate',
        componentProps: {
          options: [
            { label: '候选', value: 'candidate' },
            { label: '预案', value: 'plan' },
          ],
        },
      },
      {
        field: 'entity_id',
        label: '对象 ID',
        hint: '可后补',
        componentProps: { placeholder: 'CA-… / PL-…' },
      },
      STRATEGY_FIELD,
      {
        field: 'return_pct',
        label: '收益 %',
        component: 'input-number',
        componentProps: { step: 0.01, controls: false },
      },
      {
        field: 'max_favorable_pct',
        label: '最高浮盈 %',
        component: 'input-number',
        componentProps: { step: 0.01, controls: false },
      },
      {
        field: 'max_adverse_pct',
        label: '最深浮亏 %',
        component: 'input-number',
        componentProps: { step: 0.01, controls: false },
      },
      {
        field: 'reviewed_on',
        label: '日期',
        component: 'date-picker',
        defaultValue: today(),
        componentProps: { type: 'date', 'value-format': 'YYYY-MM-DD' },
      },
      {
        ...textarea('outcome', '结果'),
        rules: [{ required: true, message: '写下结果', trigger: 'change' }],
      },
      textarea('lesson', '教训', 2),
      textarea('next_rule', '下次规则', 2),
    ],
    submit: (values) =>
    createReview({
        entity_type: values.entity_type as 'plan' | 'candidate',
        entity_id: String(values.entity_id || 'manual'),
        outcome: String(values.outcome),
        strategy_tag: String(values.strategy_tag ?? '').trim(),
        return_pct: numberOrNull(values.return_pct),
        max_favorable_pct: numberOrNull(values.max_favorable_pct),
        max_adverse_pct: numberOrNull(values.max_adverse_pct),
        lesson: String(values.lesson ?? ''),
        next_rule: String(values.next_rule ?? ''),
        reviewed_on: String(values.reviewed_on ?? '') || null,
    }),
  },
}

function numberOrNull(value: unknown): number | null {
  if (value === '' || value === undefined || value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const props = defineProps<{
  kind: RecordKind
  presetCode?: string
  presetName?: string
}>()
const model = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [id: string] }>()

const formRef = ref<InstanceType<typeof BasicForm>>()
const submitting = ref(false)
const submitError = ref('')
const form = ref<Record<string, unknown>>({})

const schema = computed(() => SCHEMAS[props.kind])

/** 打开即重置：BasicForm 用 destroy-on-close 重新挂载，会从这里读初值 */
function reset(): void {
  const next: Record<string, unknown> = {}
  for (const field of schema.value.fields) {
    next[field.field] = field.defaultValue ?? (field.component === 'input-number' ? undefined : '')
  }
  if (props.presetCode) next.code = props.presetCode
  if (props.presetName) next.name = props.presetName
  form.value = next
  submitError.value = ''
}

watch(
  () => [model.value, props.kind] as const,
  ([isOpen]) => {
    if (isOpen) reset()
  },
)

function close(): void {
  model.value = false
}

async function submit(): Promise<void> {
  // 必填/格式由 BasicForm 的 rules 就地提示，这里只处理写入失败
  const values = await formRef.value?.submit()
  if (!values) return
  submitting.value = true
  submitError.value = ''
  try {
    const { id } = await schema.value.submit(values)
    emit('saved', id)
    close()
  } catch (caught: unknown) {
    submitError.value = caught instanceof Error ? caught.message : '写入失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="model"
    :title="schema.title"
    width="min(92vw, 560px)"
    class="record-dialog"
    destroy-on-close
    @closed="submitError = ''"
  >
    <BasicForm
      ref="formRef"
      :key="kind"
      v-model="form"
      :schemas="schema.fields"
      :hint="schema.hint"
      :columns="2"
      :input-debounce-ms="0"
      @submit.prevent="submit"
    />
    <el-alert
      v-if="submitError"
      class="record-dialog__error mt-2"
      :title="submitError"
      type="error"
      show-icon
      :closable="false"
    />
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ schema.submitLabel }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style>
/*
 * 非 scoped：el-dialog teleport 到 body，scoped 选择器进不去。
 * 长表单（复盘有 10 个字段）在 body 内滚，不许把滚动条顶到文档级。
 */
.record-dialog .el-dialog__body {
  max-height: min(62vh, 30rem);
  overflow: auto;
}
</style>
