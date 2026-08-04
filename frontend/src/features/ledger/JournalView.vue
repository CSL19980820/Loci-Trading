<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshRight, Search } from '@element-plus/icons-vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import { formValuesEqual } from '@/shared/components/ui/basicFormEqual'
import BasicTable, { type BasicTableColumn, type BasicTableRequest } from '@/shared/components/ui/BasicTable.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import ImportStateDialog from '@/shared/components/dialogs/ImportStateDialog.vue'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import TradeDialog from '@/shared/components/dialogs/TradeDialog.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { exportTradesCsv } from '@/shared/api/palace'
import { actionLabel, money, signedMoney, toneClass } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import type { TradeRecord } from '@/shared/types/palace'

const store = usePalaceStore()
const router = useRouter()
const route = useRoute()
const tradeDialogOpen = ref(false)
const importDialogOpen = ref(false)
const exporting = ref(false)
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const basicTableRef = ref<InstanceType<typeof BasicTable>>()
const filtersReady = ref(false)

const filters = reactive({
  keyword: '',
  action: '',
  dateRange: null as [string, string] | null,
})

const filterModel = computed({
  get: () => filters as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    filters.keyword = String(value.keyword ?? '')
    filters.action = String(value.action ?? '')
    const range = value.dateRange
    const nextRange =
      Array.isArray(range) && range.length === 2
        ? ([String(range[0] ?? ''), String(range[1] ?? '')] as [string, string])
        : null
    if (!formValuesEqual(filters.dateRange, nextRange)) filters.dateRange = nextRange
  },
})

const filterSchemas = computed<BasicFormSchema[]>(() => [
  {
    field: 'keyword',
    label: '关键词',
    component: 'input',
    colSpan: 6,
    componentProps: { placeholder: '代码 / 名称 / 备注' },
  },
  {
    field: 'action',
    label: '动作',
    component: 'select',
    colSpan: 5,
    componentProps: {
      placeholder: '全部',
      options: [
        { label: '买入', value: 'BUY' },
        { label: '卖出', value: 'SELL' },
        { label: '开仓快照', value: 'OPENING' },
      ],
    },
  },
  {
    field: 'dateRange',
    label: '日期',
    component: 'date-picker',
    colSpan: 8,
    componentProps: {
      type: 'daterange',
      'value-format': 'YYYY-MM-DD',
      'start-placeholder': '开始',
      'end-placeholder': '结束',
      clearable: true,
    },
  },
])

const buyCount = computed(() => store.trades.filter((item) => item.action === 'BUY' || item.action === 'OPENING').length)
const sellCount = computed(() => store.trades.filter((item) => item.action === 'SELL').length)
const sellPnl = computed(() =>
  store.trades.filter((item) => item.action === 'SELL').reduce((sum, item) => sum + item.realized_pnl, 0),
)

const listToolbar = computed<ListToolbarConfig>(() => ({
  import: {
    onClick: () => {
      importDialogOpen.value = true
    },
  },
  export: {
    loading: exporting.value,
    onClick: () => {
      void onExportCsv()
    },
  },
}))

const columns = ref<BasicTableColumn[]>([
  { prop: 'date', label: '日期', width: 110 },
  { prop: 'code', label: '标的', minWidth: 140, slotName: 'stock' },
  { prop: 'action', label: '动作', width: 108, slotName: 'action' },
  { prop: 'shares', label: '数量', width: 90, formatter: (row) => Number(row.shares).toLocaleString('zh-CN') },
  { prop: 'price', label: '成交价', width: 96, formatter: (row) => Number(row.price).toFixed(3) },
  { prop: 'amount', label: '成交额', width: 118, formatter: (row) => money(Number(row.amount)) },
  {
    prop: 'shares_after',
    label: '余仓',
    width: 90,
    formatter: (row) => Number(row.shares_after).toLocaleString('zh-CN'),
  },
  {
    prop: 'cost_after',
    label: '成本',
    width: 90,
    formatter: (row) => {
      const value = String(row.action) === 'SELL' ? row.cost_before : row.cost_after
      return value ? Number(value).toFixed(3) : '—'
    },
  },
  { prop: 'realized_pnl', label: '已实现', width: 110, slotName: 'pnl' },
  {
    prop: 'reason',
    label: '备注',
    minWidth: 120,
    align: 'left',
    headerAlign: 'center',
    showOverflowTooltip: true,
    formatter: (row) => String(row.reason || '—'),
  },
])

function matchTrade(row: TradeRecord): boolean {
  const keyword = filters.keyword.trim().toLowerCase()
  if (keyword) {
    const hay = `${row.code} ${row.name} ${row.reason}`.toLowerCase()
    if (!hay.includes(keyword)) return false
  }
  if (filters.action && row.action !== filters.action) return false
  const [start, end] = filters.dateRange ?? []
  if (start && row.date < start) return false
  if (end && row.date > end) return false
  return true
}

