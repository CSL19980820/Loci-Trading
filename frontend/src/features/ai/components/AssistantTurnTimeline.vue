<script setup lang="ts">
import { computed, ref } from 'vue'
import { normalizeArtifacts } from '../assistantArtifactState'
import { Message, MessageAvatar, MessageContent, MessageHeader } from '@/shared/components/ui/message'
import { Bubble, BubbleContent } from '@/shared/components/ui/bubble'
import { Avatar, AvatarFallback } from '@/shared/components/ui/avatar'
import { Attachment, AttachmentMedia, AttachmentTrigger } from '@/shared/components/ui/attachment'
import RecordDetailsDialog from '@/shared/components/ui/RecordDetailsDialog.vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Button } from '@/shared/components/ui/button'
import { TriangleAlert, ChartNoAxesCombined, ChevronDown } from '@lucide/vue'

import { messagePlainText } from '../assistantMessageActions'
import { renderAssistantMarkdown } from '../assistantMarkdown'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import type { AiAgentProgress, AiMessage } from '@/shared/types/ai_assistant'
import AssistantActivityStrip from './AssistantActivityStrip.vue'
import AssistantArtifactHost from './AssistantArtifactHost.vue'
import AssistantConfirmCard from './AssistantConfirmCard.vue'
import AssistantMessageActions from './AssistantMessageActions.vue'
import AssistantThinkingBlock from './AssistantThinkingBlock.vue'
import AssistantToolReceiptList from './AssistantToolReceiptList.vue'

const artifactsOpen = ref(false)
const props = withDefaults(defineProps<{
  message: AiMessage
  showConfirm?: boolean
  agents?: AiAgentProgress[]
  showActivity?: boolean
  /** 忙态禁用重跑 / 重新生成 */
  actionsDisabled?: boolean
  assistantLabel?: string
  allowRerun?: boolean
}>(), { assistantLabel: 'Loci', allowRerun: true })

const emit = defineEmits<{
  'confirm-reply': [text: string]
  'open-agent': [agentId: string]
  copy: [text: string]
  rerun: []
}>()

const isUser = computed(() => props.message.role === 'user')
const initials = computed(() => props.assistantLabel === 'Loci' ? 'LC' : props.assistantLabel.slice(0, /^[a-z]/i.test(props.assistantLabel) ? 2 : 1))
const streaming = computed(() => props.message.status === 'streaming')
const tools = computed(() => props.message.tool_receipts ?? [])
const artifactRows = computed(() => props.message.artifacts)
const artifacts = computed(() => normalizeArtifacts(artifactRows.value ?? [], streaming.value))
const previewImage = ref('')
const imageOpen = computed({ get:() => Boolean(previewImage.value), set:value => { if (!value) previewImage.value = '' } })
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
  // The execution status belongs above the answer, not in a fabricated answer paragraph.
  if (streaming.value) return ''
  if (props.message.status === 'done' && props.message.role === 'assistant' && !artifacts.value.length) return '本轮未返回文字回复。'
  return ''
})

const showAnswer = computed(() => Boolean(answerHtml.value || answerPlain.value))

/** 仍在「纯思考」阶段：有 think 增量且尚未进入工具/产物/正文。 */
const thinkingLive = computed(() => {
  if (!streaming.value) return false
  if (props.message.progress) return props.message.progress.phase === 'thinking'
  if (props.message.content?.trim()) return false
  if (toolsRunning.value) return false
  if (artifacts.value.length > 0) return false
  if (activityAgents.value.length > 0) return false
  return Boolean(props.message.thinking?.trim())
})

const pendingThinking = computed(() => streaming.value && !props.message.content?.trim()
  && !props.message.thinking?.trim() && !toolsRunning.value && !activityAgents.value.length)
