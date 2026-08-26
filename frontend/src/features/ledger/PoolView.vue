<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, RefreshRight, Search } from '@element-plus/icons-vue'

import { batchDeleteCandidates, deleteCandidate } from '@/shared/api/palace'
import { getStrategies } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import { formValuesEqual } from '@/shared/components/ui/basicFormEqual'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel, strategyLabel as formatStrategyLabel, timingLabel } from '@/shared/lib/format'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'
import type { StrategyInfo } from '@/shared/types/quant'

import { useCandidatesQuery } from './composables/useCandidatesQuery'

const route = useRoute()
const router = useRouter()
const batchStore = useBatchBrowseStore()
const strategies = ref<StrategyInfo[]>([])
const error = ref('')
const detailOpen = ref(false)
const detail = ref<Candidate | null>(null)
const recordOpen = ref(false)
const selectedIds = ref<string[]>([])
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const basicTableRef = ref<InstanceType<typeof BasicTable>>()

const filters = reactive({
  strategy: '',
  decision: '',
  dateRange: null as [string, string] | null,
})

const filterModel = computed({
  get: () => filters as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    filters.strategy = String(value.strategy ?? '')
    filters.decision = String(value.decision ?? '')
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
    field: 'strategy',
    label: '战法',
    component: 'select',
    colSpan: 6,
    componentProps: {
      clearable: true,
      filterable: true,
      placeholder: '全部',
      options: strategies.value.map((item) => ({ label: item.name, value: item.slug })),
    },
  },
  {
    field: 'decision',
    label: '裁决',
    component: 'select',
    colSpan: 5,
    componentProps: {
      clearable: true,
      placeholder: '全部',
      options: [
        { label: '精选', value: '精选' },
        { label: '落选', value: '落选' },
        { label: '观察', value: '观察' },
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

const queryFilters = computed(() => {
  const [start, end] = filters.dateRange ?? []
  return {
    strategy: filters.strategy || undefined,
    decision: filters.decision || undefined,
    start: start || undefined,
    end: end || undefined,
    limit: 1000,
  }
})

const {
  rows: cachedRows,
  isPending,
  error: queryError,
  refetch,
} = useCandidatesQuery(queryFilters)

const rows = cachedRows
const tableRows = computed(() => rows.value as unknown as Record<string, unknown>[])

const poolBatch = computed(() => {
  const seen = new Set<string>()
  const items = toBatchItems(
    rows.value.flatMap((row) => {
      if (seen.has(row.code)) return []
      seen.add(row.code)
      return [{ code: row.code, name: row.name }]
    }),
  )
  if (items.length < 2) return null
  return {
    source: '候选池',
    sourcePath: route.fullPath || '/pool',
    items,
  }
})
const busy = isPending

const decisionCounts = computed(() => {
  let selected = 0
  let watching = 0
  let rejected = 0
  for (const row of rows.value) {
    const label = decisionLabel(row.decision)
    if (label === '精选') selected += 1
    else if (label === '观察') watching += 1
    else if (label === '落选') rejected += 1
  }
  return { selected, watching, rejected }
})

watch(queryError, (err) => {
  error.value = err ? toErrorMessage(err, '加载候选失败') : ''
})

const strategyNameBySlug = computed(() => {
  const map = new Map<string, string>()
  for (const item of strategies.value) {
    map.set(item.slug, item.name)
  }
  return map
})

const detailTitle = computed(() =>
  detail.value ? `${detail.value.name} · ${detail.value.date}` : '候选详情',
)

const evidenceText = computed(() => {
  const ev = detail.value?.evidence
  if (!ev || !Object.keys(ev).length) return ''
  return JSON.stringify(ev, null, 2)
})

const columns = ref<BasicTableColumn[]>([
  { type: 'selection', width: 48, fixed: 'left' },
  { prop: 'date', label: '日期', width: 110 },
  { prop: 'code', label: '标的', width: 140, slotName: 'stock' },
  {
    prop: 'rule_version',
    label: '战法',
    width: 150,
    showOverflowTooltip: true,
    formatter: (row) => strategyLabel(String(row.rule_version ?? '')),
  },
  { prop: 'decision', label: '裁决', width: 80, slotName: 'decision' },
  {
    prop: 'timing',
    label: '时点',
    width: 90,
    formatter: (row) => timingLabel(String(row.timing ?? '')),
  },
  {
    prop: 'score',
    label: '评分',
    width: 70,
    formatter: (row) => String(row.score ?? '—'),
  },
  {
    prop: 'reason',
    label: '理由',
    minWidth: 260,
    align: 'left',
    headerAlign: 'left',
    slotName: 'reason',
  },
  { prop: 'actions', label: '操作', width: 80, slotName: 'actions', fixed: 'right' },
])

function strategyLabel(slug: string): string {
  if (!slug) return '—'
  return strategyNameBySlug.value.get(slug) || formatStrategyLabel(slug)
}

function decisionType(decision: string): 'info' | 'danger' {
  return decisionLabel(decision) === '精选' ? 'danger' : 'info'
}

async function load(): Promise<void> {
  error.value = ''
  selectedIds.value = []
  basicTableRef.value?.clearSelection()
  try {
    await refetch()
  } catch (e: unknown) {
    error.value = toErrorMessage(e, '加载失败')
  }
}

function handleSubmit(): void {
  void load()
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  void nextTick(() => load())
}

function onSelectionChange(selection: Record<string, unknown>[]): void {
  selectedIds.value = selection.map((row) => String(row.id ?? '')).filter(Boolean)
}

function openDetail(row: Record<string, unknown>): void {
  detail.value = row as unknown as Candidate
  detailOpen.value = true
}

function goArchive(): void {
  if (!detail.value) return
  detailOpen.value = false
  const seen = new Set<string>()
  const uniq: Candidate[] = []
  for (const row of rows.value) {
    if (seen.has(row.code)) continue
    seen.add(row.code)
    uniq.push(row)
  }
  if (uniq.length >= 2) {
    batchStore.openBatch({
      source: '候选池',
      sourcePath: route.fullPath || '/pool',
      focusCode: detail.value.code,
      items: toBatchItems(uniq.map((row) => ({ code: row.code, name: row.name }))),
    })
  }
  const date = String(detail.value.date || '').trim()
  void router.push({
    path: `/archive/${detail.value.code}`,
    query: /^\d{4}-\d{2}-\d{2}$/.test(date) ? { date } : undefined,
  })
}

function onRecorded(): void {
  void load()
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
    await load()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '批量删除失败')
  }
}

const listToolbar = computed<ListToolbarConfig>(() => ({
  batchDelete: {
    disabled: !selectedIds.value.length || !!busy.value,
    onClick: () => {
      void confirmBatchDelete()
    },
  },
}))

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
    <PageHeader
      title="候选池"
      :count="rows.length ? `共 ${rows.length} 条` : ''"
      note="选股产出与手动记录的候选；裁决与理由为当时快照，不随行情变动"
    >
      <template #stats>
        <HeaderStat label="精选" :value="decisionCounts.selected" tone="up" />
        <HeaderStat label="观察" :value="decisionCounts.watching" />
        <HeaderStat label="落选" :value="decisionCounts.rejected" />
      </template>
      <template #actions>
        <el-button type="primary" :icon="Plus" @click="recordOpen = true">新增</el-button>
      </template>
    </PageHeader>
    <PageContainer>
      <template #search>
        <div class="pool-search-form">
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :col-props="{ span: 6 }"
            label-width="72px"
          />
        </div>
        <div class="pool-search-actions">
          <el-button type="primary" :icon="Search" :loading="!!busy" @click="handleSubmit">查询</el-button>
          <el-button :icon="RefreshRight" :loading="!!busy" @click="handleReset">重置</el-button>
        </div>
      </template>
      <template #main>
        <el-alert
          v-if="error"
          :title="error"
          type="error"
          show-icon
          closable
          class="pool-alert"
          @close="error = ''"
        />
        <BasicTable
          v-if="rows.length || busy"
          ref="basicTableRef"
          v-model:columns="columns"
          :data-source="tableRows"
          :pagination="false"
          virtualized
          :toolbar-config="{ refresh: true, custom: true }"
          :loading="!!busy"
          stripe
          row-key="id"
          empty-text="暂无候选"
          @row-click="openDetail"
          @selection-change="onSelectionChange"
          @refresh="load"
        >
          <template #toolbarButtons>
            <ListToolbar :config="listToolbar" />
          </template>
          <template #stock="{ row }">
            <StockLink
              :code="String(row.code)"
              :name="String(row.name ?? '')"
              :date="String(row.date ?? '')"
              :batch="poolBatch"
              stop
            />
          </template>
          <template #decision="{ row }">
            <el-tag size="small" :type="decisionType(String(row.decision ?? ''))">
              {{ decisionLabel(String(row.decision ?? '')) }}
            </el-tag>
          </template>
          <template #reason="{ row }">
            <el-tooltip
              :content="String(row.reason || '—')"
              placement="top"
              :show-after="150"
              :disabled="!row.reason"
              popper-class="pool-reason-popper"
            >
              <span class="pool-reason-text">{{ String(row.reason || '—') }}</span>
            </el-tooltip>
          </template>
          <template #actions="{ row }">
            <el-button
              text
              type="danger"
              size="small"
              @click.stop="confirmDelete(row as unknown as Candidate)"
            >
              删除
            </el-button>
          </template>
        </BasicTable>
        <EmptyState
          v-else
          description="暂无候选"
          reason="候选来自选股产出与手动记录；当前筛选下暂无数据"
          eta="跑一次选股，或用侧栏「记一笔 → 候选」手动写入"
        >
          <el-button type="primary" @click="recordOpen = true">新增</el-button>
        </EmptyState>
      </template>
    </PageContainer>
  </div>

  <el-dialog
    v-model="detailOpen"
    :title="detailTitle"
    width="52rem"
    class="pool-detail-dialog"
    destroy-on-close
  >
    <template v-if="detail">
      <el-descriptions
        class="pool-detail-desc"
        :column="2"
        border
        size="small"
        label-width="4.5rem"
      >
        <el-descriptions-item label="日期">{{ detail.date }}</el-descriptions-item>
        <el-descriptions-item label="标的">
          <StockLink
            :code="detail.code"
            :name="detail.name"
            :date="detail.date"
            :batch="poolBatch"
          />
        </el-descriptions-item>
        <el-descriptions-item label="战法">{{ strategyLabel(detail.rule_version) }}</el-descriptions-item>
        <el-descriptions-item label="裁决">{{ decisionLabel(detail.decision) }}</el-descriptions-item>
        <el-descriptions-item label="时点">{{ timingLabel(detail.timing) }}</el-descriptions-item>
        <el-descriptions-item label="评分">{{ detail.score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="池">{{ detail.pool_id }}</el-descriptions-item>
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
.pool-search-form {
  flex: 1;
  min-width: 0;
}

/* 与表单末行输入框底对齐：form-item 自带 0.65rem 下间距，这里用同拍 margin 而非 padding 补丁 */
.pool-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
  align-self: flex-end;
  margin-bottom: 0.65rem;
}

.pool-reason-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.pool-alert {
  margin: 0.55rem 1rem 0;
  flex-shrink: 0;
}

.evidence {
  margin: 0.75rem 0 0;
  padding: 0.75rem;
  border-radius: var(--radius);
  background: var(--panel-2);
  font: 0.8rem/1.45 var(--mono);
  overflow: auto;
  max-height: 16rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.pool-detail-desc :deep(.el-descriptions__label) {
  width: 4.5rem;
  min-width: 4.5rem;
  max-width: 4.5rem;
  white-space: nowrap;
  vertical-align: top;
}

.pool-detail-desc :deep(.el-descriptions__content) {
  min-width: 0;
  word-break: break-word;
}

:deep(.el-table__row),
:deep(.el-table-v2__row) {
  cursor: pointer;
}
</style>

<style>
/* 理由全文气泡经 teleport 挂到 body，scoped 够不着；用 popper-class 限宽换行 */
.pool-reason-popper {
  max-width: 26rem;
}
</style>