const loadDataTable: BasicTableRequest = async (params) => {
  const list = store.trades.filter(matchTrade)
  const start = (params.currentPage - 1) * params.pageSize
  return {
    list: list.slice(start, start + params.pageSize) as unknown as Record<string, unknown>[],
    total: list.length,
  }
}

function reloadList(resetPage = true): void {
  if (resetPage) void basicTableRef.value?.restReload()
  else void basicTableRef.value?.reloadTable()
}

function handleSubmit(): void {
  reloadList(true)
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  void nextTick(() => reloadList(true))
}

function goArchive(code: string): void {
  void router.push(`/archive/${code}`)
}

function onRowClick(row: Record<string, unknown>): void {
  const code = String(row.code ?? '')
  if (code) goArchive(code)
}

async function onExportCsv(): Promise<void> {
  exporting.value = true
  try {
    await exportTradesCsv()
    ElMessage.success('交割单已导出')
  } catch (caught: unknown) {
    ElMessage.error(caught instanceof Error ? caught.message : '导出失败')
  } finally {
    exporting.value = false
  }
}

async function onImportSaved(): Promise<void> {
  await store.loadRoute(route, true)
}

watch(
  filters,
  () => {
    if (!filtersReady.value) return
    reloadList(true)
  },
  { deep: true },
)

watch(
  () => store.trades,
  () => {
    if (store.trades.length) reloadList(false)
  },
)

void nextTick(() => {
  filtersReady.value = true
})
</script>

<template>
  <div class="page-fill">
    <PageContainer>
      <template #search>
        <div class="journal-search-form">
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :col-props="{ span: 6 }"
            :input-debounce-ms="500"
            label-width="56px"
          />
        </div>
        <div class="journal-search-actions">
          <el-button type="primary" :icon="Search" @click="handleSubmit">查询</el-button>
          <el-button :icon="RefreshRight" @click="handleReset">重置</el-button>
        </div>
      </template>
      <template #main>
        <BasicTable
          v-if="store.trades.length"
          ref="basicTableRef"
          v-model:columns="columns"
          :request="loadDataTable"
          :pagination="true"
          :toolbar-config="{ refresh: true, custom: true }"
          stripe
          row-key="id"
          @row-click="onRowClick"
        >
          <template #toolbarButtons>
            <div class="journal-toolbar-meta">
              <span class="journal-tick"><em>买</em><strong>{{ buyCount }}</strong></span>
              <span class="journal-tick"><em>卖</em><strong>{{ sellCount }}</strong></span>
              <span class="journal-tick" :class="toneClass(sellPnl)">
                <em>已实现</em><strong>{{ signedMoney(sellPnl) }}</strong>
              </span>
              <span class="journal-tick"><em>合计</em><strong>{{ store.trades.length }} 笔</strong></span>
              <ListToolbar :config="listToolbar" />
            </div>
          </template>
          <template #action="{ row }">
            <span class="action-chip" :class="`action-${String(row.action).toLowerCase()}`">
              {{ actionLabel(String(row.action) as TradeRecord['action']) }}
            </span>
          </template>
          <template #stock="{ row }">
            <StockLink :code="String(row.code)" :name="String(row.name ?? '')" stop />
          </template>
          <template #pnl="{ row }">
            <span :class="toneClass(Number(row.realized_pnl))">
              {{ signedMoney(Number(row.realized_pnl)) }}
            </span>
          </template>
        </BasicTable>
        <PageBusy v-else-if="store.loading" label="加载交割…" />
        <EmptyState
          v-else
          description="还没有成交"
          reason="还没记过成交或未导入潜龙快照"
          eta="记一笔或导入后立即出现"
        >
          <el-button type="primary" @click="tradeDialogOpen = true">写入成交</el-button>
          <el-button @click="importDialogOpen = true">导入快照</el-button>
        </EmptyState>
      </template>
    </PageContainer>

    <TradeDialog v-model="tradeDialogOpen" />
    <ImportStateDialog v-model="importDialogOpen" @saved="onImportSaved" />
  </div>
</template>

<style scoped>
.journal-search-form {
  flex: 1;
  min-width: 0;
}

.journal-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
  padding-bottom: 0.65rem;
}

.journal-toolbar-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.15rem;
  min-width: 0;
}

.journal-tick {
  display: inline-flex;
  align-items: baseline;
  gap: 0.28rem;
  padding-left: 0.65rem;
  margin-left: 0.35rem;
  border-left: 1px solid var(--rule);
  font-family: var(--mono);
  font-size: 0.78rem;
  line-height: 1.25;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.journal-tick:first-child {
  padding-left: 0;
  margin-left: 0;
  border-left: none;
}

.journal-tick em {
  font-style: normal;
  font-family: var(--font);
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--mist);
}

.journal-tick strong {
  font-weight: 650;
}

.journal-tick.tone-up,
.journal-tick.tone-up strong {
  color: var(--up);
}

.journal-tick.tone-down,
.journal-tick.tone-down strong {
  color: var(--down);
}

.journal-toolbar-meta :deep(.list-toolbar) {
  margin-left: 0.5rem;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
