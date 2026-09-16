<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { askGuardian, getGuardianConversation, getGuardianConversations } from '@/shared/api/guardian'
import { renderAssistantMarkdown } from '@/features/ai/assistantMarkdown'
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
const loading = ref(false)
const history = ref<HTMLElement>()
const pending = computed(() => turns.value.some(t => ['queued', 'running'].includes(t.status)))
const renderedAnswers = computed(() => Object.fromEntries(turns.value.map(t => [t.id, renderAssistantMarkdown(t.result.answer || '')])))
let controller: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let retryPayload: Parameters<typeof askGuardian>[0] | null = null
function newTopic() { controller?.abort(); clearTimeout(timer); selected.value = createUuid(); turns.value = []; question.value = ''; error.value = ''; retryPayload = null }
async function load(id: string, restoreNotes = false) {
  controller?.abort(); const request = new AbortController(); controller = request
  loading.value = true
  try {
    const detail = await getGuardianConversation(id, request.signal)
    if (disposed || request.signal.aborted || selected.value !== id) return
    turns.value = detail.turns
    if (restoreNotes) notes.value = detail.notes
    error.value = ''
    clearTimeout(timer)
    if (pending.value) timer = setTimeout(() => void load(id), 2500)
    await nextTick()
    if (history.value) history.value.scrollTop = history.value.scrollHeight
  } catch (e) {
    if (!request.signal.aborted) {
      error.value = e instanceof Error ? e.message : String(e)
      if (pending.value && !disposed) timer = setTimeout(() => void load(id), 5000)
    }
  } finally { if (controller === request) loading.value = false }
}
async function send() {
  if (!question.value.trim() || sending.value || pending.value) return
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
onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
</script>

<template>
  <section class="consult-panel" aria-label="与交易员沟通">
    <header><div><h3>与交易员沟通</h3><p>{{ model || '请先配置模型' }} · 自动带入模拟账户、近期研判和复盘</p></div><div class="consult-tools"><el-select v-if="conversations.length" v-model="selected" aria-label="咨询话题" :disabled="sending" @change="load(selected, true)"><el-option v-for="item in conversations" :key="item.id" :value="item.id" :label="item.title" /></el-select><el-button :disabled="sending" @click="newTopic">新话题</el-button></div></header>
    <div ref="history" class="consult-history" role="log" aria-label="咨询消息" aria-live="polite" :aria-busy="loading">
      <div v-if="!turns.length" class="consult-empty"><h4>把你的真实情况告诉交易员</h4><p>例如：“我跟着买了，但买贵了 3%，现在要不要调整？”</p><p>它会结合你的描述和当前证据讨论，不会把模拟仓当成你的实盘，也不会通过对话下单。</p></div>
      <article v-for="turn in turns" :key="turn.id" class="consult-turn"><div class="consult-question"><b>你</b><p>{{ turn.question }}</p></div><div class="consult-answer"><b>交易员 <small v-if="turn.result.model">{{ turn.result.model }}</small><small v-if="turn.result.as_of">{{ turn.result.as_of.slice(0, 16).replace('T', ' ') }}</small></b><div v-if="turn.result.answer" class="consult-rich" v-html="renderedAnswers[turn.id]" /><el-alert v-else-if="turn.status === 'failed'" :title="turn.result.error || '咨询未完成，请重新提问'" type="warning" :closable="false" /><p v-else class="consult-pending">正在读取账户、查询证据并形成建议…</p><el-button v-if="turn.status === 'failed'" link @click="question = turn.question">重新编辑提问</el-button></div></article>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-collapse class="consult-context"><el-collapse-item title="我的实际持仓 / 执行偏差（选填，随话题保存）" name="notes"><el-input v-model="notes" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" maxlength="12000" placeholder="写明股票名称或代码、实际股数、成本、买入日期、可用现金，以及和模拟操作有哪些不同。这里只保存咨询背景，不会修改模拟账户。" /></el-collapse-item></el-collapse>
    <el-input v-model="question" type="textarea" :autosize="{ minRows: 3, maxRows: 7 }" maxlength="6000" aria-label="咨询问题" placeholder="说说你担心什么，或继续追问上一条建议…" :disabled="sending" @keydown.ctrl.enter.prevent="send" />
    <footer><span>实际情况以你的描述为准 · 咨询不执行交易 · Ctrl + Enter 发送</span><el-button type="primary" :loading="sending || pending" :disabled="!model || !selected || !question.trim() || pending || loading" @click="send">{{ pending ? '正在研究' : '发送问题' }}</el-button></footer>
  </section>
</template>

<style scoped>
.consult-panel { display:flex; flex-direction:column; gap:var(--gap-2); padding:var(--gap-3); background:var(--surface); border:1px solid var(--rule); border-radius:var(--radius); min-width:0; min-height:0; overflow:hidden; flex:1 1 auto; }
header, footer, .consult-tools { display:flex; align-items:center; justify-content:space-between; gap:var(--gap-3); flex-wrap:wrap; }
h3 { font-size:var(--fs-body); margin:0; } header p, footer span { font-size:var(--fs-aux); color:var(--muted); margin:var(--gap-1) 0; }
.consult-tools .el-select { width:230px; max-width:100%; }
.consult-history { flex:1 1 auto; min-height:0; overflow:auto; overscroll-behavior:contain; padding:var(--gap-3); border:1px solid var(--rule-soft); border-radius:var(--radius); background:var(--surface-canvas); }
.consult-empty { text-align:center; padding:var(--gap-4) var(--gap-3); color:var(--muted); line-height:1.9; }
.consult-empty h4 { color:var(--ink); font-weight:500; }
.consult-turn { margin-bottom:var(--gap-4); font-size:var(--fs-body); line-height:1.9; }
.consult-turn p { white-space:pre-wrap; overflow-wrap:anywhere; margin:var(--gap-2) 0 0; }
.consult-rich :deep(p) { margin: var(--gap-2) 0; white-space: normal; }
.consult-rich :deep(ul), .consult-rich :deep(ol) { padding-left: 1.5em; margin: var(--gap-2) 0; }
.consult-rich :deep(ul) { list-style: disc; } .consult-rich :deep(ol) { list-style: decimal; }
.consult-rich :deep(a) { color: var(--seal-ink); text-decoration: underline; overflow-wrap: anywhere; }
.consult-question { margin-left:10%; background:var(--surface-sunken); border:1px solid var(--rule); border-radius:var(--radius); padding:var(--gap-3); }
.consult-answer { padding:var(--gap-3) 0; } .consult-answer small { font-weight:400; color:var(--muted); margin-left:var(--gap-2); } .consult-pending { color:var(--muted); }
.consult-context :deep(.el-collapse-item__header) { font-size:var(--fs-aux); color:var(--muted); }
@media(max-width:650px) { .consult-question { margin-left:0; } .consult-tools .el-select { width:190px; } .consult-panel { padding:var(--gap-3); } }
.consult-panel > header, .consult-panel > footer, .consult-context { flex-shrink:0; }
.consult-panel > header { padding-bottom:var(--gap-2); border-bottom:1px solid var(--rule); }
.consult-panel > footer { padding-top:var(--gap-1); }
.consult-rich :deep(pre) { max-width:100%; overflow:auto; }
.consult-rich :deep(table) { display:block; max-width:100%; overflow:auto; }
@media(max-height:640px) { .consult-panel { overflow:auto; } .consult-history { flex:0 0 auto; max-height:50dvh; } }
</style>
