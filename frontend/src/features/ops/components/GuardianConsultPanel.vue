<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { MessageScroller, MessageScrollerProvider, MessageScrollerViewport, MessageScrollerContent, MessageScrollerItem, MessageScrollerButton } from '@/shared/components/ui/message-scroller'
import { Badge } from '@/shared/components/ui/badge'
import { Plus, LoaderCircle, Trash2 } from '@lucide/vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as Disclosure } from '@/shared/components/ui/app/Disclosure.vue'
import { default as DisclosurePanel } from '@/shared/components/ui/app/DisclosurePanel.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'

import { computed, nextTick, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { askGuardian, deleteGuardianConversation, getGuardianConversation, getGuardianConversations, streamGuardianConsultation } from '@/shared/api/guardian'
import { renderAssistantMarkdown } from '@/features/ai/assistantMarkdown'
import { confirmAction } from '@/shared/lib/confirm'
import { createUuid } from '@/shared/lib/uuid'
import type { GuardianConversation, GuardianConsultTurn } from '@/shared/types/guardian'
defineProps<{ model: string }>()
const conversations = ref<GuardianConversation[]>([])
const selected = ref('')
const turns = ref<GuardianConsultTurn[]>([])
const question = ref('')
const notes = ref('')
const error = ref('')
const sending = ref(false)
const deleting = ref(false)
const loading = ref(false)
const pending = computed(() => turns.value.some(t => ['queued', 'running'].includes(t.status)))
const renderedAnswers = computed(() => Object.fromEntries(turns.value.map(t => [t.id, ['queued', 'running'].includes(t.status) ? '' : renderAssistantMarkdown(t.result.answer || '')])))
let controller: AbortController | undefined
let streamController: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let suspended = false
let retryPayload: Parameters<typeof askGuardian>[0] | null = null
function newTopic() { controller?.abort(); streamController?.abort(); clearTimeout(timer); selected.value = createUuid(); turns.value = []; question.value = ''; notes.value = ''; error.value = ''; retryPayload = null }
async function follow(id: string, requestId: string) {
  streamController?.abort()
  const request = new AbortController(); streamController = request
  try {
    await streamGuardianConsultation(id, requestId, turn => {
      if (disposed || suspended || request.signal.aborted || selected.value !== id) return
      turns.value = turns.value.map(item => item.id === turn.id ? turn : item)
    }, request.signal)
  } catch {
    // 旧服务或网络中断时回读已保存正文；后台研究不随订阅断开取消。
  } finally {
    if (!disposed && !suspended && !request.signal.aborted && selected.value === id && pending.value) {
      clearTimeout(timer)
      timer = setTimeout(() => void load(id), 2500)
    }
  }
}
async function deleteTopic() {
  if (sending.value || pending.value || deleting.value || !conversations.value.some(item => item.id === selected.value)) return
  const id = selected.value
  deleting.value = true
  try {
    if (!await confirmAction({ title: '删除当前话题', message: '删除此话题的全部提问、回答和实际持仓背景，其他话题不受影响。', confirmText: '删除话题', cancelText: '取消', danger: true })) return
    controller?.abort(); clearTimeout(timer)
    await deleteGuardianConversation(id)
    conversations.value = (await getGuardianConversations()).conversations
    if (selected.value === id) {
      newTopic()
      if (conversations.value.length) { selected.value = conversations.value[0]!.id; await load(selected.value, true) }
    }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { deleting.value = false }
}
async function load(id: string, restoreNotes = false) {
  if (disposed || suspended) return
  controller?.abort(); streamController?.abort(); clearTimeout(timer)
  const request = new AbortController(); controller = request
  loading.value = true
  try {
    const detail = await getGuardianConversation(id, request.signal)
    if (disposed || request.signal.aborted || selected.value !== id) return
    turns.value = detail.turns
    if (restoreNotes) notes.value = detail.notes
    error.value = ''
    clearTimeout(timer)
    await nextTick()
    if (disposed || suspended || request.signal.aborted || selected.value !== id) return
    const active = turns.value.find(t => ['queued', 'running'].includes(t.status))
    if (active) void follow(id, active.id)
  } catch (e) {
    if (!request.signal.aborted) {
      error.value = e instanceof Error ? e.message : String(e)
      if (pending.value && !disposed && !suspended) timer = setTimeout(() => void load(id), 5000)
    }
  } finally { if (controller === request) loading.value = false }
}
async function send() {
  if (!question.value.trim() || sending.value || pending.value || deleting.value) return
  sending.value = true; error.value = ''
  const message = question.value.trim()
  try {
    if (!retryPayload || retryPayload.message !== message || retryPayload.conversation_id !== selected.value || retryPayload.real_context !== notes.value) retryPayload = { conversation_id: selected.value, request_id: createUuid(), message, real_context: notes.value }
    await askGuardian(retryPayload)
    retryPayload = null; question.value = ''
    turns.value.push({ id: 'pending', question: message, status: 'queued', created: Date.now() / 1000, result: {} })
    await load(selected.value)
    conversations.value = (await getGuardianConversations()).conversations
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { sending.value = false }
}
onMounted(async () => {
  try {
    const result = await getGuardianConversations()
    if (disposed) return
    conversations.value = result.conversations
    if (conversations.value.length) { selected.value = conversations.value[0]!.id; await load(selected.value, true) }
    else newTopic()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); selected.value = createUuid() }
})
onDeactivated(() => { suspended = true; controller?.abort(); streamController?.abort(); loading.value = false; clearTimeout(timer) })
onActivated(() => {
  if (!suspended || disposed) return
  suspended = false
  if (turns.value.length || conversations.value.some(item => item.id === selected.value)) void load(selected.value)
})
onUnmounted(() => { disposed = true; controller?.abort(); streamController?.abort(); clearTimeout(timer) })
</script>

<template>
  <section class="consult-panel" aria-label="与交易员沟通">
    <header class="consult-header">
      <div class="consult-tools">
        <Button variant="outline" size="sm" :disabled="sending || deleting" @click="newTopic"><Plus class="size-3" />新话题</Button>
        <ChoiceField v-if="conversations.length" v-model="selected" placeholder="选择话题" aria-label="咨询话题" :disabled="sending || deleting" class="consult-topic-select" @change="load(selected, true)">
          <ChoiceOption v-for="item in conversations" :key="item.id" :value="item.id" :label="item.title" />
        </ChoiceField>
        <Badge v-if="!model" variant="outline">请先配置模型</Badge>
        <Button variant="ghost" size="icon-sm" class="consult-delete" aria-label="删除当前话题" title="删除当前话题全部内容" :disabled="sending || pending || deleting || !conversations.some(item => item.id === selected)" @click="deleteTopic"><Trash2 class="size-4" /></Button>
      </div>
    </header>
    <MessageScrollerProvider :key="selected" default-scroll-position="end" :auto-scroll="true" :scroll-edge-threshold="80">
    <MessageScroller class="consult-scroller">
    <MessageScrollerViewport class="consult-history" aria-label="咨询消息">
    <MessageScrollerContent class="consult-transcript" aria-live="polite" :aria-busy="loading">
      <div v-if="!turns.length" class="consult-empty"><h4>把你的真实情况告诉交易员</h4><p>例如：“我跟着买了，但买贵了 3%，现在要不要调整？”</p><p>它会结合你的描述和当前证据讨论，不会把模拟仓当成你的实盘，也不会通过对话下单。</p></div>
      <MessageScrollerItem v-for="turn in turns" :key="turn.id" :message-id="turn.id" scroll-anchor class="consult-turn">
        <div class="consult-question" aria-label="你的消息">{{ turn.question }}</div>
        <div class="consult-answer" aria-label="交易员的回复">
          <div class="consult-answer-meta">
            <span class="consult-identity">交易员</span>
            <span v-if="turn.result.model" class="consult-model">{{ turn.result.model }}</span>
            <time v-if="turn.result.as_of">{{ turn.result.as_of.slice(0, 16).replace('T', ' ') }}</time>
            <span v-if="['queued', 'running'].includes(turn.status)" class="consult-progress"><LoaderCircle class="size-3 animate-spin" />{{ turn.result.answer ? '正在回复' : '正在研究' }}</span>
          </div>
          <div v-if="turn.result.answer && ['queued', 'running'].includes(turn.status)" class="consult-streaming">{{ turn.result.answer }}</div>
          <div v-else-if="turn.result.answer" class="consult-rich" v-html="renderedAnswers[turn.id]" />
          <Notice v-if="turn.status === 'failed'" :title="turn.result.error || '咨询未完成，请重新提问'" tone="warning" :closable="false" />
          <p v-else-if="!turn.result.answer" class="consult-pending">正在读取账户、查询证据…</p>
          <ActionButton v-if="turn.status === 'failed'" variant="link" @click="question = turn.question">重新编辑提问</ActionButton>
        </div>
      </MessageScrollerItem>
    </MessageScrollerContent>
    </MessageScrollerViewport>
    <MessageScrollerButton access="read" aria-label="回到最新咨询" />
    </MessageScroller>
    </MessageScrollerProvider>
    <Notice v-if="error" :title="error" tone="error" :closable="false" show-icon />
    <div class="consult-composer">
    <Disclosure class="consult-context"><DisclosurePanel title="我的实际持仓 / 执行偏差（选填，随话题保存）" name="notes"><TextField v-model="notes" :disabled="deleting" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" maxlength="12000" placeholder="写明股票名称或代码、实际股数、成本、买入日期、可用现金，以及和模拟操作有哪些不同。这里只保存咨询背景，不会修改模拟账户。" /></DisclosurePanel></Disclosure>
    <TextField v-model="question" type="textarea" :autosize="{ minRows: 3, maxRows: 7 }" maxlength="6000" aria-label="咨询问题" placeholder="说说你担心什么，或继续追问上一条建议…" :disabled="sending || deleting" @keydown.ctrl.enter.prevent="send" />
    <footer class="consult-footer">
      <span>咨询不执行交易<span class="consult-shortcut"> · Ctrl + Enter 发送</span></span>
      <Button
        size="sm"
        class="h-7 text-xs px-3 font-medium"
        :disabled="!model || !selected || !question.trim() || pending || loading || deleting"
        @click="send"
      >
        <LoaderCircle v-if="sending || pending" class="size-3 animate-spin mr-1" />
        <span>{{ pending ? '正在研究' : '发送问题' }}</span>
      </Button>
    </footer>
    </div>
  </section>
</template>

<style scoped>
.consult-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: 14px 16px;
  background: transparent;
  border: 0;
  box-shadow: none;
  min-width: 0;
  min-height: 0;
  flex: 1 1 0%;
  overflow: hidden;
  color: var(--ink);
}

.consult-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap-2);
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule-soft);
  flex-shrink: 0;
}

