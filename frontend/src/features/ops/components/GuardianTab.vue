<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, defineAsyncComponent, KeepAlive, onMounted, onUnmounted, ref, shallowRef, useId, watch } from 'vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import GuardianMobileSummary from './GuardianMobileSummary.vue'
import { toast } from 'vue-sonner'
import { Archive, Bot, Ellipsis, Info, Cpu, Pause, Play, RefreshCw, Settings, TriangleAlert } from '@lucide/vue'
import { getGuardian, saveGuardian } from '@/shared/api/guardian'
import { getProviders } from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/shared/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import GuardianStoragePanel from '@/features/agents/components/GuardianStoragePanel.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import type { GuardianStatus, GuardianConfig } from '@/shared/types/guardian'
import type { LlmProvider } from '@/shared/types/quant'
import { agentMoney } from '@/features/agents/agentFormat'
import GuardianSettingsDrawer from './GuardianSettingsDrawer.vue'
import GuardianAccountPanel from './GuardianAccountPanel.vue'
const GuardianReviewPanel = defineAsyncComponent(() => import('./GuardianReviewPanel.vue'))
const GuardianConsultPanel = defineAsyncComponent(() => import('./GuardianConsultPanel.vue'))
const GuardianResearchPanel = defineAsyncComponent(() => import('./GuardianResearchPanel.vue'))

