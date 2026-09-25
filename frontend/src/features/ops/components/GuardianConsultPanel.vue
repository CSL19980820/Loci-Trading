<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import { ArrowUp, MessageSquare, PanelLeftOpen, PanelRightOpen } from '@lucide/vue'
import { Alert, AlertDescription } from '@/shared/components/ui/alert'
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription } from '@/shared/components/ui/empty'
import { SidebarProvider } from '@/shared/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/shared/components/ui/sheet'
import { useElementSize } from '@vueuse/core'
import AssistantSessionRail from '@/features/ai/components/AssistantSessionRail.vue'
import AssistantConversation from '@/features/ai/components/AssistantConversation.vue'
import { copyTextToClipboard } from '@/features/ai/assistantMessageActions'
import { guardianMessages, guardianPendingLabel } from '../guardianConsultAdapter'
import { InputGroup, InputGroupAddon, InputGroupTextarea } from '@/shared/components/ui/input-group'
import AssistantTaskSidebar from '@/features/ai/components/AssistantTaskSidebar.vue'
import { buildTaskModel } from '@/features/ai/assistantTaskModel'
import GuardianConsultContext from './GuardianConsultContext.vue'

import { computed, nextTick, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { askGuardian, deleteGuardianConversation, getGuardianConversation, getGuardianConversations, streamGuardianConsultation } from '@/shared/api/guardian'
import { confirmAction } from '@/shared/lib/confirm'
import { createUuid } from '@/shared/lib/uuid'
import type { GuardianConversation, GuardianConsultTurn } from '@/shared/types/guardian'
const props = defineProps<{ model: string }>()
const conversations = ref<GuardianConversation[]>([])
const selected = ref('')
const turns = ref<GuardianConsultTurn[]>([])
const question = ref('')
const notes = ref('')
const error = ref('')
const sending = ref(false)
const deleting = ref(false)
const loading = ref(false)
const questionInput = ref<InstanceType<typeof InputGroupTextarea> | null>(null)
const canSend = computed(() => Boolean(props.model && selected.value && question.value.trim()) && !sending.value && !pending.value && !loading.value && !deleting.value)
const pending = computed(() => turns.value.some(t => ['queued', 'running'].includes(t.status)))
const failedQuestions = computed(() => Object.fromEntries(turns.value.filter(turn => turn.status === 'failed').map(turn => [`${turn.id}:assistant`, turn.question])))
const messages = computed(() => guardianMessages(turns.value))
const pendingLabel = computed(() => guardianPendingLabel(turns.value.find(t => ['queued', 'running'].includes(t.status))))
const panelRoot = ref<InstanceType<typeof SidebarProvider> | null>(null)
const { width: panelWidth } = useElementSize(() => {
  const element = panelRoot.value?.$el
  return element instanceof HTMLElement ? element : undefined
})
const smallScreen = computed(() => panelWidth.value <= 700)
const historyOpen = ref(false)
const detailDrawer = computed(() => panelWidth.value < 1100)
const detailsOpen = ref(false)
const desktopDetailsOpen = ref(true)
const taskModel = computed(() => buildTaskModel({ messages: messages.value, agents: [], busy: pending.value }))
const taskProps = computed(() => ({ model: taskModel.value, title: '咨询详情', visibleTabs: ['sources', 'cabin'] as ('sources' | 'cabin')[] }))
const collapsed = ref(false)
const currentTitle = computed(() => conversations.value.find(item => item.id === selected.value)?.title || '新话题')
const sessions = computed(() => conversations.value.map(item => ({ id: item.id, title: item.title, updated_at: new Date(item.updated * 1000).toISOString() })))
const railProps = computed(() => ({ sessions: sessions.value, activeId: selected.value, disabled: sending.value || deleting.value, archiveEnabled: false, batchEnabled: false, settingsEnabled: false, title: '咨询话题', createLabel: '新话题', searchPlaceholder: '搜索咨询话题', brandLabel: '交易员咨询', emptyDescription: '还没有咨询话题', emptyReason: '从实际持仓或执行偏差开始讨论' }))
async function selectTopic(id: string): Promise<void> {
  if (sending.value || deleting.value || selected.value === id) return
  selected.value = id; turns.value = []; question.value = ''; notes.value = ''; retryPayload = null; historyOpen.value = false
  await load(id, true)
}
async function copyAnswer(text: string): Promise<void> {
  if (!await copyTextToClipboard(text)) error.value = '复制失败，请重试'
}
let controller: AbortController | undefined
let streamController: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let suspended = false
let retryPayload: Parameters<typeof askGuardian>[0] | null = null
function newTopic() { controller?.abort(); streamController?.abort(); clearTimeout(timer); selected.value = createUuid(); turns.value = []; question.value = ''; notes.value = ''; error.value = ''; retryPayload = null; loading.value = false; historyOpen.value = false }
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
async function deleteTopic(id: string) {
  if (sending.value || (pending.value && id === selected.value) || deleting.value || !conversations.value.some(item => item.id === id)) return
  deleting.value = true
  try {
    if (!await confirmAction({ title: '删除咨询话题', message: '删除此话题的全部提问、回答和实际持仓背景，其他话题不受影响。', confirmText: '删除话题', cancelText: '取消', danger: true })) return
    if (selected.value === id) { controller?.abort(); streamController?.abort(); clearTimeout(timer) }
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
  if (!canSend.value) return
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
function focusQuestion(): void {
  const input = questionInput.value?.$el
  if (input instanceof HTMLTextAreaElement) input.focus()
}
function editAgain(value: string): void { question.value = value; void nextTick(focusQuestion) }
function onQuestionKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || !event.ctrlKey || event.isComposing) return
  event.preventDefault()
  void send()
}
watch(question, async () => {
  await nextTick()
  const input = questionInput.value?.$el
  if (!(input instanceof HTMLTextAreaElement)) return
  input.style.height = 'auto'
  const line = Number.parseFloat(getComputedStyle(input).lineHeight) || 22
  input.style.height = `${Math.max(line * 3 + 20, Math.min(input.scrollHeight, line * 7 + 20))}px`
}, { flush: 'post' })
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
  <SidebarProvider ref="panelRoot" :persist="false" :keyboard-shortcut="false" class="consult-panel" aria-label="与交易员沟通">
    <AssistantSessionRail v-if="!smallScreen" v-bind="railProps" v-model:collapsed="collapsed" class="consult-rail" @select="selectTopic" @create="newTopic" @remove="deleteTopic" />
    <Sheet v-else v-model:open="historyOpen">
      <SheetContent side="left" class="consult-history-sheet">
        <SheetTitle class="sr-only">咨询话题</SheetTitle><SheetDescription class="sr-only">搜索、打开或管理与交易员的咨询话题</SheetDescription>
        <AssistantSessionRail v-bind="railProps" drawer @select="selectTopic" @create="newTopic" @remove="deleteTopic" @update:collapsed="historyOpen = false" />
      </SheetContent>
    </Sheet>
    <section class="consult-main">
      <header class="consult-header">
        <Button v-if="smallScreen" access="read" variant="ghost" size="icon-sm" aria-label="打开咨询历史" @click="historyOpen = true"><PanelLeftOpen class="size-4" /></Button>
        <div class="consult-heading"><h3>{{ currentTitle }}</h3><span>交易员 · {{ model || '请先配置模型' }}</span></div>
        <Badge v-if="pending" variant="info"><Spinner class="size-3" />{{ pendingLabel }}</Badge>
        <Spinner v-else-if="loading" class="size-4" aria-label="加载咨询" />
        <Button v-if="detailDrawer" access="read" variant="ghost" size="icon-sm" aria-label="打开咨询详情" @click="detailsOpen = true"><PanelRightOpen class="size-4" /></Button>
      </header>
      <Empty v-if="!turns.length && !loading" class="consult-empty">
        <EmptyHeader><EmptyMedia variant="icon"><MessageSquare /></EmptyMedia><EmptyTitle>把你的真实情况告诉交易员</EmptyTitle><EmptyDescription>例如：“我跟着买了，但买贵了 3%，现在要不要调整？”</EmptyDescription></EmptyHeader>
        <EmptyDescription>结合你的描述和当前证据讨论，不会把模拟仓当成你的实盘，也不会通过对话下单。</EmptyDescription>
      </Empty>
      <AssistantConversation v-else :key="selected" :messages="messages" :busy="pending" assistant-label="交易员" :allow-rerun="false" class="consult-conversation" @copy="copyAnswer">
        <template #after-message="{ message }"><Button v-if="failedQuestions[message.id]" access="read" variant="link" size="sm" class="consult-retry" @click="editAgain(failedQuestions[message.id]!)">重新编辑提问</Button></template>
      </AssistantConversation>
    <Alert v-if="error" variant="destructive"><AlertDescription>{{ error }}</AlertDescription></Alert>
    <div class="consult-composer">

    <InputGroup class="consult-input" aria-label="向交易员提问">
      <InputGroupTextarea ref="questionInput" v-model="question" :rows="3" maxlength="6000" aria-label="咨询问题" placeholder="说说你担心什么，或继续追问上一条建议…" :disabled="sending || deleting" class="consult-question-input" @keydown="onQuestionKeydown" />
      <InputGroupAddon align="block-end" class="consult-footer">
        <span>咨询不执行交易<span class="consult-shortcut"> · Ctrl + Enter 发送</span></span>
        <Button size="sm" class="consult-send" :disabled="!canSend" :aria-busy="sending || pending" @click="send">
          <Spinner v-if="sending || pending" class="size-3" aria-hidden="true" /><ArrowUp v-else class="size-3.5" aria-hidden="true" />
          {{ pending ? '正在研究' : sending ? '正在发送' : '发送问题' }}
        </Button>
      </InputGroupAddon>
    </InputGroup>
    </div>
    </section>
    <AssistantTaskSidebar v-if="!detailDrawer" v-bind="taskProps" v-model:open="desktopDetailsOpen" class="consult-detail">
      <template #cabin><GuardianConsultContext v-model="notes" :disabled="deleting" /></template>
    </AssistantTaskSidebar>
    <Sheet v-else v-model:open="detailsOpen">
      <SheetContent class="consult-history-sheet">
        <SheetTitle class="sr-only">咨询详情</SheetTitle><SheetDescription class="sr-only">查看研究来源与编辑本话题持仓背景</SheetDescription>
        <AssistantTaskSidebar v-bind="taskProps" :open="true" drawer @update:open="detailsOpen = $event">
          <template #cabin><GuardianConsultContext v-model="notes" :disabled="deleting" /></template>
        </AssistantTaskSidebar>
      </SheetContent>
    </Sheet>
  </SidebarProvider>
</template>

<style scoped>
.consult-panel { --ai-fs-title:var(--fs-title); --ai-fs-prose:var(--fs-body); --ai-fs-body:var(--fs-ui); --ai-fs-aux:var(--fs-aux); --ai-fs-meta:var(--fs-kicker); display:flex; flex:1 1 0%; min-width:0; min-height:0; height:100%; overflow:hidden; color:var(--ink); background:transparent; }
.consult-rail { width:240px; flex:0 0 240px; border-right:1px solid var(--rule-soft); }
.consult-rail.is-collapsed { width:48px; flex-basis:48px; }
.consult-detail { width:260px; flex:0 0 260px; min-width:0; }
.consult-detail.is-collapsed { width:44px; flex-basis:44px; }
.consult-main { display:flex; flex-direction:column; flex:1 1 0%; min-width:0; min-height:0; overflow:hidden; padding:0 20px 14px; gap:8px; }
.consult-header { display:flex; align-items:center; gap:10px; min-height:60px; flex-shrink:0; border-bottom:1px solid var(--rule-soft); }
.consult-heading { flex:1; min-width:0; }
.consult-heading h3 { margin:0; font-size:var(--fs-body); font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.consult-heading > span { color:var(--muted); font-size:var(--fs-micro); }
.consult-header :deep([data-slot=badge]) { flex-shrink:0; gap:5px; }
.consult-empty { flex:1; line-height:1.8; }
.consult-conversation :deep(.assistant-conversation__viewport) { overscroll-behavior-y:auto; }
.consult-retry { align-self:flex-start; flex-shrink:0; }
.consult-composer { flex-shrink:0; align-self:center; width:min(100%,860px); display:flex; flex-direction:column; gap:6px; padding-top:4px; }
.consult-context :deep([data-slot=accordion-trigger]) { font-size:var(--fs-aux); color:var(--muted); padding:8px 0; }
.consult-footer { display:flex; justify-content:space-between; align-items:center; flex-wrap:nowrap; gap:8px; padding:4px 10px 10px; }
.consult-footer > span { font-size:var(--fs-micro); color:var(--muted); }
.consult-input { background:var(--surface); border-radius:var(--radius-lg); }
.consult-question-input { min-height:86px; max-height:12rem; line-height:1.6; overflow-y:auto; }
.consult-send { flex-shrink:0; margin-left:auto; }
:global(.consult-history-sheet) { --ai-fs-title:var(--fs-title); --ai-fs-prose:var(--fs-body); --ai-fs-body:var(--fs-ui); --ai-fs-aux:var(--fs-aux); --ai-fs-meta:var(--fs-kicker); padding:38px 0 0; gap:0; overflow:hidden; }
:global(.consult-history-sheet .assistant-task-sidebar) { flex:1; min-height:0; width:100%; border:0; }
:global(.consult-history-sheet .assistant-session-rail) { flex:1; width:100%; min-height:0; }
@media(max-width:700px) { .consult-main { padding:0 12px 10px; } .consult-shortcut { display:none; } .consult-header { min-height:56px; } }
</style>