.consult-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.consult-title-group h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.consult-sub {
  font-size: var(--fs-micro);
  color: var(--muted);
}

.consult-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.consult-scroller { flex:1 1 0%; height:auto; min-height:0; }
.consult-transcript { gap:0; }
.consult-history {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  /* 正文到达边界后继续滚动外层页面，避免鼠标停在对话区时被困住。 */
  overscroll-behavior-y: auto;
  padding: 16px 2px;
  scrollbar-width: thin;
}

.consult-empty {
  text-align: center;
  padding: var(--gap-4) var(--gap-3);
  color: var(--muted);
  line-height: 1.9;
}

.consult-empty h4 {
  color: var(--ink);
  font-weight: 500;
}

.consult-turn {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: min(100%, 960px);
  margin: 0 auto 28px;
  font-size: var(--fs-body);
  line-height: 1.75;
}

.consult-turn p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: var(--gap-2) 0 0;
}

.consult-rich :deep(p) {
  margin: var(--gap-2) 0;
  white-space: normal;
}

.consult-rich :deep(ul), .consult-rich :deep(ol) {
  padding-left: 1.5em;
  margin: var(--gap-2) 0;
}

.consult-rich :deep(ul) { list-style: disc; }
.consult-rich :deep(ol) { list-style: decimal; }
.consult-rich :deep(a) { color: var(--seal-ink); text-decoration: underline; overflow-wrap: anywhere; }

