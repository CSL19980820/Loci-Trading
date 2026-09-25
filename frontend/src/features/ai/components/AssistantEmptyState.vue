<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { computed, type Component } from 'vue'
import { ArrowUpRight, Database, History, Lightbulb, MessageSquare, Radar, Receipt, Sparkles, Wallet } from '@lucide/vue'

export type AssistantPromptCard = {
  id: string
  title: string
  hint: string
  prompt: string
}

/**
 * 空态：品牌盘 + 按时段的问候 + 一组可点的起手卡（图标 + 标题 + 一行示例）。
 * 卡片只填草稿不直接发送；忙态 / 未配模型时置灰。
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

const ICONS: Record<string, Component> = {
  'settle-today': Receipt,
  'settle-yesterday': History,
  positions: Wallet,
  screen: Radar,
  strategy: Lightbulb,
  market: Database,
}

function iconOf(id: string): Component {
  return ICONS[id] ?? MessageSquare
}

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 13) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
</script>

<template>
  <div class="assistant-empty" data-testid="assistant-empty">
    <div class="assistant-empty__hero">
      <span class="assistant-empty__disc" aria-hidden="true"><Sparkles /></span>
      <h3 class="assistant-empty__title">{{ greeting }}，今天想做什么？</h3>
    </div>
    <ul class="assistant-empty__chips" aria-label="提问示例">
      <li v-for="card in prompts" :key="card.id">
        <Item as="button" v-if="!visitor"
          type="button"
          class="assistant-empty__chip"
          :disabled="busy || !providerReady"
          :aria-label="card.title"
          @click="emit('pick', card.prompt)"
        >
          <span class="assistant-empty__chip-icon" aria-hidden="true"><component :is="iconOf(card.id)" /></span>
          <span class="assistant-empty__chip-text">
            <span class="assistant-empty__chip-title">{{ card.title }}</span>
            <span class="assistant-empty__chip-hint">{{ card.hint }}</span>
          </span>
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
  gap: 28px;
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
  gap: 14px;
  max-width: 32rem;
  text-align: center;
}

.assistant-empty__disc {
  position: relative;
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 18px;
  background: var(--ai-disc-face);
  color: var(--ai-disc-ribbon);
  box-shadow:
    inset 0 0 0 1px var(--ai-disc-edge),
    0 18px 40px -16px color-mix(in oklab, var(--seal) 70%, transparent);
}

.assistant-empty__disc::before {
  content: '';
  position: absolute;
  inset: -18px;
  z-index: -1;
  border-radius: 50%;
  background: radial-gradient(closest-side, color-mix(in oklab, var(--seal) 22%, transparent), transparent);
}

.assistant-empty__disc svg {
  width: 24px;
  height: 24px;
}

.assistant-empty__title {
  margin: 0;
  color: var(--text-primary);
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.assistant-empty__chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
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
  flex-direction: row;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 60px;
  padding: 10px 32px 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: color-mix(in oklab, var(--surface-raised) 70%, transparent);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.assistant-empty__chip:hover:not(:disabled) {
  border-color: var(--seal-border);
  background: color-mix(in oklab, var(--seal) 5%, var(--surface-raised));
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

.assistant-empty__chip-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.assistant-empty__chip-icon svg {
  width: 16px;
  height: 16px;
}

.assistant-empty__chip-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
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
  top: 50%;
  right: 12px;
  width: 14px;
  height: 14px;
  margin-top: -7px;
  color: var(--seal-ink);
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
    min-height: 54px;
  }

  .assistant-empty__title {
    font-size: 19px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-empty__chip {
    transition: none;
  }
}
</style>
