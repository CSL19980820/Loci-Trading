<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { computed, onMounted, ref } from 'vue'
import { Archive, LoaderCircle, RefreshCw, Save } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { quantRequest } from '@/shared/api/quant_client'
import { getStockAgents, getStockAgent, saveStockAgent, cleanAgentDiary } from '@/shared/api/stock_agents'
import type { AgentProfile, AgentSummary } from '@/shared/types/stock_agents'
import { confirmAction } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import GuardianStoragePanel from '@/features/agents/components/GuardianStoragePanel.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Switch } from '@/shared/components/ui/switch'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import WorkspaceLoading from '@/shared/components/ui/WorkspaceLoading.vue'

type Policy = { enabled: boolean } & Record<string, number | boolean>
type Snapshot = { policy: Policy; revision: number; global_scope: boolean; jobs: Array<{ id: string; name: string; cron: string; enabled: boolean }> }
const snapshot = ref<Snapshot | null>(null)
const draft = ref<Policy>({ enabled: true })
const baseline = ref('')
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const agents = ref<AgentSummary[]>([])
const agentError = ref('')
const selected = ref<AgentProfile | null>(null)
const agentOpen = ref(false)
const diary = ref({ days: 30, max_entries: 2000, cleanup_hours: 24 })
let pending: Promise<void> | null = null
const groups = [
  { label: '平台日志', global: true, fields: [['login_days','登录日志'],['audit_days','审计日志'],['notification_days','已读通知'],['usage_days','用量记录']] },
  { label: '运行日志', fields: [['job_days','定时执行'],['monitor_days','监控运行'],['alert_days','告警命中'],['decision_days','智能判断'],['leader_days','角色观测'],['quota_days','工具调用记录']] },
  { label: '助手与运行产物', fields: [['ai_event_days','助手事件'],['ai_grant_days','执行授权'],['skill_days','技能运行产物'],['research_days','研究运行产物']] },
  { label: '共享数据', global: true, fields: [['intraday_days','盘中留存'],['community_days','社区事件']] },
]
const isDirty = () => Boolean(snapshot.value) && JSON.stringify(draft.value) !== baseline.value
const canSave = computed(() => Boolean(snapshot.value) && !busy.value && !loading.value && isDirty())
function accept(value: Snapshot): void { snapshot.value = value; draft.value = { ...value.policy }; baseline.value = JSON.stringify(draft.value) }
async function load(): Promise<void> {
  if (pending) return pending
  loading.value = true; error.value = ''
  pending = (async () => {
    try { accept(await quantRequest<Snapshot>('/ops/settings/retention')) }
    catch (e) { error.value = toErrorMessage(e, '读取保留设置失败') }
    finally { loading.value = false; pending = null }
    try { agents.value = (await getStockAgents()).items; agentError.value = '' }
    catch (e) { agentError.value = toErrorMessage(e, '读取智能体失败') }
  })()
  return pending
}
async function save(): Promise<void> {
  if (!snapshot.value || !canSave.value) return
  busy.value = true; error.value = ''
  try { accept(await quantRequest<Snapshot>('/ops/settings/retention', { method: 'PUT', body: JSON.stringify({ policy: draft.value, revision: snapshot.value.revision }) })); toast.success('保留设置已保存，清理任务将使用新设置') }
  catch (e) { error.value = toErrorMessage(e, '保存失败') }
  finally { busy.value = false }
}
function numberValue(key: string): number { return Number(draft.value[key] ?? 0) }
function setNumber(key: string, value: string | number): void { const n = Number(value); if (Number.isFinite(n)) draft.value[key] = n }
function jobDisplayName(name: string): string { return name === '租户库清理' ? '运行日志清理' : name }
async function runMaintenance(job: Snapshot['jobs'][number]): Promise<void> {
  if (busy.value || isDirty() || !snapshot.value?.policy.enabled) return
  if (!(await confirmAction({ title: '按保留策略清理', message: `执行“${jobDisplayName(job.name)}”，删除超出已保存保留期或条数上限的日志及运行产物。账本、持仓、成交、策略源文件不删除。`, confirmText: '执行清理', danger: true }))) return
  busy.value = true
  try { await quantRequest(`/jobs/${encodeURIComponent(job.id)}/run`, { method: 'POST' }); toast.success('清理任务已提交，可在执行记录查看结果') }
  catch (e) { error.value = toErrorMessage(e, '提交清理失败') }
  finally { busy.value = false }
}
async function configureAgent(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true; agentError.value = ''
  try { selected.value = await getStockAgent(id); diary.value = { ...selected.value.config.retention }; agentOpen.value = true }
  catch (e) { agentError.value = toErrorMessage(e, '读取智能体失败') }
  finally { busy.value = false }
}
async function saveDiary(): Promise<void> {
  if (!selected.value || busy.value) return
  busy.value = true
  try { selected.value = await saveStockAgent(selected.value.id, { ...selected.value.config, retention: { ...diary.value } }, selected.value.revision); agentOpen.value = false; toast.success('智能体日志保留设置已保存') }
  catch (e) { agentError.value = toErrorMessage(e, '保存失败，请重新打开读取最新配置') }
  finally { busy.value = false }
}
async function cleanupDiary(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true; agentError.value = ''
  try {
    const preview = await cleanAgentDiary(id, true)
    if (!preview.eligible) { toast.info('没有符合清理条件的详细日志'); return }
    if (!(await confirmAction({ title: '压缩过期日志', message: `压缩 ${preview.eligible} 条过期详细上下文；保留摘要、财务账本和受保护的运行记录。`, confirmText: '清理', danger: true }))) return
    const result = await cleanAgentDiary(id, false); toast.success(`已压缩 ${result.removed} 条详细日志`)
  } catch (e) { agentError.value = toErrorMessage(e, '清理失败') }
  finally { busy.value = false }
}
onMounted(() => { void load() })
defineExpose({ load, isDirty })
</script>
<template>
  <section class="retention-settings">
    <div class="retention-toolbar">
      <Label class="retention-toggle"><Switch :model-value="draft.enabled" :disabled="!snapshot || loading || busy" @update:model-value="draft.enabled = $event" />定期保留策略</Label>
      <span class="retention-caption">天数 0 表示不按时间清理；任务条数上限独立生效</span>
      <div class="retention-actions"><Button access="read" variant="outline" size="sm" :disabled="loading || busy || isDirty()" @click="load"><RefreshCw />刷新</Button><Button size="sm" :disabled="!canSave" @click="save"><LoaderCircle v-if="busy" class="animate-spin" /><Save v-else />保存</Button></div>
    </div>
    <Alert v-if="error" variant="destructive"><AlertTitle>{{ error }}</AlertTitle></Alert>
    <WorkspaceLoading v-if="loading && !snapshot" label="读取日志保留策略…" />
    <template v-if="snapshot">
      <div class="retention-groups"><section v-for="group in groups" :key="group.label" class="retention-group"><h3>{{ group.label }}<span v-if="group.global && !snapshot.global_scope">仅主管理员可调整</span></h3><Label v-for="[key, label] in group.fields" :key="key" class="retention-field"><span>{{ label }}</span><Input type="number" :min="0" :max="3650" :step="1" :model-value="numberValue(key!)" :aria-label="`${label}保留天数`" :disabled="loading || busy || (group.global && !snapshot.global_scope)" @update:model-value="setNumber(key!, $event)" /><small>天</small></Label></section></div>
      <section class="retention-counts"><Label v-for="[key, label, min] in [['job_keep_min','每项任务保底',1],['job_keep_max','每项任务上限',1],['ai_session_keep','助手会话上限',0]]" :key="String(key)" class="retention-field"><span>{{ label }}</span><Input type="number" :min="Number(min)" :max="100000" :step="1" :model-value="numberValue(String(key))" :aria-label="String(label)" :disabled="loading || busy" @update:model-value="setNumber(String(key), $event)" /><small>条</small></Label></section>
      <div class="retention-jobs"><div v-for="job in snapshot.jobs" :key="job.id" class="retention-job"><span>{{ jobDisplayName(job.name) }}</span><code>{{ job.cron }}</code><small>{{ job.enabled ? '定时启用' : '定时已停用' }}</small><Button variant="outline" size="xs" :disabled="busy || isDirty() || !snapshot.policy.enabled" @click="runMaintenance(job)"><Archive />立即清理</Button></div><Button access="read" as-child size="xs" variant="ghost"><RouterLink to="/quant?tab=jobs">执行记录</RouterLink></Button></div>
      <p class="retention-caption">保存不立即删除数据。正在运行的任务、财务账本、持仓、成交和策略源文件不作为日志清理；智能体日记使用下面各自的策略。</p>
    </template>
    <section class="retention-agent-section"><h3>自主交易员</h3><GuardianStoragePanel expanded /></section>
    <Alert v-if="agentError" variant="destructive"><AlertTitle>{{ agentError }}</AlertTitle></Alert>
    <section v-if="agents.length" class="retention-agent-section"><h3>股票智能体</h3><div v-for="agent in agents" :key="agent.id" class="retention-job"><span>{{ agent.config.name }}</span><div class="retention-actions"><Button variant="outline" size="sm" :disabled="busy" @click="configureAgent(agent.id)">保留策略</Button><Button variant="outline" size="sm" :disabled="busy" @click="cleanupDiary(agent.id)">清理过期详情</Button></div></div></section>
    <Dialog v-model:open="agentOpen"><DialogContent class="sm:max-w-lg"><DialogHeader><DialogTitle>{{ selected?.config.name }} · 日记保留</DialogTitle></DialogHeader><Alert v-if="agentError" variant="destructive"><AlertTitle>{{ agentError }}</AlertTitle></Alert><Label v-for="[key,label,max] in [['days','保留天数',3650],['max_entries','条数上限',100000],['cleanup_hours','清理间隔（小时）',168]]" :key="String(key)" class="retention-field"><span>{{ label }}</span><Input type="number" :min="key === 'cleanup_hours' ? 1 : 0" :max="Number(max)" :model-value="diary[key as keyof typeof diary]" :disabled="busy" @update:model-value="diary[key as keyof typeof diary] = Number($event)" /></Label><p class="retention-caption">天数和条数 0 关闭对应限制；非零条数至少 20。清理不会删除财务账本。</p><DialogFooter><Button access="read" variant="outline" :disabled="busy" @click="agentOpen = false">取消</Button><Button :disabled="busy" @click="saveDiary">保存</Button></DialogFooter></DialogContent></Dialog>
  </section>
