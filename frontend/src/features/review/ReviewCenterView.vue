<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { CapabilityUnavailableError } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import { signedPct as pct } from '@/shared/lib/format'
import Sheet from '@/shared/components/layout/Sheet.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel, toneClass } from '@/shared/lib/format'

import { useCandidateOutcomesQuery } from './composables/useCandidateOutcomesQuery'
import { usePlanOutcomesQuery } from './composables/usePlanOutcomesQuery'

const activeTab = ref('candidates')
const reviewTabs = [
  { name: 'candidates', label: '候选验证' },
  { name: 'plans', label: '预案兑现' },
]

const {
  candidates,
  isPending: candidatesPending,
  error: candidatesError,
  refetch: refetchCandidates,
} = useCandidateOutcomesQuery(300, () => ({ enabled: activeTab.value === 'candidates' }))
const { plans, isPending: plansPending, error: plansError, refetch: refetchPlans } =
  usePlanOutcomesQuery(() => ({ enabled: activeTab.value === 'plans' }))

const busy = ref(false)
const errorText = ref('')
const planOpen = ref(false)
const horizons = [1, 3, 5, 10, 20, 60]

const candidateColumns = computed<BasicTableColumn[]>(() => {
  const cols: BasicTableColumn[] = [
    { prop: 'base_date', label: '日期', minWidth: 110, slotName: 'date' },
    { prop: 'code', label: '标的', minWidth: 140, slotName: 'stock' },
    { prop: 'decision', label: '裁决', minWidth: 90, slotName: 'decision' },
    { prop: 'base_close', label: '基准价', align: 'right', minWidth: 90, slotName: 'base' },
  ]
  for (const h of horizons) {
    cols.push({
      prop: `t${h}`,
      label: `T+${h}`,
      align: 'right',
      minWidth: 90,
      slotName: `t${h}`,
    })
  }
  return cols
})

const candidateRows = computed(
  () => (candidates.value?.outcomes.slice(0, 40) ?? []) as unknown as Record<string, unknown>[],
)

const candidateTotal = computed(() => candidates.value?.outcomes.length ?? 0)

const planColumns: BasicTableColumn[] = [
  { prop: 'occurred_on', label: '日期', minWidth: 110, slotName: 'date' },
  { prop: 'code', label: '标的', minWidth: 100, slotName: 'code' },
  { prop: 'title', label: '标题', minWidth: 140 },
  { prop: 'stop_price', label: '止损', align: 'right', minWidth: 90, slotName: 'stop' },
  { prop: 'target_price', label: '止盈', align: 'right', minWidth: 90, slotName: 'target' },
  { prop: 'status_final', label: '状态', minWidth: 100, slotName: 'status' },
]

const planRows = computed(() => plans.value as unknown as Record<string, unknown>[])

function formatQueryError(err: unknown): string {
  if (err instanceof CapabilityUnavailableError) return err.message
  return toErrorMessage(err, '加载失败')
}

watch([candidatesError, plansError], ([cd, pl]) => {
  const byTab = activeTab.value === 'candidates' ? cd : pl
  if (byTab) errorText.value = formatQueryError(byTab)
})

function planStatus(status: string): string {
  return (
    {
      observing: '观察中',
      stop_hit: '触发止损',
      target_hit: '触发止盈',
      stop_first: '先止损',
      target_first: '先止盈',
      expired: '窗口未兑现',
      no_data: '无行情',
    }[status] ?? status
  )
}

function selectedHorizonText(horizon: number): string {
  const selected = candidates.value?.summary?.selected as
    | Record<string, { win_rate?: number; n?: number } | null>
    | undefined
  const stats = selected?.[`t${horizon}`]
  if (!stats || stats.win_rate == null) return '—'
  return `${stats.win_rate}%（${stats.n ?? 0}）`
}

function onPlanSaved(): void {
  void refetchPlans()
}

async function reloadActive(): Promise<void> {
  busy.value = true
  errorText.value = ''
  try {
    const task = activeTab.value === 'candidates' ? refetchCandidates : refetchPlans
    await task()
    const err = activeTab.value === 'candidates' ? candidatesError.value : plansError.value
    if (err) errorText.value = formatQueryError(err)
  } catch (caught: unknown) {
    errorText.value = formatQueryError(caught) || '加载失败'
  } finally {
    busy.value = false
  }
}

const pageBusy = computed(() => {
  if (busy.value) return true
  if (activeTab.value === 'candidates') return Boolean(candidatesPending.value)
  return Boolean(plansPending.value)
})
</script>

