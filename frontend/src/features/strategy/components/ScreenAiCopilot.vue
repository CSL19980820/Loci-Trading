<script setup lang="ts">
/**
 * AI 编写：一句话描述选股思路 → 生成完整策稿（公式、参数、逻辑脉络、数据字段）。
 * 已有草稿时同一个入口就是「改写」。⌘/Ctrl + Enter 直接生成。
 */
import { computed, nextTick, ref } from 'vue'
import { ArrowUp, BookOpen, MessageCircle, Sparkles } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Spinner } from '@/shared/components/ui/spinner'
import { Textarea } from '@/shared/components/ui/textarea'
import { THINKING_OPTIONS, type LlmModelOption } from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

const props = withDefaults(
  defineProps<{
    instruction: string
    provider: string
    model: string
    thinking: string
    providers: LlmProvider[]
    providerModels: LlmModelOption[]
    /** 资料来源没有半填的错行（可以为空：为空时以需求原话为来源） */
    referencesReady: boolean
    referenceCount?: number
    busy?: boolean
    compact?: boolean
    /** 当前是空白 / 起手草稿：生成即新建，否则是改写 */
    fresh?: boolean
  }>(),
  { busy: false, compact: false, fresh: false, referenceCount: 0 },
)

const emit = defineEmits<{
  'update:instruction': [value: string]
  'update:provider': [value: string]
  'update:model': [value: string]
  'update:thinking': [value: string]
  generate: []
  'open-assistant': []
  'manage-references': []
}>()

const FRESH_IDEAS = [
  '放量突破 20 日均线，换手率 3%–15%',
  '均线多头排列 5>10>20>60，回踩 10 日线不破',
  'MACD 零轴上方金叉且当日收阳',
  '60 日新低后连续 3 天收阳放量',
  '涨停后缩量回调到 5 日线附近',
  '布林带收口后放量突破上轨',
]

const REVISE_IDEAS = [
  '加入换手率 3%–15% 过滤',
  '只保留成交额大于 2 亿的股票',
  '收紧为连续 2 天满足条件',
  '参数 N 改成可调的 10–60',
]

const ideas = computed(() => (props.fresh ? FRESH_IDEAS : REVISE_IDEAS))
const field = ref<InstanceType<typeof Textarea> | null>(null)
const canGenerate = computed(() =>
  Boolean(props.instruction.trim().length >= 4 && props.provider && props.referencesReady),
)

/** 「不启思考」的空串在 Select 里会与「未选择」撞车，用 off 哨兵代一层。 */
const thinkingModel = computed({
  get: () => props.thinking || 'off',
  set: (value: string) => emit('update:thinking', value === 'off' ? '' : value),
})

const providerModel = computed({
  get: () => props.provider,
  set: (value: string) => emit('update:provider', String(value || '')),
})

const modelListId = 'screen-ai-copilot-models'

function useIdea(text: string): void {
  const current = props.instruction.trim()
  emit('update:instruction', current ? `${current}；${text}` : text)
  void nextTick(() => {
    const el = (field.value as unknown as { $el?: HTMLElement } | null)?.$el
    const target = el instanceof HTMLTextAreaElement ? el : el?.querySelector?.('textarea')
    target?.focus()
  })
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey)) return
  event.preventDefault()
  if (canGenerate.value && !props.busy) emit('generate')
}
</script>

