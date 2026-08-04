<script setup lang="ts">
/**
 * 定时台「执行历史」弹窗：宽表、任务名左置、耗时可读。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { batchDeleteJobRuns } from '@/shared/api/quant'
import BasicTable, {
  type BasicTableColumn,
  type BasicTableRequest,
} from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { JobRun } from '@/shared/types/quant'

import {
  firstLine,
  formatLlmMeta,
  formatRunDuration,
  statusLabel,
  triggerLabel,
} from '../composables/opsLabels'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [open: boolean]
  changed: []
}>()

const { busy, guard } = useOpsFeedback()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const { runs, refetch } = useJobRunsQuery(() => ({ limit: 500 }))
const basicTableRef = ref<InstanceType<typeof BasicTable> | null>(null)
const selectedIds = ref<string[]>([])

const columns = ref<BasicTableColumn[]>([
  { type: 'selection', width: 48 },
  {
    prop: 'job_name',
    label: '任务',
    minWidth: 200,
    align: 'left',
    headerAlign: 'left',
    showOverflowTooltip: true,
  },
  {
    prop: 'started_at',
    label: '时间',
    minWidth: 160,
    formatter: (row) => String(row.started_at ?? '—'),
  },
  {
    prop: 'trigger',
    label: '触发',
    width: 72,
    formatter: (row) => triggerLabel(String(row.trigger ?? '')),
  },
  {
    prop: 'duration_ms',
    label: '耗时',
    width: 96,
    align: 'right',
    headerAlign: 'right',
    slotName: 'duration',
  },
  {
    prop: 'llm',
    label: 'LLM',
    minWidth: 110,
    showOverflowTooltip: true,
    formatter: (row) => formatLlmMeta(row as unknown as JobRun),
  },
  {
    prop: 'status',
    label: '结果',
    minWidth: 160,
    showOverflowTooltip: true,
    slotName: 'result',
  },
])

const loadDataTable: BasicTableRequest = async (params) => {
  const list = runs.value
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

async function load(resetPage = true): Promise<void> {
  selectedIds.value = []
  await refetch()
  await nextTick()
  reloadList(resetPage)
}

watch(
  () => props.modelValue,
  (opened) => {
    if (opened) void load(true)
  },
)

function onSelectionChange(selection: Record<string, unknown>[]): void {
  selectedIds.value = selection.map((row) => String(row.id ?? '')).filter(Boolean)
}

async function confirmBatchDelete(): Promise<void> {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (!(await confirmDangerous(`确定删除选中的 ${ids.length} 条执行记录？`, '批量删除', '删除'))) {
    return
  }
  const result = await guard(() => batchDeleteJobRuns(ids))
  if (!result) return
  ElMessage.success(`已删除 ${result.removed} 条`)
  emit('changed')
  await load(true)
}

const listToolbar = computed<ListToolbarConfig>(() => ({
  batchDelete: {
    disabled: !selectedIds.value.length || busy.value,
    onClick: () => {
      void confirmBatchDelete()
    },
  },
}))

defineExpose({ load })
</script>

<template>
  <el-dialog
    v-model="open"
    title="执行历史"
    width="72rem"
    top="6vh"
    destroy-on-close
    class="job-runs-dialog"
    append-to-body
  >
    <div v-if="runs.length || busy" class="runs-body">
      <BasicTable
        ref="basicTableRef"
        v-model:columns="columns"
        :request="loadDataTable"
        :pagination="true"
        :toolbar-config="{ refresh: true }"
        :loading="busy"
        :has-default-request="false"
        stripe
        row-key="id"
        height="100%"
        empty-text="还没有执行记录"
        @selection-change="onSelectionChange"
        @refresh="load(false)"
      >
        <template #toolbarButtons>
          <ListToolbar :config="listToolbar" />
        </template>
        <template #duration="{ row }">
          <span class="runs-duration">{{ formatRunDuration(Number(row.duration_ms ?? 0)) }}</span>
        </template>
        <template #result="{ row }">
          <el-tag
            size="small"
            effect="light"
            :type="
              row.status === 'failed' ? 'danger' : row.status === 'success' ? 'success' : 'info'
            "
          >
            {{ statusLabel(String(row.status ?? '')) }}
          </el-tag>
          <span v-if="row.error_text" class="dim">{{ firstLine(String(row.error_text)) }}</span>
        </template>
      </BasicTable>
    </div>
    <EmptyState v-else description="还没有执行记录" />
  </el-dialog>
</template>

<style scoped>
.runs-body {
  height: min(68vh, 36rem);
  min-height: 16rem;
  display: flex;
  flex-direction: column;
}

.runs-body :deep(.basic-table) {
  flex: 1 1 auto;
  min-height: 0;
}

.runs-body :deep(.basic-table__toolbar) {
  margin: 0;
}

.runs-body :deep(.el-table .cell) {
  white-space: nowrap;
}

.runs-duration {
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.88em;
}

.dim {
  margin-left: 0.35rem;
  color: var(--muted);
}
</style>

<style>
.job-runs-dialog.el-dialog {
  max-width: 96vw;
}

.job-runs-dialog .el-dialog__body {
  padding-top: 0.5rem;
}
</style>
