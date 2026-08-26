<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { createCandidate, createPlan, createReview } from '@/shared/api/palace'
import { dialogWidth, localToday } from '@/shared/lib/format'

export type RecordKind = 'candidate' | 'plan' | 'review'

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

const today = (): string => localToday()

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
      {
        key: 'decision',
        label: '裁决',
        type: 'select',
        required: true,
        default: '精选',
        options: [
          { value: '精选', label: '精选' },
          { value: '观察', label: '观察' },
          { value: '落选', label: '落选' },
        ],
      },
      { key: 'score', label: '评分', type: 'number', min: 0, max: 100, step: 1 },
      { key: 'timing', label: '时点', type: 'text', placeholder: '尾盘 / 低吸 / 平开 / 高开回踩 / 观望' },
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
        score: values.score === '' || values.score === undefined || values.score === null ? null : Number(values.score),
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
        stop_price: values.stop_price === '' || values.stop_price === undefined || values.stop_price === null ? null : Number(values.stop_price),
        target_price:
          values.target_price === '' || values.target_price === undefined || values.target_price === null ? null : Number(values.target_price),
        layers: values.layers === '' || values.layers === undefined || values.layers === null ? null : Number(values.layers),
        invalidation: String(values.invalidation ?? ''),
        occurred_on: String(values.occurred_on ?? '') || null,
      }),
  },
  review: {
    title: '写复盘',
    hint: '最高浮盈 / 最深浮亏看持有期内曾经到过的最好与最差；对象 ID 可后补。',
    fields: [
      {
        key: 'entity_type',
        label: '对象',
        type: 'select',
        default: 'candidate',
        options: [
          { value: 'candidate', label: '候选' },
          { value: 'plan', label: '预案' },
        ],
      },
      { key: 'entity_id', label: '对象 ID（可选）', type: 'text', placeholder: 'CA-… / PL-…' },
      { key: 'strategy_tag', label: '战法', type: 'text', required: true, placeholder: '如 qianlong-close-v3 / sanyuan-tail-v1' },
      { key: 'return_pct', label: '收益 %', type: 'number', step: 0.01 },
      { key: 'max_favorable_pct', label: '最高浮盈 %', type: 'number', step: 0.01 },
      { key: 'max_adverse_pct', label: '最深浮亏 %', type: 'number', step: 0.01 },
      { key: 'reviewed_on', label: '日期', type: 'date', default: today() },
      { key: 'outcome', label: '结果', type: 'textarea', required: true, rows: 3 },
      { key: 'lesson', label: '教训', type: 'textarea', rows: 2 },
      { key: 'next_rule', label: '下次规则', type: 'textarea', rows: 2 },
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

const submitting = ref(false)
const submitError = ref('')
const form = reactive<Record<string, unknown>>({})
const width = computed(() => dialogWidth())

const schema = computed(() => SCHEMAS[props.kind])
const inlineFields = computed(() => schema.value.fields.filter((f) => f.type !== 'textarea'))
const blockFields = computed(() => schema.value.fields.filter((f) => f.type === 'textarea'))

function reset(): void {
  for (const key of Object.keys(form)) delete form[key]
  for (const field of schema.value.fields) {
    form[field.key] = field.default ?? (field.type === 'number' ? undefined : '')
  }
  if (props.presetCode) form.code = props.presetCode
  if (props.presetName) form.name = props.presetName
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
  const missing = schema.value.fields.find(
    (field) => field.required && (form[field.key] === undefined || form[field.key] === null || !String(form[field.key]).trim()),
  )
  if (missing) {
    submitError.value = `请填写「${missing.label}」`
    return
  }
  const badCode = schema.value.fields.find(
    (field) => field.pattern === '\\d{6}' && !/^\d{6}$/.test(String(form[field.key] ?? '').trim()),
  )
  if (badCode) {
    submitError.value = `「${badCode.label}」须为 6 位数字`
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

<template>
  <el-dialog
    v-model="model"
    :title="schema.title"
    :width="width"
    destroy-on-close
    @closed="submitError = ''"
  >
    <p v-if="schema.hint" class="form-hint">{{ schema.hint }}</p>
    <el-form label-position="top" @submit.prevent="submit">
      <div class="form-grid">
        <el-form-item
          v-for="field in inlineFields"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <el-select v-if="field.type === 'select'" v-model="form[field.key]" class="full">
            <el-option
              v-for="option in field.options"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-date-picker
            v-else-if="field.type === 'date'"
            v-model="form[field.key]"
            type="date"
            value-format="YYYY-MM-DD"
            class="full"
          />
          <el-input-number
            v-else-if="field.type === 'number'"
            v-model="form[field.key]"
            :min="field.min"
            :max="field.max"
            :step="field.step ?? 1"
            :controls="false"
            class="full"
          />
          <el-input
            v-else
            v-model="form[field.key]"
            :maxlength="field.maxlength"
            :placeholder="field.placeholder"
            :inputmode="field.inputmode"
          />
        </el-form-item>
      </div>
      <el-form-item
        v-for="field in blockFields"
        :key="field.key"
        :label="field.label"
        :required="field.required"
      >
        <el-input
          v-model="form[field.key]"
          type="textarea"
          :rows="field.rows ?? 2"
          :placeholder="field.placeholder"
        />
      </el-form-item>
      <el-alert v-if="submitError" :title="submitError" type="error" show-icon :closable="false" />
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">写入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-hint {
  margin: 0 0 0.75rem;
  color: var(--mist);
  font-size: 0.82rem;
  line-height: 1.5;
}
</style>
