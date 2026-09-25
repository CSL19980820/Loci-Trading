<script setup lang="ts">
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'

import { computed, nextTick, onMounted, onUnmounted, reactive, ref, useId, watch } from 'vue'
import { RadioGroup, RadioGroupItem } from '@/shared/components/ui/radio-group'
import { FieldSet, FieldLegend, FieldLabel, FieldError } from '@/shared/components/ui/field'

import {
  formatAskAnswers,
  isMultiAsk,
  missingRequiredAnswers,
} from '../assistantConfirmFormat'
import type { AiHitlAsk, AiHitlQuestion } from '@/shared/types/ai_assistant'

const props = defineProps<{
  ask?: AiHitlAsk | null
  /** Global waiting_user without per-message hitl. */
  fallback?: boolean
}>()

const emit = defineEmits<{
  /** 选项点击 / 数字键 / 多题提交全部 = 直接提交该答复 */
  reply: [text: string]
}>()

const multi = computed(() => isMultiAsk(props.ask))
const questions = computed<AiHitlQuestion[]>(() => props.ask?.questions ?? [])
/** 操作说明不占常驻段落，挂在「?」标记的 tooltip 里 */
const interactionHint = computed(() => {
  if (multi.value) return '逐题点选或填写，再点「提交全部」；数字键作用于当前/首个未答选择题。'
  if (props.fallback && !props.ask?.prompt) return '助手已暂停。点选项或按数字键直接继续，也可在输入框回复 / 取消本轮。'
  return '点选项或按 1–9 即提交；也可在输入框改写后发送。'
})
const fieldId = useId()
const answers = reactive<Record<string, string>>({})
const focusedId = ref<string>('')
const submitError = ref('')
const root = ref<HTMLElement | null>(null)
const attempted = ref(false)
const answeredCount = computed(() => questions.value.filter(question => (answers[question.id] || '').trim()).length)
const missingIds = computed(() => attempted.value ? missingRequiredAnswers(questions.value, answers) : [])


watch(
  questions,
  (rows) => {
    for (const key of Object.keys(answers)) {
      if (!rows.some((row) => row.id === key)) delete answers[key]
    }
    for (const row of rows) {
      if (answers[row.id] === undefined) answers[row.id] = ''
    }
    if (!rows.some((row) => row.id === focusedId.value)) {
      focusedId.value = rows[0]?.id || ''
    }
    submitError.value = ''
    attempted.value = false
  },
  { immediate: true, deep: true },
)

function pick(option: string): void {
  const text = option.trim()
  if (!text) return
  emit('reply', text)
}

function setAnswer(questionId: string, value: string): void {
  answers[questionId] = value
  focusedId.value = questionId
  submitError.value = ''
}

function submitAll(): void {
  attempted.value = true
  const missing = missingRequiredAnswers(questions.value, answers)
  if (missing.length) {
    submitError.value = `请先回答：${questions.value.filter(question => missing.includes(question.id)).map(question => question.prompt).join('、')}`
    focusedId.value = missing[0] || focusedId.value
    const index = questions.value.findIndex(question => question.id === missing[0])
    void nextTick(() => root.value?.querySelectorAll('fieldset')[index]?.querySelector<HTMLElement>('[role="radio"], textarea')?.focus())
    return
  }
  emit('reply', formatAskAnswers(questions.value, answers))
}

