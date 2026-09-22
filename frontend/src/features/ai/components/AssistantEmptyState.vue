<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { ArrowUpRight } from '@lucide/vue'

export type AssistantPromptCard = {
  id: string
  title: string
  hint: string
  prompt: string
}

/**
 * 空态（ChatGPT / Claude 首屏一路）：居中品牌盘 + 一句问候 + 一排可点的建议 chip。
 * chip 只填草稿不直接发送；忙态 / 未配模型时置灰。
 */
withDefaults(defineProps<{
  prompts: AssistantPromptCard[]
  /** 忙态 / 未配模型时父级会静默丢弃 pick，按钮同步置灰而不是点了没反应 */
  busy?: boolean
  providerReady?: boolean
}>(), {
  busy: false,
  providerReady: true,
})

const emit = defineEmits<{ pick: [prompt: string] }>()
</script>

<template>
  <div class="assistant-empty" data-testid="assistant-empty">
    <div class="assistant-empty__hero">
      <span class="assistant-empty__disc" aria-hidden="true">LC</span>
      <h3 class="assistant-empty__title">今天想做什么？</h3>
      <p class="assistant-empty__sub">记交割、看持仓、跑选股、查行情同步——直接说，或从下面挑一个开始。</p>
    </div>
    <ul class="assistant-empty__chips" aria-label="提问示例">
      <li v-for="card in prompts" :key="card.id">
        <Item as="button" v-if="!visitor"
          type="button"
          class="assistant-empty__chip"
          :disabled="busy || !providerReady"
          :aria-label="card.title"
          :title="'填入输入框：' + card.hint"
          @click="emit('pick', card.prompt)"
        >
          <span class="assistant-empty__chip-title">{{ card.title }}</span>
          <span class="assistant-empty__chip-hint">{{ card.hint }}</span>
          <ArrowUpRight class="assistant-empty__chip-arrow" aria-hidden="true" />
        </Item>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.assistant-empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: safe center;
  gap: var(--gap-5);
  min-width: 0;
  min-height: 0;
  padding-block: var(--gap-6);
  overflow: auto;
  scrollbar-width: thin;
}

.assistant-empty__hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-2);
  max-width: 32rem;
  text-align: center;
}

.assistant-empty__disc {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin-bottom: var(--gap-2);
  border-radius: 50%;
  background: linear-gradient(160deg, color-mix(in oklab, var(--seal) 90%, white), var(--seal-hover));
  color: var(--on-primary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 700;
  letter-spacing: 0.04em;
  box-shadow:
    var(--shadow-inset-highlight),
    0 10px 28px -10px color-mix(in oklab, var(--seal) 60%, transparent);
}

.assistant-empty__title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-hero);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.assistant-empty__sub {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-ui);
  line-height: 1.6;
}

.assistant-empty__chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-2);
  width: min(100%, 40rem);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assistant-empty__chips li {
  min-width: 0;
}

.assistant-empty__chip {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  min-height: 56px;
  padding: 10px 34px 10px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition:
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.assistant-empty__chip:hover:not(:disabled) {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.assistant-empty__chip:active:not(:disabled) {
  transform: none;
}

.assistant-empty__chip:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.assistant-empty__chip:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.assistant-empty__chip-title {
  font-size: var(--fs-ui);
  font-weight: 600;
  line-height: 1.4;
}

.assistant-empty__chip-hint {
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.4;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-empty__chip-arrow {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.assistant-empty__chip:hover .assistant-empty__chip-arrow {
  opacity: 1;
}

@container (max-width: 480px) {
  .assistant-empty__chips {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 640px) {
  .assistant-empty__chips {
    grid-template-columns: minmax(0, 1fr);
  }

  .assistant-empty__chip {
    min-height: 52px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-empty__chip {
    transition: none;
  }
}
</style>