<template>
  <section class="ai" :class="{ 'is-busy': busy }" aria-label="AI 编写">
    <header class="ai__head">
      <span class="ai__mark" aria-hidden="true"><Sparkles /></span>
      <strong class="ai__title">AI 编写</strong>
      <span class="ai__mode">{{ fresh ? '新建' : '改写' }}</span>
    </header>

    <div class="ai__box">
      <Textarea
        ref="field"
        :model-value="instruction"
        :rows="compact ? 6 : 5"
        maxlength="1200"
        :placeholder="fresh ? '描述选股思路…' : '描述要改的地方…'"
        aria-label="给 AI 的编写要求"
        class="ai__input"
        :disabled="busy"
        @update:model-value="(value) => emit('update:instruction', String(value))"
        @keydown="onKeydown"
      />
      <div class="ai__bar">
        <Select v-model="providerModel">
          <SelectTrigger size="sm" class="ai__provider" aria-label="AI 供应商">
            <SelectValue placeholder="供应商" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="item in providers" :key="item.name" :value="item.name">
              {{ item.name }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="thinkingModel">
          <SelectTrigger size="sm" class="ai__thinking" aria-label="思考程度">
            <SelectValue placeholder="思考" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="item in THINKING_OPTIONS"
              :key="item.value || 'off'"
              :value="item.value || 'off'"
            >
              {{ item.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="ai__count">{{ instruction.length }}/1200</span>
        <Button
          size="icon-sm"
          class="ai__send"
          :disabled="!canGenerate || busy"
          :aria-label="fresh ? '生成策稿' : '按要求改写'"
          @click="emit('generate')"
        >
          <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
          <ArrowUp v-else aria-hidden="true" />
        </Button>
      </div>
    </div>

    <details v-if="!compact || providerModels.length" class="ai__model">
      <summary>模型</summary>
      <Input
        :model-value="model"
        :list="modelListId"
        size="sm"
        placeholder="供应商默认"
        aria-label="AI 模型"
        @update:model-value="(value) => emit('update:model', String(value || ''))"
      />
      <datalist :id="modelListId">
        <option v-for="item in providerModels" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </datalist>
    </details>

    <div class="ai__ideas" role="list" aria-label="思路">
      <button
        v-for="idea in ideas"
        :key="idea"
        type="button"
        role="listitem"
        class="ai__idea"
        :disabled="busy"
        @click="useIdea(idea)"
      >
        {{ idea }}
      </button>
    </div>

    <footer class="ai__foot">
      <Button variant="ghost" size="xs" :class="{ 'is-warn': !referencesReady }" @click="emit('manage-references')">
        <BookOpen aria-hidden="true" />
        资料 {{ referenceCount }}
      </Button>
      <Button variant="ghost" size="xs" @click="emit('open-assistant')">
        <MessageCircle aria-hidden="true" />
        在助手中继续
      </Button>
    </footer>
  </section>
</template>

<style scoped>
.ai {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  height: 100%;
  padding: 14px;
  background:
    radial-gradient(120% 60% at 100% 0%, color-mix(in oklab, var(--seal) 9%, transparent), transparent 70%),
    var(--surface);
}

.ai__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai__mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: linear-gradient(145deg, color-mix(in oklab, var(--seal) 88%, white), var(--seal-active));
  color: var(--on-primary);
  box-shadow: var(--shadow-inset-highlight), 0 6px 16px -8px color-mix(in oklab, var(--seal) 70%, transparent);
}

.ai__mark svg {
  width: 14px;
  height: 14px;
}

.ai.is-busy .ai__mark {
  animation: ai-breathe 1.6s ease-in-out infinite;
}

.ai__title {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 650;
  letter-spacing: -0.01em;
}

.ai__mode {
  margin-left: auto;
  padding: 0 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--fs-kicker);
  font-weight: 600;
  line-height: 20px;
}

.ai__box {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  background: var(--surface-raised);
  box-shadow: var(--shadow-sm);
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.ai__box:focus-within {
  border-color: var(--focus-ring);
  box-shadow: 0 0 0 3px var(--focus-halo), var(--shadow-sm);
}

.ai__input {
  min-height: 112px;
  padding: 12px 14px 4px;
  border: 0;
  background: transparent;
  box-shadow: none;
  font-size: var(--fs-body);
  line-height: 1.65;
  resize: none;
}

.ai__input:focus-visible {
  box-shadow: none;
  outline: none;
}

.ai__bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 8px;
}

.ai__provider {
  width: auto;
  min-width: 0;
  max-width: 9rem;
  border-color: transparent;
  background: var(--surface-sunken);
  box-shadow: none;
}

.ai__thinking {
  width: auto;
  min-width: 0;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}

.ai__count {
  margin-left: auto;
  color: var(--text-disabled);
  font: var(--fs-micro) / 1 var(--mono);
}

.ai__send {
  border-radius: var(--radius-pill);
}

.ai__model {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.ai__model summary {
  width: fit-content;
  cursor: pointer;
  list-style: none;
}

.ai__model summary::before {
  content: '＋ ';
}

.ai__model[open] summary::before {
  content: '－ ';
}

.ai__model > :not(summary) {
  margin-top: 6px;
}

.ai__ideas {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ai__idea {
  max-width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}

.ai__idea:hover:not(:disabled) {
  border-color: var(--seal-border);
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.ai__idea:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}

.ai__idea:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.ai__foot {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.ai__foot :deep(.is-warn) {
  color: var(--warn-ink);
}

@keyframes ai-breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(0.9); }
}

@media (prefers-reduced-motion: reduce) {
  .ai.is-busy .ai__mark { animation: none; }
}
</style>