function targetQuestionForDigit(): AiHitlQuestion | undefined {
  const rows = questions.value
  if (!rows.length) return undefined
  const focused = rows.find((row) => row.id === focusedId.value)
  if (focused?.options?.length) return focused
  return rows.find((row) => row.options?.length && !(answers[row.id] || '').trim()) || rows.find((row) => row.options?.length)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.repeat || event.isComposing || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
  const target = event.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return
  const index = Number(event.key) - 1
  if (!Number.isInteger(index) || index < 0 || index >= 9) return

  if (multi.value) {
    const question = targetQuestionForDigit()
    const option = question?.options?.[index]
    if (!question || !option) return
    event.preventDefault()
    setAnswer(question.id, option)
    return
  }

  const options = props.ask?.options
  if (!options?.length || index >= options.length) return
  const option = options[index]
  if (!option) return
  event.preventDefault()
  pick(option)
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <section
    ref="root"
    class="assistant-ask"
    data-testid="assistant-confirm"
    role="group"
    :aria-label="ask?.prompt || '等待你的确认'"
  >
    <header class="assistant-ask__head">
      <HintTooltip :content="interactionHint" placement="top">
        <span class="assistant-ask__mark" role="img" tabindex="0" :aria-label="interactionHint">?</span>
      </HintTooltip>
      <p class="assistant-ask__prompt">
        {{ ask?.prompt || (multi ? '请回答下列问题' : '等待你的确认') }}
      </p>
      <StatusBadge v-if="ask?.risk" size="small" tone="warning" effect="plain" class="assistant-ask__risk">
        {{ ask.risk }}
      </StatusBadge>
    </header>

    <div v-if="multi" class="assistant-ask__questions" data-testid="assistant-confirm-questions">
      <p class="assistant-ask__summary" role="status" aria-live="polite">已回答 {{ answeredCount }}/{{ questions.length }} · 全部必答，确认后一次提交</p>
      <FieldSet
        v-for="(question, qIndex) in questions"
        :key="question.id"
        class="assistant-ask__question"
        :data-focused="focusedId === question.id ? '1' : '0'"
        :data-invalid="missingIds.includes(question.id) || undefined"
        @click="focusedId = question.id"
        @focusin="focusedId = question.id"
      >
        <FieldLegend variant="label" class="assistant-ask__q-prompt">
          <span class="assistant-ask__q-idx">{{ qIndex + 1 }}</span>
          {{ question.prompt }}
          <span class="assistant-ask__required">必答</span>
        </FieldLegend>
        <RadioGroup
          v-if="question.options?.length"
          class="assistant-ask__rail"
          :model-value="answers[question.id]"
          :aria-label="question.prompt"
          :aria-required="!question.allow_free_text || undefined"
          :aria-invalid="missingIds.includes(question.id) || undefined"
          :aria-describedby="missingIds.includes(question.id) ? `${fieldId}-${qIndex}-error` : undefined"
          @update:model-value="setAnswer(question.id, String($event))"
        >
          <FieldLabel
            v-for="(option, index) in question.options"
            :key="`${question.id}-${index}-${option}`"
            :for="`${fieldId}-${qIndex}-${index}`"
            class="assistant-ask__chip assistant-ask__choice"
            :data-selected="answers[question.id] === option"
          >
            <RadioGroupItem :id="`${fieldId}-${qIndex}-${index}`" :value="option" />
            <span class="assistant-ask__chip-idx" aria-hidden="true">{{ index + 1 }}</span>
            {{ option }}
          </FieldLabel>
        </RadioGroup>
        <TextField
          v-if="question.allow_free_text || !question.options?.length"
          :model-value="answers[question.id]"
          @update:model-value="setAnswer(question.id, String($event))"
          :aria-label="question.prompt"
          :aria-required="!question.options?.length || undefined"
          :aria-invalid="missingIds.includes(question.id) || undefined"
          :aria-describedby="missingIds.includes(question.id) ? `${fieldId}-${qIndex}-error` : undefined"
          class="assistant-ask__free"
          size="small"
          type="textarea"
          :rows="2"
          :placeholder="question.options?.length ? '或填写补充说明' : '请输入回答'"
          @focus="focusedId = question.id"
        />
        <FieldError v-if="missingIds.includes(question.id)" :id="`${fieldId}-${qIndex}-error`">请选择或填写本题答案</FieldError>
      </FieldSet>
      <FieldError v-if="submitError" class="assistant-ask__error" data-testid="assistant-confirm-error" role="alert">
        {{ submitError }}
      </FieldError>
      <div class="assistant-ask__actions">
        <ActionButton tone="primary" data-testid="assistant-confirm-submit" @click="submitAll">
          提交全部
        </ActionButton>
      </div>
    </div>

    <div v-else-if="ask?.options?.length" class="assistant-ask__rail">
      <ActionButton
        v-for="(option, index) in ask.options"
        :key="`${index}-${option}`"
        class="assistant-ask__chip"
        size="small"
        @click="pick(option)"
      >
        <span class="assistant-ask__chip-idx" aria-hidden="true">{{ index + 1 }}</span>
        {{ option }}
      </ActionButton>
    </div>
  </section>
</template>

<style scoped>
.assistant-ask { width: 100%; min-width: 0; box-sizing: border-box; padding: var(--gap-3); border-radius: var(--ai-r-card); border: 1px solid color-mix(in oklab, var(--warn) 40%, var(--rule)); background: var(--surface); }
.assistant-ask__head { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--gap-2); min-width: 0; }
.assistant-ask__mark { flex: 0 0 auto; display: grid; place-items: center; width: var(--row-h-sm); height: var(--row-h-sm); border-radius: var(--ai-r-chip); font: 650 var(--ai-fs-body) var(--mono); color: var(--warn-ink); background: var(--warn-soft); }
.assistant-ask__mark:focus-visible, .assistant-ask :deep(button:focus-visible) { outline: 2px solid var(--seal); outline-offset: -2px; }
.assistant-ask__prompt { flex: 1; min-width: 0; margin: 0; font-size: var(--ai-fs-prose); font-weight: 600; line-height: 1.55; color: var(--ink); overflow-wrap: anywhere; }
.assistant-ask__risk { flex: 0 0 auto; }
.assistant-ask__questions { display: flex; flex-direction: column; gap: var(--gap-3); margin-top: var(--gap-3); }
.assistant-ask__question { gap: 0; min-width: 0; padding: var(--gap-2); border-radius: var(--ai-r-chip); border: 1px solid var(--rule); background: var(--surface-sunken); }
.assistant-ask__question[data-focused='1'] { border-color: var(--seal-border); }
.assistant-ask__q-prompt { margin: 0 0 var(--gap-2); font-size: var(--ai-fs-body); font-weight: 600; line-height: 1.5; color: var(--ink); overflow-wrap: anywhere; }
.assistant-ask__q-idx { display: inline-grid; place-items: center; min-width: var(--gap-4); margin-right: var(--gap-1); font: var(--ai-fs-meta) var(--mono); color: var(--mist); }
.assistant-ask__rail { display: flex; flex-wrap: wrap; gap: var(--gap-2); margin-top: var(--gap-3); }
.assistant-ask__question .assistant-ask__rail { margin-top: 0; }
.assistant-ask__chip { height: auto; min-height: var(--ctl-h); margin: 0; padding: var(--gap-2); max-width: 100%; white-space: normal; text-align: left; }
.assistant-ask__chip :deep(> span) { line-height: 1.5; overflow-wrap: anywhere; }
.assistant-ask__chip-idx { flex-shrink: 0; display: inline-grid; place-items: center; min-width: var(--gap-4); margin-right: var(--gap-2); font: var(--ai-fs-meta) var(--mono); color: var(--mist); }
.assistant-ask__choice { display: inline-flex; align-items: center; border: 1px solid var(--rule); border-radius: var(--ai-r-chip); cursor: pointer; }
.assistant-ask__choice[data-selected="true"] { border-color: var(--seal-border); background: var(--seal-soft); }
.assistant-ask__free { margin-top: var(--gap-2); }
.assistant-ask__error { margin: 0; color: var(--warn-ink); font-size: var(--ai-fs-body); }
.assistant-ask__actions { display: flex; justify-content: flex-end; }
.assistant-ask__summary { margin: 0; color: var(--mist); font-size: var(--ai-fs-aux); }
.assistant-ask__required { margin-left: var(--gap-2); color: var(--mist); font-size: var(--ai-fs-meta); font-weight: 400; }
</style>
