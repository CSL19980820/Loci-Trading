<script setup lang="ts">
import { computed } from 'vue'

import { messagePlainText } from '../assistantMessageActions'
import { renderAssistantMarkdown } from '../assistantMarkdown'
import type { AiAgentProgress, AiMessage } from '@/shared/types/ai_assistant'
import AssistantActivityStrip from './AssistantActivityStrip.vue'
import AssistantArtifactHost from './AssistantArtifactHost.vue'
import AssistantConfirmCard from './AssistantConfirmCard.vue'
import AssistantMessageActions from './AssistantMessageActions.vue'
import AssistantThinkingBlock from './AssistantThinkingBlock.vue'
import AssistantToolReceiptList from './AssistantToolReceiptList.vue'

const props = defineProps<{
  message: AiMessage
  showConfirm?: boolean
  agents?: AiAgentProgress[]
  showActivity?: boolean
  /** 忙态禁用重跑 / 重新生成 */
  actionsDisabled?: boolean
}>()

const emit = defineEmits<{
  'confirm-reply': [text: string]
  'open-agent': [agentId: string]
  copy: [text: string]
  rerun: []
}>()

const isUser = computed(() => props.message.role === 'user')
const streaming = computed(() => props.message.status === 'streaming')
const tools = computed(() => props.message.tool_receipts ?? [])
const artifacts = computed(() => props.message.artifacts ?? [])
const toolsRunning = computed(() => tools.value.some((tool) => tool.status === 'running'))
const activityAgents = computed(() => {
  if (!props.showActivity) return []
  // 直播态由父级传入 Host.agents；历史态用 message.agents（收口已 fold）。
  if (props.agents !== undefined) return props.agents
  return props.message.agents ?? []
})

/** Markdown only after the turn settles — streaming tokens stay plain text. */
const answerHtml = computed(() => {
  if (isUser.value || streaming.value) return ''
  const content = props.message.content ?? ''
  return content.trim() ? renderAssistantMarkdown(content) : ''
})

const answerPlain = computed(() => {
  if (answerHtml.value) return ''
  const content = props.message.content ?? ''
  if (content) return content
  if (streaming.value) return '正在生成…'
  if (props.message.status === 'done' && props.message.role === 'assistant') return '正在整理回复…'
  return ''
})

const showAnswer = computed(() => Boolean(answerHtml.value || answerPlain.value))

/** 仍在「纯思考」阶段：有 think 增量且尚未进入工具/产物/正文。 */
const thinkingLive = computed(() => {
  if (!streaming.value) return false
  if (props.message.content?.trim()) return false
  if (toolsRunning.value) return false
  if (artifacts.value.length > 0) return false
  if (activityAgents.value.length > 0) return false
  return Boolean(props.message.thinking?.trim())
})

/** 思考一结束（出工具/正文/收口）就收起，把视口留给最新块。 */
const collapseThinking = computed(() => {
  if (!props.message.thinking?.trim()) return false
  return !thinkingLive.value
})

const showActions = computed(() => {
  if (isUser.value) return Boolean(messagePlainText(props.message) || props.message.images?.length)
  if (streaming.value) return false
  return Boolean(messagePlainText(props.message))
})

const rerunLabel = computed(() => (isUser.value ? '重跑' : '重新生成'))

function onCopy(): void {
  const text = messagePlainText(props.message)
  if (text) emit('copy', text)
}

function onRerun(): void {
  if (props.actionsDisabled) return
  emit('rerun')
}
</script>

