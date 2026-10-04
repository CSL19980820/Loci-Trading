<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import { Archive, ArrowLeft, BookOpen, Clock, Coins, Cpu, Ellipsis, Flag, History, NotebookPen, Pause, Play, Plus, RefreshCw, ScanEye, Settings, Telescope, Trash2, Wallet } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { confirmAction } from '@/shared/lib/confirm'
import { getProviders } from '@/shared/api/quant'
import { archiveStockAgent, cleanAgentDiary, fundAgent, getAgentEquity, getAgentOptions, getStockAgent, runStockAgent, saveStockAgent } from '@/shared/api/stock_agents'
import type { AgentConfig, AgentEquity, AgentEquityRange, AgentHistoryKind, AgentOptions, AgentPhase, AgentProfile } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
import AgentConfigDrawer from './AgentConfigDrawer.vue'
import AgentEquityChart from './AgentEquityChart.vue'
import AgentHistoryPanel from './AgentHistoryPanel.vue'
import FalconLearningPanel from './FalconLearningPanel.vue'
import AgentWorkspaceNav from './AgentWorkspaceNav.vue'
import AgentPositionsPanel from './AgentPositionsPanel.vue'
import AgentWatchPanel from './AgentWatchPanel.vue'
import { actionName, agentMoney, agentTime, phaseName, requestKey, statusName } from '../agentFormat'

type StudioTab = 'account' | 'watch' | 'plan' | 'learning' | 'history' | AgentHistoryKind
const TABS: { name: StudioTab; label: string; icon: Component }[] = [
  { name: 'account', label: '账户与持仓', icon: Wallet },
  { name: 'watch', label: '观察名单', icon: Telescope },
  { name: 'plan', label: '研究计划', icon: NotebookPen },
  { name: 'runs', label: '今日日记', icon: BookOpen },
  { name: 'trades', label: '成交记录', icon: RefreshCw },
  { name: 'funding', label: '资金流水', icon: Coins },
  { name: 'learning', label: '经验沉淀', icon: ScanEye },
  { name: 'history', label: '历史日记', icon: History },
]
function parseTab(raw: unknown): StudioTab {
  const value = String(raw || '')
  return TABS.some(item => item.name === value) ? (value as StudioTab) : 'account'
}

const props = defineProps<{ id:string }>()
const router = useRouter()
const route = useRoute()
const isMobile = useMobileLayout()
const data = shallowRef<AgentProfile | null>(null)
const options = shallowRef<AgentOptions | null>(null)
const providers = shallowRef<LlmProvider[]>([])
const points = shallowRef<AgentEquity[]>([])
const accountTab = ref('positions')
const equityRange = ref<AgentEquityRange>('day')
const chartLoading = ref(false)
const chartGranularity = ref<'intraday' | 'daily'>('intraday')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const readError = ref('')
const chartError = ref('')
const settingsError = ref('')
const settingsOpen = ref(false)
const fundingOpen = ref(false)
const scheduleOpen = ref(false)
const fundingAmount = ref(10000)
const fundingError = ref('')
const pendingFunding = ref<{ key:string; cents:number } | null>(null)
/** 总览卡的「日记 / 成交」快捷入口通过 ?tab= 直落对应栏目 */
const tab = ref<StudioTab>(parseTab(route.query.tab))
const workspacePanel = ref<HTMLElement | null>(null)

