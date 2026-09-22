<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import MobilePageHeader from '@/shared/components/layout/MobilePageHeader.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import GuardianMobileSummary from '@/features/ops/components/GuardianMobileSummary.vue'
import { Archive, ArrowLeft, ChevronDown, Clock, Cpu, Ellipsis, Flag, LoaderCircle, Pause, Play, Plus, RefreshCw, Settings, Trash2 } from '@lucide/vue'
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
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { confirmAction } from '@/shared/lib/confirm'
import { getProviders } from '@/shared/api/quant'
import { archiveStockAgent, cleanAgentDiary, fundAgent, getAgentEquity, getAgentOptions, getStockAgent, runStockAgent, saveStockAgent } from '@/shared/api/stock_agents'
import type { AgentConfig, AgentEquity, AgentHistoryKind, AgentOptions, AgentPhase, AgentProfile } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
import AgentConfigDrawer from './AgentConfigDrawer.vue'
import AgentEquityChart from './AgentEquityChart.vue'
import AgentHistoryPanel from './AgentHistoryPanel.vue'
import { actionName, agentMoney, agentTime, phaseName, requestKey, statusName } from '../agentFormat'

type StudioTab = 'account' | AgentHistoryKind
const TABS: { name: StudioTab; label: string }[] = [
  { name: 'account', label: '账户与持仓' },
  { name: 'runs', label: '工作日记' },
  { name: 'trades', label: '成交记录' },
  { name: 'funding', label: '资金流水' },
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
/** 总览卡的「日记 / 成交」快捷入口通过 ?tab= 直落对应栏目 */
const tab = ref<StudioTab>(parseTab(route.query.tab))

const expanded = ref<Set<string>>(new Set())
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
const pnlTone = computed(() => {
  const pnl = data.value?.state.total_pnl_cents ?? 0
  return pnl > 0 ? 'up' : pnl < 0 ? 'down' : 'neutral'
})
const profitClass = (value:number) => value>0 ? 'gain' : value<0 ? 'loss' : ''
const signed = (cents:number) => `${cents > 0 ? '+' : cents < 0 ? '−' : ''}${agentMoney(Math.abs(cents))}`
function scheduleNote(slot: AgentProfile['schedules'][number]): string {
  if (!slot.enabled) return '未启用'
  if (slot.phase === 'closeout') return '执行已保存的收盘名单，不调用模型'
  if (slot.phase === 'intraday') return '持仓管理与模拟交易'
  if (slot.phase === 'auction') return '判断参与条件，不即时成交'
  if (slot.phase === 'premarket') return '核实隔夜变化，制定计划'
  return '回顾执行，为下一交易日准备'
}
function toggleExpand(code:string) { const next = new Set(expanded.value); if (next.has(code)) next.delete(code); else next.add(code); expanded.value = next }
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
  const proceed = await confirmAction({ message: `现在执行一次${phaseName(phase)}，可能产生模型调用费用${phase === 'intraday' ? '并按配置执行模拟交易' : '；本阶段不执行模拟成交'}。`, title: '运行智能体', confirmText: '运行一次', cancelText: '取消' })
  if (!proceed) return
  beginWrite()
  try { await runStockAgent(props.id,phase,requestKey()); toast.success('本轮已启动，结果将写入工作日记') }
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
onMounted(() => { void load(); timer = setTimeout(poll,12000) })
onUnmounted(() => { disposed = true; ++version; controller?.abort(); clearTimeout(timer) })
</script>
<template>
  <section class="stock-studio">
    <MobilePageHeader v-if="isMobile" :title="data?.config.name || '智能体'" :subtitle="data ? stateLabel : undefined">
      <template #leading><Button access="read" variant="ghost" size="icon" as-child><RouterLink to="/agents" aria-label="返回智能体"><ArrowLeft /></RouterLink></Button></template>
      <template v-if="data" #actions>
        <Button access="read" variant="ghost" size="icon" :disabled="loading || busy" aria-label="刷新智能体" @click="load(true)"><RefreshCw :class="{ 'animate-spin': loading }" /></Button>
        <DropdownMenu><DropdownMenuTrigger as-child><Button variant="ghost" size="icon" aria-label="智能体操作" :disabled="busy"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
          <DropdownMenuItem :disabled="!!data.archived" @select="configure"><Settings />设置</DropdownMenuItem>
          <DropdownMenuItem :disabled="!!data.archived" @select="toggle"><Pause v-if="data.config.enabled" /><Play v-else />{{ data.config.enabled ? '暂停' : '启用智能体' }}</DropdownMenuItem>
          <DropdownMenuItem :disabled="!!data.archived" @select="fundingOpen = true"><Plus />追加模拟资金</DropdownMenuItem>
          <DropdownMenuItem :disabled="data.running || !data.config.enabled || !!data.archived" @select="runNow"><Play />按当前时段运行一次</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem @select="cleanup"><Trash2 />清理旧日记</DropdownMenuItem>
          <DropdownMenuItem variant="destructive" :disabled="!!data.archived || !!data.state.positions.length" @select="archive"><Archive />归档智能体</DropdownMenuItem>
        </DropdownMenuContent></DropdownMenu>
      </template>
    </MobilePageHeader>
    <PageHeader v-else
      compact
      sticky
      :title="data?.config.name || '智能体'"
      :description="data ? (data.config.description || '独立的股票研究与模拟交易工作室') : undefined"
      :tabs="data ? TABS : undefined"
      v-model:tab="tab"
    >
      <template #leading>
        <Button access="read" variant="ghost" size="icon-sm" as-child>
          <RouterLink to="/agents" aria-label="返回智能体"><ArrowLeft aria-hidden="true" /></RouterLink>
        </Button>
      </template>
      <template #title>
        <span class="studio-title">
          <span class="studio-avatar" :class="{ 'is-leader': data?.config.kind === 'leader' }" aria-hidden="true">
            <Flag v-if="data?.config.kind === 'leader'" />
            <Cpu v-else />
          </span>
          <span class="studio-title__text">{{ data?.config.name || '智能体' }}</span>
          <UiBadge v-if="data" :variant="stateVariant" :dot="!data.running" class="studio-state">
            <LoaderCircle v-if="data.running" class="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            {{ stateLabel }}
          </UiBadge>
        </span>
      </template>
      <template v-if="data" #actions>
        <Button access="read" variant="ghost" size="icon-sm" :disabled="loading || busy" aria-label="刷新智能体" @click="load(true)">
          <LoaderCircle v-if="loading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <RefreshCw v-else aria-hidden="true" />
        </Button>
        <Button variant="outline" size="sm" :disabled="busy || !!data.archived" @click="configure">
          <Settings aria-hidden="true" />
          设置
        </Button>
        <Button :variant="data.config.enabled ? 'outline' : 'default'" size="sm" :disabled="busy || !!data.archived" @click="toggle">
          <LoaderCircle v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Pause v-else-if="data.config.enabled" aria-hidden="true" />
          <Play v-else aria-hidden="true" />
          {{ data.config.enabled ? '暂停' : '启用智能体' }}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="icon-sm" aria-label="更多操作" :disabled="busy">
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
      </template>
      <template v-if="data" #default>
        <span class="studio-meta">
          <Cpu class="size-3.5" aria-hidden="true" />
          <b>{{ data.config.model || '尚未配置模型' }}</b>
        </span>
        <span class="studio-meta">
          <Clock class="size-3.5" aria-hidden="true" />
          上次工作 {{ agentTime(data.latest_at) }}
        </span>
        <span class="studio-meta">
          累计 <b>{{ data.total_runs }}</b> 次工作 · <b>{{ data.total_actions }}</b> 条操作 · <b>{{ data.total_trades }}</b> 笔成交
        </span>
      </template>
    </PageHeader>
    <PageTabs v-if="isMobile && data" :model-value="tab" :items="TABS" variant="pill" :sticky="false" class="studio-phone-tabs" aria-label="智能体工作区" @update:model-value="value => tab = parseTab(value)" />

    <Alert v-if="(error || readError) && !settingsOpen" variant="destructive" class="studio-error">
      <AlertTitle class="line-clamp-none">{{ error || readError }}</AlertTitle>
      <Button access="read" variant="link" size="xs" class="col-start-2 justify-self-start px-0" @click="load(true)">刷新核对</Button>
    </Alert>

    <div v-if="loading && !data" class="studio-skeleton" aria-hidden="true">
      <div class="stat-strip cols-4 studio-kpis">
        <Skeleton v-for="n in 4" :key="n" class="h-[66px] rounded-md" />
      </div>
      <Skeleton class="h-[260px] rounded-lg" />
      <Skeleton class="h-[180px] rounded-lg" />
    </div>

    <template v-if="data">
      <!-- Primary balances and secondary accounting facts are each shown once. -->
      <GuardianMobileSummary v-if="isMobile && tab === 'account'" :data="{ state:data.state, config:data.config, observation_count:data.state.watchlist?.length }" />
      <section v-if="!isMobile" class="stat-strip cols-4 studio-kpis" aria-label="模拟账户概览">
        <StatCard
          label="模拟净资产 / 元"
        >
          {{ agentMoney(data.state.equity_cents) }}
        </StatCard>
        <StatCard
          label="累计盈亏 / 元"
          :tone="pnlTone"
        >
          {{ signed(data.state.total_pnl_cents) }}
        </StatCard>
        <StatCard label="可用现金 / 元">
          {{ agentMoney(data.state.cash_cents) }}
        </StatCard>
        <StatCard label="投入本金 / 元" >
          <template #icon>
            <Button
              variant="ghost"
              size="xs"
              class="-my-1 text-seal-ink"
              :disabled="busy || !!data.archived"
              @click="fundingOpen = true"
            >
              <Plus aria-hidden="true" />
              追加
            </Button>
          </template>
          {{ agentMoney(data.state.initial_capital_cents) }}
        </StatCard>
      </section>
      <dl v-if="!isMobile" class="studio-account-context" aria-label="账户补充读数">
        <div><dt>持仓市值</dt><dd>{{ agentMoney(data.state.market_value_cents) }} 元</dd></div>
        <div v-if="allocationPct != null"><dt>仓位</dt><dd>{{ allocationPct }}%</dd></div>
        <div v-if="returnPct != null"><dt>收益率</dt><dd :class="pnlTone === 'up' ? 'text-up' : pnlTone === 'down' ? 'text-down' : ''">{{ returnPct > 0 ? '+' : '' }}{{ returnPct.toFixed(2) }}%</dd></div>
        <div><dt>已实现</dt><dd>{{ signed(data.state.realized_pnl_cents) }} 元</dd></div>
      </dl>

      <Alert v-if="data.state.stale_codes?.length" class="studio-stale">
        <AlertTitle class="line-clamp-none">部分持仓沿用最后有效报价，当前估值不是实时成交价</AlertTitle>
      </Alert>

      <!-- 账户与持仓 -->
      <template v-if="tab === 'account'">
        <Card class="studio-positions">
          <CardHeader class="border-b">
            <CardTitle class="flex flex-wrap items-center gap-2">
              当前持仓
              <UiBadge variant="secondary">{{ data.state.positions.length }} / {{ data.config.position_limit }} 只</UiBadge>
              <UiBadge v-if="data.config.temporary_position_limit" variant="default">临时上限 {{ data.config.temporary_position_limit }}</UiBadge>
            </CardTitle>
            <CardDescription>累计交易规费 {{ agentMoney(data.state.fees_cents) }} 元</CardDescription>
          </CardHeader>

          <div v-if="!data.state.positions.length" class="studio-positions__empty">
            <EmptyState description="当前空仓" compact />
          </div>

          <!-- 手机：卡片列表 -->
          <ul v-else-if="isMobile" class="position-cards">
            <li v-for="row in data.state.positions" :key="row.code" class="position-card">
              <Item as="button" type="button" class="position-card__main" :aria-expanded="expanded.has(row.code)" @click="toggleExpand(row.code)">
                <span class="stock-cell">
                  <strong class="stock-name">{{ row.name }}</strong>
                  <small class="stock-code">{{ row.code }}</small>
                </span>
                <span class="position-card__value">
                  <b :class="profitClass(row.unrealized_pnl_cents)">{{ signed(row.unrealized_pnl_cents) }}</b>
                  <small>{{ agentMoney(row.market_value_cents) }} 元</small>
                </span>
                <ChevronDown class="position-card__chevron" :class="{ 'rotate-180': expanded.has(row.code) }" aria-hidden="true" />
              </Item>
              <div class="position-card__meta">
                <span>{{ row.quantity }} / {{ row.available_quantity }} 股</span>
                <span>成本 {{ Number(row.average_cost).toFixed(3) }}</span>
                <span>现价 {{ agentMoney(row.mark_price_cents) }}</span>
              </div>
              <div v-if="expanded.has(row.code)" class="position-plans position-plans--card">
                <div class="plan-item"><b>持有计划</b><p>{{ row.holding_plan || '等待下一轮研究' }}</p></div>
                <div class="plan-item"><b>止盈条件</b><p>{{ row.take_profit_plan || '尚无文字计划' }}</p></div>
                <div class="plan-item"><b>止损条件</b><p>{{ row.stop_loss_plan || '尚无文字计划' }}</p></div>
                <div class="plan-item"><b>报价时间</b><time>{{ agentTime(row.mark_at) }}</time></div>
              </div>
            </li>
          </ul>

          <!-- 桌面：表格 -->
          <Table v-else class="positions-table">
            <TableHeader>
              <TableRow>
                <TableHead class="w-9"><span class="sr-only">展开持有计划</span></TableHead>
                <TableHead class="text-center">标的 · 编码</TableHead>
                <TableHead class="text-center">持仓 / 可卖</TableHead>
                <TableHead class="text-center">含费成本</TableHead>
                <TableHead class="text-center">参考现价</TableHead>
                <TableHead class="text-center">持仓市值</TableHead>
                <TableHead class="text-center">浮动盈亏</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <template v-for="row in data.state.positions" :key="row.code">
                <TableRow class="position-row" @click="toggleExpand(row.code)">
                  <TableCell>
                    <Button access="read" variant="ghost" size="icon-xs" :aria-label="`展开 ${row.name} 的持有计划`" :aria-expanded="expanded.has(row.code)" @click.stop="toggleExpand(row.code)">
                      <ChevronDown :class="['size-3.5 transition-transform', expanded.has(row.code) ? 'rotate-180' : '']" aria-hidden="true" />
                    </Button>
                  </TableCell>
                  <TableCell class="text-center">
                    <span class="stock-cell-inline" :title="`${row.name} ${row.code}`">
                      <strong class="stock-name">{{ row.name }}</strong>
                      <small class="stock-code">{{ row.code }}</small>
                    </span>
                  </TableCell>
                  <TableCell class="num text-center">{{ row.quantity }} / {{ row.available_quantity }}</TableCell>
                  <TableCell class="num text-center">{{ Number(row.average_cost).toFixed(3) }}</TableCell>
                  <TableCell class="num text-center">{{ agentMoney(row.mark_price_cents) }}</TableCell>
                  <TableCell class="num text-center font-medium">{{ agentMoney(row.market_value_cents) }}</TableCell>
                  <TableCell class="num text-center font-medium">
                    <span :class="profitClass(row.unrealized_pnl_cents)">{{ signed(row.unrealized_pnl_cents) }}</span>
                  </TableCell>
                </TableRow>
                <TableRow v-if="expanded.has(row.code)" class="plan-row">
                  <TableCell :colspan="7" class="p-0">
                    <div class="position-plans">
                      <div class="plan-item"><b>持有计划</b><p>{{ row.holding_plan || '等待下一轮研究' }}</p></div>
                      <div class="plan-item"><b>止盈条件</b><p>{{ row.take_profit_plan || '尚无文字计划' }}</p></div>
                      <div class="plan-item"><b>止损条件</b><p>{{ row.stop_loss_plan || '尚无文字计划' }}</p></div>
                      <div class="plan-item"><b>报价时间</b><time>{{ agentTime(row.mark_at) }}</time></div>
                    </div>
                  </TableCell>
                </TableRow>
              </template>
            </TableBody>
          </Table>
        </Card>

        <div class="studio-bento">
          <AgentEquityChart :points="points" :loading="loading" :error="chartError" class="studio-bento__chart" />

          <Card class="studio-schedule">
            <CardHeader class="border-b">
              <CardTitle>工作日程 <span class="text-xs font-normal text-muted-foreground">北京时间</span></CardTitle>
            </CardHeader>
            <CardContent class="studio-schedule__body">
              <ol class="schedule-list">
                <li v-for="slot in data.schedules" :key="slot.phase" class="schedule-slot" :class="{ 'is-off': !slot.enabled }">
                  <time class="schedule-slot__time">{{ slot.time }}</time>
                  <div class="schedule-slot__detail">
                    <strong>{{ slot.label }}</strong>
                    <span>{{ scheduleNote(slot) }}</span>
                  </div>
                </li>
              </ol>
              <Button
                variant="outline"
                size="sm"
                class="mt-auto w-full"
                :disabled="busy || data.running || !data.config.enabled || !!data.archived"
                @click="runNow"
              >
                <Play aria-hidden="true" />
                按当前时段运行一次
              </Button>
            </CardContent>
          </Card>
        </div>

        <div class="studio-bento studio-bento--even">
          <Card>
            <CardHeader class="border-b">
              <CardTitle class="flex flex-wrap items-center gap-2">
                观察名单
                <UiBadge variant="secondary">{{ data.state.watchlist?.length || 0 }} / {{ data.config.watch_limit }}</UiBadge>
              </CardTitle>
              <CardDescription>今日入选 {{ selectedToday }} / {{ data.config.daily_selection_limit }}</CardDescription>
            </CardHeader>
            <CardContent class="p-0">
              <ul v-if="data.state.watchlist?.length" class="watch-list">
                <li v-for="stock in data.state.watchlist" :key="stock.code" class="watch-item">
                  <span class="stock-cell">
                    <strong class="stock-name">{{ stock.name || stock.code }}</strong>
                    <small class="stock-code">{{ stock.code }}</small>
                  </span>
                  <p class="watch-reason">{{ stock.reason || '等待进一步研究' }}</p>
                </li>
              </ul>
              <EmptyState v-else description="尚无观察标的" compact />
            </CardContent>
          </Card>

          <Card>
            <CardHeader class="border-b">
              <CardTitle>最近工作</CardTitle>
              <CardDescription>{{ data.latest_phase ? phaseName(data.latest_phase) : '最近动态' }} · {{ agentTime(data.latest_at) }}</CardDescription>
            </CardHeader>
            <CardContent class="latest-work">
              <p class="work-summary">{{ data.latest_summary || '完成配置后，启用智能体开始第一次研究。' }}</p>
              <div v-if="data.latest_actions.length" class="latest-actions">
                <span v-for="(action,i) in data.latest_actions.slice(0,5)" :key="i" class="action-tag">
                  {{ actionName(action.action) }} {{ action.name || action.code }} · {{ statusName(action.status) }}
                </span>
              </div>
              <Button access="read" variant="link" size="xs" class="mt-auto self-start px-0" @click="tab = 'runs'">
                查看全部工作日记 →
              </Button>
            </CardContent>
          </Card>
        </div>
      </template>

      <!-- 历史：工作日记 / 成交记录 / 资金流水 -->
      <template v-else>
        <div v-if="tab === 'runs'" class="storage-toolbar">
          <span class="storage-toolbar__text">
            累计 <b>{{ data.total_runs }}</b> 次 · 当前保留 <b>{{ data.history_kept }}</b> 条 · 已清理 <b>{{ data.cleaned_runs }}</b> 条
          </span>
          <div class="storage-toolbar__actions">
            <Button variant="outline" size="xs" @click="configure">保留策略</Button>
            <Button variant="outline" size="xs" class="text-stamp" :disabled="busy" @click="cleanup">
              <Trash2 aria-hidden="true" />
              清理旧日记
            </Button>
          </div>
        </div>
        <AgentHistoryPanel :id="id" :kind="historyKind" :refresh-key="snapshotKey" />
      </template>

      <footer class="studio-footer">
        模拟成交不连接券商；按实际报价校验费用、T+1 及数量约束，未模拟盘口排队与分红送转。
      </footer>

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
            <DialogDescription>本次追加计入投入本金与可用现金，不计为盈利。正在研究的旧结果会失效，防止覆盖新资金余额。</DialogDescription>
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
              <LoaderCircle v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              {{ pendingFunding ? '重试同笔追加' : '确认追加' }}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </template>
  </section>
</template>
<style scoped src="./StockAgentStudio.css"></style>