const thinkingLabel = computed(() => {
  if (props.message.status === 'error') return '思考已中断'
  if (props.message.status === 'cancelled') return '思考已停止'
  if (!pendingThinking.value) return undefined
  return props.message.progress?.label || ({
    queued: '等待研究开始', preparing: '正在准备上下文', thinking: '正在思考',
    tools: '正在查询证据', answering: '正在整理回答', done: '研究完成', error: '研究已中断',
  }[props.message.progress?.phase || 'preparing'])
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
  if (!props.allowRerun || props.actionsDisabled) return
  emit('rerun')
}
</script>

<template>
  <Message as="article" :align="isUser ? 'end' : 'start'"
    class="assistant-turn"
    :class="[`is-${message.role}`, { 'is-streaming': streaming }]"
    data-testid="assistant-turn"
    :aria-label="isUser ? '你的消息' : `${assistantLabel === 'Loci' ? '助手' : assistantLabel}消息`"
  >
    <MessageContent v-if="isUser" class="assistant-user-content">
      <header class="assistant-turn__identity sr-only">你</header>
      <Bubble align="end" variant="secondary" class="assistant-turn__bubble"><BubbleContent class="assistant-user-bubble">
        <div v-if="message.images?.length" class="assistant-turn__images">
          <Attachment v-for="(src,index) in message.images" :key="`${message.id}-img-${index}`" orientation="vertical" class="assistant-image-attachment">
            <AttachmentMedia class="assistant-image-media"><img :src="src" alt="用户附图" class="assistant-turn__image" /></AttachmentMedia>
            <AttachmentTrigger :aria-label="`放大附图 ${index + 1}`" @click="previewImage = src" />
          </Attachment>
        </div>
        <p v-if="message.content" class="assistant-turn__content">{{ message.content }}</p>
      </BubbleContent></Bubble>
      <AssistantMessageActions
        v-if="showActions"
        :rerun-label="rerunLabel"
        :show-rerun="allowRerun"
        :disabled="actionsDisabled"
        class="assistant-turn__actions"
        @copy="onCopy"
        @rerun="onRerun"
      />
    </MessageContent>

    <template v-else>
      <MessageContent class="assistant-turn__flow">
        <MessageHeader class="assistant-turn__identity"><MessageAvatar class="assistant-message-avatar"><Avatar class="size-6"><AvatarFallback class="assistant-avatar-fallback">{{ initials }}</AvatarFallback></Avatar></MessageAvatar><span>{{ assistantLabel }}</span><span v-if="message.meta" class="assistant-turn__meta">{{ message.meta }}</span></MessageHeader>
        <!-- Keep the answer readable; chart evidence is available without pushing it below several screens. -->
        <AssistantThinkingBlock
          :content="message.thinking ?? ''"
          :streaming="thinkingLive"
          :auto-collapse="collapseThinking"
          :pending="pendingThinking"
          :label="thinkingLabel"
          :interrupted="message.status === 'error' || message.status === 'cancelled'"
        />
        <AssistantActivityStrip
          v-if="activityAgents.length"
          :agents="activityAgents"
          :lines="[]"
          @open="emit('open-agent', $event)"
        />
        <AssistantToolReceiptList :tools="tools" :has-activity="activityAgents.length > 0" />

        <div v-if="showAnswer" class="assistant-turn__answer">
          <div
            v-if="answerHtml"
            class="assistant-turn__content is-markdown"
            v-html="answerHtml"
          />
          <p
            v-else
            class="assistant-turn__content"
            :class="{ 'is-placeholder': !message.content }"
            v-text="answerPlain"
          />
          <span v-if="streaming && message.content" class="assistant-turn__caret" aria-hidden="true" />
        </div>
        <Collapsible v-if="artifacts.length" v-model:open="artifactsOpen" class="assistant-turn__evidence">
          <CollapsibleTrigger as-child><Button access="read" variant="ghost" class="assistant-turn__evidence-trigger"><ChartNoAxesCombined aria-hidden="true" /><span>图表与数据 · {{ artifacts.length }} 项</span><ChevronDown class="assistant-evidence-chevron" :class="{ 'is-open': artifactsOpen }" aria-hidden="true" /></Button></CollapsibleTrigger>
          <CollapsibleContent class="assistant-turn__evidence-content">
            <AssistantArtifactHost v-for="artifact in artifacts" :key="artifact.id" :artifact="artifact" :active="streaming" />
          </CollapsibleContent>
        </Collapsible>
        <AssistantMessageActions
          v-if="showActions"
          :rerun-label="rerunLabel"
          :show-rerun="allowRerun"
          :disabled="actionsDisabled"
          class="assistant-turn__actions"
          @copy="onCopy"
          @rerun="onRerun"
        />
        <Alert
          v-for="(warning, warningIndex) in message.warnings"
          :key="`${message.id}-warn-${warningIndex}`"
          class="assistant-turn__warning"
        >
          <TriangleAlert class="assistant-turn__warning-icon" />
          <AlertTitle class="line-clamp-none">{{ warning }}</AlertTitle>
        </Alert>
        <AssistantConfirmCard
          v-if="showConfirm"
          :ask="message.hitl"
          :fallback="!message.hitl?.prompt"
          @reply="emit('confirm-reply', $event)"
        />
      </MessageContent>
    </template>
  </Message>
  <RecordDetailsDialog v-model:open="imageOpen" title="查看附图"><img :src="previewImage" alt="附图完整预览" class="assistant-full-image" /></RecordDetailsDialog>
</template>

<style scoped>
.assistant-turn {
  display: flex;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: var(--gap-1);
  align-self: stretch;
}

/* ─── 用户：右对齐的主色浅底气泡 ─── */
.assistant-turn.is-user {
  align-items: flex-end;
}

.assistant-turn.is-user .assistant-turn__bubble {
  max-width: min(85%, 42rem);
  min-width: 0;
  padding: 0;
  background: transparent;
  color: var(--text-primary);
  box-sizing: border-box;
}

.assistant-turn.is-user .assistant-turn__actions {
  justify-content: flex-end;
}

/* ─── 助手：左侧品牌头像 + 全宽正文 ─── */
.assistant-turn.is-assistant {
  flex-direction: row;
  align-items: flex-start;
  gap: var(--gap-3);
}


.assistant-turn__flow {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-2);
  min-width: 0;
}

