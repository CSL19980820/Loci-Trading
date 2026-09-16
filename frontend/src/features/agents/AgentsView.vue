<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Search, Compass, Cpu, Flag, ArrowRight } from '@element-plus/icons-vue'
import { getProviders } from '@/shared/api/quant'
import { createStockAgent, getAgentOptions, getStockAgents, getGuardianCard } from '@/shared/api/stock_agents'
import type { AgentConfig, AgentKind, AgentOptions, AgentSummary, GuardianCard } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
import AgentConfigDrawer from './components/AgentConfigDrawer.vue'
import { actionName, agentMoney, agentTime, phaseName, statusName } from './agentFormat'
const router = useRouter()
const guardian = shallowRef<GuardianCard | null>(null)
const agents = shallowRef<AgentSummary[]>([])
const query = ref('')
const filter = ref('all')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const guardianError = ref('')
const settingsError = ref('')
const options = shallowRef<AgentOptions | null>(null)
const providers = shallowRef<LlmProvider[]>([])
const creating = shallowRef<AgentConfig | null>(null)
const drawer = ref(false)
const lastLoaded = ref('')
let disposed = false
let controller:AbortController | undefined
let timer:ReturnType<typeof setTimeout> | undefined
const filtered = computed(() => agents.value.filter(agent => {
  const match = `${agent.config.name} ${agent.config.description}`.toLowerCase().includes(query.value.trim().toLowerCase())
  return match && (filter.value === 'all' || (filter.value === 'enabled' ? agent.config.enabled : !agent.config.enabled))
}))
const showGuardian = computed(() => !query.value.trim() || '自主交易员 自有策略 持仓管理'.includes(query.value.trim()))
const guardianVisible = computed(() => showGuardian.value && (filter.value === 'all' || (filter.value === 'enabled' ? guardian.value?.config.enabled : !guardian.value?.config.enabled)))
const countEnabled = computed(() => agents.value.filter(a => a.config.enabled).length + Number(guardian.value?.config.enabled ?? false))
const lastGuardian = computed(() => guardian.value?.runs[0])
const lastGuardianAt = computed(() => lastGuardian.value?.result.as_of || (lastGuardian.value?.started ? new Date(lastGuardian.value.started * 1000).toISOString() : null))
const lastGuardianSummary = computed(() => lastGuardian.value?.result.error || lastGuardian.value?.result.analysis || (lastGuardian.value ? '查看最近研判及实际操作记录' : '围绕已启用的工坊战法，研究候选并管理自有模拟持仓。'))
async function load() {
  if (loading.value || disposed) return
  controller = new AbortController()
  const request = controller
  loading.value = true
  await Promise.all([
    getGuardianCard(request.signal).then(value => { if (!disposed && !request.signal.aborted) { guardian.value = value; guardianError.value = '' } }).catch(e => { if (!request.signal.aborted) guardianError.value = e instanceof Error ? e.message : String(e) }),
    getStockAgents(request.signal).then(value => { if (!disposed && !request.signal.aborted) { agents.value = value.items; lastLoaded.value = value.as_of; error.value = '' } }).catch(e => { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }),
  ])
  if (!disposed) loading.value = false
}
async function poll() { if (disposed) return; if (!document.hidden && !drawer.value && !busy.value) await load(); if (!disposed) timer = setTimeout(poll, 15000) }
async function configure(kind:AgentKind) {
  if (busy.value) return
  busy.value = true; settingsError.value = ''; error.value = ''
  try {
    const [nextOptions, nextProviders] = await Promise.all([getAgentOptions(), getProviders()])
    if (disposed) return
    options.value = nextOptions; providers.value = nextProviders.filter(p => p.is_active)
    creating.value = JSON.parse(JSON.stringify(nextOptions.templates[kind])); drawer.value = true
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function save(config:AgentConfig) {
  busy.value = true; settingsError.value = ''
  try { const profile = await createStockAgent(config); if (!disposed) { drawer.value = false; await router.push(`/agents/${profile.id}`) } }
  catch(e) { if (!disposed) settingsError.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
onMounted(() => { void load(); timer = setTimeout(poll, 15000) })
onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
</script>
<template>
  <main class="agents-page">
    <header class="agents-heading"><div><div class="eyebrow">我的 / 智能体</div><h1>让每个智能体，各司其职。</h1><p>独立的研究方向、工作日程与模拟账户。重要操作，一眼可见。</p></div><el-button type="primary" size="large" :icon="Plus" :loading="busy" @click="configure('custom')">新建智能体</el-button></header>
    <div class="agents-overview"><span><b>{{ agents.length + 1 }}</b> 个智能体</span><span><i class="status-dot" /><b>{{ countEnabled }}</b> 个已启用</span><span class="overview-note">模拟交易 · 人民币账户 · 北京时间</span></div>
    <section class="agents-toolbar" aria-label="筛选智能体"><div class="filter-tabs"><button v-for="tab in [{ id:'all', name:'全部' }, { id:'enabled', name:'已启用' }, { id:'paused', name:'已暂停' }]" :key="tab.id" :class="{ selected:filter === tab.id }" :aria-pressed="filter === tab.id" @click="filter = tab.id">{{ tab.name }}</button></div><div class="toolbar-right"><el-input v-model="query" :prefix-icon="Search" placeholder="搜索名称或职责" clearable class="agent-search" /><el-button :icon="Refresh" circle :loading="loading" aria-label="刷新智能体列表" @click="load" /></div></section>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="list-error"><el-button link @click="load">重新加载</el-button></el-alert>
    <div v-if="loading && !lastLoaded" class="agents-grid"><el-skeleton v-for="n in 2" :key="n" :rows="7" animated class="agent-card" /></div>
    <div v-else class="agents-grid">
      <article v-if="guardianVisible" class="agent-card guardian-card">
        <div class="card-top"><span class="agent-avatar"><el-icon><Compass /></el-icon></span><div class="identity"><RouterLink to="/agents/guardian"><h2>自主交易员</h2></RouterLink><span>自有战法 · 持仓管理</span></div><span class="agent-status" :class="{ enabled:guardian?.config.enabled }"><i />{{ guardianError ? '加载异常' : lastGuardian?.status === 'running' ? '正在研究' : guardian?.config.enabled ? '已启用' : '已暂停' }}</span></div>
        <p class="agent-description">管理你的工坊策略与自有交易。原有算法、提示词和交易规则保持独立。</p>
        <div class="card-work"><div class="work-meta"><span>最近一次工作</span><time>{{ agentTime(lastGuardianAt) }}</time></div><p>{{ guardianError || lastGuardianSummary }}</p><div class="operation-chips"><span v-for="(trade, i) in lastGuardian?.result.fills?.slice(0,3)" :key="i">{{ actionName(trade.action || trade.side) }} {{ trade.name || trade.code }}<small>模拟成交</small></span><span v-if="!lastGuardian?.result.fills?.length" class="no-action">{{ lastGuardian ? '最近一轮无模拟成交' : '等待首次工作' }}</span></div></div>
        <div class="card-account"><div><label>模拟净资产</label><strong>{{ agentMoney(guardian?.state.equity_cents) }}</strong></div><div><label>累计盈亏</label><strong :class="{ gain:(guardian?.state.total_pnl_cents ?? 0)>0, loss:(guardian?.state.total_pnl_cents ?? 0)<0 }">{{ agentMoney(guardian?.state.total_pnl_cents) }}</strong></div><div><label>当前持仓</label><strong>{{ guardian ? guardian.state.positions.length : '—' }}<small>只</small></strong></div></div>
        <footer><span>{{ guardian?.config.model || '尚未配置模型' }}</span><RouterLink to="/agents/guardian">进入工作室<el-icon><ArrowRight /></el-icon></RouterLink></footer>
      </article>
      <article v-for="agent in filtered" :key="agent.id" class="agent-card" :class="{ 'leader-card':agent.config.kind === 'leader' }">
        <div class="card-top"><span class="agent-avatar"><el-icon><Flag v-if="agent.config.kind === 'leader'" /><Cpu v-else /></el-icon></span><div class="identity"><RouterLink :to="`/agents/${agent.id}`"><h2>{{ agent.config.name }}</h2></RouterLink><span>{{ agent.config.kind === 'leader' ? '龙头研究 · 节奏与接力' : '自定义研究 · 独立账户' }}</span></div><span class="agent-status" :class="{ enabled:agent.config.enabled, failed:['failed','interrupted'].includes(agent.latest_status || '') }"><i />{{ agent.running ? '正在研究' : ['failed','interrupted'].includes(agent.latest_status || '') ? statusName(agent.latest_status) : agent.config.enabled ? '已启用' : '已暂停' }}</span></div>
        <p class="agent-description">{{ agent.config.description || '按设定的模型、提示词与交易约束，独立完成研究和模拟交易。' }}</p>
        <div class="card-work"><div class="work-meta"><span>{{ agent.latest_phase ? phaseName(agent.latest_phase) : '最近一次工作' }}</span><time>{{ agentTime(agent.latest_at) }}</time></div><p>{{ agent.latest_summary || '还没有工作记录。完成配置并启用后，将按日程开始研究。' }}</p><div class="operation-chips"><span v-for="(action,i) in agent.latest_actions.slice(0,3)" :key="i">{{ actionName(action.action) }} {{ action.name || action.code }}<small>{{ statusName(action.status) }}</small></span><span v-if="!agent.latest_actions.length" class="no-action">{{ agent.total_runs ? '最近一轮无操作' : '等待首次工作' }}</span></div></div>
        <div class="card-account"><div><label>模拟净资产</label><strong>{{ agentMoney(agent.state.equity_cents) }}</strong></div><div><label>累计盈亏</label><strong :class="{ gain:agent.state.total_pnl_cents>0, loss:agent.state.total_pnl_cents<0 }">{{ agentMoney(agent.state.total_pnl_cents) }}</strong></div><div><label>当前持仓</label><strong>{{ agent.state.position_count }}<small>只</small></strong></div></div>
        <footer><span>{{ agent.config.model || '尚未配置模型' }} · {{ agent.total_runs }} 次工作</span><RouterLink :to="`/agents/${agent.id}`">进入工作室<el-icon><ArrowRight /></el-icon></RouterLink></footer>
      </article>
      <div v-if="!filtered.length && !guardianVisible" class="empty-agents"><el-icon><Search /></el-icon><h3>没有匹配的智能体</h3><p>调整搜索内容或状态筛选。</p></div>
    </div>
    <section class="agent-template"><div class="template-symbol"><el-icon><Flag /></el-icon></div><div class="template-copy"><span class="eyebrow">内置模板</span><h2>龙头选手</h2><p>1进2、2进3、接力与龙空龙。盘前计划、09:25竞价研判、20:00晚间复盘，形成完整研究节奏。</p><div class="template-terms"><span>每日入选 ≤ 3</span><span>观察 ≤ 3</span><span>常态持仓 ≤ 3 · 临时 ≤ 5</span></div></div><el-button :icon="Plus" :loading="busy" @click="configure('leader')">创建龙头选手</el-button></section>
    <p class="list-footnote">{{ lastLoaded ? `状态更新于 ${agentTime(lastLoaded)}。` : '' }}账户估值来自最近一次实际行情记录，不代表实时成交保证。新建智能体默认暂停。</p>
    <AgentConfigDrawer v-if="creating && options" v-model="drawer" :config="creating" :options="options" :providers="providers" :busy="busy" :error="settingsError" creating @save="save" />
  </main>
</template>
<style scoped>
.agents-page { max-width:1440px; padding:32px; margin:0 auto; width:100%; box-sizing:border-box; color:var(--ink); }.agents-heading { display:flex; justify-content:space-between; align-items:center; gap:24px; margin-bottom:28px; }.eyebrow { font-size:11px; letter-spacing:.12em; color:var(--muted); margin-bottom:10px; }h1 { font-size:clamp(23px,2.1vw,31px); font-weight:600; letter-spacing:-.04em; margin:0 0 12px; }.agents-heading p,.agent-description { color:var(--muted); line-height:1.7; font-size:13px; margin:0; }.agents-overview { display:flex; align-items:center; gap:28px; padding:18px 0 24px; border-bottom:1px solid var(--line); font-size:13px; color:var(--muted); }.agents-overview span { display:flex; align-items:center; gap:8px; }.agents-overview b { color:var(--ink); font-size:18px; font-variant-numeric:tabular-nums; font-weight:550; }.overview-note { margin-left:auto; font-size:12px; }.status-dot,.agent-status i { width:6px; height:6px; display:inline-block; border-radius:50%; background:var(--muted); }.status-dot { background:var(--el-color-success); }.agents-toolbar { display:flex; justify-content:space-between; gap:20px; margin:26px 0 20px; }.filter-tabs { display:flex; gap:6px; }.filter-tabs button { border:0; border-radius:6px; padding:8px 16px; font-size:13px; color:var(--muted); background:transparent; cursor:pointer; white-space:nowrap; }.filter-tabs button.selected { color:var(--ink); background:var(--el-fill-color); font-weight:600; }.toolbar-right { display:flex; gap:12px; align-items:center; }.agent-search { width:230px; }.agents-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:22px; }.agent-card { border:1px solid var(--line); border-radius:12px; background:var(--el-bg-color); padding:26px; min-width:0; box-sizing:border-box; transition:border-color .18s,box-shadow .18s; }.agent-card:hover { border-color:var(--el-color-primary-light-5); box-shadow:0 8px 24px rgba(0,0,0,.025); }.card-top { display:flex; gap:14px; align-items:center; margin-bottom:19px; }.agent-avatar { display:grid; place-items:center; flex-shrink:0; width:44px; height:44px; border-radius:12px; background:var(--el-fill-color-light); color:var(--seal-ink,var(--el-color-primary)); font-size:24px; }.identity { min-width:0; }.identity a { text-decoration:none; color:inherit; }.identity h2 { font-size:17px; margin:0 0 5px; font-weight:650; overflow-wrap:anywhere; }.identity span { color:var(--muted); font-size:11px; }.agent-status { margin-left:auto; display:inline-flex; align-items:center; gap:6px; font-size:11px; white-space:nowrap; color:var(--muted); }.agent-status.enabled i { background:var(--el-color-success); }.agent-status.failed { color:var(--el-color-danger); }.agent-status.failed i { background:var(--el-color-danger); }.agent-description { min-height:44px; font-size:12px; }.card-work { margin-top:20px; padding:17px 18px; background:var(--el-fill-color-lighter); border-radius:8px; }.work-meta { display:flex; justify-content:space-between; gap:12px; color:var(--muted); font-size:11px; }.card-work p { font-size:13px; line-height:1.85; margin:12px 0; min-height:48px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }.operation-chips { display:flex; flex-wrap:wrap; gap:6px; min-height:22px; }.operation-chips>span { font-size:11px; padding:4px 7px; background:var(--el-bg-color); border:1px solid var(--line); border-radius:4px; }.operation-chips small { color:var(--muted); margin-left:7px; font-size:10px; }.operation-chips .no-action { background:transparent; border-color:transparent; padding-left:0; color:var(--muted); }.card-account { display:grid; grid-template-columns:1.3fr 1.2fr .7fr; gap:12px; margin:24px 0; }.card-account label { display:block; color:var(--muted); font-size:11px; margin-bottom:10px; }.card-account strong { font-size:clamp(15px,1.4vw,21px); font-weight:550; font-variant-numeric:tabular-nums; letter-spacing:-.02em; }.card-account strong small { font-size:11px; color:var(--muted); margin-left:5px; }.gain { color:var(--el-color-danger); }.loss { color:var(--el-color-success); }footer { border-top:1px solid var(--line); padding-top:17px; display:flex; justify-content:space-between; align-items:center; gap:16px; font-size:11px; }footer>span { color:var(--muted); overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }footer a { display:flex; align-items:center; gap:7px; text-decoration:none; color:var(--seal-ink,var(--el-color-primary)); white-space:nowrap; }.agent-template { margin-top:32px; padding:27px 30px; display:flex; align-items:center; gap:25px; border:1px dashed var(--el-border-color); border-radius:12px; }.template-symbol { width:56px; height:56px; border-radius:50%; background:var(--el-fill-color-light); display:grid; place-items:center; font-size:27px; flex-shrink:0; color:var(--seal-ink,var(--el-color-primary)); }.template-copy { flex:1; }.template-copy h2 { font-size:18px; margin:5px 0 10px; }.template-copy p { font-size:12px; line-height:1.8; color:var(--muted); margin:0 0 13px; }.template-terms { display:flex; flex-wrap:wrap; gap:8px 18px; font-size:11px; color:var(--muted); }.list-footnote { font-size:11px; color:var(--muted); margin:20px 0; line-height:1.8; }.empty-agents { grid-column:1/-1; text-align:center; padding:50px; color:var(--muted); }.empty-agents>.el-icon { font-size:30px; }.empty-agents h3 { font-size:15px; }.empty-agents p { font-size:12px; }.list-error { margin-bottom:20px; }
@media(min-width:1700px) { .agents-page { padding-top:40px; } }
@media(max-width:960px) { .agents-page { padding:22px; }.agents-grid { grid-template-columns:1fr; }.overview-note { display:none!important; }.agent-template { padding:22px; flex-wrap:wrap; }.agent-template>.el-button { margin-left:81px; }.card-account strong { font-size:22px; } }
@media(max-width:600px) { .agents-page { padding:16px 12px; }.agents-heading { align-items:flex-start; flex-direction:column; gap:18px; }.agents-heading h1 { font-size:23px; }.agents-toolbar { flex-direction:column; gap:14px; }.toolbar-right { width:100%; }.agent-search { flex:1; }.agent-card { padding:19px; }.agent-status { font-size:10px; }.identity h2 { font-size:16px; }.card-account strong { font-size:18px; }.agent-template { padding:20px; gap:15px; }.template-symbol { display:none; }.agent-template>.el-button { margin-left:0; } }
</style>