const mobile = useMobileLayout()
const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })
const data = shallowRef<GuardianStatus | null>(null)
const providers = shallowRef<LlmProvider[]>([])
const providersLoading = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const settingsOpen = ref(false)
const feesOpen = ref(false)
const storage = ref<InstanceType<typeof GuardianStoragePanel> | null>(null)
const startOnSave = ref(false)
const settings = ref<InstanceType<typeof GuardianSettingsDrawer> | null>(null)
const section = ref('account')
const accountSection = ref('positions')
const active = computed(() => props.active)
const enabled = computed(() => data.value?.config.enabled ?? false)
const configured = computed(() => Boolean(data.value?.config.model && data.value.config.provider))
const allocation = computed(() => data.value?.state.equity_cents ? data.value.state.market_value_cents / data.value.state.equity_cents * 100 : 0)
const stateLabel = computed(() => {
  if (data.value?.runs[0]?.status === 'running') return '正在研判'
  if (!configured.value) return '等待配置'
  if (!enabled.value) return '已暂停'
  if (data.value?.notification_silence === 'market_closed') return '休市静默'
  if (data.value?.notification_silence) return '日历待核验'
  return '运行中'
})
const workspaceTabs = computed(() => [
  { name: 'account', label: '持仓股', badge: data.value?.state.positions.length || undefined },
  { name: 'research', label: '自选股', badge: data.value?.observation_count || undefined },
  { name: 'reviews', label: '复盘计划' },
  { name: 'consult', label: '对话' },
])
const pnlTone = (value?: number) => (value ?? 0) > 0 ? 'gain' : (value ?? 0) < 0 ? 'loss' : ''
const signedMoney = (value?: number) => ((value ?? 0) > 0 ? '+' : '') + agentMoney(value ?? 0)
const totalPct = computed(() => {
  const state = data.value?.state
  if (!state?.initial_capital_cents) return ''
  const pct = state.total_pnl_cents / state.initial_capital_cents * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`
})
const allocationText = computed(() => `${Number(allocation.value.toFixed(1))}%`)
const valuationText = computed(() => {
  const state = data.value?.state
  if (!state?.valuation_date) return ''
  return `${state.valuation_date} ${state.valuation_kind === 'official_close' ? '收盘估值' : '参考估值'}`
})
const emit = defineEmits<{ summary: [value: { tail: string; state: 'ok' | 'idle' | 'bad' }] }>()
let controller: AbortController | undefined
let pending: Promise<void> | undefined
let providerVersion = 0
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
function accept(value: GuardianStatus): void {
  data.value = value
  emit('summary', { tail: value.config.enabled ? '运行中' : '已暂停', state: value.config.enabled ? 'ok' : 'idle' })
}
async function load(): Promise<void> {
  if (!props.active || disposed || busy.value) return
  // 父页刷新、手动刷新与轮询共用进行中的读取，避免反复取消首屏请求。
  if (pending && !controller?.signal.aborted) return pending
  const request = new AbortController(); controller = request
  loading.value = true
  pending = (async () => {
    try {
      const status = await getGuardian(request.signal)
      if (!disposed && !request.signal.aborted) { accept(status); error.value = '' }
    } catch (e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
    finally { if (controller === request) { loading.value = false; pending = undefined } }
  })()
  return pending
}
async function configure(start = false): Promise<void> {
  startOnSave.value = start; settingsOpen.value = true; error.value = ''
  const version = ++providerVersion
  providersLoading.value = true
  try {
    const list = await getProviders()
    if (!disposed && version === providerVersion) providers.value = list.filter(p => p.is_active)
  } catch (e) { if (!disposed && version === providerVersion) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (version === providerVersion) providersLoading.value = false }
}
async function save(config: GuardianConfig): Promise<void> {
  controller?.abort()
  busy.value = true; error.value = ''
  try { const result = await saveGuardian(config); if (!disposed) { accept(result); settingsOpen.value = false; toast.success('交易员配置已保存') } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
function toggle(): void {
  if (!data.value) return
  if (!configured.value && !enabled.value) { void configure(true); return }
  void save({ ...data.value.config, enabled: !enabled.value })
}
async function poll(): Promise<void> {
  if (disposed) return
  if (props.active && data.value && !busy.value && !loading.value && !settingsOpen.value && !document.hidden) await load()
  if (!disposed) timer = setTimeout(poll, 10000)
}
watch(() => props.active, active => { if (!active) { controller?.abort(); providerVersion++; providersLoading.value = false } })
onMounted(() => { timer = setTimeout(poll, 10000) })
onUnmounted(() => { disposed = true; providerVersion++; controller?.abort(); clearTimeout(timer) })
defineExpose({ load, isDirty: () => settings.value?.isDirty() ?? false })

/** `Tabs` 的 modelValue 是 reka-ui 的 `AcceptableValue`，这里收成本页的 string 档 */
function onSectionChange(value: unknown): void {
  section.value = String(value)
}
const panelId = `guardian-workspace-panel-${useId()}`
</script>

<template>
  <div class="guardian-workspace" aria-label="天才交易员">
    <header class="guardian-header">
      <div class="guardian-identity">
        <slot name="leading" />
        <span class="guardian-avatar" :class="{ 'is-live': enabled && configured }" aria-hidden="true"><Bot /></span>
        <div class="guardian-id-text">
          <div class="guardian-id-row">
            <h1>天才交易员</h1>
            <Badge variant="outline" class="guardian-state" :class="{ 'is-running': enabled && configured }">
              <Spinner v-if="data?.runs[0]?.status === 'running'" class="size-3 animate-spin" aria-hidden="true" />
              <span v-else class="guardian-state__dot" aria-hidden="true" />
              {{ stateLabel }}
            </Badge>
          </div>
          <span v-if="data" class="guardian-model" :title="data.config.model"><Cpu aria-hidden="true" />{{ data.config.model || '模型未配置' }}</span>
        </div>
      </div>
      <PageTabs v-if="mobile" :panel-id="panelId" :model-value="section" :items="workspaceTabs" variant="pill" :sticky="false" aria-label="交易员工作区" @update:model-value="onSectionChange" class="guardian-inline-tabs" />
      <div class="guardian-actions">
        <Button v-if="!mobile" class="guardian-storage-action" variant="ghost" size="sm" :disabled="storage?.busy" @click="storage?.configure()"><Settings aria-hidden="true" />保留策略</Button>
        <Button v-if="!mobile" class="guardian-storage-action" variant="ghost" size="sm" :disabled="storage?.busy" @click="storage?.cleanup()"><Archive aria-hidden="true" />清理过期详情</Button>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="刷新交易员" :disabled="busy || loading" @click="load">
          <Spinner v-if="loading" class="animate-spin" aria-hidden="true" /><RefreshCw v-else aria-hidden="true" />
        </Button>
        <Button v-if="!mobile" variant="outline" size="sm" :disabled="!data || busy" @click="configure()"><Settings aria-hidden="true" />设置</Button>
        <Button v-if="!mobile" :variant="enabled ? 'outline' : 'default'" size="sm" :disabled="busy || !data" @click="toggle">
          <Spinner v-if="busy" class="animate-spin" aria-hidden="true" /><Pause v-else-if="enabled" aria-hidden="true" /><Play v-else aria-hidden="true" />
          {{ enabled ? '暂停' : configured ? '启动' : '配置开启' }}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon-sm" aria-label="更多交易员操作"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem v-if="mobile" :disabled="!data || busy" @select="configure()"><Settings />交易员设置</DropdownMenuItem>
            <DropdownMenuItem v-if="mobile" :disabled="!data || busy" @select="toggle"><Pause v-if="enabled" /><Play v-else />{{ enabled ? '暂停交易员' : configured ? '启动交易员' : '配置并开启' }}</DropdownMenuItem>
            <DropdownMenuItem class="guardian-storage-menu" :disabled="storage?.busy" @select="storage?.configure()"><Settings aria-hidden="true" />保留策略</DropdownMenuItem>
            <DropdownMenuItem class="guardian-storage-menu" :disabled="storage?.busy" @select="storage?.cleanup()"><Archive aria-hidden="true" />清理过期详情</DropdownMenuItem>
            <DropdownMenuItem access="read" :disabled="!data" @select="feesOpen = true"><Info aria-hidden="true" />费用与成交口径</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
    <GuardianStoragePanel ref="storage" :show-actions="false" />

    <Alert v-if="error && !settingsOpen" variant="destructive">
      <TriangleAlert />
      <div class="guardian-error-row">
        <AlertTitle class="line-clamp-none">{{ error }}</AlertTitle>
        <Button access="read" variant="link" size="xs" @click="load">重试加载</Button>
      </div>
    </Alert>

    <div v-if="!data" :id="panelId" role="tabpanel" tabindex="0" :aria-labelledby="`${panelId}-tab-${section}`" :aria-busy="loading">
      <div v-if="loading" class="guardian-loading" aria-hidden="true">
        <Skeleton v-for="n in 5" :key="n" class="guardian-loading__row" />
      </div>
    </div>

    <template v-if="data">
      <GuardianMobileSummary v-if="mobile && section === 'account' && accountSection === 'positions'" :data="data" />
      <section v-if="!mobile" class="guardian-ledger" aria-label="模拟账户资产，单位元">
        <div class="guardian-ledger__hero">
          <span class="guardian-ledger__label">模拟净资产</span>
          <strong class="guardian-ledger__equity">{{ agentMoney(data.state.equity_cents) }}</strong>
          <span class="guardian-ledger__pnl" :class="pnlTone(data.state.total_pnl_cents)">
            {{ signedMoney(data.state.total_pnl_cents) }}<em v-if="totalPct">{{ totalPct }}</em>
          </span>
        </div>
        <dl class="guardian-ledger__facts">
          <div><dt>可用现金</dt><dd>{{ agentMoney(data.state.cash_cents) }}</dd></div>
          <div><dt>持仓市值</dt><dd>{{ agentMoney(data.state.market_value_cents) }}</dd></div>
          <div><dt>已实现</dt><dd :class="pnlTone(data.state.realized_pnl_cents)">{{ signedMoney(data.state.realized_pnl_cents) }}</dd></div>
          <div><dt>浮动</dt><dd :class="pnlTone(data.state.unrealized_pnl_cents)">{{ signedMoney(data.state.unrealized_pnl_cents) }}</dd></div>
        </dl>
        <div class="guardian-ledger__alloc">
          <div class="guardian-ledger__alloc-row">
            <span class="guardian-ledger__label">仓位</span>
            <strong>{{ allocationText }}</strong>
          </div>
          <span class="guardian-ledger__bar" aria-hidden="true"><i :style="{ width: `${Math.min(100, Math.max(0, allocation))}%` }" /></span>
          <span v-if="valuationText" class="guardian-ledger__valuation">{{ valuationText }}</span>
        </div>
      </section>

      <div v-if="!mobile" class="guardian-tabs-row">
        <PageTabs :panel-id="panelId" :model-value="section" :items="workspaceTabs" :sticky="false" aria-label="交易员工作区" @update:model-value="onSectionChange" class="guardian-tabs">
          <template #trailing>
            <span class="guardian-history-summary" :title="storage?.summary">{{ storage?.summary }}</span>
          </template>
        </PageTabs>
      </div>

      <!-- 视图内容 -->
      <div :id="panelId" class="guardian-content-area" role="tabpanel" tabindex="0" :aria-labelledby="`${panelId}-tab-${section}`">
        <KeepAlive v-if="active">
          <GuardianAccountPanel v-if="section === 'account'" :account="data.state" :experience="data.experience" @review="section = 'research'" @section-change="value => accountSection = value" />
          <GuardianResearchPanel v-else-if="section === 'research'" :account="data.state" :enabled="enabled" :notify="data.config.notify" @changed="load" />
          <GuardianReviewPanel v-else-if="section === 'reviews'" :enabled="enabled" @changed="load" />
          <GuardianConsultPanel v-else-if="section === 'consult'" :model="data.config.model" />
        </KeepAlive>
      </div>

      <Dialog v-model:open="feesOpen"><DialogContent class="sm:max-w-xl"><DialogHeader><DialogTitle>费用与成交口径</DialogTitle></DialogHeader><div class="space-y-3 text-sm leading-7"><p>初始本金 {{ agentMoney(data.state.initial_capital_cents) }} 元 · T+1。</p><p>累计费用 {{ agentMoney(data.state.fees_cents) }} 元。成本含买入费用，卖出净收入扣除费用后计盈亏。</p><p>佣金万 2.5（免 5，无最低收费）；印花税卖出万五；过户费双向十万一。</p><p>按新鲜行情参考价模拟成交，未模拟盘口排队及分红送转。</p></div></DialogContent></Dialog>
      <GuardianSettingsDrawer
        ref="settings"
        v-model="settingsOpen"
        :config="data.config"
        :default-prompt="data.default_prompt"
        :default-weekly-prompt="data.default_weekly_prompt"
        :providers="providers"
        :providers-loading="providersLoading"
        :busy="busy"
        :error="error"
        :start-on-save="startOnSave"
        @save="save"
      />
    </template>
  </div>
</template>
<style scoped src="./GuardianTab.css"></style>
<style scoped src="./GuardianTab.mobile.css"></style>
