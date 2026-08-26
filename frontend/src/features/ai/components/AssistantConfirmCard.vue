<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

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
const answers = reactive<Record<string, string>>({})
const focusedId = ref<string>('')
const submitError = ref('')

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
  const missing = missingRequiredAnswers(questions.value, answers)
  if (missing.length) {
    submitError.value = `请先回答：${missing.join('、')}`
    focusedId.value = missing[0] || focusedId.value
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
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
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
    class="assistant-ask"
    data-testid="assistant-confirm"
    role="group"
    :aria-label="ask?.prompt || '等待你的确认'"
  >
    <header class="assistant-ask__head">
      <span class="assistant-ask__mark" aria-hidden="true">?</span>
      <div class="assistant-ask__copy">
        <p class="assistant-ask__prompt">
          {{ ask?.prompt || (multi ? '请回答下列问题' : '等待你的确认') }}
        </p>
        <p class="assistant-ask__hint">
          <template v-if="multi">
            逐题点选或填写，再点「提交全部」；数字键作用于当前/首个未答选择题。
          </template>
          <template v-else-if="fallback && !ask?.prompt">
            助手已暂停。点选项或按数字键直接继续，也可在输入框回复 / 取消本轮。
          </template>
          <template v-else>
            点选项或按 1–9 即提交；也可在输入框改写后发送。
          </template>
        </p>
      </div>
      <el-tag v-if="ask?.risk" size="small" type="danger" effect="plain" class="assistant-ask__risk">
        {{ ask.risk }}
      </el-tag>
    </header>

    <div v-if="multi" class="assistant-ask__questions" data-testid="assistant-confirm-questions">
      <article
        v-for="(question, qIndex) in questions"
        :key="question.id"
        class="assistant-ask__question"
        :data-focused="focusedId === question.id ? '1' : '0'"
        @click="focusedId = question.id"
      >
        <p class="assistant-ask__q-prompt">
          <span class="assistant-ask__q-idx">{{ qIndex + 1 }}</span>
          {{ question.prompt }}
        </p>
        <div v-if="question.options?.length" class="assistant-ask__rail">
          <el-button
            v-for="(option, index) in question.options"
            :key="`${question.id}-${index}-${option}`"
            class="assistant-ask__chip"
            size="small"
            :type="answers[question.id] === option ? 'primary' : 'default'"
            @click="setAnswer(question.id, option)"
          >
            <span class="assistant-ask__chip-idx" aria-hidden="true">{{ index + 1 }}</span>
            {{ option }}
          </el-button>
        </div>
        <el-input
          v-if="question.allow_free_text || !question.options?.length"
          v-model="answers[question.id]"
          class="assistant-ask__free"
          size="small"
          type="textarea"
          :rows="2"
          :placeholder="question.options?.length ? '或填写补充说明' : '请输入回答'"
          @focus="focusedId = question.id"
        />
      </article>
      <p v-if="submitError" class="assistant-ask__error" data-testid="assistant-confirm-error" role="alert">
        {{ submitError }}
      </p>
      <div class="assistant-ask__actions">
        <el-button type="primary" data-testid="assistant-confirm-submit" @click="submitAll">
          提交全部
        </el-button>
      </div>
    </div>

    <div v-else-if="ask?.options?.length" class="assistant-ask__rail">
      <el-button
        v-for="(option, index) in ask.options"
        :key="`${index}-${option}`"
        class="assistant-ask__chip"
        size="small"
        @click="pick(option)"
      >
        <span class="assistant-ask__chip-idx" aria-hidden="true">{{ index + 1 }}</span>
        {{ option }}
      </el-button>
    </div>
  </section>
</template>

<style scoped>
/* 交易台「抉择票」：冷灰底 + 琥珀问号，避开 cream/serif 与酸绿黑底默认套路 */
.assistant-ask {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: .7rem .85rem .75rem;
  border-radius: var(--ai-r-card);
  border: 1px solid color-mix(in srgb, var(--warn) 35%, var(--rule));
  background:
    linear-gradient(
      135deg,
      color-mix(in srgb, var(--warn) 8%, transparent) 0%,
      transparent 42%
    ),
    var(--sheet);
}
.assistant-ask__head {
  display: flex;
  align-items: flex-start;
  gap: .65rem;
  min-width: 0;
}
.assistant-ask__mark {
  flex: 0 0 auto;
  width: 1.55rem;
  height: 1.55rem;
  display: grid;
  place-items: center;
  border-radius: var(--ai-r-card);
  font-family: var(--mono);
  font-size: var(--ai-fs-title);
  font-weight: 700;
  color: var(--sheet);
  background: var(--warn);
  line-height: 1;
}
.assistant-ask__copy {
  flex: 1 1 auto;
  min-width: 0;
}
.assistant-ask__prompt {
  margin: 0;
  font-size: var(--ai-fs-body);
  font-weight: 600;
  line-height: 1.4;
  color: var(--ink);
  letter-spacing: .01em;
}
.assistant-ask__hint {
  margin: .28rem 0 0;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  line-height: 1.45;
}
.assistant-ask__risk {
  flex: 0 0 auto;
  margin-top: .1rem;
}
.assistant-ask__questions {
  display: flex;
  flex-direction: column;
  gap: .7rem;
  margin-top: .7rem;
}
.assistant-ask__question {
  padding: .55rem .6rem;
  border-radius: var(--ai-r-card);
  border: 1px solid color-mix(in srgb, var(--rule) 80%, transparent);
  background: color-mix(in srgb, var(--sheet) 55%, transparent);
}
.assistant-ask__question[data-focused='1'] {
  border-color: color-mix(in srgb, var(--warn) 45%, var(--rule));
}
.assistant-ask__q-prompt {
  margin: 0 0 .45rem;
  font-size: var(--ai-fs-body);
  font-weight: 600;
  line-height: 1.4;
  color: var(--ink);
}
.assistant-ask__q-idx {
  display: inline-grid;
  place-items: center;
  min-width: 1.1rem;
  margin-right: .35rem;
  padding: 0 .2rem;
  border-radius: var(--ai-r-chip);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  font-weight: 700;
  color: var(--sheet);
  background: var(--warn);
}
.assistant-ask__rail {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin-top: .65rem;
}
.assistant-ask__question .assistant-ask__rail {
  margin-top: 0;
}
.assistant-ask__chip {
  --el-button-bg-color: color-mix(in srgb, var(--sheet) 70%, transparent);
  --el-button-border-color: color-mix(in srgb, var(--warn) 40%, var(--rule));
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: color-mix(in srgb, var(--warn) 18%, var(--sheet));
  --el-button-hover-border-color: var(--warn);
  --el-button-hover-text-color: var(--ink);
  font-weight: 500;
}
.assistant-ask__chip-idx {
  display: inline-grid;
  place-items: center;
  min-width: .95rem;
  margin-right: .35rem;
  padding: 0 .15rem;
  border-radius: var(--ai-r-chip);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  font-weight: 700;
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 16%, transparent);
}
.assistant-ask__free {
  margin-top: .45rem;
}
.assistant-ask__error {
  margin: 0;
  color: var(--loss);
  font-size: var(--ai-fs-aux);
}
.assistant-ask__actions {
  display: flex;
  justify-content: flex-end;
}
@media (prefers-reduced-motion: no-preference) {
  .assistant-ask {
    animation: assistant-ask-in .28s ease-out;
  }
}
@keyframes assistant-ask-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