.assistant-turn__flow > :deep(*) {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.assistant-turn__identity {
  padding: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 600;
  line-height: 1.4;
}

.assistant-turn__meta { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text-tertiary); font-size:var(--fs-kicker); font-weight:400; }

.assistant-turn__answer {
  position: relative;
  min-width: 0;
  padding: 2px 0;
}

.assistant-turn__images {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-2);
  margin-bottom: var(--gap-2);
}

.assistant-turn__image {
  display: block;
  max-width: min(12rem, 100%);
  max-height: 10rem;
  border-radius: var(--radius);
  object-fit: cover;
}

.assistant-turn__content {
  margin: 0;
  max-width: 100%;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--ai-fs-prose);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.assistant-turn__content.is-placeholder {
  color: var(--text-tertiary);
}

/* 流式光标 */
.assistant-turn__caret {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  border-radius: 2px;
  background: var(--seal);
  vertical-align: -2px;
  animation: assistant-caret 1s steps(2, start) infinite;
}

@keyframes assistant-caret {
  to {
    visibility: hidden;
  }
}

/* ─── Markdown 正文 ─── */
.assistant-turn__content.is-markdown {
  white-space: normal;
  overflow-x: hidden;
}

.assistant-turn__content.is-markdown :deep(p) {
  margin: 0 0 0.7em;
}

.assistant-turn__content.is-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.assistant-turn__content.is-markdown :deep(h1),
.assistant-turn__content.is-markdown :deep(h2),
.assistant-turn__content.is-markdown :deep(h3) {
  margin: 1em 0 0.4em;
  color: var(--text-primary);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.35;
}

.assistant-turn__content.is-markdown :deep(h1) {
  font-size: 1.25em;
}

.assistant-turn__content.is-markdown :deep(h2) {
  font-size: 1.12em;
}

.assistant-turn__content.is-markdown :deep(h3) {
  font-size: 1.04em;
}

.assistant-turn__content.is-markdown :deep(h1:first-child),
.assistant-turn__content.is-markdown :deep(h2:first-child),
.assistant-turn__content.is-markdown :deep(h3:first-child) {
  margin-top: 0;
}

.assistant-turn__content.is-markdown :deep(ul),
.assistant-turn__content.is-markdown :deep(ol) {
  margin: 0.3em 0 0.7em;
  padding-left: 1.4em;
}

.assistant-turn__content.is-markdown :deep(ul) { list-style:disc; }
.assistant-turn__content.is-markdown :deep(ol) { list-style:decimal; }

.assistant-turn__content.is-markdown :deep(li) {
  margin: 0.15em 0;
}

.assistant-turn__content.is-markdown :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}

.assistant-turn__content.is-markdown :deep(a) {
  color: var(--seal-ink);
  text-decoration: underline;
  text-decoration-color: var(--seal-border);
  text-underline-offset: 3px;
  overflow-wrap: anywhere;
}

.assistant-turn__content.is-markdown :deep(a:hover) {
  text-decoration-color: currentColor;
}

