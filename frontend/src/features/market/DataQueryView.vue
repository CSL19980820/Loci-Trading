<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshRight, Search } from '@element-plus/icons-vue'

import { getMarketCoverage, getMarketIndustries } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import type { BoardRow, MarketCoverage } from '@/shared/types/quant'

import {
  chgClass,
  fmtAmount,
  fmtChange,
  fmtPct,
  fmtPrice,
  fmtTurnover,
} from './composables/dataQueryFormat'
import { useDataQueryMarket, type BoardSort } from './composables/useDataQueryMarket'

const route = useRoute()
const router = useRouter()

const busy = ref(false)
const error = ref('')
const liveError = ref('')
const coverage = ref<MarketCoverage | null>(null)
const coverageLoaded = ref(false)
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const filtersReady = ref(false)
const industryOptions = ref<{ label: string; value: string }[]>([])

const filters = reactive({
  keyword: '',
  industry: '',
  turnoverMin: null as number | null,
  sort: 'code' as BoardSort,
})

const {
  marketQ,
  liveOn,
  industryFilter,
  turnoverMin,
  boardSort,
  liveEnriching,
  page,
  pageSize,
  boardRows,
  boardTotal,
  loadBoard,
  openDetail,
  startRefresh,
} = useDataQueryMarket({ route, router, busy, error, liveError })

const filterModel = computed({
  get: () =>
    ({
      keyword: filters.keyword,
      industry: filters.industry,
      turnoverMin: filters.turnoverMin,
      sort: filters.sort,
    }) as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    filters.keyword = String(value.keyword ?? '')
    filters.industry = String(value.industry ?? '')
    const rawMin = value.turnoverMin
    filters.turnoverMin =
      rawMin === '' || rawMin == null || Number.isNaN(Number(rawMin)) ? null : Number(rawMin)
    filters.sort = (String(value.sort || 'code') as BoardSort) || 'code'
    syncFiltersToQuery()
  },
})

const filterSchemas = computed<BasicFormSchema[]>(() => [
  {
    field: 'keyword',
    label: '关键词',
    component: 'input',
    colSpan: 6,
    componentProps: { placeholder: '代码 / 名称', clearable: true },
  },
  {
    field: 'industry',
    label: '所属行业',
    component: 'select',
    colSpan: 6,
    componentProps: {
      clearable: true,
      filterable: true,
      allowCreate: true,
      defaultFirstOption: true,
      placeholder: industryOptions.value.length ? '半导体 / 电力…' : '先同步证券列表',
      options: industryOptions.value,
    },
  },
  {
    field: 'turnoverMin',
    label: '换手≥%',
    component: 'input-number',
    colSpan: 5,
    componentProps: {
      min: 0,
      max: 100,
      step: 0.5,
      controlsPosition: 'right',
      placeholder: '不限',
    },
  },
  {
    field: 'sort',
    label: '排序',
    component: 'select',
    colSpan: 5,
    componentProps: {
      options: [
        { label: '代码', value: 'code' },
        { label: '换手率高→低', value: 'turnover_desc' },
        { label: '换手率低→高', value: 'turnover_asc' },
      ],
    },
  },
])

const columns = ref<BasicTableColumn[]>([
  { prop: 'code', label: '代码', width: 88, slotName: 'code' },
  { prop: 'name', label: '名称', minWidth: 108, showOverflowTooltip: true },
  {
    prop: 'industry',
    label: '所属行业',
    minWidth: 110,
    showOverflowTooltip: true,
    formatter: (row) => String(row.industry || '—'),
  },
  { prop: 'price', label: '最新', width: 92, slotName: 'price' },
  { prop: 'pct', label: '涨跌%', width: 100, slotName: 'pct' },
  { prop: 'change', label: '涨跌', width: 80, slotName: 'change' },
  {
    prop: 'turnover',
    label: '换手率',
    width: 92,
    formatter: (row) => fmtTurnover(row.turnover as number | null),
  },
  {
    prop: 'open',
    label: '今开',
    width: 84,
    formatter: (row) => fmtPrice(row.open as number | null),
  },
  {
    prop: 'high',
    label: '最高',
    width: 84,
    formatter: (row) => fmtPrice(row.high as number | null),
  },
  {
    prop: 'low',
    label: '最低',
    width: 84,
    formatter: (row) => fmtPrice(row.low as number | null),
  },
  {
    prop: 'amount',
    label: '成交额',
    minWidth: 100,
    formatter: (row) => fmtAmount(row.amount as number | null),
  },
  { prop: 'ok', label: '来源', width: 72, slotName: 'source' },
  {
    prop: 'local_date',
    label: '本地日',
    width: 108,
    formatter: (row) => String(row.local_date || '—'),
  },
])

const tableRows = computed(() => boardRows.value as unknown as Record<string, unknown>[])
const batch = computed(() => ({
  source: '行情台',
  sourcePath: route.fullPath || '/data',
  items: toBatchItems(
    boardRows.value.map((row) => ({
      code: row.code,
      name: row.name,
      pct: row.pct ?? row.local_pct ?? null,
    })),
  ),
}))
const hasMarket = computed(() => (coverage.value?.rows ?? 0) > 0)

function syncFiltersToQuery(): void {
  marketQ.value = filters.keyword.trim()
  industryFilter.value = filters.industry
  turnoverMin.value = filters.turnoverMin
  boardSort.value = filters.sort
}

async function loadCoverage(): Promise<void> {
  try {
    coverage.value = await getMarketCoverage()
  } catch (caught: unknown) {
    error.value = (caught as Error).message || '读覆盖失败'
  } finally {
    coverageLoaded.value = true
  }
}

