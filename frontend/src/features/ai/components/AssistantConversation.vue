<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { renderAssistantMarkdown } from '../assistantMarkdown'
import AssistantDecisionChart from './AssistantDecisionChart.vue'
import type { AiMessage, AiToolReceipt } from '@/shared/types/ai_assistant'

const props = defineProps<{ messages: AiMessage[]; busy?: boolean; waitingUser?: boolean }>()
const scrollRoot = ref<HTMLElement | null>(null)

function scrollToLatest(): void {
  void nextTick(() => {
    const root = scrollRoot.value
    if (root) root.scrollTop = root.scrollHeight
  })
}

watch(() => props.messages, scrollToLatest, { deep: true, flush: 'post' })
watch(() => props.waitingUser, scrollToLatest)
watch(() => props.busy, scrollToLatest)
onMounted(scrollToLatest)

function receiptType(status: AiToolReceipt['status']): 'success' | 'danger' | 'warning' | 'info' {
  return status === 'done' ? 'success' : status === 'error' ? 'danger' : status === 'awaiting_confirmation' ? 'warning' : 'info'
}

function receiptLabel(tool: AiToolReceipt): string {
  return tool.summary || tool.preview || (tool.status === 'running' ? '运行中' : tool.status === 'awaiting_confirmation' ? '等待确认' : tool.status)
}

function fallbackPlain(message: AiMessage): string {
  const content = message.content ?? ''
  if (content) return content
  if (message.status === 'streaming') return '正在生成…'
  if (message.status === 'done' && message.role === 'assistant') return '正在整理回复…'
  return ''
}

const rendered = computed(() => props.messages.map((message) => {
  const content = message.content ?? ''
  const html = message.role === 'assistant' && content.trim()
    ? renderAssistantMarkdown(content)
    : ''
  return {
    message,
    html,
    plain: html ? '' : fallbackPlain(message),
  }
}))
</script>

<template>
  <section ref="scrollRoot" class="assistant-conversation" role="log" aria-live="polite">
    <article
      v-for="item in rendered"
      :key="item.message.id"
      class="assistant-message"
      :class="[`is-${item.message.role}`, { 'is-streaming': item.message.status === 'streaming' }]"
    >
      <el-text v-if="item.message.thinking" class="assistant-message__thinking" type="info" size="small">
        {{ item.message.thinking }}
      </el-text>
      <div v-if="item.message.tool_receipts?.length" class="assistant-receipts" aria-label="工具回执">
        <div v-for="tool in item.message.tool_receipts" :key="tool.call_id" class="assistant-receipt">
          <el-tag size="small" :type="receiptType(tool.status)" class="assistant-receipt__name">{{ tool.name }}</el-tag>
          <span class="assistant-receipt__label" :title="receiptLabel(tool)">{{ receiptLabel(tool) }}</span>
          <small v-if="tool.elapsed_ms != null">{{ tool.elapsed_ms }}ms</small>
        </div>
      </div>
      <div v-if="item.html || item.plain" class="assistant-message__bubble">
        <div
          v-if="item.html"
          class="assistant-message__content is-markdown"
          v-html="item.html"
        />
        <p v-else class="assistant-message__content">{{ item.plain }}</p>
      </div>
      <AssistantDecisionChart
        v-for="artifact in item.message.artifacts"
        :key="artifact.id"
        :artifact="artifact"
      />
      <el-alert
        v-for="(warning, warningIndex) in item.message.warnings"
        :key="`${item.message.id}-warn-${warningIndex}`"
        class="assistant-message__warning"
        type="warning"
        :closable="false"
        :title="warning"
        show-icon
      />
    </article>
    <el-alert
      v-if="waitingUser"
      class="assistant-conversation__wait"
      type="warning"
      :closable="false"
      title="等待你的确认"
      description="助手已暂停。在输入框直接回复即可继续，也可取消本轮运行。"
      show-icon
    />
    <p v-else-if="busy" class="assistant-conversation__status" aria-live="polite">正在接收运行事件…</p>
  </section>
</template>

