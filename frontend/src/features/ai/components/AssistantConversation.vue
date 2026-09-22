<script setup lang="ts">
import { computed } from 'vue'
import { MessageScroller, MessageScrollerProvider, MessageScrollerViewport, MessageScrollerContent, MessageScrollerItem, MessageScrollerButton } from '@/shared/components/ui/message-scroller'

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
  <MessageScrollerProvider default-scroll-position="end" :auto-scroll="true" :scroll-edge-threshold="80">
    <MessageScroller class="assistant-conversation">
      <MessageScrollerViewport class="assistant-conversation__viewport" aria-label="对话记录">
        <MessageScrollerContent class="assistant-conversation__content" aria-live="polite">
          <MessageScrollerItem v-for="message in messages" :key="message.id" :message-id="message.id" :scroll-anchor="message.role === 'user'">
    <AssistantTurnTimeline
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
          </MessageScrollerItem>
    <AssistantConfirmCard
      v-if="showGlobalConfirm"
      fallback
      @reply="emit('confirm-reply', $event)"
    />
    <p v-else-if="busy && !waitingUser" class="assistant-conversation__status" aria-live="polite">
      正在接收运行事件…
    </p>
        </MessageScrollerContent>
      </MessageScrollerViewport>
      <MessageScrollerButton access="read" aria-label="回到最新消息" />
    </MessageScroller>
  </MessageScrollerProvider>
</template>

<style scoped>
.assistant-conversation { flex:1 1 0%; height:auto; min-height:0; width:100%; }
.assistant-conversation__viewport { padding:var(--gap-4) 0 var(--gap-3); overflow-x:hidden; scrollbar-width:thin; }
.assistant-conversation__content { width:100%; max-width:none; margin:0 auto; gap:var(--gap-5); }
.assistant-conversation__status { margin:var(--gap-1) 0 0; color:var(--mist); font-size:var(--ai-fs-aux); }
.assistant-conversation__viewport:focus-visible { outline:2px solid var(--seal); outline-offset:-2px; }
</style>