.consult-question {
  align-self: flex-end;
  max-width: min(85%, 42rem);
  background: var(--seal-soft);
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-xs) var(--radius-xl);
  padding: 10px 14px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.consult-answer {
  min-width: 0;
}

.consult-answer-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-bottom: 8px;
  font-size: var(--fs-aux);
  color: var(--muted);
}
.consult-identity { color: var(--ink); font-weight: 600; }
.consult-model { overflow-wrap: anywhere; }
.consult-progress { display: inline-flex; align-items: center; gap: 5px; color: var(--seal-ink); }
.consult-streaming { white-space: pre-wrap; overflow-wrap: anywhere; }
.consult-rich { overflow-wrap: anywhere; }
.consult-rich :deep(> :first-child) { margin-top: 0; }
.consult-rich :deep(h1), .consult-rich :deep(h2), .consult-rich :deep(h3) { margin: 1em 0 .4em; font-size: 1.12em; font-weight: 600; line-height: 1.4; }
.consult-rich :deep(th), .consult-rich :deep(td) { padding: 6px 10px; border-bottom: 1px solid var(--rule-soft); text-align: left; }
.consult-rich :deep(blockquote) { margin: .5em 0; padding-left: 12px; border-left: 2px solid var(--rule); color: var(--muted); }
.consult-composer { flex-shrink: 0; align-self: center; width: min(100%, 960px); display: flex; flex-direction: column; gap: 8px; padding-top: 10px; border-top: 1px solid var(--rule-soft); }

.consult-pending {
  color: var(--muted);
}

.consult-context :deep([data-slot='accordion-trigger']) {
  font-size: var(--fs-aux);
  color: var(--muted);
}

.consult-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--gap-2);
  padding-top: var(--gap-1);
  flex-shrink: 0;
}

.consult-footer span {
  font-size: var(--fs-micro);
  color: var(--muted);
}

.consult-context {
  flex-shrink: 0;
}

.consult-rich :deep(pre) {
  max-width: 100%;
  overflow: auto;
}

.consult-rich :deep(table) {
  display: block;
  max-width: 100%;
  overflow: auto;
}

@media(max-width: 650px) {
  .consult-question { max-width: 92%; }
  .consult-shortcut { display: none; }
  .consult-panel { padding: var(--gap-3); }
}
</style>

<style scoped>
.consult-tools { width:100%; min-width:0; flex-wrap:nowrap; }
.consult-tools > button { flex-shrink:0; }
.consult-topic-select { flex:0 1 480px; min-width:0; }
.consult-topic-select :deep(.choice-field__value) { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.consult-topic-select :deep(.choice-field__trigger) { width:100%; min-width:0; }
.consult-delete { margin-left:auto; color:var(--destructive); }
.consult-delete:hover { color:var(--destructive); background:var(--stamp-soft); }
</style>
