<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { CapabilityUnavailableError } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import { signedPct as pct } from '@/shared/lib/format'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel, toneClass } from '@/shared/lib/format'
import { InfoFilled, RefreshRight } from '@element-plus/icons-vue'

import { useCandidateOutcomesQuery } from './composables/useCandidateOutcomesQuery'
import { usePlanOutcomesQuery } from './composables/usePlanOutcomesQuery'

const activeTab = ref('candidates')
/** 页面口径：不占正文行，只作 PageTabs 尾部的一枚 ⓘ */
const PAGE_NOTE = '落库记录的事后核对，本页只读'

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
    { prop: 'base_date', label: '日期', minWidth: 110, align: 'center', headerAlign: 'center', slotName: 'date' },
    { prop: 'code', label: '标的', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'stock' },
    { prop: 'decision', label: '裁决', minWidth: 90, align: 'center', headerAlign: 'center', slotName: 'decision' },
    { prop: 'base_close', label: '基准价', align: 'center', headerAlign: 'center', minWidth: 90, slotName: 'base' },
  ]
  for (const h of horizons) {
    cols.push({
      prop: `t${h}`,
      label: `T+${h}`,
      align: 'center',
      headerAlign: 'center',
      minWidth: 90,
      slotName: `t${h}`,
    })
  }
  return cols
})

const candidatePage = ref(1)
const CANDIDATE_PAGE_SIZE = 40
const candidateRows = computed(
  () =>
    ((candidates.value?.outcomes ?? []).slice(
      (candidatePage.value - 1) * CANDIDATE_PAGE_SIZE,
      candidatePage.value * CANDIDATE_PAGE_SIZE,
    ) ?? []) as unknown as Record<string, unknown>[],
)

const candidateTotal = computed(() => candidates.value?.outcomes.length ?? 0)