<style scoped>
.assistant-conversation {
  display: flex; min-height: 0; flex: 1; flex-direction: column; gap: .65rem;
  overflow: auto; padding: .8rem;
}
.assistant-message {
  display: flex; width: min(100%, 36rem); max-width: 100%; min-width: 0;
  flex-direction: column; gap: .35rem; align-self: flex-start;
}
.assistant-message.is-user { align-self: flex-end; }
.assistant-message__bubble {
  min-width: 0; padding: .55rem .75rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2);
}
.assistant-message.is-assistant .assistant-message__bubble {
  border-color: color-mix(in srgb, var(--ink) 10%, var(--rule));
  background: color-mix(in srgb, var(--panel-2) 88%, var(--paper));
}
.assistant-message.is-user .assistant-message__bubble {
  border-color: color-mix(in srgb, var(--el-color-primary) 34%, var(--rule));
  background: color-mix(in srgb, var(--el-color-primary) 16%, var(--paper));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 8%, transparent);
}
.assistant-message.is-streaming .assistant-message__bubble { border-style: dashed; }
.assistant-message__thinking { padding: 0 .2rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-message__content {
  margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  color: var(--ink); font-size: .88rem; line-height: 1.55;
}
.assistant-message__content.is-markdown { white-space: normal; }
.assistant-message__content.is-markdown :deep(p) { margin: 0 0 .55rem; }
.assistant-message__content.is-markdown :deep(p:last-child) { margin-bottom: 0; }
.assistant-message__content.is-markdown :deep(h1),
.assistant-message__content.is-markdown :deep(h2),
.assistant-message__content.is-markdown :deep(h3) {
  margin: .55rem 0 .35rem; color: var(--ink); font-weight: 650; line-height: 1.35;
}
.assistant-message__content.is-markdown :deep(h1) { font-size: 1.12rem; }
.assistant-message__content.is-markdown :deep(h2) { font-size: 1.02rem; }
.assistant-message__content.is-markdown :deep(h3) { font-size: .94rem; }
.assistant-message__content.is-markdown :deep(h1:first-child),
.assistant-message__content.is-markdown :deep(h2:first-child),
.assistant-message__content.is-markdown :deep(h3:first-child) { margin-top: 0; }
.assistant-message__content.is-markdown :deep(ul),
.assistant-message__content.is-markdown :deep(ol) { margin: .2rem 0 .55rem; padding-left: 1.2rem; }
.assistant-message__content.is-markdown :deep(a) {
  color: var(--el-color-primary); text-decoration: underline; text-underline-offset: 2px;
  overflow-wrap: anywhere;
}
.assistant-message__content.is-markdown :deep(blockquote) {
  margin: .35rem 0 .55rem; padding: .2rem 0 .2rem .7rem;
  border-left: 3px solid color-mix(in srgb, var(--el-color-primary) 45%, var(--rule));
  color: var(--muted);
}
.assistant-message__content.is-markdown :deep(hr) {
  margin: .65rem 0; border: 0; border-top: 1px solid var(--rule);
}
.assistant-message__content.is-markdown :deep(table) {
  display: block; width: 100%; max-width: 100%; margin: .35rem 0 .55rem;
  overflow-x: auto; border-collapse: collapse; font-size: .82rem;
}
.assistant-message__content.is-markdown :deep(th),
.assistant-message__content.is-markdown :deep(td) {
  padding: .28rem .4rem; border: 1px solid var(--rule); text-align: left; vertical-align: top;
}
.assistant-message__content.is-markdown :deep(th) {
  background: color-mix(in srgb, var(--ink) 6%, transparent); font-weight: 600;
}
.assistant-message__content.is-markdown :deep(code) {
  padding: .05rem .3rem; border-radius: 4px;
  background: color-mix(in srgb, var(--ink) 8%, transparent);
  font-family: var(--mono); font-size: .82em;
}
.assistant-message__content.is-markdown :deep(pre) {
  margin: .35rem 0 .55rem; padding: .55rem .65rem; overflow: auto; max-width: 100%;
  border-radius: 6px; background: color-mix(in srgb, var(--ink) 8%, transparent);
}
.assistant-message__content.is-markdown :deep(pre code) { padding: 0; background: transparent; }
.assistant-message__content.is-markdown :deep(img) {
  display: block; max-width: 100%; height: auto; margin: .35rem 0; border-radius: 4px;
}
.assistant-receipts { display: grid; gap: .25rem; width: 100%; min-width: 0; }
.assistant-receipt {
  display: flex; align-items: center; gap: .35rem; min-width: 0; max-width: 100%;
  padding: .3rem .4rem; border: 1px solid var(--rule); border-radius: 4px;
  background: var(--panel-2); font-size: .74rem;
}
.assistant-receipt__name { flex: 0 1 auto; max-width: 42%; overflow: hidden; }
.assistant-receipt__label {
  min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--muted);
}
.assistant-receipt small {
  flex: 0 0 auto; color: var(--mist); font-family: var(--mono);
}
.assistant-message__warning, .assistant-conversation__wait { margin-top: .2rem; width: 100%; min-width: 0; }
.assistant-conversation__status {
  margin: .15rem 0 0; color: var(--mist); font-size: .75rem;
}
</style>
