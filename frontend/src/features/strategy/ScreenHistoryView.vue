<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  CapabilityUnavailableError,
  getScreenToday,
  getStrategies,
  syncMarket,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import TableFoot from '@/shared/components/ui/TableFoot.vue'
import TradeDialog from '@/shared/components/dialogs/TradeDialog.vue'
import { useClientPagination } from '@/shared/composables/useClientPagination'
import { decisionLabel } from '@/shared/lib/format'
import type { Pick, ScreenTodayResult, StrategyInfo } from '@/shared/types/quant'

import { useScreenHistoryQuery } from './composables/useScreenHistoryQuery'

const strategies = ref<StrategyInfo[]>([])
const selectedStrategy = ref('')
const startDate = ref<string | undefined>()
const endDate = ref<string | undefined>()

const {
  history,
  isPending: historyPending,
  error: historyError,
  refetch: refetchHistory,
} = useScreenHistoryQuery(() => ({
  strategy: selectedStrategy.value,
  start: startDate.value || undefined,
  end: endDate.value || undefined,
  limit: 500,
}))

const todayResult = ref<ScreenTodayResult | null>(null)
const syncNote = ref('')
const syncBusy = ref(false)
const bootBusy = ref(false)
const error = ref('')
const busy = historyPending

watch(historyError, (err) => {
  if (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
})

const candidateOpen = ref(false)
const tradeOpen = ref(false)
const actionPreset = reactive({ code: '', name: '' })

const {
  currentPage: todayPage,
  pageSize: todayPageSize,
  total: todayTotal,
  paginated: paginatedTodayPicks,
  reset: resetTodayPage,
} = useClientPagination(() => todayResult.value?.picks ?? [], 20)

const historySubtitle = computed(() => {
  if (!history.value) return selectedStrategy.value || undefined
  return `${history.value.strategy} · ${history.value.total} 条`
})

const needsBootstrap = computed(
  () =>
    /行情仓是空的|没有可同步的标的|数据体检未通过|empty_store|请先刷新证券列表/i.test(
      error.value,
    ),
)

const todayFactorKeys = computed(() => {
  const keys = new Set<string>()
  for (const pick of todayResult.value?.picks ?? []) {
    for (const [key, value] of Object.entries(pick.factors)) {
      if (typeof value === 'number') keys.add(key)
    }
  }
  return [...keys]
})

function scoreTone(score: number | null): string {
  if (score === null) return 'score-neutral'
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}

function fmtNum(value: number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '✓' : '—'
  return Number(value).toFixed(2)
}

function openCandidate(row: Pick): void {
  actionPreset.code = row.code
  candidateOpen.value = true
}

function openTrade(row: Pick): void {
  actionPreset.code = row.code
  tradeOpen.value = true
}

function onCandidateSaved(): void {
  ElMessage.success('候选已写入')
}

function onTradeSaved(): void {
  ElMessage.success('成交已写入')
}

function onStrategyChange(): void {
  todayResult.value = null
  resetTodayPage()
  error.value = ''
}

async function load(): Promise<void> {
  if (!selectedStrategy.value) return
  error.value = ''
  try {
    await refetchHistory()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function loadToday(forceSync = false): Promise<void> {
  if (!selectedStrategy.value) {
    error.value = '请先选择一个战法'
    return
  }
  syncBusy.value = true
  syncNote.value = forceSync ? '正在同步今日行情并选股，请稍候…' : ''
  error.value = ''
  resetTodayPage()
  try {
    todayResult.value = await getScreenToday({
      strategy: selectedStrategy.value,
      force_sync: forceSync,
    })
    syncNote.value = todayResult.value.sync_note
      ? `行情同步：${todayResult.value.sync_note}`
      : `选股完成 · ${todayResult.value.picks.length} 只 · ${todayResult.value.trade_date}`
    ElMessage.success(`选股完成：${todayResult.value.picks.length} 只`)
    await refetchHistory()
  } catch (e: unknown) {
    error.value =
      e instanceof CapabilityUnavailableError
        ? e.message
        : e instanceof Error
          ? e.message
          : '请求失败'
    syncNote.value = ''
  } finally {
    syncBusy.value = false
  }
}

async function bootstrapMarket(): Promise<void> {
  bootBusy.value = true
  error.value = ''
  try {
    const report = await syncMarket({
      refresh_instruments: true,
      limit: 200,
      workers: 6,
      interval: 0.1,
    })
    ElMessage.success(
      `初始化完成：成功 ${String(report.succeeded ?? 0)} / 跳过 ${String(report.skipped ?? 0)}`,
    )
    if (selectedStrategy.value) await loadToday(false)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '初始化失败'
  } finally {
    bootBusy.value = false
  }
}

onMounted(async () => {
  try {
    strategies.value = await getStrategies()
    if (strategies.value.length && !selectedStrategy.value) {
      selectedStrategy.value = strategies.value[0].slug
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '无法加载战法列表'
  }
})
</script>

<template>
  <PageHeader title="选股" :subtitle="historySubtitle">
    <el-button :disabled="!selectedStrategy || busy" @click="load">刷新历史</el-button>
    <el-button
      type="primary"
      :loading="syncBusy"
      :disabled="!selectedStrategy"
      @click="loadToday(true)"
    >
      今日选股
    </el-button>
  </PageHeader>

  <el-alert
    v-if="error"
    :title="error"
    type="error"
    show-icon
    closable
    class="mb"
    @close="error = ''"
  >
    <template v-if="needsBootstrap" #default>
      <p class="hint">行情仓可能为空。可先初始化行情，或到「工坊」页同步。</p>
      <el-button size="small" type="primary" :loading="bootBusy" @click="bootstrapMarket">
        初始化行情
      </el-button>
    </template>
  </el-alert>

  <el-alert v-if="syncNote" :title="syncNote" type="success" show-icon closable class="mb" @close="syncNote = ''" />

  <Sheet quiet class="filter-bar" padded>
    <el-form inline class="filter-form">
      <el-form-item label="战法">
        <el-select
          v-model="selectedStrategy"
          placeholder="选择战法"
          filterable
          style="width: 14rem"
          @change="onStrategyChange"
        >
          <el-option
            v-for="s in strategies"
            :key="s.slug"
            :label="s.name"
            :value="s.slug"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="起始">
        <el-date-picker
          v-model="startDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="不限"
          @change="load"
        />
      </el-form-item>
      <el-form-item label="截止">
        <el-date-picker
          v-model="endDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="不限"
          @change="load"
        />
      </el-form-item>
    </el-form>
  </Sheet>

  <Sheet
    v-if="todayResult"
    title="今日结果"
    :chip="todayResult.picks.length"
    margin
  >
    <template #actions>
      <span class="mono dim">{{ todayResult.trade_date }}</span>
      <span class="dim">
        {{ todayResult.entry_timing === 'open' ? '当日开盘入场' : '次日开盘入场' }}
      </span>
    </template>
    <p v-if="todayResult.synced && todayResult.sync_note" class="form-hint">✓ {{ todayResult.sync_note }}</p>
    <template v-if="todayResult.picks.length">
      <el-table :data="paginatedTodayPicks" size="small">
        <el-table-column label="代码" min-width="120">
          <template #default="{ row }">
            <StockLink :code="row.code" />
          </template>
        </el-table-column>
        <el-table-column label="开" align="right" width="90">
          <template #default="{ row }">{{ fmtNum(row.open) }}</template>
        </el-table-column>
        <el-table-column label="收" align="right" width="90">
          <template #default="{ row }">{{ fmtNum(row.close) }}</template>
        </el-table-column>
        <el-table-column
          v-for="key in todayFactorKeys"
          :key="key"
          :label="key"
          align="right"
          min-width="90"
        >
          <template #default="{ row }">{{ fmtNum(row.factors[key]) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="148" align="center" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click.stop="openCandidate(row)">记候选</el-button>
            <el-button text size="small" @click.stop="openTrade(row)">记成交</el-button>
          </template>
        </el-table-column>
      </el-table>
      <TableFoot v-model:page="todayPage" :total="todayTotal" :page-size="todayPageSize" />
    </template>
    <EmptyState v-else description="当日无标的满足条件" />
  </Sheet>

  <Sheet v-if="history && history.dates.length" title="历史" :chip="history.total" margin>
    <el-collapse>
      <el-collapse-item v-for="date in history.dates" :key="date" :name="date">
        <template #title>
          <span class="collapse-title">
            <strong class="mono">{{ date }}</strong>
            <el-tag size="small">{{ history.by_date[date].length }} 只</el-tag>
          </span>
        </template>
        <ul class="rows">
          <li v-for="item in history.by_date[date]" :key="item.id" class="cand">
            <span class="score" :class="scoreTone(item.score)">{{ item.score ?? '—' }}</span>
            <div class="grow">
              <div class="row-main">
                <StockLink :code="item.code" :name="item.name" />
                <el-tag size="small" type="info">{{ decisionLabel(item.decision) }}</el-tag>
                <span v-if="item.timing" class="dim">{{ item.timing }}</span>
              </div>
              <p class="reason">{{ item.reason }}</p>
            </div>
          </li>
        </ul>
      </el-collapse-item>
    </el-collapse>
  </Sheet>

  <EmptyState
    v-else-if="!busy && selectedStrategy && history"
    description="该战法在此区间没有历史记录。可先跑今日选股，或在设置里开启选股任务。"
  >
    <el-button type="primary" :loading="syncBusy" @click="loadToday(true)">今日选股</el-button>
  </EmptyState>

  <EmptyState v-else-if="!selectedStrategy" description="请先选择一个战法，再查看历史或触发选股。" />

  <RecordDialog
    v-model="candidateOpen"
    kind="candidate"
    :preset-code="actionPreset.code"
    @saved="onCandidateSaved"
  />
  <TradeDialog
    v-model="tradeOpen"
    :preset-code="actionPreset.code"
    @saved="onTradeSaved"
  />
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem 0.35rem;
}

.filter-form :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 0.75rem;
}

.hint {
  margin: 0.35rem 0 0.65rem;
  color: var(--muted);
  font-size: 0.88rem;
}

.collapse-title {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}
</style>
