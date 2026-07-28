<script setup lang="ts">
import { ElCheckbox, ElMessage, ElTag, type Column } from 'element-plus'
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { batchDeleteCandidates, deleteCandidate } from '@/shared/api/palace'
import { getStrategies } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { decisionLabel } from '@/shared/lib/format'
import type { Candidate } from '@/shared/types/palace'
import type { StrategyInfo } from '@/shared/types/quant'

import { useCandidatesQuery } from './composables/useCandidatesQuery'

const router = useRouter()
const strategies = ref<StrategyInfo[]>([])
const error = ref('')
const detailOpen = ref(false)
const detail = ref<Candidate | null>(null)
const recordOpen = ref(false)
const selectedIds = ref<string[]>([])

const filters = reactive({
  strategy: '',
  decision: '' as string,
  start: undefined as string | undefined,
  end: undefined as string | undefined,
})

const {
  rows: cachedRows,
  isPending,
  error: queryError,
  refetch,
} = useCandidatesQuery(() => ({
  strategy: filters.strategy || undefined,
  decision: filters.decision || undefined,
  start: filters.start,
  end: filters.end,
  limit: 2000,
}))

const rows = cachedRows
const busy = isPending

watch(queryError, (err) => {
  error.value = err instanceof Error ? err.message : err ? String(err) : ''
})

const strategyNameBySlug = computed(() => {
  const map = new Map<string, string>()
  for (const item of strategies.value) {
    map.set(item.slug, item.name)
  }
  return map
})

const selectedSet = computed(() => new Set(selectedIds.value))

const detailTitle = computed(() =>
  detail.value ? `${detail.value.name} · ${detail.value.date}` : '候选详情',
)

const evidenceText = computed(() => {
  const ev = detail.value?.evidence
  if (!ev || !Object.keys(ev).length) return ''
  return JSON.stringify(ev, null, 2)
})

function strategyLabel(slug: string): string {
  if (!slug) return '—'
  return strategyNameBySlug.value.get(slug) || slug
}

function decisionType(decision: string): 'success' | 'info' | 'danger' | 'warning' {
  const d = decision.toLowerCase()
  if (d.includes('select') || d.includes('精选') || d.includes('值得')) return 'danger'
  if (d.includes('reject') || d.includes('落选') || d.includes('否')) return 'info'
  return 'warning'
}