<template>
  <article
    class="assistant-turn"
    :class="[`is-${message.role}`, { 'is-streaming': streaming }]"
    data-testid="assistant-turn"
    :aria-label="isUser ? '你的消息' : '助手消息'"
  >
    <header class="assistant-turn__identity">{{ isUser ? '你' : 'Loci' }}</header>
    <template v-if="isUser">
      <div class="assistant-turn__bubble">
        <div v-if="message.images?.length" class="assistant-turn__images">
          <img
            v-for="(src, index) in message.images"
            :key="`${message.id}-img-${index}`"
            :src="src"
            alt="用户附图"
            class="assistant-turn__image"
          >
        </div>
        <p v-if="message.content" class="assistant-turn__content">{{ message.content }}</p>
      </div>
      <AssistantMessageActions
        v-if="showActions"
        :rerun-label="rerunLabel"
        show-rerun
        :disabled="actionsDisabled"
        @copy="onCopy"
        @rerun="onRerun"
      />
    </template>

    <template v-else>
      <!-- TurnTimeline: Thinking → Activity → Tool → Artifact* → Answer → Actions -->
      <AssistantThinkingBlock
        :content="message.thinking ?? ''"
        :streaming="thinkingLive"
        :auto-collapse="collapseThinking"
      />
      <AssistantActivityStrip
        v-if="activityAgents.length"
        :agents="activityAgents"
        :lines="[]"
        @open="emit('open-agent', $event)"
      />
      <AssistantToolReceiptList :tools="tools" :has-activity="activityAgents.length > 0" />
      <AssistantArtifactHost
        v-for="artifact in artifacts"
        :key="artifact.id"
        :artifact="artifact"
      />
      <div v-if="showAnswer" class="assistant-turn__bubble">
        <div
          v-if="answerHtml"
          class="assistant-turn__content is-markdown"
          v-html="answerHtml"
        />
        <p
          v-else
          class="assistant-turn__content"
          v-text="answerPlain"
        />
      </div>
      <AssistantMessageActions
        v-if="showActions"
        :rerun-label="rerunLabel"
        show-rerun
        :disabled="actionsDisabled"
        @copy="onCopy"
        @rerun="onRerun"
      />
      <el-alert
        v-for="(warning, warningIndex) in message.warnings"
        :key="`${message.id}-warn-${warningIndex}`"
        class="assistant-turn__warning"
        type="warning"
        :closable="false"
        :title="warning"
        show-icon
      />
      <AssistantConfirmCard
        v-if="showConfirm"
        :ask="message.hitl"
        :fallback="!message.hitl?.prompt"
        @reply="emit('confirm-reply', $event)"
      />
    </template>
  </article>
</template>

