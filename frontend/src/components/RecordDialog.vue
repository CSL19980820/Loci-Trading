<template>
  <dialog ref="dialog" class="trade-dialog" :aria-labelledby="titleId" @close="model = false">
    <form class="trade-form" method="dialog" @submit.prevent="submit">
      <div class="dialog-heading">
        <h2 :id="titleId">{{ schema.title }}</h2>
        <button class="icon-button" type="button" aria-label="关闭" @click="close">×</button>
      </div>

      <p v-if="schema.hint" class="form-hint">{{ schema.hint }}</p>

      <fieldset>
        <label v-for="field in inlineFields" :key="field.key">
          {{ field.label }}
          <select v-if="field.type === 'select'" v-model="form[field.key]">
            <option v-for="option in field.options" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input
            v-else
            v-model="form[field.key]"
            :type="field.type"
            :required="field.required"
            :min="field.min"
            :max="field.max"
            :step="field.step"
            :maxlength="field.maxlength"
            :pattern="field.pattern"
            :inputmode="field.inputmode"
            :placeholder="field.placeholder"
          />
        </label>
      </fieldset>

      <label v-for="field in blockFields" :key="field.key" class="wide-label">
        {{ field.label }}
        <textarea
          :value="String(form[field.key] ?? '')"
          :rows="field.rows ?? 2"
          :required="field.required"
          @input="onInput(field.key, $event)"
        />
      </label>

      <p v-if="submitError" class="form-error" role="alert">{{ submitError }}</p>
      <div class="dialog-actions">
        <button class="quiet-button" type="button" @click="close">取消</button>
        <button class="primary-button" type="submit" :disabled="submitting">
          {{ submitting ? '…' : '写入' }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import {
  createCandidate,
  createCashflow,
  createPlan,
  createReview,
  createSnapshot,
} from '@/api/palace'

/** 五类录入此前后端都有接口、前端一个按钮都没有——这是"线上只能看不能记"的根因。
 *
 * 用一个 schema 驱动的对话框而不是五个几乎一样的组件：字段差异都在数据里，
 * 加一类录入只需要多一份 schema，不必再复制一遍弹窗、校验和提交逻辑。
 */
export type RecordKind = 'candidate' | 'plan' | 'review' | 'snapshot' | 'cashflow'

interface FieldSpec {
  key: string
  label: string
  type: 'text' | 'number' | 'date' | 'select' | 'textarea'
  required?: boolean
  min?: number
  max?: number
  step?: number
  maxlength?: number
  pattern?: string
  inputmode?: 'text' | 'numeric' | 'decimal' | 'tel'
  placeholder?: string
  rows?: number
  options?: { value: string; label: string }[]
  default?: string | number
}

interface SchemaSpec {
  title: string
  hint?: string
  fields: FieldSpec[]
  submit: (values: Record<string, unknown>) => Promise<{ id: string }>
}

const today = (): string => new Date().toISOString().slice(0, 10)

const CODE_FIELD: FieldSpec = {
  key: 'code',
  label: '代码',
  type: 'text',
  required: true,
  pattern: '\\d{6}',
  maxlength: 6,
  inputmode: 'numeric',
}

const SCHEMAS: Record<RecordKind, SchemaSpec> = {
  candidate: {
    title: '记候选',
    hint: '同日同池同标的会覆盖上一次裁决，改判直接再记一次即可。',
    fields: [
      CODE_FIELD,
      { key: 'name', label: '名称', type: 'text' },
      { key: 'decision', label: '裁决', type: 'text', required: true, placeholder: '精选 / 观察 / 剔除' },
      { key: 'score', label: '评分', type: 'number', min: 0, max: 100, step: 1 },
      { key: 'timing', label: '时点', type: 'text', placeholder: '竞价 / 尾盘' },
      { key: 'pool_id', label: '池', type: 'text', placeholder: '默认按日期归池' },
      { key: 'occurred_on', label: '日期', type: 'date', default: today() },
      { key: 'reason', label: '理由', type: 'textarea', required: true, rows: 3 },
    ],
    submit: (values) =>
      createCandidate({
        code: String(values.code),
        name: String(values.name ?? ''),
        decision: String(values.decision),
        reason: String(values.reason),
        score: values.score === '' || values.score === undefined ? null : Number(values.score),
        timing: String(values.timing ?? ''),
        pool_id: String(values.pool_id ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
      }),
  },
  plan: {
    title: '写预案',
    hint: '止损、止盈、分批层数事后可以逐条核对是否兑现，填得越具体复盘越有效。',
    fields: [
      CODE_FIELD,
      { key: 'title', label: '标题', type: 'text', required: true },
      { key: 'entry_zone', label: '买点区间', type: 'text', placeholder: '如 12.30-12.80' },
      { key: 'stop_price', label: '止损价', type: 'number', min: 0, step: 0.001 },
      { key: 'target_price', label: '目标价', type: 'number', min: 0, step: 0.001 },
      { key: 'layers', label: '分批层数', type: 'number', min: 1, max: 10, step: 1 },
      { key: 'occurred_on', label: '日期', type: 'date', default: today() },
      { key: 'scenario', label: '情景', type: 'textarea', required: true, rows: 3 },
      { key: 'invalidation', label: '失效条件', type: 'textarea', rows: 2 },
    ],
    submit: (values) =>
      createPlan({
        code: String(values.code),
        title: String(values.title),
        scenario: String(values.scenario),
        entry_zone: String(values.entry_zone ?? ''),
        stop_price: values.stop_price === '' || values.stop_price === undefined ? null : Number(values.stop_price),
        target_price:
          values.target_price === '' || values.target_price === undefined ? null : Number(values.target_price),
        layers: values.layers === '' || values.layers === undefined ? null : Number(values.layers),
        invalidation: String(values.invalidation ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
      }),
  },
  review: {
    title: '写复盘',
    hint: 'MFE / MAE 是持有期内的最大浮盈与最大浮亏，回测引擎能算出来，这里先手填。',
    fields: [
      {
        key: 'entity_type',
        label: '对象',
        type: 'select',
        default: 'trade',
        options: [
          { value: 'trade', label: '成交' },
          { value: 'candidate', label: '候选' },
          { value: 'plan', label: '预案' },
        ],
      },
      { key: 'entity_id', label: '对象 ID', type: 'text', required: true, placeholder: 'TX-… / CA-… / PL-…' },
      { key: 'strategy_tag', label: '战法', type: 'text', default: 'qianlong' },
      { key: 'return_pct', label: '收益 %', type: 'number', step: 0.01 },
      { key: 'max_favorable_pct', label: 'MFE %', type: 'number', step: 0.01 },
      { key: 'max_adverse_pct', label: 'MAE %', type: 'number', step: 0.01 },
      { key: 'reviewed_on', label: '日期', type: 'date', default: today() },
      { key: 'outcome', label: '结果', type: 'textarea', required: true, rows: 3 },
      { key: 'lesson', label: '教训', type: 'textarea', rows: 2 },
      { key: 'next_rule', label: '下次规则', type: 'textarea', rows: 2 },
    ],
    submit: (values) =>
      createReview({
        entity_type: values.entity_type as 'plan' | 'candidate' | 'trade',
        entity_id: String(values.entity_id),
        outcome: String(values.outcome),
        strategy_tag: String(values.strategy_tag ?? 'qianlong'),
        return_pct: numberOrNull(values.return_pct),
        max_favorable_pct: numberOrNull(values.max_favorable_pct),
        max_adverse_pct: numberOrNull(values.max_adverse_pct),
        lesson: String(values.lesson ?? ''),
        next_rule: String(values.next_rule ?? ''),
        reviewed_on: String(values.reviewed_on ?? '') || null,
      }),
  },
  snapshot: {
    title: '记资产快照',
    hint: '总资产快照是"持仓占比"和真实资金曲线的锚点，缺了它曲线只能靠估算。',
    fields: [
      { key: 'total_assets', label: '总资产', type: 'number', required: true, min: 0, step: 0.01 },
      { key: 'cash', label: '可用现金', type: 'number', min: 0, step: 0.01 },
      { key: 'occurred_on', label: '日期', type: 'date', default: today() },
      { key: 'note', label: '备注', type: 'textarea', rows: 2 },
    ],
    submit: (values) =>
      createSnapshot({
        total_assets: Number(values.total_assets),
        cash: numberOrNull(values.cash),
        note: String(values.note ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
      }),
  },
  cashflow: {
    title: '记出入金',
    hint: '出入金不计入已实现盈亏，只影响本金口径——不记的话收益率会算错。',
    fields: [
      { key: 'amount', label: '金额', type: 'number', required: true, step: 0.01, placeholder: '入金为正，出金为负' },
      { key: 'occurred_on', label: '日期', type: 'date', default: today() },
      { key: 'note', label: '备注', type: 'textarea', rows: 2 },
    ],
    submit: (values) =>
      createCashflow({
        amount: Number(values.amount),
        note: String(values.note ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
      }),
  },
}

function onInput(key: string, event: Event): void {
  form[key] = (event.target as HTMLTextAreaElement).value
}

function numberOrNull(value: unknown): number | null {
  if (value === '' || value === undefined || value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const props = defineProps<{ kind: RecordKind }>()
const model = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [id: string] }>()

const dialog = ref<HTMLDialogElement>()
const submitting = ref(false)
const submitError = ref('')
const form = reactive<Record<string, unknown>>({})

const schema = computed(() => SCHEMAS[props.kind])
const titleId = computed(() => `record-${props.kind}-title`)
const inlineFields = computed(() => schema.value.fields.filter((f) => f.type !== 'textarea'))
const blockFields = computed(() => schema.value.fields.filter((f) => f.type === 'textarea'))

function reset(): void {
  for (const key of Object.keys(form)) delete form[key]
  for (const field of schema.value.fields) {
    form[field.key] = field.default ?? ''
  }
  submitError.value = ''
}

watch(
  () => [model.value, props.kind] as const,
  ([isOpen]) => {
    if (isOpen) {
      reset()
      if (dialog.value && !dialog.value.open) dialog.value.showModal()
    } else if (dialog.value?.open) {
      dialog.value.close()
    }
  },
  { immediate: true },
)

function close(): void {
  model.value = false
}

async function submit(): Promise<void> {
  const missing = schema.value.fields.find(
    (field) => field.required && !String(form[field.key] ?? '').trim(),
  )
  if (missing) {
    submitError.value = `请填写「${missing.label}」`
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    const { id } = await schema.value.submit({ ...form })
    emit('saved', id)
    close()
  } catch (caught: unknown) {
    submitError.value = caught instanceof Error ? caught.message : '写入失败'
  } finally {
    submitting.value = false
  }
}
</script>