</template>
<style scoped>
.retention-settings { display:flex; flex-direction:column; gap:12px; min-width:0; }
.retention-toolbar,.retention-toggle,.retention-actions,.retention-job { display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; }
.retention-toggle { font-size:var(--fs-ui); }
.retention-actions { margin-left:auto; }
.retention-caption { margin:0; font-size:var(--fs-aux); color:var(--text-tertiary); line-height:1.6; }
.retention-groups { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.retention-group,.retention-agent-section { padding:12px 14px; border:1px solid var(--border-subtle); border-radius:var(--radius-lg); background:var(--surface); }
h3 { display:flex; gap:10px; margin:0 0 10px; font-size:var(--fs-ui); font-weight:600; }
h3 span { font-weight:400; font-size:var(--fs-aux); color:var(--text-tertiary); }
.retention-field { display:grid; grid-template-columns:minmax(0,1fr) 90px auto; align-items:center; gap:8px; min-height:38px; font-size:var(--fs-ui); }
.retention-field small { color:var(--text-tertiary); }
.retention-field :deep(input) { text-align:right; font-variant-numeric:tabular-nums; }
.retention-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
.retention-job { min-height:38px; font-size:var(--fs-ui); }
.retention-job code,.retention-job small { font-size:var(--fs-aux); color:var(--text-tertiary); }
@media(max-width:1180px) { .retention-counts { grid-template-columns:minmax(0,1fr); gap:4px; } }
@media(max-width:640px) { .retention-groups { grid-template-columns:minmax(0,1fr); } .retention-toolbar > .retention-caption { order:3; } }
</style>
