<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'

/**
 * 入库历史列表：日期筛选 + BasicTable 分页（列表页样式，嵌在弹窗里）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw, Search } from '@lucide/vue'

import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import BasicTable, {
  type BasicTableColumn,
  type BasicTableRequest,
} from '@/shared/components/ui/BasicTable.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { strategyLabel } from '@/shared/lib/format'
import type { ScreenCandidate, ScreenHistory } from '@/shared/types/quant'

export type HistoryRow = {
  key: string
  capability: string
  tradeDate: string
  count: number
  formalCount: number
  watchCount: number
  items: ScreenCandidate[]
}

const props = defineProps<{
  capabilityName: string
  history: ScreenHistory | null
  loading?: boolean
  running?: boolean
}>()

const emit = defineEmits<{
  rerun: [tradeDate: string]
  refresh: []
}>()

const route = useRoute()
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const basicTableRef = ref<InstanceType<typeof BasicTable>>()
const detailOpen = ref(false)
const detailRow = ref<HistoryRow | null>(null)

/** 表单草稿（随输入变）；点查询后写入 appliedRange。 */
const appliedDraft = ref<[string, string] | null>(null)
/** 已生效的查询条件。 */
const appliedRange = ref<[string, string] | null>(null)

const filterModel = computed({
  get: () =>
    ({
      dateRange: appliedDraft.value,
    }) as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    const range = value.dateRange
    appliedDraft.value =
      Array.isArray(range) && range.length === 2
        ? ([String(range[0] ?? ''), String(range[1] ?? '')] as [string, string])
        : null
  },
})

const filterSchemas: BasicFormSchema[] = [
  {
    field: 'dateRange',
    label: '选股日期',
    component: 'date-picker',
    componentProps: {
      type: 'daterange',
      'value-format': 'YYYY-MM-DD',
      'start-placeholder': '开始',
      'end-placeholder': '结束',
      clearable: true,
      'unlink-panels': true,
    },
  },
]

const allRows = computed<HistoryRow[]>(() => {
  const hist = props.history
  if (!hist?.dates?.length) return []
  // 兜底不能是裸 slug：父级没传中文名时，`hist.strategy` 是 `sanyuan-tail-v1`
  // 这种英文编码，直接摆到弹窗标题与详情行上。
  const name = props.capabilityName || strategyLabel(hist.strategy)
  return hist.dates.map((date) => {
    const items = hist.by_date[date] ?? []
    return {
      key: `${hist.strategy}:${date}`,
      capability: name,
      tradeDate: date,
      count: items.length,
      formalCount: items.filter((item) => item.decision === '精选').length,
      watchCount: items.filter((item) => item.decision === '观察').length,
      items,
    }
  })
})

const filteredRows = computed(() => {
  const range = appliedRange.value
  if (!range) return allRows.value
  const [from, to] = range
  return allRows.value.filter((row) => row.tradeDate >= from && row.tradeDate <= to)
})

const columns = ref<BasicTableColumn[]>([
  { type: 'index', label: '#', width: 72, align: 'center', headerAlign: 'center' },
  {
    prop: 'tradeDate',
    label: '选股日期',
    minWidth: 128,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => String(row.tradeDate ?? '—'),
  },
  {
    prop: 'formalCount',
    label: '正式 / 观察',
    width: 120,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => `${String(row.formalCount ?? 0)} / ${String(row.watchCount ?? 0)}`,
  },
  {
    prop: 'actions',
    label: '操作',
    width: 148,
    align: 'center',
    headerAlign: 'center',
    fixed: 'right',
    slotName: 'actions',
  },
])

