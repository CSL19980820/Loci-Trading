<script setup lang="ts">
/**
 * 候选池（路由 `/pool`）：筛选一批候选、读数、进档案、删。
 *
 * 表格上方只留一条横栏（页头与表格工具栏都已下线），所以这个文件里剩下的是
 * 「拿到结果之后」的事：选中集合、当前已加载口径的读数、单删与批量删、进档案时
 * 写批次会话。筛选草稿在 usePoolFilters，中文化文案在 poolLabels，详情在
 * PoolCandidateDialog——它们各自都能独立说清职责，也就不该挤在这一屏里。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { InfoFilled, Plus, RefreshRight, Search } from '@element-plus/icons-vue'

import { batchDeleteCandidates, deleteCandidate } from '@/shared/api/palace'
import { getStrategies } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import PageContainer from '@/shared/components/layout/PageContainer.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel, timingLabel } from '@/shared/lib/format'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'
import type { StrategyInfo } from '@/shared/types/quant'

import PoolCandidateDialog from './components/PoolCandidateDialog.vue'
import { useCandidatesQuery } from './composables/useCandidatesQuery'
import { decisionType, sourceLabel, usePoolLabels } from './composables/poolLabels'
import { usePoolFilters } from './composables/usePoolFilters'

/** 口径不占正文行：只作这条功能行末端的一枚 ⓘ */
const PAGE_NOTE = '候选为当时快照，不随行情变动'

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

const { filterModel, filterSchemas, queryFilters } = usePoolFilters(strategies)
const { strategyLabel, poolLabel } = usePoolLabels(strategies)

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
    <PageContainer>
      <!--
        页头已删。原来表格上方堆着三条横栏（页头 / 筛选 / 表格工具栏），
        现在压成这一条：左边筛选，右边「查询 · 重置 · 读数 · 批量删除 · 记一条候选 · ⓘ口径」。
      -->
      <template #search>
        <div class="pool-search-form">
          <!--
            筛选条统一档（shared BasicForm 契约）：columns 栅格 + label-position="left" + 定宽
            label，换行/退列后各列控件左缘仍对齐。DataQueryView 用同一组参数。
          -->
          <BasicForm
            ref="basicFormRef"
            v-model="filterModel"
            :schemas="filterSchemas"
            :columns="3"
            label-position="left"
            label-width="5.5em"
            size="small"
          />
        </div>
        <div class="pool-search-actions">
          <el-button type="primary" size="small" :icon="Search" :loading="!!busy" @click="handleSubmit">
            查询
          </el-button>
          <el-button size="small" :icon="RefreshRight" :loading="!!busy" @click="handleReset">
            重置
          </el-button>
          <span class="pool-stats">
            <HeaderStat label="共" :value="rows.length" />
            <HeaderStat label="精选" :value="decisionCounts.selected" tone="up" />
            <HeaderStat label="观察" :value="decisionCounts.watching" />
            <HeaderStat label="落选" :value="decisionCounts.rejected" />
          </span>
          <ListToolbar :config="listToolbar" />
          <el-button type="primary" size="small" :icon="Plus" @click="recordOpen = true">
            记一条候选
          </el-button>
          <el-tooltip :content="PAGE_NOTE" placement="bottom-end" :show-after="200">
            <el-icon class="pool-note" tabindex="0" :aria-label="PAGE_NOTE"><InfoFilled /></el-icon>
          </el-tooltip>
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
          :loading="!!busy"
          stripe
          row-key="id"
          empty-text="暂无候选"
          @row-click="openDetail"
          @selection-change="onSelectionChange"
        >
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
          reason="当前筛选下没有记录"
          eta="跑一次选股，或手动写入一条"
        >
          <el-button type="primary" @click="recordOpen = true">记一条候选</el-button>
        </EmptyState>
      </template>
    </PageContainer>
  </div>

  <PoolCandidateDialog
    v-model="detailOpen"
    :candidate="detail"
    :strategy-text="detail ? strategyLabel(detail.rule_version) : '—'"
    :pool-text="poolLabel(detail?.pool_id)"
    :source-text="sourceLabel(detail?.source)"
    :batch="poolBatch"
    @delete="confirmDelete"
    @archive="goArchive"
  />

  <RecordDialog v-model="recordOpen" kind="candidate" @saved="onRecorded" />
</template>

<style scoped>
.pool-search-form {
  flex: 1;
  min-width: 0;
}
/* 与表单末行输入框底对齐：form-item 自带 --gap-2 下间距，这里用同拍 margin 而非 padding 补丁 */
.pool-search-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-2);
  flex-shrink: 0;
  align-self: flex-end;
  margin-bottom: var(--gap-2);
}
/* 读数并进这一行：不再为「精选/观察/落选」单开一条页头 */
.pool-stats {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-3);
  min-width: 0;
  align-self: center;
}
/* 口径提示：一枚 ⓘ，不占文本宽度 */
.pool-note {
  flex-shrink: 0;
  align-self: center;
  font-size: var(--fs-aux);
  color: var(--mist);
  cursor: help;
}
.pool-note:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 2px;
  border-radius: var(--radius);
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
  margin: var(--gap-1) var(--gap-3) 0;
  flex-shrink: 0;
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
