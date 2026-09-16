<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, Refresh, VideoPlay, VideoPause, Plus, Cpu, Flag, Clock, Delete } from '@element-plus/icons-vue'
import { getProviders } from '@/shared/api/quant'
import { archiveStockAgent, cleanAgentDiary, fundAgent, getAgentEquity, getAgentOptions, getStockAgent, runStockAgent, saveStockAgent } from '@/shared/api/stock_agents'
import type { AgentConfig, AgentEquity, AgentHistoryKind, AgentOptions, AgentPhase, AgentProfile } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
import AgentConfigDrawer from './AgentConfigDrawer.vue'
import AgentEquityChart from './AgentEquityChart.vue'
import AgentHistoryPanel from './AgentHistoryPanel.vue'
import { actionName, agentMoney, agentTime, phaseName, requestKey, statusName } from '../agentFormat'
const props = defineProps<{ id:string }>()
const router = useRouter()
const data = shallowRef<AgentProfile | null>(null)
const options = shallowRef<AgentOptions | null>(null)
const providers = shallowRef<LlmProvider[]>([])
const points = shallowRef<AgentEquity[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const readError = ref('')
const chartError = ref('')
const settingsError = ref('')
const settingsOpen = ref(false)
const fundingOpen = ref(false)
const fundingAmount = ref(10000)
const fundingError = ref('')
const pendingFunding = ref<{ key:string; cents:number } | null>(null)
const tab = ref<'account' | AgentHistoryKind>('account')
const lastRefresh = ref('')
let disposed = false
let controller:AbortController | undefined
let timer:ReturnType<typeof setTimeout> | undefined
let version = 0
const snapshotKey = computed(() => `${data.value?.state_version}:${data.value?.total_runs}:${data.value?.latest_status}:${data.value?.cleaned_runs}`)
const historyKind = computed<AgentHistoryKind>(() => tab.value === 'account' ? 'runs' : tab.value)
const today = computed(() => new Intl.DateTimeFormat('sv-SE',{ timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date(lastRefresh.value || Date.now())))
const selectedToday = computed(() => data.value?.state.selected_today?.date === today.value ? data.value.state.selected_today.codes.length : 0)
const stateLabel = computed(() => data.value?.archived ? '已归档' : data.value?.running ? '正在研究' : !data.value?.config.enabled ? '已暂停' : ['failed','interrupted'].includes(data.value?.latest_status || '') ? statusName(data.value?.latest_status) : '按日程运行')
const profitClass = (value:number) => value>0 ? 'gain' : value<0 ? 'loss' : ''
async function load(force = false) {
  if (disposed || busy.value || (loading.value && !force)) return
  controller?.abort(); controller = new AbortController()
  const request = controller; const current = ++version
  loading.value = true
  try {
    const result = await getStockAgent(props.id,request.signal)
    if (disposed || current !== version) return
    const changed = !data.value || result.state_version !== data.value.state_version
    data.value = result; lastRefresh.value = new Date().toISOString(); readError.value = ''
    if (tab.value === 'account' && (changed || force || !points.value.length)) {
      try { const equity = await getAgentEquity(props.id,request.signal); if (!disposed && current === version) { points.value = equity.items; chartError.value = '' } }
      catch(e) { if (!request.signal.aborted) chartError.value = e instanceof Error ? e.message : String(e) }
    }
  } catch(e) { if (!disposed && !request.signal.aborted) readError.value = e instanceof Error ? e.message : String(e) }
  finally { if (current === version) loading.value = false }
}
async function poll() { if (disposed) return; if (!document.hidden && !settingsOpen.value && !fundingOpen.value) await load(); if (!disposed) timer = setTimeout(poll, data.value?.running ? 5000 : 12000) }
function beginWrite() { controller?.abort(); ++version; loading.value = false; busy.value = true; error.value = '' }
async function configure() {
  if (busy.value) return
  beginWrite(); settingsError.value = ''
  try { const [nextOptions,nextProviders] = await Promise.all([getAgentOptions(),getProviders()]); if (!disposed) { options.value = nextOptions; providers.value = nextProviders.filter(p => p.is_active); settingsOpen.value = true } }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function save(config:AgentConfig) {
  if (!data.value || busy.value) return
  beginWrite(); settingsError.value = ''
  try { const result = await saveStockAgent(props.id,config,data.value.revision); if (!disposed) { data.value = result; settingsOpen.value = false; ElMessage.success('智能体配置已保存') } }
  catch(e) { settingsError.value = e instanceof Error ? e.message : String(e); error.value = settingsError.value }
  finally { busy.value = false }
}
function toggle() {
  if (!data.value || busy.value) return
  if (!data.value.config.enabled && (!data.value.config.provider || !data.value.config.model)) { void configure(); return }
  void save({ ...data.value.config,enabled:!data.value.config.enabled })
}
async function deposit() {
  if (busy.value) return
  if (!pendingFunding.value && (!Number.isFinite(fundingAmount.value) || fundingAmount.value <= 0)) { fundingError.value = '请输入有效的追加金额'; return }
  pendingFunding.value ??= { key:requestKey(),cents:Math.round(fundingAmount.value*100) }
  beginWrite(); fundingError.value = ''
  try { const result = await fundAgent(props.id,pendingFunding.value.cents,pendingFunding.value.key); if (!disposed) { data.value = result; pendingFunding.value = null; fundingOpen.value = false; ElMessage.success('模拟资金已追加，未计入盈利') } }
  catch(e) { fundingError.value = `${e instanceof Error ? e.message : String(e)}。本次请求号已保留，重试不会重复追加。` }
  finally { busy.value = false; if (!fundingOpen.value) void load(true) }
}
function currentPhase():AgentPhase | null {
  const clock = new Intl.DateTimeFormat('en-GB',{ timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false }).format(new Date())
  if (clock >= '15:00') return 'review'
  if (clock >= '06:00' && clock < '09:15') return 'premarket'
  if (clock >= '09:25' && clock < '09:30') return 'auction'
  if ((clock >= '09:30' && clock < '11:30') || (clock >= '13:00' && clock < '14:57')) return 'intraday'
  return null
}
async function runNow() {
  if (!data.value || busy.value) return
  const phase = currentPhase()
  if (!phase) { ElMessage.info('当前不在研究或连续交易时段，等待下一个工作阶段'); return }
  try { await ElMessageBox.confirm(`现在执行一次${phaseName(phase)}，可能产生模型调用费用${phase === 'intraday' ? '并按配置执行模拟交易' : '；本阶段不执行模拟成交'}。`, '运行智能体', { confirmButtonText:'运行一次',cancelButtonText:'取消' }) }
  catch { return }
  beginWrite()
  try { await runStockAgent(props.id,phase,requestKey()); ElMessage.success('本轮已启动，结果将写入工作日记') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; void load(true) }
}
async function cleanup() {
  if (busy.value) return
  beginWrite()
  try {
    const preview = await cleanAgentDiary(props.id,true)
    if (!preview.eligible) { ElMessage.info('当前没有符合清理条件的旧日记'); return }
    try { await ElMessageBox.confirm(`本批清理 ${preview.eligible} 条旧日记。成交、资金流水、曲线和累计次数不受影响。`, '清理工作日记', { type:'warning',confirmButtonText:'清理本批',cancelButtonText:'取消' }) }
    catch { return }
    const result = await cleanAgentDiary(props.id,false)
    ElMessage.success(`已清理 ${result.removed} 条日记${result.more_possible ? '，仍有符合条件的记录，可继续分批清理' : ''}`)
  } catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; void load(true) }
}
async function archive() {
  if (!data.value || busy.value) return
  try { await ElMessageBox.confirm('归档后停止运行并从在用列表移除，历史与账户保留。仍有持仓的智能体不能归档。', '归档智能体', { type:'warning',confirmButtonText:'归档',cancelButtonText:'取消' }) }
  catch { return }
  beginWrite()
  try { await archiveStockAgent(props.id,data.value.revision); await router.push('/agents') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
watch(tab,value => { if (value === 'account') void load(true) })
onMounted(() => { void load(); timer = setTimeout(poll,12000) })
onUnmounted(() => { disposed = true; ++version; controller?.abort(); clearTimeout(timer) })
</script>
<template>
  <section class="stock-studio">
    <el-alert v-if="(error || readError) && !settingsOpen" :title="error || readError" type="error" :closable="false" show-icon class="studio-error"><el-button link @click="load(true)">刷新核对</el-button></el-alert>
    <el-skeleton v-if="loading && !data" :rows="12" animated />
    <template v-if="data">
      <header class="studio-header"><div class="studio-identity"><span class="studio-avatar"><el-icon><Flag v-if="data.config.kind === 'leader'" /><Cpu v-else /></el-icon></span><div><div class="identity-line"><h1>{{ data.config.name }}</h1><span class="running-status" :class="{ enabled:data.config.enabled }"><i />{{ stateLabel }}</span></div><p>{{ data.config.description || '独立的股票研究与模拟交易工作室' }}</p></div></div><div class="studio-controls"><el-button :icon="Refresh" circle aria-label="刷新智能体" :loading="loading" :disabled="busy" @click="load(true)" /><el-button :icon="Setting" :disabled="busy || !!data.archived" @click="configure">设置</el-button><el-button :icon="data.config.enabled ? VideoPause : VideoPlay" :type="data.config.enabled ? 'default' : 'primary'" :loading="busy" :disabled="!!data.archived" @click="toggle">{{ data.config.enabled ? '暂停' : '启用智能体' }}</el-button></div></header>
      <div class="studio-context"><span>{{ data.config.model || '尚未配置模型' }}</span><span>上次工作 {{ agentTime(data.latest_at) }}</span><span>累计 {{ data.total_runs }} 次工作 · {{ data.total_actions }} 条操作 · {{ data.total_trades }} 笔成交</span></div>
      <section class="account-metrics" aria-label="模拟账户概览"><div class="metric primary"><label>模拟净资产 <small>元</small></label><strong>{{ agentMoney(data.state.equity_cents) }}</strong><span>持仓市值 {{ agentMoney(data.state.market_value_cents) }}</span></div><div class="metric"><label>累计盈亏 <small>元</small></label><strong :class="profitClass(data.state.total_pnl_cents)">{{ agentMoney(data.state.total_pnl_cents) }}</strong><span>已实现 {{ agentMoney(data.state.realized_pnl_cents) }}</span></div><div class="metric"><label>可用现金 <small>元</small></label><strong>{{ agentMoney(data.state.cash_cents) }}</strong><span>当前持仓 {{ data.state.positions.length }} 只</span></div><div class="metric"><label>累计投入 <small>元</small></label><strong>{{ agentMoney(data.state.initial_capital_cents) }}</strong><el-button link type="primary" :icon="Plus" :disabled="busy || !!data.archived" @click="fundingOpen = true">追加模拟资金</el-button></div></section>
      <el-alert v-if="data.state.stale_codes?.length" type="warning" :closable="false" show-icon title="部分持仓沿用最后有效报价，当前估值不是实时成交价" class="valuation-note" />
      <nav class="studio-tabs" aria-label="智能体详情栏目"><button v-for="item in [{ id:'account',label:'账户与持仓' },{ id:'runs',label:'工作日记' },{ id:'trades',label:'成交记录' },{ id:'funding',label:'资金流水' }]" :key="item.id" :class="{ selected:tab === item.id }" :aria-pressed="tab === item.id" @click="tab = item.id as typeof tab">{{ item.label }}</button></nav>
      <template v-if="tab === 'account'">
        <div class="studio-main-grid"><AgentEquityChart :points="points" :loading="loading" :error="chartError" /><aside class="work-schedule"><header><h3>工作日程</h3><el-icon><Clock /></el-icon></header><p>北京时间 · 交易所交易日</p><div v-for="slot in data.schedules" :key="slot.phase" class="schedule-slot"><time>{{ slot.time }}</time><div><strong>{{ slot.label }}</strong><span>{{ !slot.enabled ? '未启用' : slot.phase === 'closeout' ? '执行已保存的收盘名单，不调用模型' : slot.phase === 'intraday' ? '持仓管理与模拟交易' : slot.phase === 'auction' ? '判断参与条件，不即时成交' : slot.phase === 'premarket' ? '核实隔夜变化，制定计划' : '回顾执行，为下一交易日准备' }}</span></div></div><el-button :icon="VideoPlay" :disabled="busy || data.running || !data.config.enabled || !!data.archived" @click="runNow">按当前时段运行一次</el-button></aside></div>
        <section class="positions-panel"><header><h3>当前持仓<span>{{ data.state.positions.length }} / {{ data.config.position_limit }} 只 · 临时上限 {{ data.config.temporary_position_limit }}</span></h3><span>累计费用 {{ agentMoney(data.state.fees_cents) }} 元</span></header><el-table v-if="data.state.positions.length" :data="data.state.positions" row-key="code"><el-table-column label="股票" min-width="150"><template #default="{ row }"><strong>{{ row.name }}</strong><small class="stock-code">{{ row.code }}</small></template></el-table-column><el-table-column label="持仓 / 可卖" min-width="140" align="right"><template #default="{ row }">{{ row.quantity }} / {{ row.available_quantity }} 股</template></el-table-column><el-table-column label="含费成本（元）" min-width="130" align="right"><template #default="{ row }">{{ Number(row.average_cost).toFixed(4) }}</template></el-table-column><el-table-column label="参考价（元）" min-width="130" align="right"><template #default="{ row }">{{ agentMoney(row.mark_price_cents) }}</template></el-table-column><el-table-column label="持仓市值（元）" min-width="140" align="right"><template #default="{ row }">{{ agentMoney(row.market_value_cents) }}</template></el-table-column><el-table-column label="浮动盈亏（元）" min-width="140" align="right"><template #default="{ row }"><span :class="profitClass(row.unrealized_pnl_cents)">{{ agentMoney(row.unrealized_pnl_cents) }}</span></template></el-table-column><el-table-column type="expand"><template #default="{ row }"><div class="position-plans"><p><b>持有计划</b>{{ row.holding_plan || '等待下一轮研究' }}</p><p><b>止盈条件</b>{{ row.take_profit_plan || '尚无文字计划' }}</p><p><b>止损条件</b>{{ row.stop_loss_plan || '尚无文字计划' }}</p><p><b>报价时间</b>{{ agentTime(row.mark_at) }}</p></div></template></el-table-column></el-table><el-empty v-else description="当前空仓，保留现金也是一种选择" :image-size="65" /></section>
        <div class="studio-bottom-grid"><section class="watch-panel"><header><h3>观察名单<span>{{ data.state.watchlist?.length || 0 }} / {{ data.config.watch_limit }}</span></h3><span>今日累计入选 {{ selectedToday }} / {{ data.config.daily_selection_limit }}</span></header><article v-for="stock in data.state.watchlist" :key="stock.code"><div><b>{{ stock.name || stock.code }}</b><small>{{ stock.code }}</small></div><p>{{ stock.reason || '等待进一步研究' }}</p></article><p v-if="!data.state.watchlist?.length" class="empty-note">尚无观察标的。智能体不会为凑数量而强行入选。</p></section><section class="latest-work"><header><h3>最近工作</h3><span>{{ agentTime(data.latest_at) }}</span></header><p>{{ data.latest_summary || '完成配置后，启用智能体开始第一次研究。' }}</p><div class="latest-actions"><span v-for="(action,i) in data.latest_actions.slice(0,5)" :key="i">{{ actionName(action.action) }} {{ action.name || action.code }} · {{ statusName(action.status) }}</span></div><el-button link type="primary" @click="tab = 'runs'">查看全部工作日记</el-button></section></div>
      </template>
      <template v-else><div v-if="tab === 'runs'" class="storage-toolbar"><span>累计 {{ data.total_runs }} 次 · 当前保留 {{ data.history_kept }} 条 · 已清理 {{ data.cleaned_runs }} 条</span><div><el-button link @click="configure">保留策略</el-button><el-button link :icon="Delete" :disabled="busy" @click="cleanup">清理旧日记</el-button></div></div><AgentHistoryPanel :id="id" :kind="historyKind" :refresh-key="snapshotKey" /></template>
      <footer class="studio-footer"><span>模拟成交不连接券商；按实际报价校验费用、T+1及数量约束，未模拟盘口排队与分红送转。</span><el-button link :disabled="busy || !!data.archived || !!data.state.positions.length" @click="archive">归档智能体</el-button></footer>
      <AgentConfigDrawer v-if="options" v-model="settingsOpen" :config="data.config" :options="options" :providers="providers" :busy="busy" :error="settingsError" @save="save" />
      <el-dialog v-model="fundingOpen" title="追加模拟资金" width="min(460px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy"><p class="funding-help">本次追加计入投入本金与可用现金，不计为盈利。正在研究的旧结果会失效，防止覆盖新资金余额。</p><el-alert v-if="fundingError" :title="fundingError" type="error" :closable="false" class="funding-error" /><el-form label-position="top" @submit.prevent="deposit"><el-form-item label="追加金额（元）"><el-input-number v-model="fundingAmount" :min="0.01" :max="1000000000" :precision="2" :step="1000" :disabled="!!pendingFunding || busy" controls-position="right" style="width:100%" /></el-form-item></el-form><template #footer><el-button :disabled="busy" @click="fundingOpen = false">关闭</el-button><el-button type="primary" :loading="busy" @click="deposit">{{ pendingFunding ? '重试同笔追加' : '确认追加' }}</el-button></template></el-dialog>
    </template>
  </section>
</template>
<style scoped src="./StockAgentStudio.css"></style>