const planColumns: BasicTableColumn[] = [
  { prop: 'occurred_on', label: '日期', minWidth: 110, align: 'center', headerAlign: 'center', slotName: 'date' },
  { prop: 'code', label: '标的', minWidth: 100, align: 'center', headerAlign: 'center', slotName: 'code' },
  { prop: 'title', label: '标题', minWidth: 140, align: 'center', headerAlign: 'center' },
  { prop: 'stop_price', label: '止损', align: 'center', headerAlign: 'center', minWidth: 90, slotName: 'stop' },
  { prop: 'target_price', label: '止盈', align: 'center', headerAlign: 'center', minWidth: 90, slotName: 'target' },
  { prop: 'status_final', label: '状态', minWidth: 100, align: 'center', headerAlign: 'center', slotName: 'status' },
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

function horizonReturn(row: Record<string, unknown>, horizon: number): number | null {
  const returns = row.returns
  if (!returns || typeof returns !== 'object' || Array.isArray(returns)) return null
  const value = (returns as Record<string, unknown>)[`t${horizon}`]
  return typeof value === 'number' ? value : null
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

/** 预案条数原来印在 Sheet 标题的 chip 上，标题删掉后挂到 Tab 徽标 */
const reviewTabs = computed(() => [
  { name: 'candidates', label: '候选验证' },
  { name: 'plans', label: '预案兑现', badge: plans.value.length || undefined },
])
</script>

<template>
  <div class="review-center page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden" :aria-busy="pageBusy">
    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="mb-2 shrink-0"
      @close="errorText = ''"
    />

    <PageTabs v-model="activeTab" :items="reviewTabs" :sticky="false" aria-label="复盘分区">
      <template #trailing>
        <div
          v-if="activeTab === 'candidates' && candidates && candidates.outcomes.length"
          class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1"
        >
          <HeaderStat
            v-for="h in [1, 3, 5]"
            :key="h"
            :label="`T+${h} 胜率`"
            :value="selectedHorizonText(h)"
          />
        </div>
        <el-button size="small" :icon="RefreshRight" :loading="pageBusy" @click="reloadActive">刷新</el-button>
        <el-tooltip :content="PAGE_NOTE" placement="bottom-end" :show-after="200">
          <el-icon
            class="text-aux text-mist inline-flex shrink-0 cursor-help"
            tabindex="0"
            :aria-label="PAGE_NOTE"
          >
            <InfoFilled />
          </el-icon>
        </el-tooltip>
      </template>
    </PageTabs>

    <div class="flex h-0 min-h-0 flex-1 flex-col overflow-hidden">
      <div v-show="activeTab === 'candidates'" class="page-pane">
        <div v-if="candidates?.summary.missed_winners.length" class="brief missed shrink-0">
          <span class="missed__kicker">
            当初否决、事后大涨 · {{ candidates.summary.missed_winners.length }}
          </span>
          <span
            v-for="item in candidates.summary.missed_winners"
            :key="item.code + item.base_date"
            class="missed__item"
          >
            <strong>{{ item.name || item.code }}</strong>
            <span class="code">{{ item.code }}</span>
            <el-tag size="small" effect="plain" type="info">
              {{ decisionLabel(item.decision) }}
            </el-tag>
            <span class="mono tone-up">T+20 {{ pct(item.return_t20) }}</span>
          </span>
        </div>
        <BasicTable
          :columns="candidateColumns"
          :data-source="candidateRows"
          :loading="pageBusy"
          height="100%"
          :pagination="{
            currentPage: candidatePage,
            pageSize: CANDIDATE_PAGE_SIZE,
            total: candidateTotal,
            hideOnSinglePage: true,
            layout: 'total, prev, pager, next',
          }"
          :row-key="(row) => `${row.code}-${row.base_date}`"
          empty-text="候选池还没有记录"
          empty-reason="选股落池后自动出现"
          @current-change="(page) => { candidatePage = page }"
        >
          <template #date="{ row }">
            <span class="mono dim">{{ row.base_date }}</span>
          </template>
          <template #stock="{ row }">
            <StockLink :code="String(row.code)" :name="String(row.name || row.code)" />
          </template>
          <template #decision="{ row }">
            <el-tag size="small" effect="plain" type="info">
              {{ decisionLabel(String(row.decision)) }}
            </el-tag>
          </template>
          <template #base="{ row }">
            {{ row.base_close != null ? Number(row.base_close).toFixed(2) : '—' }}
          </template>
          <template v-for="h in horizons" :key="h" #[`t${h}`]="{ row }">
            <span :class="toneClass(Number(horizonReturn(row, h) ?? 0))">
              {{ pct(horizonReturn(row, h)) }}
            </span>
          </template>
          <template #empty>
            <EmptyState description="候选池还没有记录" reason="选股落池后自动出现">
              <RouterLink to="/pool"><el-button type="primary">去候选池</el-button></RouterLink>
            </EmptyState>
          </template>
        </BasicTable>
      </div>

      <div v-show="activeTab === 'plans'" class="page-pane">
        <BasicTable
          :columns="planColumns"
          :data-source="planRows"
          :loading="pageBusy"
          :pagination="false"
          height="100%"
          row-key="plan_id"
          empty-text="还没有预案"
          empty-reason="写一份后自动核对止损止盈"
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
            <el-tag size="small" effect="plain" type="info">
              {{ planStatus(String(row.status_final ?? '')) }}
            </el-tag>
          </template>
          <template #empty>
            <EmptyState description="还没有预案" reason="写一份后自动核对止损止盈">
              <el-button type="primary" @click="planOpen = true">写预案</el-button>
            </EmptyState>
          </template>
        </BasicTable>
      </div>

      <RecordDialog v-model="planOpen" kind="plan" @saved="onPlanSaved" />
    </div>
  </div>
</template>

<style scoped>
.dim {
  color: var(--mist);
}

.missed {
  max-height: calc(var(--row-h) * 3);
  overflow: auto;
  overscroll-behavior: contain;
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-3);
}

.missed__kicker {
  font-size: var(--fs-kicker);
  letter-spacing: 0;
  color: var(--mist);
  white-space: normal;
}

.missed__item {
  flex-wrap: wrap;
  overflow-wrap: anywhere;
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  min-width: 0;
  font-size: var(--fs-aux);
}
.review-center :deep(.el-table__body .cell) { font-variant-numeric: tabular-nums; }
</style>