const loadDataTable: BasicTableRequest = async (params) => {
  const list = filteredRows.value
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

watch(
  () => [props.history?.strategy, props.history?.dates?.length, appliedRange.value] as const,
  async () => {
    await nextTick()
    reloadList(true)
  },
)

onMounted(() => {
  void nextTick(() => reloadList(true))
})

const detailColumns: BasicTableColumn[] = [
  { type: 'index', label: '#', width: 48, align: 'center', headerAlign: 'center' },
  { prop: 'code', label: '标的 · 编码', minWidth: 168, align: 'center', headerAlign: 'center', slotName: 'code' },
  { prop: 'decision', label: '裁决', width: 82, align: 'center', headerAlign: 'center', slotName: 'decision' },
  {
    prop: 'score',
    label: '分数',
    width: 88,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => (row.score == null ? '—' : String(row.score)),
  },
  {
    prop: 'reason',
    label: '理由',
    minWidth: 200,
    align: 'center',
    headerAlign: 'center',
    showOverflowTooltip: true,
    formatter: (row) => String(row.reason || '—'),
  },
]

const detailTableRows = computed(
  () => (detailRow.value?.items ?? []) as unknown as Record<string, unknown>[],
)

const detailBatch = computed(() => ({
  source: detailRow.value
    ? `${detailRow.value.capability} · ${detailRow.value.tradeDate}`
    : '入库历史',
  sourcePath: route.fullPath || '/screen-history',
  items: toBatchItems(detailRow.value?.items ?? []),
}))

function openDetail(row: HistoryRow): void {
  detailRow.value = row
  detailOpen.value = true
}

function handleSearch(): void {
  const range = appliedDraft.value
  appliedRange.value =
    Array.isArray(range) && range.length === 2 ? [range[0], range[1]] : null
  reloadList(true)
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  appliedDraft.value = null
  appliedRange.value = null
  reloadList(true)
}

function onToolbarRefresh(): void {
  emit('refresh')
  void nextTick(() => reloadList(false))
}
</script>

<template>
  <div class="history-panel" aria-label="入库历史列表">
    <div class="history-panel__search">
      <BasicForm
        ref="basicFormRef"
        v-model="filterModel"
        :schemas="filterSchemas"
        :columns="1"
        label-width="6.5em"
        class="history-panel__form"
      />
      <div class="history-panel__actions">
        <Button access="read" :disabled="loading" @click="handleSearch">
          <Spinner v-if="loading" class="size-4 animate-spin" aria-hidden="true" />
          <Search v-else class="size-4" aria-hidden="true" />
          查询
        </Button>
        <Button access="read" variant="outline" :disabled="loading" @click="handleReset">
          <RefreshCw class="size-4" aria-hidden="true" />
          重置
        </Button>
      </div>
    </div>

    <div v-if="allRows.length || loading" class="history-panel__table">
      <BasicTable
        ref="basicTableRef"
        v-model:columns="columns"
        :request="loadDataTable"
        :pagination="{
          pageSize: 10,
          pageSizes: [10, 20, 50],
          layout: 'total, sizes, prev, pager, next, jumper',
          background: true,
          hideOnSinglePage: false,
        }"
        :toolbar-config="{ refresh: true }"
        :loading="loading"
        :has-default-request="false"
        stripe
        border
        row-key="key"
        height="100%"
        empty-text="该日期范围内暂无入库记录"
        @refresh="onToolbarRefresh"
      >
        <template #actions="{ row }">
          <div class="history-ops">
            <Button access="read"
              variant="link"
              size="sm"
              @click="openDetail(row as unknown as HistoryRow)"
            >
              详情
            </Button>
            <Button
              variant="link"
              size="sm"
              class="text-foreground"
              :disabled="running"
              @click="emit('rerun', String((row as HistoryRow).tradeDate))"
            >
              重跑
            </Button>
          </div>
        </template>
      </BasicTable>
    </div>

    <EmptyState
      v-else-if="!loading"
      description="该能力还没有入库记录。选好选股日后点右上角「选股」。"
      :image-size="56"
    />

    <DialogPanel
      v-model="detailOpen"
      append-to-body
      :title="
        detailRow
          ? `${detailRow.capability} · ${detailRow.tradeDate} · ${detailRow.count} 只`
          : '详情'
      "
      width="min(92vw, 40rem)"
      destroy-on-close
      class="history-detail-dialog"
    >
      <BasicTable
        :columns="detailColumns"
        :data-source="detailTableRows"
        :pagination="false"
        row-key="id"
        stripe
        border
        empty-text="无标的"
        max-height="22rem"
      >
        <template #code="{ row }">
          <span class="history-cell-inline" :title="`${row.name || row.code} ${row.code}`">
            <StockLink
              :code="String(row.code)"
              :name="String(row.name || row.code)"
              :date="detailRow?.tradeDate"
              :batch="detailBatch"
            />
            <span class="history-code">{{ row.code }}</span>
          </span>
        </template>
        <template #decision="{ row }">
          <StatusBadge
            size="small"
            :tone="row.decision === '精选' ? 'primary' : row.decision === '观察' ? 'warning' : 'info'"
            effect="plain"
          >
            {{ row.decision || '—' }}
          </StatusBadge>
        </template>
      </BasicTable>
    </DialogPanel>
  </div>
</template>

<style scoped>
.history-panel {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-height: 0;
  height: min(68vh, 34rem);
}

.history-panel__search {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.55rem 0.75rem;
  padding-bottom: 0.15rem;
  border-bottom: 1px solid var(--rule);
}

.history-panel__form {
  flex: 1 1 16rem;
  min-width: 0;
}

.history-panel__form :deep(.form-field) {
  margin-bottom: 0;
}

.history-panel__actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0.4rem;
  flex-shrink: 0;
  padding-bottom: 0.1rem;
}

.history-panel__table {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.history-panel__table :deep(.basic-table) {
  flex: 1 1 auto;
  min-height: 0;
}

.history-panel__table :deep(.basic-table__toolbar) {
  margin: 0;
}

.history-ops {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.15rem;
  white-space: nowrap;
}

.history-cell-inline {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-code {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}
</style>

<style>
</style>