const lastRefresh = ref('')
let disposed = false
let controller:AbortController | undefined
let chartController:AbortController | undefined
let chartVersion = 0
let timer:ReturnType<typeof setTimeout> | undefined
let version = 0
const snapshotKey = computed(() => `${data.value?.state_version}:${data.value?.total_runs}:${data.value?.latest_status}:${data.value?.cleaned_runs}`)
const isHistory = computed(() => ['runs', 'history', 'trades', 'funding'].includes(tab.value))
const historyKind = computed<AgentHistoryKind>(() => tab.value === 'history' ? 'runs' : isHistory.value ? tab.value as AgentHistoryKind : 'runs')
const today = computed(() => new Intl.DateTimeFormat('sv-SE',{ timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date(lastRefresh.value || Date.now())))
const selectedToday = computed(() => data.value?.state.selected_today?.date === today.value ? data.value.state.selected_today.codes.length : 0)
const stateLabel = computed(() => data.value?.archived ? '已归档' : data.value?.running ? '正在研究' : !data.value?.config.enabled ? '已暂停' : ['failed','interrupted'].includes(data.value?.latest_status || '') ? statusName(data.value?.latest_status) : '按日程运行')
const stateVariant = computed(() => {
  if (!data.value || data.value.archived) return 'secondary' as const
  if (data.value.running) return 'info' as const
  if (['failed','interrupted'].includes(data.value.latest_status || '')) return 'stamp' as const
  return data.value.config.enabled ? ('ok' as const) : ('secondary' as const)
})
const allocationPct = computed(() => {
  const state = data.value?.state
  if (!state?.equity_cents) return null
  return Math.round(state.market_value_cents / state.equity_cents * 100)
})
const returnPct = computed(() => {
  const state = data.value?.state
  if (!state?.initial_capital_cents) return null
  return state.total_pnl_cents / state.initial_capital_cents * 100
})
const profitClass = (value:number) => value>0 ? 'gain' : value<0 ? 'loss' : ''
const signed = (cents:number) => `${cents > 0 ? '+' : cents < 0 ? '−' : ''}${agentMoney(Math.abs(cents))}`
const tabItems = computed(() => TABS.filter(item => item.name !== 'learning' || data.value?.config.kind === 'falcon').map((item) => {
  const profile = data.value
  const badge = !profile ? undefined
    : item.name === 'account' ? profile.state.positions.length || undefined
      : item.name === 'watch' ? profile.state.watchlist?.length || undefined
        : item.name === 'learning' ? (profile.state.falcon_learning?.lessons.length || 0) + (profile.state.falcon_learning?.optimization_proposals.length || 0) || undefined
          : item.name === 'history' ? profile.total_runs || undefined
        : item.name === 'trades' ? profile.total_trades || undefined
          : undefined
  return { ...item, badge }
}))
const stockNames = computed(() => new Map([...(data.value?.state.positions ?? []), ...(data.value?.state.watchlist ?? [])].map(row => [row.code, row.name || row.code])))
const latestWorkTab = computed<StudioTab>(() => {
  const at = new Date(data.value?.latest_at || '')
  if (Number.isNaN(at.getTime())) return 'history'
  const day = new Intl.DateTimeFormat('sv-SE', { timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit' }).format(at)
  return day === today.value ? 'runs' : 'history'
})
async function loadEquity() {
  if (disposed || tab.value !== 'account' || accountTab.value !== 'curve') return
  chartController?.abort(); chartController = new AbortController()
  const request = chartController; const current = ++chartVersion
  chartLoading.value = true; chartError.value = ''; points.value = []; chartGranularity.value = equityRange.value === 'day' ? 'intraday' : 'daily'
  try {
    const result = await getAgentEquity(props.id, request.signal, equityRange.value)
    if (!disposed && current === chartVersion) { points.value = result.items; chartGranularity.value = result.granularity ?? (equityRange.value === 'day' ? 'intraday' : 'daily') }
  } catch (e) { if (!disposed && !request.signal.aborted) chartError.value = e instanceof Error ? e.message : String(e) }
  finally { if (current === chartVersion) chartLoading.value = false }
}
function changeAccountTab(value: unknown) { if (value === 'positions' || value === 'curve') accountTab.value = value }
async function load(force = false) {
  if (disposed || busy.value || (loading.value && !force)) return
  controller?.abort(); controller = new AbortController()
  const request = controller; const current = ++version
  loading.value = true
  try {
    const result = await getStockAgent(props.id,request.signal)
    if (disposed || current !== version) return
    const changed = !data.value || result.state_version !== data.value.state_version || result.latest_at !== data.value.latest_at
    data.value = result; lastRefresh.value = new Date().toISOString(); readError.value = ''
    if (tab.value === 'learning' && result.config.kind !== 'falcon') tab.value = 'account'
    if (tab.value === 'account' && accountTab.value === 'curve' && (changed || force || !points.value.length)) await loadEquity()
  } catch(e) { if (!disposed && !request.signal.aborted) readError.value = e instanceof Error ? e.message : String(e) }
  finally { if (current === version) loading.value = false }
}
async function poll() { if (disposed) return; if (!document.hidden && !settingsOpen.value && !fundingOpen.value) await load(); if (!disposed) timer = setTimeout(poll, data.value?.running ? 5000 : 12000) }
function beginWrite() { controller?.abort(); chartController?.abort(); ++chartVersion; chartLoading.value = false; ++version; loading.value = false; busy.value = true; error.value = '' }
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
  try { const result = await saveStockAgent(props.id,config,data.value.revision); if (!disposed) { data.value = result; settingsOpen.value = false; toast.success('智能体配置已保存') } }
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
  try { const result = await fundAgent(props.id,pendingFunding.value.cents,pendingFunding.value.key); if (!disposed) { data.value = result; pendingFunding.value = null; fundingOpen.value = false; toast.success('模拟资金已追加，未计入盈利') } }
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
  if (!phase) { toast.info('当前不在研究或连续交易时段，等待下一个工作阶段'); return }
  await runPhase(phase)
}
async function runPhase(phase:AgentPhase) {
  if (!data.value || busy.value || data.value.running || !data.value.config.enabled || data.value.archived) return
  if (phase === 'weekly_review') {
    const clock = new Intl.DateTimeFormat('en-GB',{ timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false }).format(new Date())
    if (clock < '15:00') { toast.info('周复盘可在北京时间15:00后运行'); return }
  }
  const research = phase === 'research'
  const proceed = await confirmAction({
    message: research ? '即时研判可随时执行，只更新研究和观察，不执行模拟成交；本次会调用模型并可能产生费用。'
      : `现在执行一次${phaseName(phase)}，可能产生模型调用费用${phase === 'intraday' ? '并按配置执行模拟交易' : '；本阶段不执行模拟成交'}。`,
    title: research ? '即时研判' : '运行智能体', confirmText: research ? '开始研判' : '运行一次', cancelText: '取消',
  })
  if (!proceed) return
  beginWrite()
  try { await runStockAgent(props.id,phase,requestKey()); toast.success(research ? '即时研判已启动，不执行模拟成交，结果将写入工作日记' : '本轮已启动，结果将写入工作日记') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; void load(true) }
}
async function cleanup() {
  if (busy.value) return
  beginWrite()
  try {
    const preview = await cleanAgentDiary(props.id,true)
    if (!preview.eligible) { toast.info('当前没有符合清理条件的旧日记'); return }
    const proceed = await confirmAction({ message: `本批清理 ${preview.eligible} 条旧日记。成交、资金流水、曲线和累计次数不受影响。`, title: '清理工作日记', confirmText: '清理本批', cancelText: '取消', danger: true })
    if (!proceed) return
    const result = await cleanAgentDiary(props.id,false)
    toast.success(`已清理 ${result.removed} 条日记${result.more_possible ? '，仍有符合条件的记录，可继续分批清理' : ''}`)
  } catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; void load(true) }
}
async function archive() {
  if (!data.value || busy.value) return
  const proceed = await confirmAction({ message: '归档后停止运行并从在用列表移除，历史与账户保留。仍有持仓的智能体不能归档。', title: '归档智能体', confirmText: '归档', cancelText: '取消', danger: true })
  if (!proceed) return
  beginWrite()
  try { await archiveStockAgent(props.id,data.value.revision); await router.push('/agents') }
  catch(e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
watch(tab,value => {
  if (value === 'account') void load(true)
  const next = value === 'account' ? undefined : value
  if (String(route.query.tab || '') !== String(next || '')) void router.replace({ query: { ...route.query, tab: next } })
})
watch(() => route.query.tab, raw => { const next = parseTab(raw); if (next !== tab.value) tab.value = next })
watch(tab, () => { workspacePanel.value?.scrollTo({ top: 0, left: 0, behavior: 'instant' }) }, { flush: 'post' })
watch([accountTab, equityRange], () => { if (tab.value === 'account' && accountTab.value === 'curve') void loadEquity() })
onMounted(() => { void load(); timer = setTimeout(poll,12000) })
onUnmounted(() => { disposed = true; ++version; ++chartVersion; controller?.abort(); chartController?.abort(); clearTimeout(timer) })
</script>
<template>
  <section class="stock-studio">
    <MobilePageHeader v-if="isMobile" :title="data?.config.name || '智能体'" :subtitle="data ? stateLabel : undefined">
      <template #leading><Button access="read" variant="ghost" size="icon" as-child><RouterLink to="/agents" aria-label="返回智能体"><ArrowLeft /></RouterLink></Button></template>
      <template v-if="data" #actions>
        <Button access="read" variant="ghost" size="icon" aria-label="查看工作日程" @click="scheduleOpen = true"><Clock /></Button>
        <Button access="read" variant="ghost" size="icon" :disabled="loading || busy" aria-label="刷新智能体" @click="load(true)"><RefreshCw :class="{ 'animate-spin': loading }" /></Button>
        <DropdownMenu><DropdownMenuTrigger as-child><Button variant="ghost" size="icon" aria-label="智能体操作" :disabled="busy"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
          <DropdownMenuItem :disabled="!!data.archived" @select="configure"><Settings />设置</DropdownMenuItem>
          <DropdownMenuItem :disabled="!!data.archived" @select="toggle"><Pause v-if="data.config.enabled" /><Play v-else />{{ data.config.enabled ? '暂停' : '启用智能体' }}</DropdownMenuItem>
          <DropdownMenuItem :disabled="!!data.archived" @select="fundingOpen = true"><Plus />追加模拟资金</DropdownMenuItem>
          <DropdownMenuItem :disabled="data.running || !data.config.enabled || !!data.archived" @select="runNow"><Play />按当前时段运行一次</DropdownMenuItem>
          <DropdownMenuItem v-if="data.config.kind === 'falcon'" :disabled="data.running || !data.config.enabled || !!data.archived" @select="runPhase('research')"><ScanEye />即时研判</DropdownMenuItem>
          <DropdownMenuItem v-if="data.config.kind === 'falcon' || data.config.schedule.weekly_review_enabled" :disabled="data.running || !data.config.enabled || !!data.archived" @select="runPhase('weekly_review')"><RefreshCw />运行周复盘</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem @select="cleanup"><Trash2 />清理旧日记</DropdownMenuItem>
          <DropdownMenuItem variant="destructive" :disabled="!!data.archived || !!data.state.positions.length" @select="archive"><Archive />归档智能体</DropdownMenuItem>
        </DropdownMenuContent></DropdownMenu>
      </template>
    </MobilePageHeader>
    <header v-else class="studio-head">
      <div class="studio-head__id">
        <Button access="read" variant="ghost" size="icon-sm" as-child>
          <RouterLink to="/agents" aria-label="返回智能体"><ArrowLeft aria-hidden="true" /></RouterLink>
        </Button>
        <span class="studio-avatar" :class="{ 'is-leader': data?.config.kind === 'leader', 'is-falcon': data?.config.kind === 'falcon', 'is-live': data?.config.enabled && !data?.archived }" aria-hidden="true">
          <Flag v-if="data?.config.kind === 'leader'" />
          <ScanEye v-else-if="data?.config.kind === 'falcon'" />
          <Cpu v-else />
        </span>
        <div class="studio-head__text">
          <div class="studio-head__name">
            <h1 :title="data?.config.name">{{ data?.config.name || '智能体' }}</h1>
            <UiBadge v-if="data" :variant="stateVariant" :dot="!data.running" class="studio-state">
              <Spinner v-if="data.running" class="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              {{ stateLabel }}
            </UiBadge>
          </div>
          <div v-if="data" class="studio-head__meta">
            <span :title="data.config.model"><Cpu aria-hidden="true" />{{ data.config.model || '模型未配置' }}</span>
            <span><Clock aria-hidden="true" />{{ agentTime(data.latest_at) }}</span>
          </div>
        </div>
      </div>
      <div v-if="data" class="studio-head__actions">
        <Button access="read" variant="outline" size="sm" @click="scheduleOpen = true"><Clock aria-hidden="true" />工作日程</Button>
        <Button access="read" variant="ghost" size="icon-sm" :disabled="loading || busy" aria-label="刷新智能体" @click="load(true)">
          <Spinner v-if="loading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <RefreshCw v-else aria-hidden="true" />
        </Button>
        <Button variant="outline" size="sm" :disabled="busy || !!data.archived" @click="configure">
          <Settings aria-hidden="true" />
          设置
        </Button>
        <Button :variant="data.config.enabled ? 'outline' : 'default'" size="sm" :disabled="busy || !!data.archived" @click="toggle">
          <Spinner v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Pause v-else-if="data.config.enabled" aria-hidden="true" />
          <Play v-else aria-hidden="true" />
          {{ data.config.enabled ? '暂停' : '启用' }}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="ghost" size="icon-sm" aria-label="更多操作" :disabled="busy">
              <Ellipsis aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem :disabled="!!data.archived" @select="fundingOpen = true">
              <Plus aria-hidden="true" />
              追加模拟资金
            </DropdownMenuItem>
            <DropdownMenuItem :disabled="data.running || !data.config.enabled || !!data.archived" @select="runNow">
              <Play aria-hidden="true" />
              按当前时段运行一次
            </DropdownMenuItem>
            <DropdownMenuItem v-if="data.config.kind === 'falcon'" :disabled="data.running || !data.config.enabled || !!data.archived" @select="runPhase('research')">
              <ScanEye aria-hidden="true" />
              即时研判
            </DropdownMenuItem>
            <DropdownMenuItem v-if="data.config.kind === 'falcon' || data.config.schedule.weekly_review_enabled" :disabled="data.running || !data.config.enabled || !!data.archived" @select="runPhase('weekly_review')">
              <RefreshCw aria-hidden="true" />
              运行周复盘
            </DropdownMenuItem>
            <DropdownMenuItem @select="cleanup">
              <Trash2 aria-hidden="true" />
              清理旧日记
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" :disabled="!!data.archived || !!data.state.positions.length" @select="archive">
              <Archive aria-hidden="true" />
              归档智能体
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <Alert v-if="(error || readError) && !settingsOpen" variant="destructive" class="studio-error">
      <AlertTitle class="line-clamp-none">{{ error || readError }}</AlertTitle>
      <Button access="read" variant="link" size="xs" class="col-start-2 justify-self-start px-0" @click="load(true)">刷新核对</Button>
    </Alert>

    <div v-if="loading && !data" class="studio-skeleton" aria-hidden="true">
      <Skeleton class="h-[104px] rounded-lg" />
      <Skeleton class="h-[260px] rounded-lg" />
      <Skeleton class="h-[180px] rounded-lg" />
    </div>

    <template v-if="data">
      <div class="studio-workspace">
        <AgentWorkspaceNav panel-id="stock-agent-panel" :model-value="tab" :items="tabItems"
          @update:model-value="value => tab = parseTab(value)">
        </AgentWorkspaceNav>
        <div id="stock-agent-panel" ref="workspacePanel" class="studio-tab-panel" :class="{ 'studio-tab-panel--contained': isHistory || tab === 'learning' || tab === 'account' || tab === 'watch' || tab === 'plan', 'studio-tab-panel--plan': tab === 'plan' }"
          role="tabpanel" tabindex="0" :aria-labelledby="`stock-agent-panel-tab-${tab}`" data-agent-workspace-scroll>
          <template v-if="tab === 'account'">
            <section class="studio-ledger" aria-label="模拟账户，单位元">
              <div class="studio-ledger__hero"><span class="studio-ledger__label">模拟净资产</span><strong class="studio-ledger__equity">{{ agentMoney(data.state.equity_cents) }}</strong><span class="studio-ledger__pnl" :class="profitClass(data.state.total_pnl_cents)">{{ signed(data.state.total_pnl_cents) }}<em v-if="returnPct != null">{{ returnPct > 0 ? '+' : '' }}{{ returnPct.toFixed(2) }}%</em></span></div>
              <dl class="studio-ledger__facts">
                <div><dt>可用现金</dt><dd>{{ agentMoney(data.state.cash_cents) }}</dd></div><div><dt>持仓市值</dt><dd>{{ agentMoney(data.state.market_value_cents) }}</dd></div><div><dt>已实现</dt><dd :class="profitClass(data.state.realized_pnl_cents)">{{ signed(data.state.realized_pnl_cents) }}</dd></div><div><dt>浮动盈亏</dt><dd :class="profitClass(data.state.unrealized_pnl_cents)">{{ signed(data.state.unrealized_pnl_cents) }}</dd></div>
                <div><dt>投入本金<Button variant="ghost" size="xs" class="studio-ledger__fund" :disabled="busy || !!data.archived" @click="fundingOpen = true"><Plus aria-hidden="true" />追加</Button></dt><dd>{{ agentMoney(data.state.initial_capital_cents) }}</dd></div>
              </dl>
              <div class="studio-ledger__alloc"><div class="studio-ledger__alloc-row"><span class="studio-ledger__label">仓位</span><strong>{{ allocationPct ?? 0 }}%</strong></div><span class="studio-ledger__bar" aria-hidden="true"><i :style="{ width: `${Math.min(100, Math.max(0, allocationPct ?? 0))}%` }" /></span><span class="studio-ledger__runs">工作 {{ data.total_runs }} · 成交 {{ data.total_trades }}</span></div>
            </section>
            <Alert v-if="data.state.stale_codes?.length" class="studio-stale"><AlertTitle class="line-clamp-none">部分持仓估值沿用最后有效报价</AlertTitle></Alert>
            <div class="studio-account-switch"><ToggleGroup :model-value="accountTab" type="single" variant="outline" size="sm" aria-label="账户视图" @update:model-value="changeAccountTab"><ToggleGroupItem value="positions">持仓</ToggleGroupItem><ToggleGroupItem value="curve">账户曲线</ToggleGroupItem></ToggleGroup><span>操作 {{ data.total_actions }} · 规费 {{ agentMoney(data.state.fees_cents) }} 元</span></div>
            <AgentPositionsPanel v-if="accountTab === 'positions'" :positions="data.state.positions" :limit="data.config.position_limit" :temporary-limit="data.config.temporary_position_limit" :fees-cents="data.state.fees_cents" />
            <AgentEquityChart v-else v-model:range="equityRange" :points="points" :loading="chartLoading" :error="chartError" :granularity="chartGranularity" />
          </template>
          <AgentWatchPanel v-else-if="tab === 'watch'" :stocks="data.state.watchlist ?? []" :selected-today="selectedToday" :selection-limit="data.config.daily_selection_limit" :watch-limit="data.config.watch_limit" :falcon="data.config.kind === 'falcon'" />
          <div v-else-if="tab === 'plan'" class="studio-plan-layout">
            <Card class="studio-plan-main">
              <CardHeader class="border-b"><CardTitle class="studio-plan-title"><span>接续研究计划</span><UiBadge v-if="data.state.research_plan_structured?.next_trade_date" variant="ok">下一交易日 {{ data.state.research_plan_structured.next_trade_date }}</UiBadge></CardTitle><CardDescription v-if="data.state.research_plan_date || data.state.research_plan_at">{{ data.state.research_plan_date }}<template v-if="data.state.research_plan_at"> · 更新 {{ agentTime(data.state.research_plan_at) }}</template></CardDescription></CardHeader>
              <div class="studio-plan-scroll" data-agent-plan-scroll>
                <CardContent v-if="data.state.research_plan_structured" class="structured-plan">
                  <section class="structured-plan__market"><h4>市场判断</h4><p>{{ data.state.research_plan_structured.market_view || '—' }}</p></section>
                  <section v-for="stock in data.state.research_plan_structured.stocks" :key="stock.code" class="structured-plan__stock"><h4><strong>{{ stockNames.get(stock.code) || stock.code }}</strong><small>{{ stock.code }}</small></h4><dl><div><dt>进场条件</dt><dd>{{ stock.entry_condition || '—' }}</dd></div><div><dt>离场条件</dt><dd>{{ stock.exit_condition || '—' }}</dd></div><div><dt>失效条件</dt><dd>{{ stock.invalidation || '—' }}</dd></div><div><dt>下一次核验</dt><dd>{{ stock.next_check || '—' }}</dd></div></dl></section>
                  <details v-if="data.state.research_plan" class="plan-original"><summary>查看原始研究计划</summary><p>{{ data.state.research_plan }}</p></details>
                </CardContent>
                <CardContent v-else-if="data.state.research_plan" class="research-plan">{{ data.state.research_plan }}</CardContent>
                <EmptyState v-else description="研究完成后，这里展示下一轮接续的计划" compact />
              </div>
            </Card>
            <Card class="studio-plan-recent"><CardHeader class="border-b"><CardTitle>最近工作</CardTitle><CardDescription>{{ data.latest_phase ? phaseName(data.latest_phase) : '最近动态' }} · {{ agentTime(data.latest_at) }}</CardDescription></CardHeader><CardContent class="latest-work"><p class="work-summary">{{ data.latest_summary || '—' }}</p><div v-if="data.latest_actions.length" class="latest-actions"><span v-for="(action,i) in data.latest_actions" :key="i" class="action-tag">{{ actionName(action.action) }} {{ action.name || action.code }} · {{ statusName(action.status) }}</span></div><p v-if="data.state.assessment_coverage" class="coverage-note">本轮评估 {{ data.state.assessment_coverage.reviewed }} / {{ data.state.assessment_coverage.total }}<template v-if="!data.state.assessment_coverage.complete"> · 部分标的待核验</template></p><Button access="read" variant="link" size="xs" class="self-start px-0" @click="tab = latestWorkTab">查看完整日记</Button></CardContent></Card>
          </div>
          <FalconLearningPanel v-else-if="tab === 'learning'" :memory="data.state.falcon_learning" />
          <AgentHistoryPanel v-else :id="id" :kind="historyKind" :refresh-key="snapshotKey" :mode="tab === 'history' ? 'history' : 'today'" :stats="{total_runs:data.total_runs,history_kept:data.history_kept,cleaned_runs:data.cleaned_runs}" :busy="busy" @configure="configure" @cleanup="cleanup" />
      </div>
      </div>

      <Dialog v-model:open="scheduleOpen">
        <DialogContent class="schedule-dialog sm:max-w-[900px]" style="display:flex;flex-direction:column;height:min(760px,88dvh);max-height:90dvh;overflow:hidden;gap:20px" data-agent-schedule-dialog>
          <DialogHeader class="text-left" style="flex:none"><DialogTitle>工作日程</DialogTitle><DialogDescription class="sr-only">工作阶段与时间</DialogDescription></DialogHeader>
          <div class="schedule-dialog-body"><div class="schedule-agent"><strong>{{ data.config.name }}</strong><UiBadge :variant="stateVariant">{{ stateLabel }}</UiBadge><span>{{ data.config.model || '模型未配置' }}</span></div><ol class="schedule-list"><li v-for="slot in data.schedules" :key="slot.phase" class="schedule-slot" :class="{ 'is-off': !slot.enabled }"><span class="schedule-slot__clock"><Clock aria-hidden="true" /><time>{{ slot.time }}</time></span><strong>{{ slot.label }}</strong><UiBadge :variant="slot.enabled ? 'ok' : 'secondary'">{{ slot.enabled ? '启用' : '关闭' }}</UiBadge></li></ol></div>
          <DialogFooter style="flex:none"><Button access="read" variant="outline" @click="scheduleOpen = false">关闭</Button><Button variant="outline" :disabled="busy || data.running || !data.config.enabled || !!data.archived" @click="runNow"><Play aria-hidden="true" />按当前时段运行一次</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <AgentConfigDrawer
        v-if="options"
        v-model="settingsOpen"
        :config="data.config"
        :options="options"
        :providers="providers"
        :busy="busy"
        :error="settingsError"
        @save="save"
      />

      <Dialog v-model:open="fundingOpen">
        <DialogContent class="sm:max-w-md" :show-close-button="!busy" @interact-outside.prevent @escape-key-down="(event) => { if (busy) event.preventDefault() }">
          <DialogHeader class="text-left">
            <DialogTitle>追加模拟资金</DialogTitle>
            <DialogDescription class="sr-only">追加模拟资金</DialogDescription>
          </DialogHeader>
          <Alert v-if="fundingError" variant="destructive">
            <AlertTitle class="line-clamp-none">{{ fundingError }}</AlertTitle>
          </Alert>
          <form class="funding-form" @submit.prevent="deposit">
            <Label for="agent-funding-amount">追加金额（元）</Label>
            <NumberField
              v-model="fundingAmount"
              :min="0.01"
              :max="1000000000"
              :step="1000"
              :disabled="!!pendingFunding || busy"
              :format-options="{ minimumFractionDigits:2, maximumFractionDigits:2 }"
            >
              <NumberFieldContent>
                <NumberFieldInput id="agent-funding-amount" class="text-left font-mono" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </form>
          <DialogFooter>
            <Button access="read" variant="outline" :disabled="busy" @click="fundingOpen = false">取消</Button>
            <Button :disabled="busy" @click="deposit">
              <Spinner v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              {{ pendingFunding ? '重试同笔追加' : '确认追加' }}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </template>
  </section>
</template>
<style scoped src="./StockAgentStudio.css"></style>
