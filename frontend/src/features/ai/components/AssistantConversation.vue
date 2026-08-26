<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import {
  messagePlainText,
  previousUserMessage,
} from '../assistantMessageActions'
import type { AiMessage, AiAgentProgress } from '@/shared/types/ai_assistant'
import AssistantConfirmCard from './AssistantConfirmCard.vue'
import AssistantTurnTimeline from './AssistantTurnTimeline.vue'

const props = defineProps<{
  messages: AiMessage[]
  busy?: boolean
  waitingUser?: boolean
  agents?: AiAgentProgress[]
}>()
const emit = defineEmits<{
  'confirm-reply': [text: string]
  'open-agent': [agentId: string]
  copy: [text: string]
  rerun: [payload: { text: string; images?: string[] }]
}>()

const actionsDisabled = computed(() => Boolean(props.busy || props.waitingUser))

function onRerun(message: AiMessage): void {
  if (actionsDisabled.value) return
  const source = message.role === 'user'
    ? message
    : previousUserMessage(props.messages, message.id)
  if (!source) return
  const text = messagePlainText(source)
  const images = source.images?.length ? [...source.images] : undefined
  if (!text && !images?.length) return
  emit('rerun', { text, ...(images?.length ? { images } : {}) })
}

const scrollRoot = ref<HTMLElement | null>(null)
const stickToBottom = ref(true)

function onScroll(): void {
  const root = scrollRoot.value
  if (!root) return
  stickToBottom.value = root.scrollHeight - root.scrollTop - root.clientHeight < 80
}

function scrollToLatest(): void {
  if (!stickToBottom.value) return
  void nextTick(() => {
    const root = scrollRoot.value
    if (root) root.scrollTop = root.scrollHeight
  })
}

// 避免 deep watch 在每个 token 扫整棵 messages；长度/末条内容+思考变化即够滚底。
watch(
  () => {
    const list = props.messages
    const last = list[list.length - 1]
    return [
      list.length,
      last?.id ?? '',
      last?.content?.length ?? 0,
      last?.thinking?.length ?? 0,
      last?.status ?? '',
      last?.tool_receipts?.length ?? 0,
      last?.artifacts?.length ?? 0,
    ].join(':')
  },
  scrollToLatest,
  { flush: 'post' },
)
watch(() => props.waitingUser, () => {
  stickToBottom.value = true
  scrollToLatest()
})
watch(() => props.busy, scrollToLatest)
onMounted(() => {
  stickToBottom.value = true
  scrollToLatest()
})

const lastAssistantId = computed(() => {
  for (let index = props.messages.length - 1; index >= 0; index -= 1) {
    if (props.messages[index]?.role === 'assistant') return props.messages[index]?.id
  }
  return undefined
})

// 答复瞬间 beginAssistantTurn 会插空气泡；Confirm 钉在仍带 hitl 的那条上，避免闪到空 twin。
// 提成 computed 而不是留在 showConfirmFor 里：模板对每条消息各调一次，
// 在函数里现算就是每次渲染复制整张消息表 n 遍。
const hitlCarrierId = computed(() => {
  for (let index = props.messages.length - 1; index >= 0; index -= 1) {
    const row = props.messages[index]
    if (!row || row.role !== 'assistant') continue
    if (row.hitl?.questions?.length || row.hitl?.prompt || row.hitl?.options?.length) return row.id
  }
  return undefined
})

function showConfirmFor(message: AiMessage): boolean {
  if (!props.waitingUser || message.role !== 'assistant') return false
  if (hitlCarrierId.value) return message.id === hitlCarrierId.value
  return message.id === lastAssistantId.value
}

/** Fallback confirm when waiting but last assistant has no dedicated card yet. */
const showGlobalConfirm = computed(() => {
  if (!props.waitingUser) return false
  const last = props.messages.at(-1)
  return !last || last.role !== 'assistant'
})
</script>

<template>
  <section
    ref="scrollRoot"
    class="assistant-conversation"
    role="log"
    aria-live="polite"
    @scroll.passive="onScroll"
  >
    <AssistantTurnTimeline
      v-for="message in messages"
      :key="message.id"
      :message="message"
      :show-confirm="showConfirmFor(message)"
      :agents="message.id === lastAssistantId && (busy || waitingUser) && agents?.length ? agents : undefined"
      :show-activity="message.id === lastAssistantId || Boolean(message.agents?.length)"
      :actions-disabled="actionsDisabled"
      @confirm-reply="emit('confirm-reply', $event)"
      @open-agent="emit('open-agent', $event)"
      @copy="emit('copy', $event)"
      @rerun="onRerun(message)"
    />
    <AssistantConfirmCard
      v-if="showGlobalConfirm"
      fallback
      @reply="emit('confirm-reply', $event)"
    />
    <p v-else-if="busy && !waitingUser" class="assistant-conversation__status" aria-live="polite">
      正在接收运行事件…
    </p>
  </section>
</template>

<style scoped>
.assistant-conversation {
  display: flex; min-height: 0; flex: 1; flex-direction: column;
  gap: var(--ai-gap-lg);
  overflow-x: hidden; overflow-y: auto;
  /* 滚动条是长会话里唯一的位置感知，只压细不隐藏 */
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--ink) 20%, transparent) transparent;
  padding: 1rem 0 1.35rem;
  align-items: stretch;
  width: 100%; box-sizing: border-box;
}
.assistant-conversation::-webkit-scrollbar {
  width: 8px;
}
.assistant-conversation::-webkit-scrollbar-track {
  background: transparent;
}
.assistant-conversation::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: var(--ai-r-pill);
  background: color-mix(in srgb, var(--ink) 18%, transparent);
  background-clip: padding-box;
}
.assistant-conversation:hover::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--ink) 32%, transparent);
  background-clip: padding-box;
}
.assistant-conversation__status {
  margin: .15rem 0 0; color: var(--mist); font-size: var(--ai-fs-aux); width: 100%;
}
</style>