<template>
  <div class="page-fill">
  <el-alert v-if="errorText" :title="errorText" type="error" show-icon closable class="mb" @close="errorText = ''" />

  <PageHeader
    title="复盘中心"
    note="候选 T+N 与预案兑现为落库记录的事后核对，本页只读"
  />

  <PageTabs v-model="activeTab" :items="reviewTabs" :sticky="false" aria-label="复盘分区">
    <template #trailing>
      <el-button size="small" :disabled="pageBusy" @click="reloadActive">刷新</el-button>
    </template>
  </PageTabs>

  <div class="page-scroll page-scroll--flush-top">
  <div v-show="activeTab === 'candidates'">
      <Sheet plain padded>
        <template v-if="candidates && candidates.outcomes.length">
          <div class="brief">
            <div class="brief-top"><strong class="brief-title">精选短线兑现</strong></div>
            <div class="stat-row">
              <StatCard
                v-for="h in [1, 3, 5]"
                :key="h"
                layout="row"
                :label="`T+${h} 胜率`"
                :value="selectedHorizonText(h)"
              />
            </div>
          </div>
          <div v-if="candidates.summary.missed_winners.length" class="brief">
            <div class="brief-top"><strong class="brief-title">当初否决、事后大涨</strong></div>
            <ul class="rows">
              <li v-for="item in candidates.summary.missed_winners" :key="item.code + item.base_date">
                <div class="row-main">
                  <strong>{{ item.name || item.code }}</strong>
                  <span class="code">{{ item.code }}</span>
                  <span class="tag">{{ decisionLabel(item.decision) }}</span>
                  <span class="mono tone-up">T+20 {{ pct(item.return_t20) }}</span>
                </div>
              </li>
            </ul>
          </div>
          <BasicTable
            :columns="candidateColumns"
            :data-source="candidateRows"
            :pagination="false"
            :row-key="(row) => `${row.code}-${row.base_date}`"
          >
            <template #date="{ row }">
              <span class="mono dim">{{ row.base_date }}</span>
            </template>
            <template #stock="{ row }">
              <StockLink :code="String(row.code)" :name="String(row.name || row.code)" />
            </template>
            <template #decision="{ row }">
              <span class="tag">{{ decisionLabel(String(row.decision)) }}</span>
            </template>
            <template #base="{ row }">
              {{ row.base_close != null ? Number(row.base_close).toFixed(2) : '—' }}
            </template>
            <template v-for="h in horizons" :key="h" #[`t${h}`]="{ row }">
              <span :class="toneClass(Number((row.returns as Record<string, number | null>)?.[`t${h}`] ?? 0))">
                {{ pct((row.returns as Record<string, number | null>)?.[`t${h}`]) }}
              </span>
            </template>
          </BasicTable>
          <p v-if="candidateTotal > 40" class="form-hint truncate-hint">
            仅显示前 40 条，共 {{ candidateTotal }} 条
          </p>
        </template>
        <PageBusy v-else-if="pageBusy" label="加载候选验证…" />
        <EmptyState v-else description="候选池还没有记录">
          <RouterLink to="/pool"><el-button type="primary">去候选池</el-button></RouterLink>
        </EmptyState>
      </Sheet>
  </div>

  <div v-show="activeTab === 'plans'">
      <Sheet title="预案兑现" :chip="plans.length || undefined" plain padded>
        <BasicTable
          v-if="plans.length"
          :columns="planColumns"
          :data-source="planRows"
          :pagination="false"
          row-key="plan_id"
        >
          <template #date="{ row }">
            <span class="mono dim">{{ row.occurred_on }}</span>
          </template>
          <template #code="{ row }">
            <span class="code">{{ row.code }}</span>
          </template>
          <template #stop="{ row }">{{ row.stop_price ?? '—' }}</template>
          <template #target="{ row }">{{ row.target_price ?? '—' }}</template>
          <template #status="{ row }">
            <span class="tag">{{ planStatus(String(row.status_final ?? '')) }}</span>
          </template>
        </BasicTable>
        <PageBusy v-else-if="pageBusy" label="加载预案…" />
        <EmptyState v-else description="还没有预案。写一份后可自动核对止损止盈是否触发。">
          <el-button type="primary" @click="planOpen = true">写预案</el-button>
        </EmptyState>
      </Sheet>
  </div>
  </div>

  <RecordDialog v-model="planOpen" kind="plan" @saved="onPlanSaved" />
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
}

.dim {
  color: var(--mist);
}

.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 0.5rem;
}

.truncate-hint {
  margin: 0.4rem 0 0;
  text-align: right;
}

</style>