async function loadIndustries(): Promise<void> {
  try {
    const res = await getMarketIndustries()
    industryOptions.value = (res.items ?? []).map((name) => ({ label: name, value: name }))
  } catch {
    industryOptions.value = []
  }
}

function handleSubmit(): void {
  syncFiltersToQuery()
  page.value = 1
  void loadBoard()
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  void nextTick(() => {
    filters.keyword = ''
    filters.industry = ''
    filters.turnoverMin = null
    filters.sort = 'code'
    syncFiltersToQuery()
    liveOn.value = true
    page.value = 1
    void loadBoard()
  })
}

function onPageChange(next: number): void {
  page.value = next
  void loadBoard()
}

function onSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void loadBoard()
}

function onRowClick(row: Record<string, unknown>): void {
  void openDetail(row as unknown as BoardRow)
}

function goBootstrapHint(): void {
  void router.push('/ops')
}

watch(
  filters,
  () => {
    if (!filtersReady.value) return
    syncFiltersToQuery()
  },
  { deep: true },
)

onMounted(async () => {
  liveOn.value = true
  filters.keyword = marketQ.value
  filters.industry = industryFilter.value
  filters.turnoverMin = turnoverMin.value
  filters.sort = boardSort.value
  void nextTick(() => {
    filtersReady.value = true
  })
  const code = String(route.query.code || '').trim()
  if (code) {
    await router.replace({ path: `/archive/${code}`, query: { view: 'quote' } })
    return
  }
  void loadIndustries()
  await Promise.all([loadCoverage(), loadBoard()])
  startRefresh()
})
</script>

<template>
  <div class="page-fill data-desk">
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

    <PageContainer>
      <template #search>
        <div class="desk-search-form">
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :col-props="{ span: 6 }"
            label-width="72px"
          />
        </div>
        <div class="desk-search-actions">
          <el-button type="primary" :icon="Search" :loading="busy" @click="handleSubmit">查询</el-button>
          <el-button :icon="RefreshRight" :loading="busy" @click="handleReset">重置</el-button>
        </div>
      </template>
      <template #main>
        <EmptyState
          v-if="coverageLoaded && !hasMarket"
          description="还没有历史日 K"
          reason="数据目录已就绪，但 market.db 里尚无行情。初始化后才能查日线。"
        >
          <el-button type="primary" @click="goBootstrapHint">去初始化</el-button>
        </EmptyState>
        <div v-else class="desk-main">
          <PageBusy overlay :busy="busy" />
          <BasicTable
            v-model:columns="columns"
            :data-source="tableRows"
            :pagination="{
              currentPage: page,
              pageSize,
              total: boardTotal,
              pageSizes: [30, 50, 100],
              layout: 'total, sizes, prev, pager, next',
            }"
            :toolbar-config="{ refresh: true, custom: true }"
            :loading="busy || liveEnriching"
            stripe
            row-key="code"
            empty-text="无证券"
            @row-click="onRowClick"
            @current-change="onPageChange"
            @size-change="onSizeChange"
            @refresh="loadBoard"
          >
            <template #code="{ row }">
              <span class="mono board-code">
                <StockLink
                  :code="String(row.code ?? '')"
                  :batch="batch"
                  :stop="true"
                  :show-code="false"
                />
              </span>
            </template>
            <template #price="{ row }">
              <span class="mono" :class="chgClass(row.pct as number | null)">{{
                fmtPrice(row.price as number | null)
              }}</span>
            </template>
            <template #pct="{ row }">
              <span class="mono" :class="chgClass(row.pct as number | null)">{{
                fmtPct(row.pct as number | null)
              }}</span>
            </template>
            <template #change="{ row }">
              <span class="mono" :class="chgClass(row.pct as number | null)">{{
                fmtChange(row.change as number | null)
              }}</span>
            </template>
            <template #source="{ row }">
              <span class="src" :class="{ 'src--live': Boolean(row.ok) }">{{
                row.ok ? '实时' : '日线'
              }}</span>
            </template>
          </BasicTable>
        </div>
      </template>
    </PageContainer>
  </div>
</template>

<style scoped>
.data-desk {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.desk-alert {
  margin: 0;
  flex-shrink: 0;
}

.desk-search-form {
  flex: 1;
  min-width: 0;
}

.desk-search-form :deep(.el-col) {
  min-width: 14rem;
}

.desk-search-form :deep(.el-form-item__content),
.desk-search-form :deep(.el-input),
.desk-search-form :deep(.el-select),
.desk-search-form :deep(.el-input-number) {
  width: 100%;
  min-width: 11rem;
}

.desk-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
  padding-bottom: 0.65rem;
}

@media (max-width: 700px) {
  :deep(.page-container__search) {
    flex-direction: column;
    flex-wrap: nowrap;
  }

  .desk-search-form,
  .desk-search-actions {
    width: 100%;
    flex: 0 0 auto;
  }

  .desk-search-form :deep(.el-col) {
    flex: 0 0 100%;
    max-width: 100%;
    min-width: 0;
  }

  .desk-search-form :deep(.el-form-item__content),
  .desk-search-form :deep(.el-input),
  .desk-search-form :deep(.el-select),
  .desk-search-form :deep(.el-input-number) {
    min-width: 0;
  }

  .desk-search-actions {
    justify-content: flex-end;
  }
}

.desk-main {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.board-code {
  font-weight: 600;
}

.src {
  font-size: 0.72rem;
  color: var(--mist);
}

.src--live {
  color: var(--lake);
}

.mono {
  font-family: var(--mono);
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