<style scoped>
.assistant-turn {
  display: flex; width: 100%; max-width: 100%; min-width: 0;
  flex-direction: column; gap: var(--ai-gap-md); align-self: stretch;
}
.assistant-turn.is-user { align-items: flex-end; }
.assistant-turn.is-assistant {
  align-items: stretch;
}
.assistant-turn.is-assistant > :deep(.assistant-thinking),
.assistant-turn.is-assistant > :deep(.assistant-activity),
.assistant-turn.is-assistant > :deep(.assistant-receipts),
.assistant-turn.is-assistant > :deep(.assistant-artifact-host),
.assistant-turn.is-assistant > .assistant-turn__bubble,
.assistant-turn.is-assistant > .assistant-turn__warning {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  align-self: stretch;
  box-sizing: border-box;
}
.assistant-turn__bubble {
  min-width: 0; max-width: 100%;
  padding: var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card); background: var(--panel-2);
  box-sizing: border-box;
}
.assistant-turn.is-assistant .assistant-turn__bubble {
  width: 100%;
  background: var(--surface);
  border-color: color-mix(in oklab, var(--rule) 85%, transparent);
}
.assistant-turn.is-user .assistant-turn__bubble {
  max-width: min(100%, 42rem);
  background: var(--seal-soft);
  border-color: color-mix(in oklab, var(--seal) 28%, var(--rule));
}
.assistant-turn.is-streaming .assistant-turn__bubble { border-color: var(--seal-border); }
.assistant-turn__images {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin-bottom: .35rem;
}
.assistant-turn__image {
  display: block;
  max-width: min(12rem, 100%);
  max-height: 10rem;
  border-radius: var(--ai-r-card);
  object-fit: cover;
}
.assistant-turn__content {
  margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  color: var(--ink); font-size: var(--ai-fs-prose); line-height: 1.65;
  max-width: 100%;
  min-width: 0;
}
.assistant-turn__content.is-markdown { white-space: normal; overflow-x: hidden; }
.assistant-turn__content.is-markdown :deep(p) { margin: 0 0 .55rem; }
.assistant-turn__content.is-markdown :deep(p:last-child) { margin-bottom: 0; }
.assistant-turn__content.is-markdown :deep(h1),
.assistant-turn__content.is-markdown :deep(h2),
.assistant-turn__content.is-markdown :deep(h3) {
  margin: .55rem 0 .35rem; color: var(--ink); font-weight: 650; line-height: 1.35;
}
/* 标题跟着 --ai-fs-body 缩放：调契约时正文与小标题不会脱节 */
.assistant-turn__content.is-markdown :deep(h1) { font-size: 1.3em; }
.assistant-turn__content.is-markdown :deep(h2) { font-size: 1.15em; }
.assistant-turn__content.is-markdown :deep(h3) { font-size: 1.05em; }
.assistant-turn__content.is-markdown :deep(h1:first-child),
.assistant-turn__content.is-markdown :deep(h2:first-child),
.assistant-turn__content.is-markdown :deep(h3:first-child) { margin-top: 0; }
.assistant-turn__content.is-markdown :deep(ul),
.assistant-turn__content.is-markdown :deep(ol) { margin: .2rem 0 .55rem; padding-left: 1.2rem; }
.assistant-turn__content.is-markdown :deep(a) {
  color: var(--el-color-primary); text-decoration: underline; text-underline-offset: 2px;
  overflow-wrap: anywhere;
}
.assistant-turn__content.is-markdown :deep(blockquote) {
  margin: .35rem 0 .55rem; padding: .2rem 0 .2rem .7rem;
  border-left: 3px solid color-mix(in oklab, var(--el-color-primary) 45%, var(--rule));
  color: var(--muted);
}
.assistant-turn__content.is-markdown :deep(hr) {
  margin: .65rem 0; border: 0; border-top: 1px solid var(--rule);
}
.assistant-turn__content.is-markdown :deep(table) {
  display: table;
  width: 100%;
  max-width: 100%;
  margin: .35rem 0 .55rem;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: var(--ai-fs-aux);
}
.assistant-turn__content.is-markdown :deep(th),
.assistant-turn__content.is-markdown :deep(td) {
  padding: .2rem .35rem; border: 1px solid var(--rule); text-align: left; vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.assistant-turn__content.is-markdown :deep(th) {
  background: color-mix(in oklab, var(--ink) 6%, transparent); font-weight: 600;
}
.assistant-turn__content.is-markdown :deep(code) {
  padding: .05rem .3rem; border-radius: var(--ai-r-chip);
  background: color-mix(in oklab, var(--ink) 8%, transparent);
  font-family: var(--mono); font-size: .82em;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.assistant-turn__content.is-markdown :deep(pre) {
  margin: .35rem 0 .55rem; padding: .55rem .65rem;
  max-width: 100%;
  overflow-x: auto;
  border-radius: var(--ai-r-card); background: color-mix(in oklab, var(--ink) 8%, transparent);
  white-space: pre-wrap;
  word-break: break-word;
}
.assistant-turn__content.is-markdown :deep(pre code) {
  padding: 0; background: transparent; white-space: inherit;
}
.assistant-turn__content.is-markdown :deep(img) {
  display: block; max-width: 100%; height: auto; margin: .35rem 0; border-radius: var(--ai-r-chip);
}
.assistant-turn__warning { width: 100%; min-width: 0; }
.assistant-turn__identity { color: var(--mist); font-size: var(--ai-fs-body); font-weight: 600; }
.assistant-turn.is-user .assistant-turn__identity { align-self: flex-end; }
</style>
