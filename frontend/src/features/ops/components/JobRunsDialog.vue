<script setup lang="ts">
/**
 * 定时台「执行历史」弹窗：宽表、任务名左置、耗时可读。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { batchDeleteJobRuns } from '@/shared/api/quant'
import BasicTable, {
  type BasicTableColumn,
} from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import ListToolbar, { type ListToolbarConfig } from '@/shared/components/ui/ListToolbar.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { JobRun } from '@/shared/types/quant'

import {
  cnStrategyName,
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
const tableRows = computed(() => runs.value as unknown as Record<string, unknown>[])

/**
 * 历史表的 `job_name` 是后端原样字段：战法/技能绑定任务叫 `screen:sanyuan-tail-v1`，
 * 直接摆进单元格就是把英文 slug 甩给用户。统一过 cnStrategyName（含拼音词根兜底）。
 */
function runJobLabel(raw: unknown): string {
  const name = String(raw ?? '').trim()
  if (!name) return '—'
  const bound = /^(?:screen|skill):(.+)$/.exec(name)
  return bound ? cnStrategyName('', bound[1]) : name
}

const columns = ref<BasicTableColumn[]>([
  { type: 'selection', width: 48, fixed: 'left' },
  {
    prop: 'job_name',
    label: '任务',
    minWidth: 200,
    align: 'center',
    headerAlign: 'center',
    showOverflowTooltip: true,
    fixed: 'left',
    formatter: (row) => runJobLabel(row.job_name),
  },
  {
    prop: 'started_at',
    label: '时间',
    minWidth: 160,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => String(row.started_at ?? '—'),
  },
  {
    prop: 'trigger',
    label: '触发',
    width: 72,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => triggerLabel(String(row.trigger ?? '')),
  },
  {
    prop: 'duration_ms',
    label: '耗时',
    width: 96,
    align: 'center',
    headerAlign: 'center',
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

async function load(): Promise<void> {
  selectedIds.value = []
  basicTableRef.value?.clearSelection()
  await refetch()
}

watch(
  () => props.modelValue,
  (opened) => {
    if (opened) void load()
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
  await load()
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
        :data-source="tableRows"
        :pagination="false"
        virtualized
        :toolbar-config="{ refresh: true }"
        :loading="busy"
        stripe
        row-key="id"
        height="100%"
        empty-text="还没有执行记录"
        @selection-change="onSelectionChange"
        @refresh="load"
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
  font-family: var(--mono);
  font-size: var(--fs-body);
}

.dim {
  margin-left: var(--gap-1);
  color: var(--muted);
}
</style>

<style>
.job-runs-dialog.el-dialog {
  max-width: 96vw;
}

.job-runs-dialog .el-dialog__body {
  padding-top: var(--gap-2);
}
</style>