function toggleRow(id: string, checked: boolean): void {
  const next = new Set(selectedIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedIds.value = [...next]
}

function toggleAll(checked: boolean): void {
  selectedIds.value = checked ? rows.value.map((r) => r.id) : []
}

function clearSelection(): void {
  selectedIds.value = []
}

function openDetail(row: Candidate): void {
  detail.value = row
  detailOpen.value = true
}

function goArchive(): void {
  if (!detail.value) return
  detailOpen.value = false
  void router.push(`/archive/${detail.value.code}`)
}

function onRecorded(): void {
  void load()
}

function onFilterChange(): void {
  clearSelection()
  void load()
}

async function load(): Promise<void> {
  error.value = ''
  try {
    await refetch()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function confirmDelete(row: Candidate): Promise<void> {
  if (!(await confirmDangerous(
    `确定删除 ${row.name}（${row.date}）这条候选记录？`,
    '删除候选',
    '删除',
  ))) return
  try {
    await deleteCandidate(row.id)
    ElMessage.success('已删除')
    if (detail.value?.id === row.id) {
      detailOpen.value = false
      detail.value = null
    }
    clearSelection()
    await load()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

async function confirmBatchDelete(): Promise<void> {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (!(await confirmDangerous(`确定删除选中的 ${ids.length} 条候选记录？`, '批量删除', '删除'))) return
  try {
    const result = await batchDeleteCandidates(ids)
    ElMessage.success(`已删除 ${result.removed} 条`)
    if (detail.value && ids.includes(detail.value.id)) {
      detailOpen.value = false
      detail.value = null
    }
    clearSelection()
    await load()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '批量删除失败')
  }
}

const columns = computed(() => {
  const allChecked = rows.value.length > 0 && selectedIds.value.length === rows.value.length
  const someChecked = selectedIds.value.length > 0 && !allChecked
  const cols: Column<Candidate>[] = [
    {
      key: 'selection',
      width: 48,
      align: 'center',
      headerCellRenderer: () =>
        h(ElCheckbox, {
          modelValue: allChecked,
          indeterminate: someChecked,
          'onUpdate:modelValue': (v: boolean | string | number) => toggleAll(Boolean(v)),
        }),
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h(ElCheckbox, {
          modelValue: selectedSet.value.has(rowData.id),
          'onUpdate:modelValue': (v: boolean | string | number) =>
            toggleRow(rowData.id, Boolean(v)),
          onClick: (e: MouseEvent) => e.stopPropagation(),
        }),
    },
    {
      key: 'date',
      dataKey: 'date',
      title: '日期',
      width: 110,
    },
    {
      key: 'strategy',
      title: '战法',
      width: 140,
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h('span', null, strategyLabel(rowData.rule_version)),
    },
    {
      key: 'symbol',
      title: '标的',
      width: 160,
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h(StockLink, { code: rowData.code, name: rowData.name, stop: true }),
    },
    {
      key: 'decision',
      title: '裁决',
      width: 90,
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h(
          ElTag,
          { size: 'small', type: decisionType(rowData.decision) },
          () => decisionLabel(rowData.decision),
        ),
    },
    {
      key: 'timing',
      dataKey: 'timing',
      title: '时点',
      width: 90,
    },
    {
      key: 'score',
      title: '评分',
      width: 80,
      align: 'right',
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h('span', { class: 'mono' }, String(rowData.score ?? '—')),
    },
    {
      key: 'reason',
      dataKey: 'reason',
      title: '理由',
      width: 220,
    },
    {
      key: 'actions',
      title: '操作',
      width: 72,
      align: 'center',
      cellRenderer: ({ rowData }: { rowData: Candidate }) =>
        h(
          'button',
          {
            type: 'button',
            class: 'pool-del',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              void confirmDelete(rowData)
            },
          },
          '删除',
        ),
    },
  ]
  return cols
})

watch(rows, () => {
  const alive = new Set(rows.value.map((r) => r.id))
  selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
})

onMounted(async () => {
  try {
    strategies.value = await getStrategies()
  } catch {
    strategies.value = []
  }
  await load()
})
</script>

<template>
  <div class="page-fill">
    <PageHeader title="候选池" :subtitle="`${rows.length} 条`">
      <el-button
        type="danger"
        plain
        :disabled="!selectedIds.length || busy"
        @click="confirmBatchDelete"
      >
        批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
      </el-button>
      <el-button :loading="busy" @click="load">刷新</el-button>
      <el-button type="primary" @click="recordOpen = true">记候选</el-button>
    </PageHeader>

    <Sheet quiet class="filter-bar" padded>
      <el-form inline class="filter-form">
        <el-form-item label="战法">
          <el-select
            v-model="filters.strategy"
            clearable
            filterable
            placeholder="全部"
            style="width: 12rem"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in strategies"
              :key="s.slug"
              :label="s.name"
              :value="s.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="裁决">
          <el-select
            v-model="filters.decision"
            clearable
            placeholder="全部"
            style="width: 8rem"
            @change="onFilterChange"
          >
            <el-option label="精选" value="精选" />
            <el-option label="落选" value="落选" />
            <el-option label="观察" value="观察" />
          </el-select>
        </el-form-item>
        <el-form-item label="起始">
          <el-date-picker
            v-model="filters.start"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="不限"
            @change="onFilterChange"
          />
        </el-form-item>
        <el-form-item label="截止">
          <el-date-picker
            v-model="filters.end"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="不限"
            @change="onFilterChange"
          />
        </el-form-item>
      </el-form>
    </Sheet>

    <el-alert v-if="error" :title="error" type="error" show-icon closable class="mb" @close="error = ''" />

    <Sheet class="list-sheet">
      <el-auto-resizer v-if="rows.length" class="pool-resizer">
        <template #default="{ height, width }">
          <el-table-v2
            :columns="columns"
            :data="rows"
            :width="width"
            :height="height"
            row-key="id"
            fixed
            @row-click="({ rowData }: { rowData: Candidate }) => openDetail(rowData)"
          />
        </template>
      </el-auto-resizer>
      <PageBusy v-else-if="busy" />
      <EmptyState v-else description="暂无候选">
        <el-button type="primary" @click="recordOpen = true">记候选</el-button>
      </EmptyState>
    </Sheet>
  </div>

  <el-dialog v-model="detailOpen" :title="detailTitle" width="36rem" destroy-on-close>
    <template v-if="detail">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="日期">{{ detail.date }}</el-descriptions-item>
        <el-descriptions-item label="战法">{{ strategyLabel(detail.rule_version) }}</el-descriptions-item>
        <el-descriptions-item label="池">{{ detail.pool_id }}</el-descriptions-item>
        <el-descriptions-item label="裁决">{{ decisionLabel(detail.decision) }}</el-descriptions-item>
        <el-descriptions-item label="标的" :span="2">
          <StockLink :code="detail.code" :name="detail.name" />
        </el-descriptions-item>
        <el-descriptions-item label="时点">{{ detail.timing || '—' }}</el-descriptions-item>
        <el-descriptions-item label="评分">{{ detail.score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ detail.source }}</el-descriptions-item>
        <el-descriptions-item label="理由" :span="2">{{ detail.reason }}</el-descriptions-item>
      </el-descriptions>
      <pre v-if="evidenceText" class="evidence">{{ evidenceText }}</pre>
    </template>
    <template #footer>
      <el-button @click="detailOpen = false">关闭</el-button>
      <el-button v-if="detail" type="danger" plain @click="confirmDelete(detail)">删除</el-button>
      <el-button v-if="detail" type="primary" @click="goArchive">看档案</el-button>
    </template>
  </el-dialog>

  <RecordDialog v-model="recordOpen" kind="candidate" @saved="onRecorded" />
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
  flex-shrink: 0;
}
.filter-bar {
  flex-shrink: 0;
  margin-bottom: 0.55rem;
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
.list-sheet {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.list-sheet :deep(> div) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pool-resizer {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
}
.pool-del {
  border: 0;
  background: transparent;
  color: var(--el-color-danger);
  cursor: pointer;
  font: inherit;
  font-size: 0.8rem;
  padding: 0.1rem 0.25rem;
}
.evidence {
  margin: 0.75rem 0 0;
  padding: 0.75rem;
  border-radius: var(--radius);
  background: var(--panel-2);
  font: 0.8rem/1.45 var(--mono);
  overflow: auto;
  max-height: 12rem;
}
</style>
