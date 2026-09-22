<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, Bot, CircleAlert, LoaderCircle, Plus, RefreshCw, Search, Wallet, X } from '@lucide/vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { getProviders } from '@/shared/api/quant'
import { createStockAgent, getAgentOptions, getStockAgents, getGuardianCard } from '@/shared/api/stock_agents'
import type { AgentConfig, AgentKind, AgentOptions, AgentSummary, GuardianCard } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
import AgentConfigDrawer from './components/AgentConfigDrawer.vue'
import AgentSummaryCard from './components/AgentSummaryCard.vue'
import { guardianCard, stockAgentCard, type AgentCardData } from './agentCards'
import { agentMoney } from './agentFormat'

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

const FILTERS = [
  { name: 'all', label: '全部' },
  { name: 'enabled', label: '已启用' },
  { name: 'paused', label: '已暂停' },
]

/** 卡片数据：自主交易员排第一，其后按后端顺序 */
const cards = computed<AgentCardData[]>(() => {
  const list: AgentCardData[] = []
  if (guardian.value) {
    const card = guardianCard(guardian.value)
    if (guardianError.value) { card.failed = true; card.status = '加载异常'; card.summary = guardianError.value }
    list.push(card)
  }
  for (const agent of agents.value) list.push(stockAgentCard(agent))
  return list
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return cards.value.filter(card => {
    const text = `${card.name} ${card.subtitle} ${card.model}`.toLowerCase()
    if (q && !text.includes(q)) return false
    if (filter.value === 'enabled') return card.enabled
    if (filter.value === 'paused') return !card.enabled
    return true
  })
})

const totalCount = computed(() => cards.value.length)
const countEnabled = computed(() => cards.value.filter(card => card.enabled).length)
const countRunning = computed(() => cards.value.filter(card => card.running).length)
const totalEquity = computed(() => cards.value.reduce((sum, card) => sum + (Number.isFinite(card.equity) ? card.equity : 0), 0))
const totalPnl = computed(() => cards.value.reduce((sum, card) => sum + (Number.isFinite(card.pnl) ? card.pnl : 0), 0))
const totalCapital = computed(() => cards.value.reduce((sum, card) => sum + (card.initialCapital ?? 0), 0))
const totalReturn = computed(() => (totalCapital.value > 0 ? (totalPnl.value / totalCapital.value) * 100 : null))
const totalPositions = computed(() => cards.value.reduce((sum, card) => sum + card.positions, 0))
const pnlTone = computed(() => (totalPnl.value > 0 ? 'up' : totalPnl.value < 0 ? 'down' : 'neutral'))
const signedPnl = computed(() => {
  const text = agentMoney(Math.abs(totalPnl.value))
  return `${totalPnl.value > 0 ? '+' : totalPnl.value < 0 ? '−' : ''}${text}`
})
const initialLoading = computed(() => loading.value && !lastLoaded.value && !guardian.value)

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
  <main class="agents-page page-fill">
    <PageHeader
      title="智能体"
    >
      <template #actions>
        <Button size="sm" :disabled="busy" @click="configure('custom')">
          <LoaderCircle v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Plus v-else aria-hidden="true" />
          新建智能体
        </Button>
        <Button access="read" variant="outline" size="sm" :disabled="loading" aria-label="刷新智能体列表" @click="load">
          <LoaderCircle v-if="loading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <RefreshCw v-else aria-hidden="true" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <div class="page-scroll agents-scroll">
      <Alert v-if="error" variant="destructive">
        <CircleAlert aria-hidden="true" />
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <AlertTitle class="line-clamp-none">{{ error }}</AlertTitle>
          <Button access="read" variant="link" size="xs" @click="load">重新加载</Button>
        </div>
      </Alert>

      <section class="agents-kpis stat-strip cols-4" aria-label="智能体总览读数">
        <StatCard label="模拟总权益 / 元" :loading="initialLoading" :hint="`${totalCount} 个账户合计`">
          <template #icon><Wallet /></template>
          {{ agentMoney(totalEquity) }}
        </StatCard>
        <StatCard
          label="累计盈亏 / 元"
          :loading="initialLoading"
          :tone="pnlTone"
          :delta="totalReturn"
          delta-label="收益率"
        >
          {{ signedPnl }}
        </StatCard>
        <StatCard label="持仓标的" :loading="initialLoading" >
          <template #icon><Activity /></template>
          {{ totalPositions }}<small>只</small>
        </StatCard>
        <StatCard
          label="已启用"
          :loading="initialLoading"
          :hint="countRunning ? `${countRunning} 个正在研判` : undefined"
        >
          <template #icon><Bot /></template>
          {{ countEnabled }}<small>/ {{ totalCount }}</small>
        </StatCard>
      </section>

      <div class="agents-toolbar" role="search" aria-label="筛选智能体">
        <PageTabs v-model="filter" :items="FILTERS" variant="pill" dense :sticky="false" aria-label="按状态筛选" />
        <div class="agents-search">
          <Search class="agents-search__icon" aria-hidden="true" />
          <Input
            v-model="query"
            size="sm"
            placeholder="搜索名称、职责或模型…"
            aria-label="搜索智能体名称或职责"
            class="agents-search__input"
          />
          <Button access="read"
            v-if="query"
            variant="ghost"
            size="icon-xs"
            class="agents-search__clear"
            aria-label="清除搜索"
            @click="query = ''"
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div v-if="initialLoading" class="agents-grid">
        <AgentSummaryCard v-for="n in 3" :key="n" loading />
      </div>
      <div v-else-if="filtered.length" class="agents-grid">
        <AgentSummaryCard v-for="card in filtered" :key="card.id" :card="card" />
      </div>
      <EmptyState
        v-else
        :icon="Search"
        :description="cards.length ? '没有匹配的智能体' : '还没有智能体'"
        :reason="cards.length ? '换个关键字或切换状态筛选' : '新建一个智能体，或等待自主交易员首次加载'"
        class="agents-empty"
      >
        <Button access="read" v-if="query || filter !== 'all'" variant="outline" size="sm" @click="query = ''; filter = 'all'">清除筛选</Button>
        <Button v-else size="sm" :disabled="busy" @click="configure('custom')">
          <Plus aria-hidden="true" />
          新建智能体
        </Button>
      </EmptyState>
    </div>

    <AgentConfigDrawer
      v-if="creating && options"
      v-model="drawer"
      :config="creating"
      :options="options"
      :providers="providers"
      :busy="busy"
      :error="settingsError"
      creating
      @save="save"
    />
  </main>
</template>

<style scoped>
.agents-page {
  color: var(--text-primary);
}

.agents-scroll {
  padding-top: var(--gap-4);
}

.agents-kpis {
  margin-bottom: 0;
}

.agents-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-3);
}

.agents-search {
  position: relative;
  display: flex;
  flex: 0 1 280px;
  align-items: center;
  min-width: 200px;
}

.agents-search__icon {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.agents-search__input {
  padding-left: 28px;
  padding-right: 28px;
}

.agents-search__clear {
  position: absolute;
  right: 3px;
}

.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--gap-4);
}

.agents-empty {
  min-height: 280px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

@media (max-width: 980px) {
  .agents-grid {
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  }
}

@media (max-width: 640px) {
  .agents-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--gap-2);
  }

  .agents-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .agents-search {
    flex: 1 1 auto;
    min-width: 0;
  }

  .agents-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--gap-3);
  }
}
</style>
