<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getTrades, listCandidates } from '@/shared/api/palace'
import { getDataLocation, getMarketCoverage } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import type { Candidate, TradeRecord } from '@/shared/types/palace'
import type { MarketCoverage } from '@/shared/types/quant'

import DataQueryBoardPanel from './components/DataQueryBoardPanel.vue'
import DataQueryCandidatesPanel from './components/DataQueryCandidatesPanel.vue'
import DataQueryDetailPanel from './components/DataQueryDetailPanel.vue'
import DataQueryPathTape from './components/DataQueryPathTape.vue'
import DataQueryTradesPanel from './components/DataQueryTradesPanel.vue'
import { useDataQueryMarket } from './composables/useDataQueryMarket'

type DeskTab = 'market' | 'trades' | 'candidates'

const route = useRoute()
const router = useRouter()

const tab = ref<DeskTab>('market')
const busy = ref(false)
const error = ref('')
const liveError = ref('')

const dataDir = ref('')
const coverage = ref<MarketCoverage | null>(null)
const coverageLoaded = ref(false)

const tradeCode = ref('')
const trades = ref<TradeRecord[]>([])
const candStrategy = ref('')
const candidates = ref<Candidate[]>([])

const {
  marketQ,
  liveOn,
  liveEnriching,
  page,
  pageSize,
  boardRows,
  boardTotal,
  boardAsOf,
  detailCode,
  detailName,
  quote,
  adjust,
  period,
  indicator,
  adjustLabel,
  lastClose,
  detailPct,
  loadBoard,
  onSearch,
  onPageSizeChange,
  openDetail,
  closeDetail,
  loadDetail,
  startRefresh,
  stopRefresh,
} = useDataQueryMarket({ route, router, tab, busy, error, liveError })

const hasMarket = computed(() => (coverage.value?.rows ?? 0) > 0)

const dateSpan = computed(() => {
  const c = coverage.value
  if (!c?.first_date || !c?.last_date) return '—'
  return `${c.first_date.slice(2)} → ${c.last_date.slice(2)}`
})

const pageTitle = computed(() => '行情')

const pageSubtitle = computed(() => {
  if (tab.value === 'market' && detailCode.value) {
    return `${detailName.value || detailCode.value} · 日/周/月 K`
  }
  if (tab.value === 'market') return '分页列表 · 本机日线优先'
  if (tab.value === 'trades') return '账本交割'
  return '候选记录'
})

async function loadCoverage(): Promise<void> {
  try {
    const loc = await getDataLocation()
    dataDir.value = loc.data_dir || loc.market_db || ''
    coverage.value = await getMarketCoverage()
  } catch (caught: unknown) {
    error.value = (caught as Error).message || '读覆盖失败'
  } finally {
    coverageLoaded.value = true
  }
}

function onTabChange(): void {
  if (tab.value !== 'market') {
    detailCode.value = ''
    stopRefresh()
  } else if (!detailCode.value) {
    void loadBoard()
    startRefresh()
  }
}

async function loadTrades(): Promise<void> {
  busy.value = true
  try {
    trades.value = await getTrades(tradeCode.value.trim() || undefined, 200)
  } catch (caught: unknown) {
    ElMessage.error((caught as Error).message || '查询交割失败')
  } finally {
    busy.value = false
  }
}

async function loadCandidates(): Promise<void> {
  busy.value = true
  try {
    candidates.value = await listCandidates({
      strategy: candStrategy.value.trim() || undefined,
      limit: 200,
    })
  } catch (caught: unknown) {
    ElMessage.error((caught as Error).message || '查询候选失败')
  } finally {
    busy.value = false
  }
}

function goBootstrapHint(): void {
  void router.push('/ops')
}

onMounted(async () => {
  await loadCoverage()
  const code = String(route.query.code || '').trim()
  if (code) {
    detailCode.value = code
    await loadDetail()
  } else {
    await loadBoard()
    startRefresh()
  }
})
</script>

<template>
  <div class="data-desk">
    <PageHeader :title="pageTitle" :subtitle="pageSubtitle">
      <el-radio-group v-model="tab" size="small" @change="onTabChange">
        <el-radio-button value="market">行情</el-radio-button>
        <el-radio-button value="trades">交割</el-radio-button>
        <el-radio-button value="candidates">候选</el-radio-button>
      </el-radio-group>
    </PageHeader>

    <DataQueryPathTape
      v-if="tab === 'market' && !detailCode"
      :data-dir="dataDir"
      :codes="coverage?.codes"
      :rows="coverage?.rows"
      :date-span="dateSpan"
      :board-as-of="boardAsOf"
    />

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      class="desk-alert"
      @close="error = ''"
    />
    <el-alert
      v-if="liveError"
      :title="`实时行情暂不可用，列表显示本机最新日线。${liveError}`"
      type="warning"
      show-icon
      closable
      class="desk-alert"
      @close="liveError = ''"
    />

    <EmptyState
      v-if="tab === 'market' && coverageLoaded && !hasMarket && !detailCode"
      description="还没有历史日 K"
      reason="数据目录已就绪，但 market.db 里尚无行情。初始化后才能查日线。"
    >
      <el-button type="primary" @click="goBootstrapHint">去初始化</el-button>
    </EmptyState>

    <div v-else class="desk-main">
      <PageBusy overlay :busy="busy" />

      <DataQueryBoardPanel
        v-if="tab === 'market' && !detailCode"
        v-model:market-q="marketQ"
        v-model:live-on="liveOn"
        :live-enriching="liveEnriching"
        v-model:page="page"
        v-model:page-size="pageSize"
        :busy="busy"
        :board-rows="boardRows"
        :board-total="boardTotal"
        @search="onSearch"
        @refresh="loadBoard"
        @page-size-change="onPageSizeChange"
        @row-click="openDetail"
      />

      <DataQueryDetailPanel
        v-else-if="tab === 'market' && detailCode"
        :detail-code="detailCode"
        :detail-name="detailName"
        :quote="quote"
        :busy="busy"
        v-model:period="period"
        v-model:indicator="indicator"
        v-model:adjust="adjust"
        :adjust-label="adjustLabel"
        :last-close="lastClose"
        :detail-pct="detailPct"
        @close="closeDetail"
        @adjust-change="loadDetail"
      />

      <DataQueryTradesPanel
        v-else-if="tab === 'trades'"
        v-model:trade-code="tradeCode"
        :trades="trades"
        :busy="busy"
        @query="loadTrades"
      />

      <DataQueryCandidatesPanel
        v-else
        v-model:cand-strategy="candStrategy"
        :candidates="candidates"
        :busy="busy"
        @query="loadCandidates"
      />
    </div>
  </div>
</template>

<style scoped>
.data-desk {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  min-height: 0;
}
.desk-alert {
  margin: 0;
}
.desk-main {
  position: relative;
  min-height: 8rem;
}
</style>