.assistant-turn__content.is-markdown :deep(blockquote) {
  margin: 0.5em 0 0.7em;
  padding: 0.2em 0 0.2em 0.9em;
  border-left: 2px solid var(--border-strong);
  color: var(--text-secondary);
}

.assistant-turn__content.is-markdown :deep(hr) {
  margin: 1em 0;
  border: 0;
  border-top: 1px solid var(--border-subtle);
}

/* 表格：横向可滚，不把正文列撑爆 */
.assistant-turn__content.is-markdown :deep(table) {
  display: block;
  width: 100%;
  max-width: 100%;
  margin: 0.5em 0 0.8em;
  border-collapse: collapse;
  overflow-x: auto;
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  scrollbar-width: thin;
}

.assistant-turn__content.is-markdown :deep(th),
.assistant-turn__content.is-markdown :deep(td) {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}

.assistant-turn__content.is-markdown :deep(th) {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.02em;
  background: var(--surface-sunken);
}

.assistant-turn__content.is-markdown :deep(code) {
  padding: 1px 5px;
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  font-family: var(--mono);
  font-size: 0.86em;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.assistant-turn__content.is-markdown :deep(pre) {
  margin: 0.5em 0 0.8em;
  padding: var(--gap-3);
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  white-space: pre;
  scrollbar-width: thin;
}

.assistant-turn__content.is-markdown :deep(pre code) {
  padding: 0;
  border: 0;
  background: transparent;
  font-size: var(--fs-aux);
  line-height: 1.6;
  white-space: inherit;
}

.assistant-turn__content.is-markdown :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0.5em 0;
  border-radius: var(--radius);
}

.assistant-turn__warning {
  width: 100%;
  min-width: 0;
  padding: var(--gap-2) var(--gap-3);
  border-color: color-mix(in oklab, var(--warn) 32%, var(--border-subtle));
  background: var(--warn-soft);
}

.assistant-turn__warning-icon {
  color: var(--warn);
}

/* 操作按钮 hover 才浮现（触控设备常显） */
.assistant-turn__actions {
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.assistant-turn:hover .assistant-turn__actions,
.assistant-turn:focus-within .assistant-turn__actions {
  opacity: 1;
}

@media (hover: none) {
  .assistant-turn__actions {
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .assistant-turn.is-assistant {
    gap: var(--gap-2);
  }

  .assistant-turn__avatar {
    width: 22px;
    height: 22px;
    font-size: 8px;
  }

  .assistant-turn.is-user .assistant-turn__bubble {
    max-width: 92%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-turn__caret {
    animation: none;
  }
}


.assistant-turn { flex-direction:row; }
.assistant-user-bubble { border-radius:16px 16px 4px 16px; padding:10px 14px; }
.assistant-turn__bubble :deep([data-slot="bubble-content"]) { background:var(--surface-sunken); color:var(--text-primary); }
.assistant-turn__evidence { border:1px solid var(--border-subtle); border-radius:var(--radius-lg); overflow:hidden; }
.assistant-turn__evidence-trigger { width:100%; height:auto; min-height:40px; padding:10px 12px; justify-content:flex-start; gap:8px; font-size:var(--fs-aux); color:var(--text-secondary); }
.assistant-evidence-chevron { margin-left:auto; transition:transform .15s; }.assistant-evidence-chevron.is-open { transform:rotate(180deg); }
.assistant-turn__evidence-content { display:flex; flex-direction:column; gap:12px; padding:0 8px 8px; }
.assistant-user-content { align-items:flex-end; }
.assistant-message-avatar { min-width:0; width:24px; flex:0 0 auto; align-self:center; margin-top:0; transform:none; translate:none; background:transparent; }
.assistant-avatar-fallback { background:var(--seal); color:var(--on-primary); font:600 10px var(--mono); }
.assistant-image-attachment { width:auto; padding:0; min-width:0; border:0; background:transparent; }
.assistant-image-media { width:auto; height:auto; background:transparent; }
.assistant-full-image { display:block; max-width:100%; max-height:72dvh; margin:auto; object-fit:contain; }
.assistant-turn.is-user .assistant-turn__bubble { padding:0; max-width:min(88%,42rem); }
@media(max-width:640px) { .assistant-turn.is-user .assistant-turn__bubble { max-width:92%; } }
.assistant-turn__image { object-fit:contain; max-height:180px; }
</style>
